"""Per-simulation contribution matrices and attractiveness rankings.

For every slot we build a matrix giving the points each candidate would have
earned in each simulation:
  * tier slots      : tier_total_points (match points + advancement/final bonuses)
  * scoring slot    : 0.5 * goals scored        (all 48 teams)
  * conceding slot  : 0.5 * goals conceded       (all 48 teams)
  * top-scorer slot : 0.5 * player goals + (scaled) Golden-Boot bonus

Summing the chosen slot columns per simulation gives an entry's full score
distribution and, crucially, captures correlations automatically (two teams
that can meet show negative covariance; doubling a team shows positive
covariance). From these matrices we also produce ranked "attractiveness"
tables (mean / std / P10 / P50 / P90 / upside) per slot.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import DEFAULT_RULES, ScoringRules
from .data_io import Dataset
from .scoring import (TIER_CODE, conceding_slot_points, scoring_slot_points,
                      tier_total_points)


@dataclass
class Contributions:
    tier: np.ndarray            # [S, 48] points if team used as its own tier pick
    scoring: np.ndarray         # [S, 48] points if used as scoring team
    conceding: np.ndarray       # [S, 48] points if used as conceding team
    topscorer: np.ndarray       # [S, P]  points if player used as top-scorer pick
    team_list: list[str]
    player_names: list[str]
    tier_code: np.ndarray       # [48] int code per team
    team_tier: dict[str, str]


def build_contributions(
    ds: Dataset, O: dict, golden_boot_scale: float = 1.0,
    rules: ScoringRules = DEFAULT_RULES,
) -> Contributions:
    team_tier = {r.team: r.tier for r in ds.teams.itertuples()}
    tier_code = np.array([TIER_CODE[team_tier[t]] for t in ds.team_list])

    tier = tier_total_points(O, tier_code, rules).astype(np.float32)
    scoring = scoring_slot_points(O, rules).astype(np.float32)
    conceding = conceding_slot_points(O, rules).astype(np.float32)

    S, P = O["player_goals"].shape
    is_gb = np.zeros((S, P), dtype=np.float32)
    is_gb[np.arange(S), O["golden_boot"]] = 1.0
    topscorer = (rules.per_topscorer_goal * O["player_goals"]
                 + rules.golden_boot_bonus * golden_boot_scale * is_gb).astype(np.float32)

    return Contributions(
        tier=tier, scoring=scoring, conceding=conceding, topscorer=topscorer,
        team_list=ds.team_list, player_names=O["player_names"],
        tier_code=tier_code, team_tier=team_tier,
    )


def _stats_table(mat: np.ndarray, labels: list[str], extra: dict | None = None) -> pd.DataFrame:
    rows = []
    p10, p50, p90 = np.percentile(mat, [10, 50, 90], axis=0)
    mean = mat.mean(0); std = mat.std(0)
    for i, lab in enumerate(labels):
        row = {"candidate": lab, "mean": mean[i], "std": std[i],
               "p10": p10[i], "p50": p50[i], "p90": p90[i],
               "upside": p90[i] - mean[i]}
        if extra:
            for k, v in extra.items():
                row[k] = v[i]
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("mean", ascending=False).reset_index(drop=True)
    return df


def attractiveness_tables(ds: Dataset, contrib: Contributions, O: dict) -> dict[str, pd.DataFrame]:
    """Ranked per-slot attractiveness tables (the 'which pick is best' deliverable)."""
    tl = contrib.team_list
    tiers = {r.team: r.tier for r in ds.teams.itertuples()}
    groups = {r.team: r.group for r in ds.teams.itertuples()}

    out = {}
    # Tier slots (split by tier membership)
    adv = O["advanced"].mean(0)
    title = O["won_cup"].mean(0)
    for tier_letter in ["A", "B", "C", "D"]:
        idx = [i for i, t in enumerate(tl) if tiers[t] == tier_letter]
        sub = contrib.tier[:, idx]
        labels = [tl[i] for i in idx]
        df = _stats_table(sub, labels,
                          extra={"adv_prob": adv[idx], "title_prob": title[idx]})
        df.insert(1, "group", [groups[c] for c in df["candidate"]])
        out[f"tier_{tier_letter}"] = df

    # Scoring / conceding slots (all teams)
    out["scoring"] = _stats_table(
        contrib.scoring, tl, extra={"exp_gf": O["gf"].mean(0)})
    out["conceding"] = _stats_table(
        contrib.conceding, tl, extra={"exp_ga": O["ga"].mean(0)})

    # Top-scorer slot
    gb = O["golden_boot"]; S = O["n_sims"]
    gb_prob = np.bincount(gb, minlength=len(contrib.player_names)) / S
    pteams = list(ds.players["team"])
    df = _stats_table(contrib.topscorer, contrib.player_names,
                      extra={"gb_prob": gb_prob, "exp_goals": O["player_goals"].mean(0)})
    df.insert(1, "team", [pteams[contrib.player_names.index(c)] for c in df["candidate"]])
    out["top_scorer"] = df
    return out
