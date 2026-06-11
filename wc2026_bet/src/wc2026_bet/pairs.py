"""Two-entry (pair) optimization and scenario-coverage analysis.

The pool pays only 1st (70%) and 2nd (30%); 3rd / last are refunds. With two
allowed entries the right decision variable is the *pair* (A, B), evaluated
jointly against the same field on the same simulations. We support two targets:

  * ``ev``      - maximize expected pair profit  E[prize(rank A) + prize(rank B)]
  * ``p_first`` - maximize  P(at least one of A, B finishes 1st)

Both share one engine; only the per-simulation payoff differs. Because prizes
are capped per position, jointly optimizing the pair automatically rewards
*de-correlating* the two entries' winning simulations (covering different
tournament worlds) - no hand-tuned diversity penalty is needed. A 1-2 lockout
(both entries top-2) collects the whole pool, so co-placement is the ceiling.
"""
from __future__ import annotations

import numpy as np

from .config import ENTRY_FEE_ILS
from .field import Field, finish_metrics
from .optimizer import SLOTS, Optimizer

_OBJ_KEY = {"ev": "pair_ev_gross", "p_first": "p_at_least_one_first",
            "p_top2": "p_at_least_one_top2"}


# --------------------------------------------------------------------------- #
# Joint ranking + pair finish metrics
# --------------------------------------------------------------------------- #
def _ranks_pair(a: np.ndarray, b: np.ndarray, field: Field, rng):
    """1-indexed finishing ranks of two entries inside the pool {a, b} + field."""
    a = a + rng.uniform(0, 1e-3, a.shape)
    b = b + rng.uniform(0, 1e-3, b.shape)
    fs = field.scores
    above_a = (fs > a[:, None]).sum(1)
    above_b = (fs > b[:, None]).sum(1)
    rank_a = above_a + 1 + (b > a)
    rank_b = above_b + 1 + (a > b)
    return rank_a, rank_b


def finish_metrics_pair(a: np.ndarray, b: np.ndarray, field: Field, rng=None) -> dict:
    """Joint metrics for a pair of entry score vectors (each [S])."""
    rng = rng or np.random.default_rng(0)
    rank_a, rank_b = _ranks_pair(a, b, field, rng)
    nt = field.n_total
    prize = field.prize_by_pos
    pa = prize[np.clip(rank_a, 1, nt)]
    pb = prize[np.clip(rank_b, 1, nt)]
    t2a, t2b = rank_a <= 2, rank_b <= 2
    return {
        "pair_ev_gross": float((pa + pb).mean()),
        "pair_ev_net": float((pa + pb).mean() - 2 * ENTRY_FEE_ILS),
        "p_at_least_one_first": float(((rank_a == 1) | (rank_b == 1)).mean()),
        "p_at_least_one_top2": float((t2a | t2b).mean()),
        "p_lockout": float((t2a & t2b).mean()),
    }


def _prep_partner(partner_score: np.ndarray, field: Field, rng):
    """Jitter the fixed partner once and precompute opponents-above counts."""
    p = (partner_score + rng.uniform(0, 1e-3, partner_score.shape)).astype(np.float32)
    above = np.zeros(len(p), dtype=np.int32)
    fs = field.scores
    for o in range(fs.shape[1]):
        above += (fs[:, o] > p)
    return p, above


def finish_metrics_pair_matrix(partner: np.ndarray, partner_above: np.ndarray,
                               cand_scores: np.ndarray, field: Field,
                               objective: str, rng=None) -> np.ndarray:
    """Pair objective for many candidate score vectors against a fixed partner.

    ``partner`` (already jittered, [S]) and ``partner_above`` ([S], opponents
    above the partner) come from :func:`_prep_partner`. ``cand_scores`` is
    [S, C]. Returns the pair objective per candidate ([C]).
    """
    rng = rng or np.random.default_rng(0)
    S, C = cand_scores.shape
    c = cand_scores + rng.uniform(0, 1e-3, cand_scores.shape).astype(np.float32)
    above_c = np.zeros((S, C), dtype=np.int32)
    fs = field.scores
    for o in range(fs.shape[1]):
        above_c += (fs[:, o][:, None] > c)
    p = partner[:, None]
    rank_c = above_c + 1 + (p > c)
    rank_p = partner_above[:, None] + 1 + (c > p)
    if objective == "p_first":
        return ((rank_c == 1) | (rank_p == 1)).mean(0)
    if objective == "p_top2":
        return ((rank_c <= 2) | (rank_p <= 2)).mean(0)
    nt = field.n_total
    prize = field.prize_by_pos
    return (prize[np.clip(rank_c, 1, nt)] + prize[np.clip(rank_p, 1, nt)]).mean(0)


