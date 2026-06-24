"""Append a compact metrics record to the committed history time-series.

After each pipeline run we snapshot what the model actually used / produced, so
the "Odds & ELO -> over time" dashboard on the shareable page has real history:

  * calibration params the run used (strength_spread, golden_boot_scale)
  * model-simulated title probabilities for the leading teams
  * the (mostly static) market title-implied prob + blended ELO for context
  * how many group / KO matches were baked into the run

Records go to data/history/metrics_history.jsonl (one JSON object per line),
which IS committed to the repo (unlike the per-run snapshots in data/live). To
keep the file from growing on idle forced runs, an append is skipped when the
new record is identical (by fingerprint) to the previous one.

Usage:  python3 scripts/snapshot_metrics.py [--ts 2026-06-20T1200]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

WC_ROOT = Path(__file__).resolve().parents[1]
RESULTS = WC_ROOT / "results" / "live_latest.json"
TEAMS = WC_ROOT / "data" / "processed" / "teams.csv"
HIST_DIR = WC_ROOT / "data" / "history"
HIST = HIST_DIR / "metrics_history.jsonl"
# Per-entry points + P(1st) over time, feeding the bar-chart-race visualisations
# on the shareable page. Committed (like metrics_history) so it accumulates.
ENTRY_HIST = HIST_DIR / "entry_history.jsonl"

TOP_N = 12


def _top(d: dict, n: int) -> dict:
    return {k: round(float(v), 5) for k, v in
            sorted(d.items(), key=lambda kv: -float(kv[1]))[:n]}


def _teams_metrics() -> tuple[dict, dict]:
    """(elo_blended top, market_title_prob top) from teams.csv."""
    elo, mkt = {}, {}
    if not TEAMS.exists():
        return elo, mkt
    with TEAMS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                elo[r["team"]] = float(r["elo"])
            except (KeyError, TypeError, ValueError):
                pass
            try:
                mkt[r["team"]] = float(r["market_prob"])
            except (KeyError, TypeError, ValueError):
                pass
    return _top(elo, TOP_N), _top(mkt, TOP_N)


def _fingerprint(rec: dict) -> str:
    keep = {k: rec[k] for k in ("strength_spread", "golden_boot_scale",
                                "group_played", "ko_played", "sim_title")
            if k in rec}
    return hashlib.sha256(json.dumps(keep, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def _entry_record(data: dict, ts: str) -> dict:
    """Compact per-entry snapshot: name -> {pts, p1} for the race charts."""
    ent = {}
    for e in data.get("entries") or []:
        nm = e.get("name")
        if not nm:
            continue
        try:
            ent[nm] = {"pts": round(float(e.get("current_points", 0)), 3),
                       "p1": round(float(e.get("P_first", 0)), 5)}
        except (TypeError, ValueError):
            pass
    return {"ts": ts, "generated_at": datetime.now(timezone.utc).isoformat(),
            "entries": ent}


def _append_entry_history(rec: dict, ts: str) -> None:
    """Append the per-entry snapshot, skipping if identical to the last one."""
    ENTRY_HIST.parent.mkdir(parents=True, exist_ok=True)
    fp = hashlib.sha256(json.dumps(rec["entries"], sort_keys=True,
                                   ensure_ascii=False).encode()).hexdigest()
    prev_fp = None
    if ENTRY_HIST.exists():
        lines = [ln for ln in ENTRY_HIST.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            try:
                prev = json.loads(lines[-1])
                prev_fp = hashlib.sha256(json.dumps(prev.get("entries", {}), sort_keys=True,
                                                    ensure_ascii=False).encode()).hexdigest()
            except json.JSONDecodeError:
                prev_fp = None
    if fp == prev_fp:
        print(f"snapshot_metrics: entry history unchanged; skipping ({ts}).")
        return
    with ENTRY_HIST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"snapshot_metrics: appended entry-history record for {ts} "
          f"({len(rec['entries'])} entries).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=None)
    args = ap.parse_args()

    if not RESULTS.exists():
        raise SystemExit(f"no {RESULTS}; run the pipeline first")
    data = json.loads(RESULTS.read_text(encoding="utf-8"))

    ts = args.ts or data.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    cal = data.get("calibration") or {}
    st = data.get("state") or {}
    sim_title = (data.get("champion_matrix") or {}).get("p_title") or {}
    elo_top, mkt_top = _teams_metrics()

    rec = {
        "ts": ts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strength_spread": cal.get("strength_spread"),
        "golden_boot_scale": cal.get("golden_boot_scale"),
        "group_played": st.get("group_played", 0),
        "ko_played": st.get("ko_played", 0),
        "sim_title": _top(sim_title, TOP_N),
        "market_title_prob": mkt_top,
        "elo_blended": elo_top,
    }

    # Per-entry race history is independent of the metrics fingerprint below, so
    # snapshot it first (its own dedup guards against idle duplicate runs).
    _append_entry_history(_entry_record(data, ts), ts)

    HIST_DIR.mkdir(parents=True, exist_ok=True)
    prev_fp = None
    if HIST.exists():
        lines = [ln for ln in HIST.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            try:
                prev_fp = _fingerprint(json.loads(lines[-1]))
            except json.JSONDecodeError:
                prev_fp = None

    if _fingerprint(rec) == prev_fp:
        print(f"snapshot_metrics: no change since last record; skipping ({ts}).")
        return

    with HIST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"snapshot_metrics: appended record for {ts} "
          f"(spread={rec['strength_spread']}, gb={rec['golden_boot_scale']}, "
          f"group={rec['group_played']}/72, ko={rec['ko_played']}).")


if __name__ == "__main__":
    main()
