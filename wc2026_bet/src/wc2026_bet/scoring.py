"""Bet scoring engine - the single source of truth for the point system.

An *entry* is 7 picks: one team from each of tiers A/B/C/D, a "scoring team"
(you earn per goal it scores), a "conceding team" (you earn per goal it
concedes) and a top-scorer player (Golden Boot pick). Overlap is allowed: the
same team may appear as a tier pick AND as the scoring/conceding team.

A simulated tournament *outcome* records, per team: matches won (reg/ET vs
penalties), group-stage draws, penalty-shootout losses, goals for/against,
group finishing position, whether it advanced, the round it reached, and
whether it made/won the final. Plus per-player goals and the Golden Boot winner.

This module exposes:
  * ``Entry`` - the 7-pick container.
  * vectorized point functions over arrays shaped [n_sims, n_teams] (used for
    the 50k-simulation run), and
  * ``score_entry`` - a readable scalar reference used by the unit self-test.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import DEFAULT_RULES, ScoringRules

# Tier letter -> integer code used in vectorized arrays.
TIER_CODE = {"A": 0, "B": 1, "C": 2, "D": 3}


@dataclass(frozen=True)
class Entry:
    tier_a: str
    tier_b: str
    tier_c: str
    tier_d: str
    scoring_team: str
    conceding_team: str
    top_scorer: str

    def tier_picks(self) -> list[str]:
        return [self.tier_a, self.tier_b, self.tier_c, self.tier_d]

    def as_dict(self) -> dict[str, str]:
        return {
            "tier_a": self.tier_a, "tier_b": self.tier_b,
            "tier_c": self.tier_c, "tier_d": self.tier_d,
            "scoring_team": self.scoring_team,
            "conceding_team": self.conceding_team,
            "top_scorer": self.top_scorer,
        }


# --------------------------------------------------------------------------- #
# Vectorized point functions. Each `O` is a dict of numpy arrays shaped
# [n_sims, n_teams] (or [n_sims, n_players] for player goals).
# --------------------------------------------------------------------------- #
def tier_match_points(O: dict, rules: ScoringRules = DEFAULT_RULES) -> np.ndarray:
    """Points from match results for every team, every sim. Shape [S, T]."""
    return (
        rules.win * O["reg_wins"]
        + rules.draw * O["group_draws"]
        + rules.loss * O["reg_losses"]
        + rules.pen_win * O["pen_wins"]
        + rules.pen_loss * O["pen_losses"]
    )


def tier_bonus_points(
    O: dict, tier_code: np.ndarray, rules: ScoringRules = DEFAULT_RULES
) -> np.ndarray:
    """Advancement + final/winner bonuses per team, per sim. Shape [S, T].

    ``tier_code`` is an int array shaped [T] (0=A,1=B,2=C,3=D).
    """
    finish = O["group_finish"]          # [S,T] in 1..4
    advanced = O["advanced"]            # [S,T] bool
    made_final = O["made_final"]        # [S,T] bool
    won_cup = O["won_cup"]              # [S,T] bool

    is_c = (tier_code == TIER_CODE["C"])[None, :]   # [1,T]
    is_d = (tier_code == TIER_CODE["D"])[None, :]
    top2 = advanced & (finish <= 2)
    third_adv = advanced & (finish == 3)

    bonus = np.zeros_like(finish, dtype=float)
    bonus += np.where(top2 & is_d, rules.bonus_r32_top2_tierD, 0.0)
    bonus += np.where(third_adv & is_d, rules.bonus_r32_third_tierD, 0.0)
    bonus += np.where(top2 & is_c, rules.bonus_r32_top2_tierC, 0.0)

    final_pts = (
        rules.bonus_reach_final * made_final + rules.bonus_win_cup * won_cup
    ).astype(float)
    if not rules.final_bonus_all_tiers:
        final_pts = np.where((is_c | is_d), final_pts, 0.0)
    bonus += final_pts
    return bonus


def tier_total_points(
    O: dict, tier_code: np.ndarray, rules: ScoringRules = DEFAULT_RULES
) -> np.ndarray:
    """Full points a team contributes when used as a *tier* pick. Shape [S,T]."""
    return tier_match_points(O, rules) + tier_bonus_points(O, tier_code, rules)


def scoring_slot_points(O: dict, rules: ScoringRules = DEFAULT_RULES) -> np.ndarray:
    """Points if a team is used as the 'scoring team'. Shape [S,T]."""
    return rules.per_goal_scored * O["gf"]


def conceding_slot_points(O: dict, rules: ScoringRules = DEFAULT_RULES) -> np.ndarray:
    """Points if a team is used as the 'conceding team'. Shape [S,T]."""
    return rules.per_goal_conceded * O["ga"]


def topscorer_slot_points(
    player_goals: np.ndarray, is_golden_boot: np.ndarray,
    rules: ScoringRules = DEFAULT_RULES,
) -> np.ndarray:
    """Points if a player is the top-scorer pick. Shape [S, P]."""
    return rules.per_topscorer_goal * player_goals + rules.golden_boot_bonus * is_golden_boot


# --------------------------------------------------------------------------- #
# Scalar reference implementation (clarity + tests)
# --------------------------------------------------------------------------- #
def team_points_scalar(stats: dict, tier: str, rules: ScoringRules = DEFAULT_RULES) -> float:
    """Points a single team contributes as a tier pick, for one outcome.

    ``stats`` keys: reg_wins, group_draws, reg_losses, pen_wins, pen_losses,
    group_finish, advanced, made_final, won_cup.
    """
    pts = (
        rules.win * stats["reg_wins"]
        + rules.draw * stats["group_draws"]
        + rules.loss * stats["reg_losses"]
        + rules.pen_win * stats["pen_wins"]
        + rules.pen_loss * stats["pen_losses"]
    )
    advanced = stats["advanced"]
    finish = stats["group_finish"]
    if tier == "D":
        if advanced and finish <= 2:
            pts += rules.bonus_r32_top2_tierD
        elif advanced and finish == 3:
            pts += rules.bonus_r32_third_tierD
    elif tier == "C":
        if advanced and finish <= 2:
            pts += rules.bonus_r32_top2_tierC
    final_pts = rules.bonus_reach_final * stats["made_final"] + rules.bonus_win_cup * stats["won_cup"]
    if (not rules.final_bonus_all_tiers) and tier in ("A", "B"):
        final_pts = 0.0
    return pts + final_pts


def score_entry(
    entry: Entry,
    team_stats: dict[str, dict],
    team_gf: dict[str, float],
    team_ga: dict[str, float],
    player_goals: dict[str, float],
    golden_boot: str,
    team_tier: dict[str, str],
    rules: ScoringRules = DEFAULT_RULES,
) -> dict:
    """Score a full entry for a single tournament outcome. Returns a breakdown."""
    bd = {}
    bd["tier_a"] = team_points_scalar(team_stats[entry.tier_a], team_tier[entry.tier_a], rules)
    bd["tier_b"] = team_points_scalar(team_stats[entry.tier_b], team_tier[entry.tier_b], rules)
    bd["tier_c"] = team_points_scalar(team_stats[entry.tier_c], team_tier[entry.tier_c], rules)
    bd["tier_d"] = team_points_scalar(team_stats[entry.tier_d], team_tier[entry.tier_d], rules)
    bd["scoring_team"] = rules.per_goal_scored * team_gf[entry.scoring_team]
    bd["conceding_team"] = rules.per_goal_conceded * team_ga[entry.conceding_team]
    bd["top_scorer"] = (
        rules.per_topscorer_goal * player_goals.get(entry.top_scorer, 0.0)
        + rules.golden_boot_bonus * (1.0 if entry.top_scorer == golden_boot else 0.0)
    )
    bd["total"] = sum(bd.values())
    return bd
