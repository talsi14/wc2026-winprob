"""Shared helpers for the live win-probability pipeline.

Keeps the orchestrator (run_live_update.py) and the report builder consistent:
loading the pool dataset (candidate players + the picked-but-unlisted scorers),
scoring all real entries per simulation, and turning the [n_sims, n_entries]
score matrix into prizes / probabilities under the prize-splitting tiebreak.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DATA_LIVE, prize_vector
from .contributions import Contributions
from .data_io import Dataset, load_dataset


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
