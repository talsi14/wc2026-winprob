"""Print ``yes`` when it's worth opening a short-interval polling pursuit.

The self-chaining workflow (``.github/workflows/update.yml``) bootstraps a
pursuit from the off-peak schedule, but those cron slots use ``day=*`` and so
also fire on days that have no match at that time. This gate keeps the chain
tight to real activity: it returns ``yes`` only when a fixture is currently
live, or is expected to have ended within the last hour (results post with a
lag), or is about to end. Otherwise the scheduled run does a single cheap
change-gate and stops, instead of polling for an hour against nothing.

Exit code is always 0; the decision is the single stdout token (yes/no).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet import espn

PLAY_MIN = 135          # kickoff -> expected final whistle (90 + HT + stoppage; KO a touch more)
WINDOW_MIN = 60         # keep polling up to an hour past the final whistle (ESPN posting lag)
GRACE_MIN = 5           # also arm a few minutes before the whistle


def active(now: dt.datetime) -> bool:
    for f in espn.fetch_fixtures():
        if f.get("state") == "in":          # a match is live right now
            return True
        d = f.get("date")
        if not d:
            continue
        try:
            ko = dt.datetime.fromisoformat(d.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError:
            continue
        end = ko + dt.timedelta(minutes=PLAY_MIN)
        if end - dt.timedelta(minutes=GRACE_MIN) <= now <= end + dt.timedelta(minutes=WINDOW_MIN):
            return True
    return False


def main() -> None:
    try:
        print("yes" if active(dt.datetime.now(dt.timezone.utc)) else "no")
    except Exception as exc:               # never let the gate break the run
        print(f"# pursuit_active error: {exc}", file=sys.stderr)
        print("no")


if __name__ == "__main__":
    main()
