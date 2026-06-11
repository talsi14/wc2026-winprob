"""Correlation-aware entry optimizer.

An entry's score distribution is the per-simulation sum of its seven chosen
contribution columns, so summing vectors captures correlation automatically
(teams that can meet -> negative covariance; doubling a team -> positive
covariance + higher variance). We optimize several objectives over this
distribution:

  * ``mean``   - raw expected bet points (additive; exact per-slot argmax).
  * ``ev``     - expected pool payout (uses the field model).
  * ``p_top2`` - probability of finishing 1st or 2nd (the "safe" objective).
  * ``p_first``- probability of finishing 1st (the "risky"/contrarian objective).
  * ``floor``  - a high-floor risk-adjusted score (mean - k*downside).

Search = greedy coordinate ascent from several seeds, then a top-K-per-slot
Cartesian refinement around the best optimum, returning a de-duplicated ranked
top-N list (not just the single best).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np

from .contributions import Contributions
from .field import Field, finish_metrics, finish_metrics_matrix

SLOTS = ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding", "top_scorer"]

# map objective name -> key in finish_metrics_matrix output
_FM_KEY = {"ev": "ev_gross", "p_first": "p_first", "p_top2": "p_top2"}


@dataclass
class Optimizer:
    contrib: Contributions
    field: Field
    ownership_penalty: float = 0.0       # subtract penalty*field-ownership (contrarian)

    def __post_init__(self):
        c = self.contrib
        self.mat = {
            "tier_A": c.tier, "tier_B": c.tier, "tier_C": c.tier, "tier_D": c.tier,
            "scoring": c.scoring, "conceding": c.conceding, "top_scorer": c.topscorer,
        }
        self.cand = {name: self.field.slots[name].cand_idx for name in SLOTS}
        self.labels = {name: self.field.slots[name].labels for name in SLOTS}
        self.rng = np.random.default_rng(7)
        # ownership vector aligned to each slot's candidate list
        self.own = {}
        for name in SLOTS:
            o = self.field.ownership[name]
            self.own[name] = np.array([o[self.field.slots[name].labels[i]]
                                       for i in range(len(self.cand[name]))])

    # ---- entry helpers ----------------------------------------------------- #
    def entry_score(self, entry: dict) -> np.ndarray:
        s = None
        for name in SLOTS:
            col = self.mat[name][:, entry[name]]
            s = col.copy() if s is None else s + col
        return s

    def entry_labels(self, entry: dict) -> dict:
        out = {}
        for name in SLOTS:
            gcol = entry[name]
            loc = list(self.cand[name]).index(gcol)
            out[name] = self.labels[name][loc]
        return out

    def _own_total(self, entry: dict) -> float:
        tot = 0.0
        for name in SLOTS:
            loc = list(self.cand[name]).index(entry[name])
            tot += self.own[name][loc]
        return tot

    # ---- objective --------------------------------------------------------- #
    def objective(self, score: np.ndarray, name: str) -> float:
        if name == "mean":
            return float(score.mean())
        if name == "floor":
            return float(score.mean() - 0.5 * (score.mean() - np.percentile(score, 10)))
        m = finish_metrics(score, self.field, self.rng)
        return m[name if name in m else _FM_KEY[name]]

    # ---- coordinate ascent ------------------------------------------------- #
    def _best_for_slot(self, entry: dict, name: str, objective: str):
        """Return (best_global_col, best_obj) optimizing one slot, others fixed."""
        base = None
        for nm in SLOTS:
            if nm == name:
                continue
            col = self.mat[nm][:, entry[nm]]
            base = col.copy() if base is None else base + col
        cand_cols = self.cand[name]
        cand_scores = base[:, None] + self.mat[name][:, cand_cols]   # [S, C]
        if objective == "mean":
            vals = cand_scores.mean(0)
        elif objective == "floor":
            mean = cand_scores.mean(0)
            p10 = np.percentile(cand_scores, 10, axis=0)
            vals = mean - 0.5 * (mean - p10)
        else:
            fm = finish_metrics_matrix(cand_scores, self.field, self.rng)
            vals = fm[_FM_KEY[objective]]
        if self.ownership_penalty > 0:
            vals = vals - self.ownership_penalty * self.own[name]
        best = int(np.argmax(vals))
        return int(cand_cols[best]), float(vals[best])

    def coordinate_ascent(self, objective: str, seed_entry: dict, max_iter: int = 6):
        entry = dict(seed_entry)
        for _ in range(max_iter):
            changed = False
            for name in SLOTS:
                col, _ = self._best_for_slot(entry, name, objective)
                if col != entry[name]:
                    entry[name] = col
                    changed = True
            if not changed:
                break
        return entry

    def random_seed(self) -> dict:
        return {name: int(self.rng.choice(self.cand[name])) for name in SLOTS}

    def greedy_mean_seed(self) -> dict:
        entry = {}
        for name in SLOTS:
            vals = self.mat[name][:, self.cand[name]].mean(0)
            entry[name] = int(self.cand[name][int(np.argmax(vals))])
        return entry

    # ---- ranked top-N ------------------------------------------------------ #
    def rank(self, objective: str, top_n: int = 10, n_restarts: int = 8,
             per_slot_k=(3, 3, 3, 3, 3, 3, 4), must_differ_from: dict | None = None,
             min_diff_slots: int = 2):
        # 1) find a strong optimum from several seeds
        seeds = [self.greedy_mean_seed()] + [self.random_seed() for _ in range(n_restarts)]
        optima = [self.coordinate_ascent(objective, s) for s in seeds]
        # pick the best optimum by objective
        best = max(optima, key=lambda e: self.objective(self.entry_score(e), objective))

        # 2) top-K per slot around the optimum -> Cartesian refinement pool
        topk_cols = {}
        for ki, name in enumerate(SLOTS):
            base = None
            for nm in SLOTS:
                if nm == name:
                    continue
                col = self.mat[nm][:, best[nm]]
                base = col.copy() if base is None else base + col
            cand_cols = self.cand[name]
            cand_scores = base[:, None] + self.mat[name][:, cand_cols]
            if objective == "mean":
                vals = cand_scores.mean(0)
            elif objective == "floor":
                mean = cand_scores.mean(0); p10 = np.percentile(cand_scores, 10, axis=0)
                vals = mean - 0.5 * (mean - p10)
            else:
                vals = finish_metrics_matrix(cand_scores, self.field, self.rng)[_FM_KEY[objective]]
            if self.ownership_penalty > 0:
                vals = vals - self.ownership_penalty * self.own[name]
            order = np.argsort(-vals)[:per_slot_k[ki]]
            topk_cols[name] = [int(cand_cols[o]) for o in order]

        pool = set()
        for combo in product(*[topk_cols[n] for n in SLOTS]):
            pool.add(combo)
        for e in optima:
            pool.add(tuple(e[n] for n in SLOTS))

        # 3) evaluate the pool (chunked), with optional difference constraint
        entries = [dict(zip(SLOTS, c)) for c in pool]
        if must_differ_from is not None:
            ref = must_differ_from
            entries = [e for e in entries
                       if sum(e[n] != ref[n] for n in SLOTS) >= min_diff_slots]
        results = self._evaluate_entries(entries, objective)
        results.sort(key=lambda r: -r["obj"])
        # de-duplicate identical pick-sets (already unique) and trim
        return results[:top_n]

    def _evaluate_entries(self, entries: list[dict], objective: str, chunk=150):
        out = []
        for start in range(0, len(entries), chunk):
            batch = entries[start:start + chunk]
            sc = np.empty((self.contrib.tier.shape[0], len(batch)), dtype=np.float32)
            for j, e in enumerate(batch):
                sc[:, j] = self.entry_score(e)
            fm = finish_metrics_matrix(sc, self.field, self.rng)
            for j, e in enumerate(batch):
                score = sc[:, j]
                if objective == "mean":
                    obj = float(score.mean())
                elif objective == "floor":
                    obj = self.objective(score, "floor")
                else:
                    obj = float(fm[_FM_KEY[objective]][j])
                if self.ownership_penalty > 0 and objective not in ("mean", "floor"):
                    obj = obj - self.ownership_penalty * self._own_total(e)
                out.append({
                    "entry": e, "labels": self.entry_labels(e), "obj": obj,
                    "mean_score": float(score.mean()),
                    "p10": float(np.percentile(score, 10)),
                    "p50": float(np.percentile(score, 50)),
                    "p90": float(np.percentile(score, 90)),
                    "p_first": float(fm["p_first"][j]),
                    "p_top2": float(fm["p_top2"][j]),
                    "ev_gross": float(fm["ev_gross"][j]),
                    "own_total": self._own_total(e),
                })
        return out