# --------------------------------------------------------------------------- #
# Pair optimizer: alternating coordinate ascent with restarts
# --------------------------------------------------------------------------- #
class PairOptimizer:
    def __init__(self, contrib, field: Field, objective: str = "ev", seed: int = 11):
        self.opt = Optimizer(contrib, field)     # ownership_penalty=0; reuse helpers
        self.field = field
        self.objective = objective
        self.rng = np.random.default_rng(seed)

    def entry_score(self, entry: dict) -> np.ndarray:
        return self.opt.entry_score(entry)

    def _optimize_entry(self, entry: dict, partner: dict, max_iter: int = 5) -> dict:
        """Coordinate-ascent one entry's 7 slots with the partner held fixed."""
        p, p_above = _prep_partner(self.opt.entry_score(partner), self.field, self.rng)
        entry = dict(entry)
        for _ in range(max_iter):
            changed = False
            for name in SLOTS:
                base = None
                for nm in SLOTS:
                    if nm == name:
                        continue
                    col = self.opt.mat[nm][:, entry[nm]]
                    base = col.copy() if base is None else base + col
                cand_cols = self.opt.cand[name]
                cand_scores = base[:, None] + self.opt.mat[name][:, cand_cols]
                vals = finish_metrics_pair_matrix(p, p_above, cand_scores,
                                                  self.field, self.objective, self.rng)
                best = int(np.argmax(vals))
                gcol = int(cand_cols[best])
                if gcol != entry[name]:
                    entry[name] = gcol
                    changed = True
            if not changed:
                break
        return entry

    def optimize(self, seed_a: dict, seed_b: dict, rounds: int = 5):
        """Alternate optimizing A | B and B | A until the pair stops moving."""
        A, B = dict(seed_a), dict(seed_b)
        for _ in range(rounds):
            A2 = self._optimize_entry(A, B)
            B2 = self._optimize_entry(B, A2)
            if A2 == A and B2 == B:
                A, B = A2, B2
                break
            A, B = A2, B2
        return A, B

    def pair_value(self, A: dict, B: dict):
        # deterministic rng so pair-vs-pair comparisons across restarts are
        # stable (tie-break jitter is fixed, not redrawn each evaluation).
        m = finish_metrics_pair(self.opt.entry_score(A), self.opt.entry_score(B),
                                self.field, np.random.default_rng(0))
        return m[_OBJ_KEY[self.objective]], m

    def run(self, seeds_a: list[dict], seeds_b: list[dict], rounds: int = 5):
        """Try every (seed_a, seed_b) restart; return (best_pair, pool)."""
        best = None
        pool = []
        seen = set()
        for sa in seeds_a:
            for sb in seeds_b:
                A, B = self.optimize(sa, sb, rounds)
                key = frozenset((tuple(A[n] for n in SLOTS), tuple(B[n] for n in SLOTS)))
                v, m = self.pair_value(A, B)
                if key not in seen:
                    seen.add(key)
                    pool.append((A, B, v, m))
                if best is None or v > best[2]:
                    best = (A, B, v, m)
        return best, pool


# --------------------------------------------------------------------------- #
# Replacement options (swap-ins that keep the duo strong)
# --------------------------------------------------------------------------- #
def replacement_options(opt: Optimizer, field: Field, vary: dict, partner: dict,
                        objective: str, rng=None, max_per_slot: int = 4) -> dict:
    """For each slot of ``vary`` (partner held fixed), the best alternative picks
    ranked by the pair objective, each with the fraction of the slot-optimal
    value it retains - so the reader sees the next-best swap-ins and their cost.
    """
    rng = rng or np.random.default_rng(5)
    p, p_above = _prep_partner(opt.entry_score(partner), field, rng)
    out = {}
    for name in SLOTS:
        base = None
        for nm in SLOTS:
            if nm == name:
                continue
            col = opt.mat[nm][:, vary[nm]]
            base = col.copy() if base is None else base + col
        cand_cols = opt.cand[name]
        cand_scores = base[:, None] + opt.mat[name][:, cand_cols]
        vals = finish_metrics_pair_matrix(p, p_above, cand_scores, field, objective, rng)
        best_val = float(vals.max())
        cur_local = list(cand_cols).index(vary[name])
        cur_val = float(vals[cur_local])
        denom = best_val if abs(best_val) > 1e-9 else 1.0
        opts = []
        for o in np.argsort(-vals):
            gcol = int(cand_cols[o])
            if gcol == vary[name]:
                continue
            loc = list(opt.cand[name]).index(gcol)
            opts.append({"label": opt.labels[name][loc],
                         "value": float(vals[o]),
                         "retained": float(vals[o] / denom),
                         "delta_vs_current": float(vals[o] - cur_val)})
            if len(opts) >= max_per_slot:
                break
        out[name] = {"current": opt.entry_labels(vary)[name],
                     "current_value": cur_val, "best_value": best_val,
                     "alternatives": opts}
    return out


