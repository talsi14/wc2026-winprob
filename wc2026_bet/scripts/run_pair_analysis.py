"""Stage 2b - two-entry (pair) optimization.

Reuses the exact seeded pipeline of run_analysis.py (same model, calibration and
50k simulations, so all team-level numbers match report/index.html), then
optimizes a PAIR of entries jointly under two targets:

  * Target A - expected pair profit   (objective "ev")
  * Target B - P(at least one is 1st)  (objective "p_first")

Writes results/pair_entries.json and results/pair_coverage.json.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import (ENTRY_FEE_ILS, FieldConfig, N_SIMULATIONS,
                               PRIZE_FIRST_FRAC, PRIZE_SECOND_FRAC, RESULTS_DIR,
                               DATA_PROCESSED)
from wc2026_bet.calibration import (apply_strength_offsets,
                                    compute_golden_boot_scale)
from wc2026_bet.contributions import build_contributions
from wc2026_bet.data_io import (apply_share_factors, load_calibration,
                                load_dataset)
from wc2026_bet.field import build_field, finish_metrics
from wc2026_bet.model import fit_match_model
from wc2026_bet.optimizer import SLOTS, Optimizer
from wc2026_bet.pairs import (PairOptimizer, build_coverage, finish_metrics_pair,
                              replacement_options)
from wc2026_bet.simulate import Simulator

FINAL_SIMS = N_SIMULATIONS
TARGETS = {"A": ("ev", "Expected pair profit"),
           "B": ("p_first", "P(at least one finishes 1st)")}


def jdump(obj, path):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def serialize(opt: Optimizer, field, entry: dict, rng) -> dict:
    s = opt.entry_score(entry)
    m = finish_metrics(s, field, rng)
    return {"picks": opt.entry_labels(entry),
            "mean_score": round(float(s.mean()), 2),
            "p10": round(float(np.percentile(s, 10)), 1),
            "p50": round(float(np.percentile(s, 50)), 1),
            "p90": round(float(np.percentile(s, 90)), 1),
            "p_first": round(float(m["p_first"]), 4),
            "p_top2": round(float(m["p_top2"]), 4),
            "ev_gross": round(float(m["ev_gross"]), 1),
            "own_total": round(float(opt._own_total(entry)), 3)}


def hist(opt: Optimizer, entry: dict) -> dict:
    s = opt.entry_score(entry)
    counts, edges = np.histogram(s, bins=40)
    return {"edges": [round(float(e), 2) for e in edges],
            "counts": [int(c) for c in counts],
            "mean": float(s.mean()), "p10": float(np.percentile(s, 10)),
            "p50": float(np.percentile(s, 50)), "p90": float(np.percentile(s, 90))}


def main():
    ds = load_dataset()
    elo = {r.team: r.elo for r in ds.teams.itertuples()}
    model0 = fit_match_model(ds.results, elo)

    cache = DATA_PROCESSED / "calibration.json"
    if not cache.exists():
        raise SystemExit("Run run_analysis.py first to produce calibration.json")
    cal = load_calibration()
    spread = cal["strength_spread"]
    offsets = cal.get("strength_offsets", {})
    share_factor = cal.get("player_share_factor", {})
    print(f"Using cached calibration: spread={spread:.3f}, "
          f"{len(offsets)} strength offsets, {len(share_factor)} GB factors")

    # Apply the identical calibration used by run_analysis so all team/player
    # numbers match report/index.html.
    apply_share_factors(ds, share_factor)
    model = apply_strength_offsets(replace(model0, spread=spread), offsets)

    print(f"Running {FINAL_SIMS:,} tournament simulations (seed=2026) ...")
    sim = Simulator(ds, model, seed=2026)
    O = sim.run(FINAL_SIMS)
    gb_scale = compute_golden_boot_scale(ds, O)

    contrib = build_contributions(ds, O, golden_boot_scale=gb_scale)
    field = build_field(ds, contrib, O, FieldConfig())
    base = Optimizer(contrib, field)
    rng = np.random.default_rng(2026)

    # strong single-entry seeds (also the "naive two best singles" baseline)
    print("Seeding single-entry optima ...")
    ev_single = base.coordinate_ascent("ev", base.greedy_mean_seed())
    pf_single = base.coordinate_ascent("p_first", base.greedy_mean_seed())
    # contrarian seeds: strong but low field-ownership (good complementary partners)
    contra = Optimizer(contrib, field, ownership_penalty=0.5)
    contra_pf = contra.coordinate_ascent("p_first", contra.greedy_mean_seed())
    contra_ev = contra.coordinate_ascent("ev", contra.random_seed())
    rand_seeds = [base.random_seed() for _ in range(5)]
    baseline_pair = (ev_single, pf_single)

    targets_out = {}
    coverage_out = {}
    frontier = []
    chosen = {}
    for tkey, (obj, label) in TARGETS.items():
        print(f"Optimizing pair for Target {tkey} ({label}) ...")
        po = PairOptimizer(contrib, field, objective=obj)
        seeds_a = [ev_single, pf_single, contra_pf]
        seeds_b = [pf_single, ev_single, contra_pf, contra_ev] + rand_seeds
        best, pool = po.run(seeds_a, seeds_b, rounds=4)
        A, B, _, m = best
        chosen[tkey] = (A, B)

        repA = replacement_options(base, field, A, B, obj, rng)
        repB = replacement_options(base, field, B, A, obj, rng)
        targets_out[tkey] = {
            "label": label, "objective": obj,
            "entries": [serialize(base, field, A, rng), serialize(base, field, B, rng)],
            "pair": {k: round(v, 4) if "p_" in k else round(v, 1)
                     for k, v in m.items()},
            "replacements": [repA, repB],
            "hist": [hist(base, A), hist(base, B)],
        }
        coverage_out[tkey] = build_coverage(base, field, O, A, B,
                                            baseline=baseline_pair, rng=rng)
        for (pa, pb, _, pm) in pool:
            frontier.append({"target": tkey,
                             "ev": round(pm["pair_ev_gross"], 1),
                             "p_first": round(pm["p_at_least_one_first"], 4)})

    # ---- personal-preference variant: swap Spain -> Argentina in Entry 2 ---- #
    # The recommended Target-A pair anchors Entry 2 on the tournament favourite;
    # the user roots for Argentina and wants to feel invested, so we also carry a
    # fully-scored alternative where Entry 2's Spain picks (tier-A + the doubled
    # scoring slot) become Argentina, keeping everything else fixed.
    A_main, B_main = chosen["A"]
    e1_lbls = base.entry_labels(B_main)
    swap_from = e1_lbls["tier_A"]
    swap_to = "Argentina"
    if swap_to in ds.team_index and swap_from != swap_to:
        ai = ds.team_index[swap_to]
        B_alt = dict(B_main)
        swapped = []
        for slot in ("tier_A", "scoring"):
            if e1_lbls[slot] == swap_from:
                B_alt[slot] = ai
                swapped.append(slot)
        vm = finish_metrics_pair(base.entry_score(A_main), base.entry_score(B_alt), field, rng)
        targets_out["A"]["variant_argentina"] = {
            "swap": {"from": swap_from, "to": swap_to, "slots": swapped},
            "entries": [serialize(base, field, A_main, rng),
                        serialize(base, field, B_alt, rng)],
            "pair": {k: round(v, 4) if "p_" in k else round(v, 1) for k, v in vm.items()},
            "replacements": [replacement_options(base, field, A_main, B_alt, "ev", rng),
                             replacement_options(base, field, B_alt, A_main, "ev", rng)],
            "hist": [hist(base, A_main), hist(base, B_alt)],
        }
        coverage_out["A_argentina"] = build_coverage(base, field, O, A_main, B_alt,
                                                     baseline=baseline_pair, rng=rng)

    bpair = finish_metrics_pair(base.entry_score(ev_single),
                                base.entry_score(pf_single), field, rng)
    deliverable = {
        "config": {"n_sims": FINAL_SIMS, "strength_spread": round(spread, 3),
                   "entry_fee": ENTRY_FEE_ILS, "prize_first_frac": PRIZE_FIRST_FRAC,
                   "prize_second_frac": PRIZE_SECOND_FRAC,
                   "field": FieldConfig().__dict__},
        "targets": targets_out,
        "baseline": {"label": "Two best independent singles (old SAFE+RISKY style)",
                     "entries": [serialize(base, field, ev_single, rng),
                                 serialize(base, field, pf_single, rng)],
                     "pair": {k: round(v, 4) if "p_" in k else round(v, 1)
                              for k, v in bpair.items()}},
        "frontier": frontier,
    }
    jdump(deliverable, RESULTS_DIR / "pair_entries.json")
    jdump(coverage_out, RESULTS_DIR / "pair_coverage.json")

    for tkey, (obj, label) in TARGETS.items():
        A, B = chosen[tkey]
        print(f"\n=== Target {tkey}: {label} ===")
        for nm, ent in [("Entry 1", A), ("Entry 2", B)]:
            lbls = base.entry_labels(ent)
            print(f"  {nm}: " + ", ".join(f"{k}={v}" for k, v in lbls.items()))
        pm = finish_metrics_pair(base.entry_score(A), base.entry_score(B), field, rng)
        print(f"  pair EV_net={pm['pair_ev_net']:.0f} ILS  "
              f"P(>=1 1st)={pm['p_at_least_one_first']:.1%}  "
              f"P(>=1 top2)={pm['p_at_least_one_top2']:.1%}  "
              f"P(lockout)={pm['p_lockout']:.1%}")
    print(f"\nWrote pair deliverables to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
