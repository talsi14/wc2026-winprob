"""Project paths, tournament constants, scoring rules and model defaults.

All tunable knobs live here so the analysis is reproducible and easy to audit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PKG_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_ROOT.parents[1]          # .../wc2026_bet
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_LIVE = PROJECT_ROOT / "data" / "live"   # live tournament state + entries
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_DIR = PROJECT_ROOT / "report"

for _p in (DATA_RAW, DATA_PROCESSED, DATA_LIVE, RESULTS_DIR, REPORT_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Tournament format (2026: 48 teams, 12 groups of 4)
# --------------------------------------------------------------------------- #
GROUPS = list("ABCDEFGHIJKL")
HOST_NATIONS = ("United States", "Canada", "Mexico")
N_SIMULATIONS = 50_000
RANDOM_SEED = 26

# Per-player goal plausibility caps. Each candidate's tournament goals are drawn
# binomial(team_goals_in_sim, player_share); with a fixed share the tail can
# over-attribute goals to a single star in deep, high-scoring runs (e.g. 17 of a
# team's 19 goals). Cap each candidate's per-sim total both as a fraction of the
# team's goals and in absolute terms, so simulated top-scorer tallies stay
# realistic (the modern-era record is ~8; the all-time record is 13).
MAX_PLAYER_GOAL_SHARE = 0.60     # no candidate scores >60% of the team's goals
MAX_PLAYER_GOALS = 12            # nor more than this many in any single sim

# Round indices recorded per team (max round the team *reached*).
ROUND_GROUP = 0      # eliminated in group stage
ROUND_R32 = 1        # reached Round of 32
ROUND_R16 = 2
ROUND_QF = 3
ROUND_SF = 4
ROUND_FINAL = 5      # reached the final (lost it)
ROUND_WINNER = 6     # won the cup
ROUND_NAMES = {
    ROUND_GROUP: "Group stage",
    ROUND_R32: "Round of 32",
    ROUND_R16: "Round of 16",
    ROUND_QF: "Quarter-final",
    ROUND_SF: "Semi-final",
    ROUND_FINAL: "Final",
    ROUND_WINNER: "Champion",
}

# --------------------------------------------------------------------------- #
# Match / goals model defaults (Dixon-Coles bivariate Poisson)
# --------------------------------------------------------------------------- #
# Time-decay half-life (years) and competition importance weights are used when
# fitting attack/defence ratings from historical internationals.
TIME_DECAY_HALFLIFE_YEARS = 4.0
MATCH_IMPORTANCE = {
    "FIFA World Cup": 1.00,
    "World Cup": 1.00,
    "World Cup - Qualification": 0.65,
    "WC Qualification": 0.65,
    "Euro Championship": 0.85,
    "Euro Championship - Qualification": 0.55,
    "UEFA Nations League": 0.55,
    "Copa America": 0.85,
    "Africa Cup of Nations": 0.75,
    "AFC Asian Cup": 0.70,
    "Gold Cup": 0.65,
    "CONCACAF Nations League": 0.55,
    "Friendlies": 0.30,
    "Friendly": 0.30,
}
DEFAULT_MATCH_IMPORTANCE = 0.45

# Reference date for time-decay weighting (tournament eve).
REFERENCE_DATE = "2026-06-11"

# Per-match weight given to *played 2026 WC-finals* games when they are folded
# into the attack/defence fit at run time (the live engine appends them to the
# curated results.csv so ratings reflect live tournament form; the file itself
# stays static). The strongest pre-tournament games weigh ~0.61, so 1.5 lets a
# WC result clearly outweigh any friendly/qualifier without letting a handful of
# games (often vs weaker opponents) erase two years of evidence. Tunable knob.
WC_FIT_WEIGHT = 1.5

# Split ridge for the attack/defence fit:
#   RIDGE_STRENGTH anchors (attack + defence) to the Elo-implied overall
#     strength (high => respect the authoritative Elo ordering), while
#   RIDGE_STYLE only lightly shrinks the (attack - defence) split, letting the
#     data express each team's offensive/defensive personality (which the
#     scoring-team / conceding-team picks rely on).
RIDGE_STRENGTH = 25.0
RIDGE_STYLE = 4.0

# Knockout penalty-shootout: P(stronger side wins) = 0.5 + PEN_EDGE*tanh(diff).
PEN_EDGE = 0.05

# Calibration: a global multiplier applied to (attack-defence) spread so the
# simulated title odds line up with the market / Opta. Solved in calibration.
STRENGTH_SPREAD = 1.0  # overwritten by data/processed/calibration.json at load.


# --------------------------------------------------------------------------- #
# Bet scoring rules (encoded from the official PDF)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScoringRules:
    """All point values from the bet, plus flags for the two ambiguous clauses.

    Defaults reflect the most literal reading of the PDF; flags let us test the
    alternative interpretations without touching the engine.
    """

    # Tier-team match points (every match the team plays, group + knockout).
    win: float = 3.0
    draw: float = 1.0
    loss: float = 0.0
    pen_win: float = 3.0     # knockout decided on penalties: winner
    pen_loss: float = 1.0    # knockout decided on penalties: loser

    # Advancement bonuses (depend on the *tier* of the picked team).
    # Reach R32 as group 1st/2nd:
    bonus_r32_top2_tierD: float = 3.0
    bonus_r32_top2_tierC: float = 1.0
    # Reach R32 as a (qualifying) 3rd place:
    bonus_r32_third_tierD: float = 1.0
    # Final / winner bonuses:
    bonus_reach_final: float = 2.0
    bonus_win_cup: float = 1.0

    # Goal-based slots.
    per_goal_scored: float = 0.5     # "scoring team" (\u05e0\u05d1\u05d7\u05e8\u05ea \u05db\u05d5\u05d1\u05e9\u05ea)
    per_goal_conceded: float = 0.5   # "conceding team" (\u05e0\u05d1\u05d7\u05e8\u05ea \u05e1\u05d5\u05e4\u05d2\u05ea)
    per_topscorer_goal: float = 0.5  # picked Golden-Boot player, per goal
    golden_boot_bonus: float = 1.0   # if the player wins the Golden Boot

    # --- Ambiguity flags ---------------------------------------------------- #
    # PDF asterisk: "* only if a 3rd/4th place match is played". A 3rd-place
    # match is always played at the World Cup, so the final/winner bonuses apply
    # by default. Set False to gate them on that clause (no effect in practice).
    final_bonus_requires_third_place_match: bool = False
    # Whether the final/winner bonus applies to teams from *any* tier (assumed
    # yes) or only to the lower tiers. Default: any tier.
    final_bonus_all_tiers: bool = True


DEFAULT_RULES = ScoringRules()

# --------------------------------------------------------------------------- #
# Bet logistics (for ROI / payout modelling)
# --------------------------------------------------------------------------- #
ENTRY_FEE_ILS = 50
PRIZE_FIRST_FRAC = 0.70
PRIZE_SECOND_FRAC = 0.30
PRIZE_THIRD_FIXED_ILS = 50     # 3rd place gets 50 back
PRIZE_LAST_FIXED_ILS = 50      # last place gets 50 back

# Live prize ladder in ILS, as published on the pool site (53 entries x 50 = 2650
# pot = 1800 + 750 + 50 + 50). Used by the live win-probability engine.
PRIZE_FIRST_ILS = 1800
PRIZE_SECOND_ILS = 750


def prize_vector(n_entries: int):
    """Prize (ILS) per finishing position 1..n. 1st/2nd are the cash prizes;
    3rd and last get a 50 refund; everyone else 0. Ties are resolved by the
    caller, which splits the summed prize of the tied positions equally."""
    v = [0.0] * n_entries
    if n_entries >= 1:
        v[0] = float(PRIZE_FIRST_ILS)
    if n_entries >= 2:
        v[1] = float(PRIZE_SECOND_ILS)
    if n_entries >= 3:
        v[2] = float(PRIZE_THIRD_FIXED_ILS)
    if n_entries >= 4:
        v[-1] = float(PRIZE_LAST_FIXED_ILS)   # last place
    return v


# --------------------------------------------------------------------------- #
# Live-update data sources (no API keys required for the scheduled job)
# --------------------------------------------------------------------------- #
# Friends-pool leaderboard: the lovable.app front-end is backed by this public
# Supabase table. The "anon" read key is a public client key (it's shipped in the
# site's own JS bundle), but to keep it out of this public repo it's read from the
# POOL_SUPABASE_ANON_KEY environment variable. It is ONLY needed when re-pulling
# the roster (ingest, i.e. `run_live_pipeline.py --entries`); the scheduled
# win-probability job never touches it.
POOL_SUPABASE_URL = "https://fllblqtztfmbpeofmaqu.supabase.co"
POOL_SUPABASE_ANON_KEY = os.environ.get("POOL_SUPABASE_ANON_KEY", "")
POOL_LEADERBOARD_TABLE = "leaderboard"
EXPECTED_POOL_SIZE = 53

# ESPN's keyless soccer API (FIFA World Cup feed) for live results / standings /
# goal scorers. season=2026 for WC 2026.
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings"
ESPN_SEASON = 2026


# --------------------------------------------------------------------------- #
# Field model defaults (the ~40-60 opponents)
# --------------------------------------------------------------------------- #
@dataclass
class FieldConfig:
    """Empirical field model (fit to the friend-pool's real past entries).

    The pool is favorite-chasing, not EV-optimizing: ownership concentrates on
    the strongest / most famous candidate in each slot. We reproduce the
    measured concentration (the average ownership of the single most-owned
    candidate per slot - the "top share") over the 2026 candidates ranked by
    market strength / expected goals / Golden-Boot odds. Defaults are the
    Euro 2024 + Qatar 2022 fitted values; build_field overrides them from
    data/processed/pool_behavior.json when present.
    """
    n_entries: int = 50                 # total entries in the pool (mid of 40-60)
    seed: int = 26
    tier_top_share: float = 0.44        # favorite-chase concentration (tier slots)
    scoring_top_share: float = 0.43     # scoring-team pick concentration
    conceding_top_share: float = 0.31   # conceding-team pick concentration
    top_scorer_top_share: float = 0.52  # Golden-Boot chalk concentration
    doubling_rate: float = 0.44         # P(scoring team == an own tier team)
    eps_uniform: float = 0.04           # diffuse tail mixed into each slot
