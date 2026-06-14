"""Orchestrator - chain the whole live pipeline for one timestamp (Stage 1->5).

Safe to schedule (cron / the /loop skill). Each run is fully reproducible from
its frozen state_<TS> + odds snapshots + calibration_<TS>.

  1. (optional) ingest pool entries from Supabase   [--entries]
  2. collect live tournament state from ESPN          (scripts/collect_live.py)
  3. refresh odds snapshots                            (scripts/refresh_odds.py)
  4. conditioned 50K sims -> win probabilities         (scripts/run_live_update.py)
  5. render report/live.html                           (scripts/build_live_report.py)

Usage:
  python3 scripts/run_live_pipeline.py                 # newest state, cached power ranking
  python3 scripts/run_live_pipeline.py --recalibrate   # re-fit power ranking vs refreshed odds
  python3 scripts/run_live_pipeline.py --entries       # also re-pull the roster first
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(script: str, *args: str) -> None:
    cmd = [PY, str(HERE / script), *args]
    print(f"\n\033[1m$ {' '.join([script, *args])}\033[0m")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"stage failed: {script} (exit {r.returncode})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M"))
    # 200k keeps the low-probability "who to root for" buckets (e.g. a heavy
    # favourite's loss/draw) stable; the extra sims cost only a few seconds and
    # the heavy pipeline only runs when a new result actually lands.
    ap.add_argument("--sims", type=int, default=200000)
    ap.add_argument("--recalibrate", action="store_true")
    ap.add_argument("--entries", action="store_true",
                    help="re-pull the 53 pool entries from Supabase first")
    ap.add_argument("--skip-collect", action="store_true",
                    help="reuse the existing state_latest.json instead of re-fetching "
                    "from ESPN (used by the CI change-gate, which already collected)")
    ap.add_argument("--me", default="", help="optional entry nickname to highlight "
                    "(blank by default -> neutral, shareable report)")
    args = ap.parse_args()
    ts = args.ts
    print(f"=== Live pipeline for timestamp {ts} ===")

    if args.entries:
        run("ingest_pool_entries_2026.py")
    if args.skip_collect:
        print("\n(skip-collect: reusing existing state_latest.json)")
    else:
        run("collect_live.py", "--ts", ts)
    run("refresh_odds.py", "--ts", ts)
    upd = ["--ts", ts, "--sims", str(args.sims),
           "--state", str(HERE.parent / "data" / "live" / "state_latest.json")]
    if args.recalibrate:
        upd.append("--recalibrate")
    run("run_live_update.py", *upd)
    # snapshot the calibration / simulated-odds the run actually used, for the
    # committed "over time" history powering the Odds & ELO dashboard.
    run("snapshot_metrics.py", "--ts", ts)
    run("build_live_report.py", *(["--me", args.me] if args.me else []))
    print(f"\n=== Done. Open report/live.html (snapshot {ts}). ===")


if __name__ == "__main__":
    main()
