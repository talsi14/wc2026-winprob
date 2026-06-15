"""Slim refresh: overlay the live widget tallies (completed + in-progress goals)
onto the last published live_latest.json, so build_friends_report.py can redeploy
the three leader widgets (top scoring/conceding team, top scorer) WITHOUT re-running
the simulation. Win-probabilities, standings and everything else stay exactly as the
last heavy run left them - only team_played + scorers are refreshed.

Reads  wc2026_bet/data/live/state_latest.json  (fresh from collect_live.py)
Patches wc2026_bet/results/live_latest.json     (the page's data source)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import DATA_LIVE, RESULTS_DIR


def main() -> None:
    live_path = RESULTS_DIR / "live_latest.json"
    state_path = DATA_LIVE / "state_latest.json"
    if not live_path.exists():
        print("apply_live_widgets: no live_latest.json snapshot yet; skipping.")
        return
    if not state_path.exists():
        print("apply_live_widgets: no state_latest.json; skipping.")
        return

    data = json.loads(live_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))

    n_live = int(state.get("n_live", 0) or 0)
    live_tp = state.get("live_team_played") or {}
    live_sc = state.get("live_scorers") or []
    if not live_tp and not live_sc:
        print("apply_live_widgets: no live tallies; leaving snapshot untouched.")
        return

    data["team_played"] = live_tp
    data["scorers"] = live_sc
    data["live_widgets"] = n_live > 0          # drives the 'live' indicator in the UI

    live_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"apply_live_widgets: overlaid live widgets (n_live={n_live}, "
          f"{len(live_sc)} scorers, {len(live_tp)} teams).")


if __name__ == "__main__":
    main()
