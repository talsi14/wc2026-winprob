"""Print a stable fingerprint of the *recorded* tournament state.

Used by the CI change-gate: the heavy 50k-sim + deploy only runs when this
fingerprint differs from the last published one. It hashes only the facts that
should trigger a refresh (played results + goals), ignoring volatile fields like
``collected_at``/``timestamp`` so an unchanged tournament yields a stable value.

Usage:  python3 scripts/state_fingerprint.py [--state <path>]
        -> prints a short hex digest (empty string if the state is missing)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import DATA_LIVE


def fingerprint(state: dict) -> str:
    """Stable digest over the recorded-result fields of a live state dict."""
    relevant = {
        "group_stage_complete": state.get("group_stage_complete", False),
        "n_group_played": state.get("n_group_played", 0),
        "n_ko_played": state.get("n_ko_played", 0),
        "group_scores": state.get("group_scores", {}),
        "ko_results": state.get("ko_results", []),
        "player_goals": state.get("player_goals", {}),
    }
    blob = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(DATA_LIVE / "state_latest.json"))
    args = ap.parse_args()
    p = Path(args.state)
    if not p.exists():
        print("")
        return
    print(fingerprint(json.loads(p.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
