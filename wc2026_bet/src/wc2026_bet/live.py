"""Shared helpers for the live win-probability pipeline.

Keeps the orchestrator (run_live_update.py) and the report builder consistent:
loading the pool dataset (candidate players + the picked-but-unlisted scorers),
scoring all real entries per simulation, and turning the [n_sims, n_entries]
score matrix into prizes / probabilities under the prize-splitting tiebreak.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DATA_LIVE, DEFAULT_RULES, prize_vector
from .contributions import Contributions
from .data_io import Dataset, load_dataset
from .scoring import Entry, score_entry


def load_live_dataset() -> Dataset:
    """Dataset with any picked top-scorers outside the base candidate list
    (data/live/extra_players.csv) appended, so the simulator models them too."""
    ds = load_dataset()
    extra = DATA_LIVE / "extra_players.csv"
    if extra.exists():
        ex = pd.read_csv(extra)
        ex = ex[~ex["scorer"].isin(set(ds.players["scorer"]))]
        if len(ex):
            ds.players = pd.concat([ds.players, ex[ds.players.columns]],
                                   ignore_index=True)
    return ds


def load_entries() -> pd.DataFrame:
    return pd.read_csv(DATA_LIVE / "pool_entries_2026.csv")


def score_entries(ds: Dataset, contrib: Contributions, O: dict,
                  entries: pd.DataFrame) -> np.ndarray:
    """[n_sims, n_entries] total score for each real entry, every simulation.

    Each entry's score is the sum of its 7 chosen slot columns; the tier matrix
    already encodes each team's own tier bonuses, so picks are scored by team /
    player index regardless of slot.
    """
    tidx = ds.team_index
    pcol = {n: i for i, n in enumerate(contrib.player_names)}
    S = O["n_sims"]
    scores = np.zeros((S, len(entries)), dtype=np.float32)
    for e, r in enumerate(entries.itertuples()):
        s = (contrib.tier[:, tidx[r.tierA]] + contrib.tier[:, tidx[r.tierB]]
             + contrib.tier[:, tidx[r.tierC]] + contrib.tier[:, tidx[r.tierD]]
             + contrib.scoring[:, tidx[r.scoring]]
             + contrib.conceding[:, tidx[r.conceding]]
             + contrib.topscorer[:, pcol[r.top_scorer]])
        scores[:, e] = s
    return scores


def known_team_stats(ds: Dataset, state: dict) -> dict[str, dict]:
    """Per-team locked stats from completed matches (group + knockout).

    Advancement / finish (tier C/D bonuses) and final/winner flags are only
    credited once actually determined (group complete, KO played). Shared by the
    live collector (reconciliation) and the win-prob engine (current points).
    """
    stats = {t: {"reg_wins": 0, "group_draws": 0, "reg_losses": 0,
                 "pen_wins": 0, "pen_losses": 0, "group_finish": 0,
                 "advanced": False, "made_final": False, "won_cup": False}
             for t in ds.team_list}
    sched = {r.match: (r.home, r.away) for r in ds.group_matches.itertuples()}

    for mno, (hg, ag) in (state.get("group_scores") or {}).items():
        home, away = sched[int(mno)]
        if hg > ag:
            stats[home]["reg_wins"] += 1; stats[away]["reg_losses"] += 1
        elif ag > hg:
            stats[away]["reg_wins"] += 1; stats[home]["reg_losses"] += 1
        else:
            stats[home]["group_draws"] += 1; stats[away]["group_draws"] += 1

    for ko in (state.get("ko_results") or []):
        h, a, w = ko["home"], ko["away"], ko.get("winner")
        if not w:
            continue
        l = a if w == h else h
        if ko.get("shootout"):
            stats[w]["pen_wins"] += 1; stats[l]["pen_losses"] += 1
        else:
            stats[w]["reg_wins"] += 1; stats[l]["reg_losses"] += 1

    gsc = bool(state.get("group_stage_complete"))
    for _g, rows in (state.get("standings") or {}).items():
        # A group is settled once all four teams have played their 3 matches.
        group_done = bool(rows) and all(r.get("played", 0) >= 3 for r in rows)
        for r in rows:
            rank = r.get("rank", 0)
            if gsc:
                # Full group stage over: final standings + best-third
                # qualification are known; trust the official advanced flag.
                stats[r["team"]]["group_finish"] = rank
                stats[r["team"]]["advanced"] = bool(r["advanced"])
            elif group_done:
                # This group is decided but the whole stage isn't. A top-2
                # finish guarantees advancement regardless of the other groups,
                # so credit its bonus now. Third place depends on the 8-best-
                # thirds race (needs every group complete), so 3rd/4th wait.
                stats[r["team"]]["group_finish"] = rank
                if rank <= 2:
                    stats[r["team"]]["advanced"] = True
    return stats


def current_points_breakdown(ds: Dataset, state: dict, entries: pd.DataFrame,
                             golden_boot: str = "") -> dict[str, dict]:
    """Real locked points per entry from the actual results so far, using the
    canonical scoring engine. Returns {entry name: breakdown} where the
    breakdown has tier_a/b/c/d, scoring_team, conceding_team, top_scorer, total.
    """
    stats = known_team_stats(ds, state)
    tp = state.get("team_played") or {}
    gf = {t: tp.get(t, {}).get("gf", 0) for t in ds.team_list}
    ga = {t: tp.get(t, {}).get("ga", 0) for t in ds.team_list}
    pg = state.get("player_goals") or {}
    team_tier = {r.team: r.tier for r in ds.teams.itertuples()}
    out = {}
    for r in entries.itertuples():
        e = Entry(r.tierA, r.tierB, r.tierC, r.tierD, r.scoring, r.conceding, r.top_scorer)
        out[r.name] = score_entry(e, stats, gf, ga, pg, golden_boot, team_tier,
                                  DEFAULT_RULES)
    return out


def rank_and_metrics(scores: np.ndarray, seed: int = 7) -> dict:
    """Rank entries per sim (uniform random tiebreak) and aggregate metrics.

    Random tiebreaking makes the position-prize expectation identical to the
    user's split rule (k tied entries over positions p..p+k-1 each expect the
    mean of those prizes), while giving clean P(rank==r). Returns arrays indexed
    by entry: exp_winnings (ILS), P_first/P_second/P_top2/P_third/P_last,
    exp_points, exp_rank, score percentiles, and the per-entry rank histogram.
    """
    S, N = scores.shape
    rng = np.random.default_rng(seed)
    jitter = rng.random(scores.shape) * 1e-6
    order = np.argsort(-(scores + jitter), axis=1)             # best-first entry idx
    ranks = np.empty((S, N), dtype=np.int32)
    cols = np.broadcast_to(np.arange(1, N + 1), (S, N))
    np.put_along_axis(ranks, order, cols, axis=1)             # rank (1..N) per entry

    pv = np.asarray(prize_vector(N), dtype=np.float64)        # prize by position
    winnings = pv[ranks - 1]                                  # [S,N] ILS per sim

    rank_hist = np.zeros((N, N), dtype=np.int64)              # [entry, position-1]
    for e in range(N):
        rank_hist[e] = np.bincount(ranks[:, e] - 1, minlength=N)

    p10, p50, p90 = np.percentile(scores, [10, 50, 90], axis=0)
    return {
        "exp_winnings": winnings.mean(0),
        "P_first": (ranks == 1).mean(0),
        "P_second": (ranks == 2).mean(0),
        "P_top2": (ranks <= 2).mean(0),
        "P_third": (ranks == 3).mean(0),
        "P_last": (ranks == N).mean(0),
        "exp_points": scores.mean(0),
        "exp_rank": ranks.mean(0),
        "score_p10": p10, "score_p50": p50, "score_p90": p90,
        "rank_hist": rank_hist,
        "ranks": ranks,            # [S,N], kept for champion-conditioning
    }