# --------------------------------------------------------------------------- #
# Scenario-coverage analysis for a chosen pair
# --------------------------------------------------------------------------- #
def _corr(x: np.ndarray, y: np.ndarray) -> float:
    x = x.astype(float)
    y = y.astype(float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def build_coverage(opt: Optimizer, field: Field, O: dict, A: dict, B: dict,
                   baseline: tuple | None = None, rng=None,
                   n_scatter: int = 2500, n_champs: int = 8) -> dict:
    """Everything the report needs to visualize how the pair covers scenarios."""
    rng = rng or np.random.default_rng(3)
    a = opt.entry_score(A).astype(np.float32)
    b = opt.entry_score(B).astype(np.float32)
    tl = opt.contrib.team_list
    S = len(a)

    # money-line per sim = 2nd-best opponent score; margin = entry - money-line.
    fs = field.scores
    field_top2 = np.partition(fs, -2, axis=1)[:, -2]
    margin_a = a - field_top2
    margin_b = b - field_top2
    idx = rng.choice(S, size=min(n_scatter, S), replace=False)
    scatter = {"a": [round(float(x), 2) for x in margin_a[idx]],
               "b": [round(float(x), 2) for x in margin_b[idx]]}

    rank_a, rank_b = _ranks_pair(a, b, field, rng)
    t2a, t2b = rank_a <= 2, rank_b <= 2
    inmoney = t2a | t2b
    union = {"a_only": float((t2a & ~t2b).mean()),
             "b_only": float((~t2a & t2b).mean()),
             "both": float((t2a & t2b).mean()),
             "neither": float((~t2a & ~t2b).mean())}

    # champion-conditioned coverage
    champ = O["won_cup"].argmax(1)
    freq = np.bincount(champ, minlength=len(tl))
    topk = [int(i) for i in np.argsort(-freq)[:n_champs] if freq[i] > 0]
    champ_rows = []
    for ci in topk:
        m = champ == ci
        if m.sum() == 0:
            continue
        champ_rows.append({"champion": tl[ci], "p_champ": float(m.mean()),
                           "p_inmoney": float(inmoney[m].mean()),
                           "carry_a": float(t2a[m].mean()),
                           "carry_b": float(t2b[m].mean())})
    other = ~np.isin(champ, topk)
    if other.sum() > 0:
        champ_rows.append({"champion": "Other", "p_champ": float(other.mean()),
                           "p_inmoney": float(inmoney[other].mean()),
                           "carry_a": float(t2a[other].mean()),
                           "carry_b": float(t2b[other].mean())})

    ma = finish_metrics(a, field, rng)
    mb = finish_metrics(b, field, rng)
    pair = finish_metrics_pair(a, b, field, rng)
    marginal = {
        "single_a_p_first": ma["p_first"], "single_b_p_first": mb["p_first"],
        "best_single_p_first": max(ma["p_first"], mb["p_first"]),
        "pair_p_first": pair["p_at_least_one_first"],
        "single_a_ev": ma["ev_gross"], "single_b_ev": mb["ev_gross"],
        "best_single_ev": max(ma["ev_gross"], mb["ev_gross"]),
        "pair_ev": pair["pair_ev_gross"],
    }

    out = {"scatter": scatter, "union": union, "champions": champ_rows,
           "win_corr": _corr(t2a, t2b), "marginal": marginal,
           "pair_metrics": pair}

    # scenario matrix: median rank per entry under the most likely champions
    scen = []
    for ci in topk[:6]:
        m = champ == ci
        if m.sum() < 20:
            continue
        scen.append({"champion": tl[ci],
                     "median_rank_a": float(np.median(rank_a[m])),
                     "median_rank_b": float(np.median(rank_b[m])),
                     "p_inmoney": float(inmoney[m].mean())})
    out["scenario_matrix"] = scen

    if baseline is not None:
        ba, bb = baseline
        sa = opt.entry_score(ba).astype(np.float32)
        sb = opt.entry_score(bb).astype(np.float32)
        ra, rb = _ranks_pair(sa, sb, field, rng)
        bt2a, bt2b = ra <= 2, rb <= 2
        bpair = finish_metrics_pair(sa, sb, field, rng)
        out["baseline"] = {
            "win_corr": _corr(bt2a, bt2b),
            "union": {"a_only": float((bt2a & ~bt2b).mean()),
                      "b_only": float((~bt2a & bt2b).mean()),
                      "both": float((bt2a & bt2b).mean()),
                      "neither": float((~bt2a & ~bt2b).mean())},
            "pair_ev": bpair["pair_ev_gross"],
            "p_at_least_one_first": bpair["p_at_least_one_first"],
        }
    return out
