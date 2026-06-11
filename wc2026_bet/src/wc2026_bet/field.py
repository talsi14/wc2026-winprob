"""Field model: the ~40-60 opponent entries, and finish-probability / ROI.

Opponents are modelled empirically, fit to the friend-pool's real past entries
(Euro 2024 + Qatar 2022, see scripts/ingest_pool_entries.py ->
data/processed/pool_behavior.json). The pool is favorite-chasing, not
EV-optimizing: ownership concentrates on the strongest / most-famous candidate
in each slot. We reproduce the measured concentration (the average ownership of
the single most-owned candidate per slot - the "top share") over the 2026
candidates ranked by:
  * tier slots   -> team market strength (blended Elo prior);
  * scoring      -> expected goals scored (with a doubling/stacking rate that
                    reuses one of the entry's own tier teams);
  * conceding    -> expected goals conceded (leaky minnows);
  * top scorer   -> market Golden-Boot odds (heavy chalk).

Each opponent's score distribution is summed from the contribution matrices, so
ties and correlations are handled exactly. Scores carry a tiny random jitter so
ties between entries are broken fairly (scores are multiples of 0.5, so ties are
common). Finish metrics (P1/P2/P3/Plast and expected ROI) compare a candidate's
score vector against the field across all simulations.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (DATA_PROCESSED, ENTRY_FEE_ILS, FieldConfig,
                     PRIZE_FIRST_FRAC, PRIZE_LAST_FIXED_ILS, PRIZE_SECOND_FRAC,
                     PRIZE_THIRD_FIXED_ILS)
from .contributions import Contributions
from .data_io import Dataset


def _concentration_probs(appeal, target_top: float, eps: float = 0.0):
    """Categorical pick probabilities whose most-likely candidate has share
    ``target_top``. Models favorite-chasing: probability rises with ``appeal``
    (a strength / expected-goals / Golden-Boot score). Solved by a bisection on
    the softmax temperature, then a small uniform tail ``eps`` is mixed in.
    """
    z = np.asarray(appeal, float)
    z = (z - z.mean()) / (z.std() + 1e-9)
    n = len(z)
    if n == 1:
        return np.array([1.0])
    floor = 1.0 / n
    if target_top <= floor + 1e-6:
        p = np.full(n, floor)
    else:
        def top(beta):
            e = np.exp(beta * (z - z.max()))
            return (e / e.sum()).max()
        lo, hi = 0.0, 80.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if top(mid) < target_top:
                lo = mid
            else:
                hi = mid
        beta = 0.5 * (lo + hi)
        e = np.exp(beta * (z - z.max()))
        p = e / e.sum()
    if eps > 0:
        p = (1 - eps) * p + eps * np.full(n, 1.0 / n)
    return p / p.sum()


def _load_pool_behavior(cfg: FieldConfig) -> dict:
    """Top-share / doubling targets, from pool_behavior.json if present."""
    f = DATA_PROCESSED / "pool_behavior.json"
    d = {"tier_top_share": cfg.tier_top_share,
         "scoring_top_share": cfg.scoring_top_share,
         "conceding_top_share": cfg.conceding_top_share,
         "top_scorer_top_share": cfg.top_scorer_top_share,
         "doubling_rate": cfg.doubling_rate}
    if f.exists():
        d.update({k: v for k, v in json.loads(f.read_text()).items() if k in d})
    return d


@dataclass
class SlotSpace:
    """Candidate indices + the contribution matrix column source for a slot."""
    name: str
    cand_idx: np.ndarray        # indices into the slot's contribution matrix
    matrix: np.ndarray          # [S, n_cand_total] contribution matrix
    labels: list[str]


@dataclass
class Field:
    scores: np.ndarray          # [S, n_opp] opponent score distributions (jittered)
    entries: list[tuple]        # opponent picks as slot-index tuples
    ownership: dict             # slot -> {label: ownership fraction}
    n_total: int                # opponents + 1 (the pot size basis)
    slots: dict                 # name -> SlotSpace
    prize_by_pos: np.ndarray    # gross prize by 1-indexed finishing position


def _slot_spaces(ds: Dataset, contrib: Contributions) -> dict:
    tl = contrib.team_list
    tier_of = contrib.team_tier
    sp = {}
    for L in ["A", "B", "C", "D"]:
        idx = np.array([i for i, t in enumerate(tl) if tier_of[t] == L])
        sp[f"tier_{L}"] = SlotSpace(f"tier_{L}", idx, contrib.tier,
                                    [tl[i] for i in idx])
    allidx = np.arange(len(tl))
    sp["scoring"] = SlotSpace("scoring", allidx, contrib.scoring, list(tl))
    sp["conceding"] = SlotSpace("conceding", allidx, contrib.conceding, list(tl))
    pidx = np.arange(len(contrib.player_names))
    sp["top_scorer"] = SlotSpace("top_scorer", pidx, contrib.topscorer,
                                 list(contrib.player_names))
    return sp


def build_field(ds: Dataset, contrib: Contributions, O: dict,
                cfg: FieldConfig = FieldConfig()) -> Field:
    rng = np.random.default_rng(cfg.seed)
    slots = _slot_spaces(ds, contrib)
    S = O["n_sims"]
    beh = _load_pool_behavior(cfg)

    elo = {r.team: float(r.elo) for r in ds.teams.itertuples()}
    exp_gf = O["gf"].mean(0)
    exp_ga = O["ga"].mean(0)
    # Top-scorer appeal: market Golden-Boot odds (chalk), model prior fallback.
    mkt_gb = ds.players["market_p_gb"].to_numpy(float)
    prior = np.clip(ds.players["p_top_scorer"].to_numpy(float), 1e-4, None)
    if (mkt_gb > 0).any():
        lvl = mkt_gb[mkt_gb > 0].mean() / prior[mkt_gb > 0].mean()
        gb_appeal = np.where(mkt_gb > 0, mkt_gb, prior * lvl)
    else:
        gb_appeal = prior

    # Per-slot favorite-chase appeal + target concentration (top share).
    tl = contrib.team_list
    appeal, target = {}, {}
    for name, sl in slots.items():
        if name.startswith("tier_"):
            appeal[name] = np.array([elo[tl[i]] for i in sl.cand_idx])
            target[name] = beh["tier_top_share"]
        elif name == "scoring":
            appeal[name] = exp_gf[sl.cand_idx]
            target[name] = beh["scoring_top_share"]
        elif name == "conceding":
            appeal[name] = exp_ga[sl.cand_idx]
            target[name] = beh["conceding_top_share"]
        else:  # top_scorer
            appeal[name] = gb_appeal
            target[name] = beh["top_scorer_top_share"]
    probs = {name: _concentration_probs(appeal[name], target[name], cfg.eps_uniform)
             for name in slots}

    slot_names = ["tier_A", "tier_B", "tier_C", "tier_D",
                  "scoring", "conceding", "top_scorer"]
    doubling = float(beh["doubling_rate"])
    n_opp = cfg.n_entries - 1
    entries = []
    score = np.zeros((S, n_opp), dtype=np.float32)
    own_counts = {name: np.zeros(len(slots[name].cand_idx)) for name in slot_names}
    for j in range(n_opp):
        picks = {name: int(rng.choice(len(slots[name].cand_idx), p=probs[name]))
                 for name in slot_names}
        # Doubling/stacking: reuse one of the entry's own tier teams as the
        # scoring pick (the favorite they trust to score), as ~44% of the pool
        # does. Pick the strongest of their tier teams (their Tier-A team).
        if rng.random() < doubling:
            picks["scoring"] = int(slots["tier_A"].cand_idx[picks["tier_A"]])
        sc = np.zeros(S, dtype=np.float32)
        for name in slot_names:
            sl = slots[name]
            c_local = picks[name]
            own_counts[name][c_local] += 1
            sc = sc + sl.matrix[:, sl.cand_idx[c_local]]
        entries.append(picks)
        score[:, j] = sc

    # jitter to break ties fairly
    score = score + rng.uniform(0, 1e-3, size=score.shape).astype(np.float32)

    ownership = {name: {slots[name].labels[i]: own_counts[name][i] / n_opp
                        for i in range(len(slots[name].cand_idx))}
                 for name in slot_names}

    # prize schedule by finishing position (gross winnings)
    n_total = cfg.n_entries
    pot = n_total * ENTRY_FEE_ILS
    pool = pot - PRIZE_THIRD_FIXED_ILS - PRIZE_LAST_FIXED_ILS
    prize = np.zeros(n_total + 1)
    prize[1] = PRIZE_FIRST_FRAC * pool
    prize[2] = PRIZE_SECOND_FRAC * pool
    if n_total >= 3:
        prize[3] = PRIZE_THIRD_FIXED_ILS
    prize[n_total] += PRIZE_LAST_FIXED_ILS

    return Field(scores=score, entries=entries, ownership=ownership,
                 n_total=n_total, slots=slots, prize_by_pos=prize)


# --------------------------------------------------------------------------- #
# Finish metrics
# --------------------------------------------------------------------------- #
def finish_metrics(cand_scores: np.ndarray, field: Field, rng=None) -> dict:
    """Metrics for ONE candidate (score vector [S]) vs the field."""
    rng = rng or np.random.default_rng(0)
    c = cand_scores + rng.uniform(0, 1e-3, size=cand_scores.shape)
    above = (field.scores > c[:, None]).sum(1)        # opponents strictly better
    pos = above + 1                                    # 1 = best
    S = len(c)
    p1 = float(np.mean(pos == 1))
    p2 = float(np.mean(pos <= 2))
    p3 = float(np.mean(pos == 3))
    plast = float(np.mean(pos == field.n_total))
    ev_gross = float(field.prize_by_pos[np.clip(pos, 1, field.n_total)].mean())
    return {"p_first": p1, "p_top2": p2, "p_third": p3, "p_last": plast,
            "ev_gross": ev_gross, "ev_net": ev_gross - ENTRY_FEE_ILS,
            "mean_score": float(cand_scores.mean()),
            "p50_score": float(np.percentile(cand_scores, 50))}


def finish_metrics_matrix(cand_scores: np.ndarray, field: Field, rng=None):
    """Vectorized metrics for many candidates at once. cand_scores: [S, C].

    Returns dict of arrays length C: p_first, p_top2, ev_gross, mean_score.
    """
    rng = rng or np.random.default_rng(0)
    S, C = cand_scores.shape
    c = cand_scores + rng.uniform(0, 1e-3, size=cand_scores.shape).astype(np.float32)
    above = np.zeros((S, C), dtype=np.int32)
    for o in range(field.scores.shape[1]):
        above += (field.scores[:, o][:, None] > c)
    pos = above + 1
    p_first = (pos == 1).mean(0)
    p_top2 = (pos <= 2).mean(0)
    prize = field.prize_by_pos[np.clip(pos, 1, field.n_total)]
    ev_gross = prize.mean(0)
    return {"p_first": p_first, "p_top2": p_top2, "ev_gross": ev_gross,
            "mean_score": cand_scores.mean(0)}
