"""Stage 2 - the full analysis pipeline (reads only data/processed).

Steps: load data -> fit match model -> calibrate spread + golden-boot scale ->
run the Monte-Carlo tournament -> per-team/player summaries -> contribution
matrices + attractiveness tables -> field model -> correlation-aware optimizer
-> final SAFE and RISKY entries + top-10 ranked alternatives. All artifacts are
written to results/ for the report and for re-use.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import (FieldConfig, N_SIMULATIONS, RESULTS_DIR,
                               ROUND_NAMES, DATA_PROCESSED)
from wc2026_bet.calibration import (apply_strength_offsets,
                                    calibrate_player_shares,
                                    calibrate_spread, calibrate_team_strengths,
                                    compute_golden_boot_scale,
                                    golden_boot_target, simulate_title_probs)
from wc2026_bet.data_io import apply_share_factors, load_calibration
from wc2026_bet.contributions import attractiveness_tables, build_contributions
from wc2026_bet.data_io import load_dataset
from wc2026_bet.field import Field, build_field, finish_metrics
from wc2026_bet.model import fit_match_model
from wc2026_bet.optimizer import SLOTS, Optimizer
from wc2026_bet.scenarios import build_scenario, entry_top2_mask
from wc2026_bet.simulate import Simulator

CAL_SIMS = 20_000
FINAL_SIMS = N_SIMULATIONS


def jdump(obj, path):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def main():
    ds = load_dataset()
    elo = {r.team: r.elo for r in ds.teams.itertuples()}
    model0 = fit_match_model(ds.results, elo)

    cache = DATA_PROCESSED / "calibration.json"
    recal = os.environ.get("RECALIBRATE") == "1"
    if cache.exists() and not recal:
        cal = load_calibration()
        spread = cal["strength_spread"]
        offsets = cal.get("strength_offsets", {})
        share_factor = cal.get("player_share_factor", {})
        print(f"Using cached calibration: spread={spread:.3f}, "
              f"{len(offsets)} strength offsets, {len(share_factor)} GB factors "
              f"(set RECALIBRATE=1 to re-fit)")
    else:
        print("Calibrating strength spread vs Opta ...")
        cal = calibrate_spread(ds, model0, n_sims=CAL_SIMS)
        spread = cal["best_spread"]
        print(f"  best spread = {spread:.3f}  (sse={cal['best_sse']:.5f})")
        model_s = replace(model0, spread=spread)

        print("Calibrating per-team strength vs market 'to advance' odds ...")
        cstr = calibrate_team_strengths(ds, model_s, ds.market_advance,
                                        n_sims=12_000, rounds=8)
        offsets = cstr["offsets"]
        cal["advance_trace"] = cstr["trace"]
        print(f"  advance fit: max|err| {cstr['trace'][0]['max_abs_advance_err']:.3f}"
              f" -> {cstr['trace'][-1]['max_abs_advance_err']:.3f}")

        print("Calibrating per-player goal shares vs market Golden Boot ...")
        model_so = apply_strength_offsets(model_s, offsets)
        Ocal = Simulator(ds, model_so, seed=99).run(CAL_SIMS)
        target_p = golden_boot_target(ds)
        factor = calibrate_player_shares(ds, Ocal, target_p)
        share_factor = {n: float(f) for n, f in zip(ds.players["scorer"], factor)}

    # Apply the full calibration: spread + per-team offsets + GB share factors.
    apply_share_factors(ds, share_factor)
    model = apply_strength_offsets(replace(model0, spread=spread), offsets)

    print(f"Running {FINAL_SIMS:,} tournament simulations ...")
    sim = Simulator(ds, model, seed=2026)
    O = sim.run(FINAL_SIMS)
    gb_scale = compute_golden_boot_scale(ds, O)
    jdump({"strength_spread": spread, "golden_boot_scale": gb_scale,
           "strength_offsets": offsets, "player_share_factor": share_factor,
           "best_sse": cal.get("best_sse"), "fit_teams": cal.get("fit_teams"),
           "anchors": cal.get("anchors"), "trace": cal.get("trace"),
           "advance_trace": cal.get("advance_trace")},
          DATA_PROCESSED / "calibration.json")

    # ---- team / player summaries ------------------------------------------ #
    tl = ds.team_list
    rr = O["round_reached"]
    team_rows = []
    for i, t in enumerate(tl):
        dist = {ROUND_NAMES[r]: float((rr[:, i] == r).mean()) for r in ROUND_NAMES}
        team_rows.append({
            "team": t, "elo": elo[t],
            "P_advance_R32": float(O["advanced"][:, i].mean()),
            "P_QF": float((rr[:, i] >= 3).mean()),
            "P_SF": float((rr[:, i] >= 4).mean()),
            "P_final": float(O["made_final"][:, i].mean()),
            "P_title": float(O["won_cup"][:, i].mean()),
            "exp_gf": float(O["gf"][:, i].mean()),
            "exp_ga": float(O["ga"][:, i].mean()),
            "exp_games": float(O["games"][:, i].mean()),
            **{f"round_{k}": v for k, v in dist.items()},
        })
    team_summary = pd.DataFrame(team_rows).sort_values("P_title", ascending=False)
    team_summary.to_csv(RESULTS_DIR / "team_summary.csv", index=False)

    gb = O["golden_boot"]
    gb_p = np.bincount(gb, minlength=len(O["player_names"])) / FINAL_SIMS
    player_summary = pd.DataFrame({
        "scorer": O["player_names"], "team": ds.players["team"],
        "exp_goals": O["player_goals"].mean(0), "P_golden_boot": gb_p,
    }).sort_values("P_golden_boot", ascending=False)
    player_summary.to_csv(RESULTS_DIR / "player_summary.csv", index=False)

    # ---- contributions + attractiveness ----------------------------------- #
    contrib = build_contributions(ds, O, golden_boot_scale=gb_scale)
    tables = attractiveness_tables(ds, contrib, O)
    for name, df in tables.items():
        df.to_csv(RESULTS_DIR / f"attractiveness_{name}.csv", index=False)

    # ---- field + optimizer ------------------------------------------------- #
    field = build_field(ds, contrib, O, FieldConfig())
    safe_opt = Optimizer(contrib, field, ownership_penalty=0.0)
    # Risky: maximise P(1st) with a MILD contrarian tilt so the entry is both a
    # genuine title threat and one the chalk-picking field is unlikely to copy.
    risky_opt = Optimizer(contrib, field, ownership_penalty=0.1)

    print("Optimizing SAFE entries (expected payout) ...")
    safe_rank = safe_opt.rank("ev", top_n=10)
    safe = safe_rank[0]
    print("Optimizing RISKY entries (P(1st), contrarian) ...")
    risky_rank = risky_opt.rank("p_first", top_n=10,
                                must_differ_from=safe["entry"], min_diff_slots=3)
    # reference rankings
    mean_rank = safe_opt.rank("mean", top_n=10)
    ptop2_rank = safe_opt.rank("p_top2", top_n=10)

    def serialize(rank):
        out = []
        for r in rank:
            out.append({
                "picks": r["labels"],
                "mean_score": round(r["mean_score"], 2),
                "p10": round(r["p10"], 1), "p50": round(r["p50"], 1),
                "p90": round(r["p90"], 1),
                "p_first": round(r["p_first"], 4),
                "p_top2": round(r["p_top2"], 4),
                "ev_gross": round(r["ev_gross"], 1),
                "ev_net": round(r["ev_gross"] - 50, 1),
                "field_ownership_sum": round(r["own_total"], 3),
            })
        return out

    # score-distribution histograms for the two headline entries
    def hist(entry):
        s = safe_opt.entry_score(entry)
        counts, edges = np.histogram(s, bins=40)
        return {"edges": [round(float(e), 2) for e in edges],
                "counts": [int(c) for c in counts],
                "mean": float(s.mean()), "p10": float(np.percentile(s, 10)),
                "p50": float(np.percentile(s, 50)), "p90": float(np.percentile(s, 90))}

    deliverable = {
        "config": {"n_sims": FINAL_SIMS, "strength_spread": spread,
                   "golden_boot_scale": round(gb_scale, 3),
                   "field": FieldConfig().__dict__},
        "safe_entry": serialize([safe])[0],
        "risky_entry": serialize([risky_rank[0]])[0],
        "safe_top10": serialize(safe_rank),
        "risky_top10": serialize(risky_rank),
        "mean_top10": serialize(mean_rank),
        "ptop2_top10": serialize(ptop2_rank),
        "safe_hist": hist(safe["entry"]),
        "risky_hist": hist(risky_rank[0]["entry"]),
        "ownership": field.ownership,
    }
    jdump(deliverable, RESULTS_DIR / "entries.json")

    # ---- most-plausible tournament projections (overall + per entry) ------- #
    print("Building tournament scenario projections ...")
    team_picks = lambda r: list({r["labels"][k] for k in
                                 ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding"]})
    player_pick = lambda r: r["labels"]["top_scorer"]
    scen = {
        "overall": build_scenario(ds, O, np.ones(FINAL_SIMS, bool)),
        "safe": build_scenario(ds, O, entry_top2_mask(safe_opt, field, safe["entry"]),
                               team_picks(safe), player_pick(safe)),
        "risky": build_scenario(ds, O, entry_top2_mask(risky_opt, field, risky_rank[0]["entry"]),
                                team_picks(risky_rank[0]), player_pick(risky_rank[0])),
        "mean": build_scenario(ds, O, entry_top2_mask(safe_opt, field, mean_rank[0]["entry"]),
                               team_picks(mean_rank[0]), player_pick(mean_rank[0])),
        "ptop2": build_scenario(ds, O, entry_top2_mask(safe_opt, field, ptop2_rank[0]["entry"]),
                                team_picks(ptop2_rank[0]), player_pick(ptop2_rank[0])),
    }
    labels = {"overall": "Overall (average simulation)",
              "safe": f"SAFE - {safe['labels']['tier_A']} + {safe['labels']['top_scorer']}",
              "risky": f"RISKY - {risky_rank[0]['labels']['tier_A']} + {risky_rank[0]['labels']['top_scorer']}",
              "mean": f"Reference: max mean - {mean_rank[0]['labels']['tier_A']} + {mean_rank[0]['labels']['top_scorer']}",
              "ptop2": f"Reference: max P(top-2) - {ptop2_rank[0]['labels']['tier_A']} + {ptop2_rank[0]['labels']['top_scorer']}"}
    jdump({"labels": labels, "scenarios": scen}, RESULTS_DIR / "scenarios.json")

    print("\n=== SAFE entry (max expected payout) ===")
    for k, v in safe["labels"].items():
        print(f"  {k:11s}: {v}")
    print(f"  mean={safe['mean_score']:.1f}  P(top2)={safe['p_top2']:.1%}  "
          f"P(1st)={safe['p_first']:.1%}  EV_net={safe['ev_gross']-50:.0f} ILS")
    print("\n=== RISKY entry (max P(1st), contrarian) ===")
    rk = risky_rank[0]
    for k, v in rk["labels"].items():
        print(f"  {k:11s}: {v}")
    print(f"  mean={rk['mean_score']:.1f}  P(top2)={rk['p_top2']:.1%}  "
          f"P(1st)={rk['p_first']:.1%}  EV_net={rk['ev_gross']-50:.0f} ILS")
    print(f"\nWrote deliverables to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
