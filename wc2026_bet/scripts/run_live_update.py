"""Stage 2-4 - the live win-probability engine (reads data/live + data/processed).

For a given timestamp it: refreshes / reuses the calibrated power ranking,
conditions the 50K-sim engine on the frozen tournament state, scores all 53
real entries per sim, ranks them against each other, applies the prize ladder
with the prize-splitting tiebreak, and writes per-entry probabilities + the
deltas vs the previous timestamp.

Outputs:
  data/live/win_probabilities_<TS>.json   (full, per-entry + champion matrix)
  results/live_latest.json                (stable pointer for the report/site)
  data/processed/calibration_<TS>.json     (the power-ranking snapshot used)

Usage:
  python3 scripts/run_live_update.py [--ts ...] [--state data/live/state_X.json]
                                     [--sims 50000] [--recalibrate]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.calibration import (apply_strength_offsets,
                                    calibrate_player_shares, calibrate_spread,
                                    calibrate_team_strengths,
                                    compute_golden_boot_scale,
                                    golden_boot_target)
from wc2026_bet.config import (DATA_LIVE, DATA_PROCESSED, N_SIMULATIONS,
                               RESULTS_DIR)
from wc2026_bet.contributions import build_contributions
from wc2026_bet.data_io import apply_share_factors, load_calibration
from wc2026_bet.live import (current_points_breakdown, load_entries,
                             load_live_dataset, rank_and_metrics, score_entries)
from wc2026_bet.model import fit_match_model
from wc2026_bet.simulate import KnownState, Simulator


def jdump(obj, path):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def build_calibration(ds, model0, ts: str, recalibrate: bool) -> dict:
    """Reuse the cached power ranking (fast) unless --recalibrate. Either way,
    snapshot it to calibration_<TS>.json so each run is reproducible."""
    cache = DATA_PROCESSED / "calibration.json"
    if cache.exists() and not recalibrate:
        cal = load_calibration()
        print(f"Power ranking: cached (spread={cal['strength_spread']:.3f}, "
              f"{len(cal.get('strength_offsets', {}))} offsets). "
              "Use --recalibrate to re-fit vs refreshed odds.")
    else:
        print("Recalibrating power ranking vs refreshed odds ...")
        cs = calibrate_spread(ds, model0, n_sims=20_000)
        spread = cs["best_spread"]
        model_s = replace(model0, spread=spread)
        cstr = calibrate_team_strengths(ds, model_s, ds.market_advance,
                                        n_sims=12_000, rounds=8)
        offsets = cstr["offsets"]
        model_so = apply_strength_offsets(model_s, offsets)
        Ocal = Simulator(ds, model_so, seed=99).run(20_000)
        factor = calibrate_player_shares(ds, Ocal, golden_boot_target(ds))
        share_factor = {n: float(f) for n, f in zip(ds.players["scorer"], factor)}
        cal = {"strength_spread": spread, "strength_offsets": offsets,
               "player_share_factor": share_factor,
               "advance_trace": cstr["trace"], "best_sse": cs["best_sse"]}
        jdump(cal, cache)
        print(f"  best spread={spread:.3f}; "
              f"advance max|err| -> {cstr['trace'][-1]['max_abs_advance_err']:.3f}")
    jdump(cal, DATA_PROCESSED / f"calibration_{ts}.json")
    return cal


def champion_matrix(ranks, O, ds, names, n_champ: int = 10) -> dict:
    """P(entry wins the pool | team X is champion) for the leading champions.
    ``names`` is the entry order matching the columns of ``ranks``; the matrix is
    keyed by entry name so the report can re-sort entries freely."""
    title = O["won_cup"].mean(0)
    champs = [ds.team_list[i] for i in np.argsort(-title)[:n_champ] if title[i] > 0]
    mat = {}
    for c in champs:
        ci = ds.team_index[c]
        mask = O["won_cup"][:, ci]
        if mask.sum() < 20:
            continue
        cond = (ranks[mask] == 1).mean(0)            # [N] P(entry first | champ c)
        mat[c] = {nm: round(float(cond[i]), 4) for i, nm in enumerate(names)}
    return {"champions": list(mat.keys()),
            "p_title": {c: round(float(title[ds.team_index[c]]), 4) for c in mat},
            "matrix": mat}


def previous_metrics(ts: str) -> dict | None:
    """Most recent win_probabilities_*.json strictly before this ts (by name)."""
    files = sorted(DATA_LIVE.glob("win_probabilities_*.json"))
    prev = [f for f in files if f.stem.replace("win_probabilities_", "") < ts]
    if not prev:
        return None
    data = json.loads(prev[-1].read_text())
    return {e["name"]: e for e in data["entries"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M"))
    ap.add_argument("--state", default=str(DATA_LIVE / "state_latest.json"))
    ap.add_argument("--sims", type=int, default=N_SIMULATIONS)
    ap.add_argument("--recalibrate", action="store_true")
    args = ap.parse_args()
    ts = args.ts

    ds = load_live_dataset()
    entries = load_entries()
    elo = {r.team: r.elo for r in ds.teams.itertuples()}
    model0 = fit_match_model(ds.results, elo)

    cal = build_calibration(ds, model0, ts, args.recalibrate)
    apply_share_factors(ds, cal.get("player_share_factor", {}))
    model = apply_strength_offsets(
        replace(model0, spread=cal["strength_spread"]),
        cal.get("strength_offsets", {}))

    state = json.loads(Path(args.state).read_text())
    known = KnownState.from_state(ds, state)
    print(f"Conditioning on state {ts}: group {state.get('n_group_played',0)}/72 "
          f"played, KO {state.get('n_ko_played',0)}, "
          f"complete={state.get('group_stage_complete')}")

    print(f"Running {args.sims:,} conditioned simulations ...")
    O = Simulator(ds, model, seed=2026).run(args.sims, known=known)
    gb_scale = compute_golden_boot_scale(ds, O)
    contrib = build_contributions(ds, O, golden_boot_scale=gb_scale)

    scores = score_entries(ds, contrib, O, entries)
    M = rank_and_metrics(scores)
    chmat = champion_matrix(M["ranks"], O, ds, list(entries["name"]))

    # real current (locked) points from the actual results so far, via the
    # canonical scoring engine (replaces the pool site's buggy/lagging totals).
    bd_map = current_points_breakdown(ds, state, entries)
    name_idx = {r.name: i for i, r in enumerate(entries.itertuples())}
    totals = {nm: round(float(bd_map[nm]["total"]), 1) for nm in name_idx}
    # rank by current points; ties broken by model P(1st) so the leader is the
    # strongest among equals (sequential 1..N for a clean leaderboard).
    cur_order = sorted(name_idx, key=lambda n: (-totals[n],
                                                -float(M["P_first"][name_idx[n]]), n))
    cur_rank = {n: i + 1 for i, n in enumerate(cur_order)}

    # per-group standings: current played/points/GD (from the frozen state) plus
    # simulated qualify% (P reach the Round of 32).
    adv = O["advanced"].mean(0)                       # [T] P(advance to R32)
    cur_stats: dict[str, dict] = {}
    for _g, rows in (state.get("standings") or {}).items():
        for r in rows:
            cur_stats[r["team"]] = {"played": r.get("played", 0),
                                    "points": r.get("points", 0),
                                    "gd": r.get("gd", 0)}
    groups_payload: dict[str, list] = {}
    for g in sorted(ds.groups):
        lst = []
        for t in ds.groups[g]:
            c = cur_stats.get(t, {})
            lst.append({"team": t,
                        "played": int(c.get("played", 0)),
                        "points": int(c.get("points", 0)),
                        "gd": int(c.get("gd", 0)),
                        "p_advance": round(float(adv[ds.team_index[t]]), 4)})
        # current points/GD first; qualify% breaks ties (and orders pre-tournament)
        lst.sort(key=lambda x: (-x["points"], -x["gd"], -x["p_advance"]))
        groups_payload[g] = lst

    prev = previous_metrics(ts)
    N = len(entries)
    out_entries = []
    for e, r in enumerate(entries.itertuples()):
        nm = r.name
        bd = bd_map[nm]
        rec = {
            "name": nm,
            "picks": {"tierA": r.tierA, "tierB": r.tierB, "tierC": r.tierC,
                      "tierD": r.tierD, "scoring": r.scoring,
                      "conceding": r.conceding, "top_scorer": r.top_scorer},
            "current_points": totals[nm],
            "current_rank": cur_rank[nm],
            "pts_breakdown": {
                "tierA": round(float(bd["tier_a"]), 1),
                "tierB": round(float(bd["tier_b"]), 1),
                "tierC": round(float(bd["tier_c"]), 1),
                "tierD": round(float(bd["tier_d"]), 1),
                "scoring": round(float(bd["scoring_team"]), 1),
                "conceding": round(float(bd["conceding_team"]), 1),
                "top_scorer": round(float(bd["top_scorer"]), 1),
            },
            "exp_winnings": round(float(M["exp_winnings"][e]), 1),
            "P_first": round(float(M["P_first"][e]), 4),
            "P_second": round(float(M["P_second"][e]), 4),
            "P_top2": round(float(M["P_top2"][e]), 4),
            "P_third": round(float(M["P_third"][e]), 4),
            "P_last": round(float(M["P_last"][e]), 4),
            "exp_points": round(float(M["exp_points"][e]), 2),
            "exp_rank": round(float(M["exp_rank"][e]), 2),
            "score_p10": round(float(M["score_p10"][e]), 1),
            "score_p50": round(float(M["score_p50"][e]), 1),
            "score_p90": round(float(M["score_p90"][e]), 1),
            "rank_hist": [int(x) for x in M["rank_hist"][e]],
        }
        if prev and nm in prev:
            p = prev[nm]
            rec["d_exp_winnings"] = round(rec["exp_winnings"] - p.get("exp_winnings", 0), 1)
            rec["d_P_top2"] = round(rec["P_top2"] - p.get("P_top2", 0), 4)
            rec["d_exp_rank"] = round(rec["exp_rank"] - p.get("exp_rank", 0), 2)
            if p.get("current_rank") is not None:
                rec["d_current_rank"] = rec["current_rank"] - p["current_rank"]
        out_entries.append(rec)

    # sort by expected winnings (headline), then P_top2
    out_entries.sort(key=lambda x: (-x["exp_winnings"], -x["P_top2"]))

    payload = {
        "timestamp": ts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_sims": args.sims,
        "n_entries": N,
        "prize_ladder": {"1st": 1800, "2nd": 750, "3rd": 50, "last": 50,
                         "tiebreak": "tied entries split the summed prize of the positions they occupy"},
        "state": {"group_played": state.get("n_group_played", 0),
                  "ko_played": state.get("n_ko_played", 0),
                  "group_stage_complete": state.get("group_stage_complete", False),
                  "player_goals": state.get("player_goals", {})},
        "calibration": {"strength_spread": cal["strength_spread"],
                        "golden_boot_scale": round(gb_scale, 3)},
        "champion_matrix": chmat,
        "groups": groups_payload,
        "scorers": (state.get("all_scorers") or [])[:15],
        "entries": out_entries,
    }
    jdump(payload, DATA_LIVE / f"win_probabilities_{ts}.json")
    jdump(payload, RESULTS_DIR / "live_latest.json")
    print(f"\nWrote win_probabilities_{ts}.json + results/live_latest.json")

    print("\n=== Top 8 by expected winnings (ILS) ===")
    print(f"{'entry':<24}{'EV ILS':>8}{'P(1st)':>8}{'P(top2)':>9}{'expRank':>9}")
    for rec in out_entries[:8]:
        print(f"{rec['name'][:23]:<24}{rec['exp_winnings']:>8.0f}"
              f"{rec['P_first']*100:>7.1f}%{rec['P_top2']*100:>8.1f}%"
              f"{rec['exp_rank']:>9.1f}")


if __name__ == "__main__":
    main()
