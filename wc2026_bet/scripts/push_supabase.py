"""Push the live leaderboard to the friends-bet.lovable.app Supabase table.

Reads results/live_latest.json, converts each entry's English-canonical picks to
the Hebrew strings the `leaderboard` table stores (via the inverted
data/processed/he_aliases.json map), and upserts one row per participant keyed
on `name`.

The lovable app reads from this table, so this script is the sole writer once the
friend's cron is disabled.

Credentials (never hard-code the service-role key):
  SUPABASE_URL                 default: https://fllblqtztfmbpeofmaqu.supabase.co
  SUPABASE_SERVICE_ROLE_KEY    required for an actual write

Usage:
  python3 scripts/push_supabase.py --dry-run        # print rows, no write, no key needed
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/push_supabase.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_LATEST = REPO / "results" / "live_latest.json"
HE_ALIASES = REPO / "data" / "processed" / "he_aliases.json"

DEFAULT_SUPABASE_URL = "https://fllblqtztfmbpeofmaqu.supabase.co"
TABLE = "leaderboard"

# When several Hebrew spellings map to the same canonical name, prefer the
# spelling currently shown on friends-bet.lovable.app for visual consistency.
PREFERRED_HE = {
    "Curaçao": "קורסאו",
    "Czech Republic": "צ'כיה",
    "Vinícius Júnior": "ויניסיוס ז'וניור",
}


def _build_reverse_maps() -> tuple[dict[str, str], dict[str, str]]:
    raw = json.loads(HE_ALIASES.read_text(encoding="utf-8"))
    teams_he2en: dict[str, str] = raw["teams"]
    players_he2en: dict[str, str] = raw["players"]

    def invert(he2en: dict[str, str]) -> dict[str, str]:
        en2he: dict[str, str] = {}
        for he, en in he2en.items():
            if en in PREFERRED_HE:
                en2he[en] = PREFERRED_HE[en]
            else:
                en2he.setdefault(en, he)
        return en2he

    return invert(teams_he2en), invert(players_he2en)


def _to_he(value: str, en2he: dict[str, str], kind: str, missing: set[str]) -> str:
    if value in en2he:
        return en2he[value]
    missing.add(f"{kind}:{value}")
    return value  # fall back to the English string so the write still succeeds


def build_rows(payload: dict) -> tuple[list[dict], set[str]]:
    teams_en2he, players_en2he = _build_reverse_maps()
    missing: set[str] = set()
    now_iso = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for e in payload["entries"]:
        picks = e["picks"]
        b = e["pts_breakdown"]

        # Our d_current_rank is (current - previous): negative means moved up.
        # The table's `movement` is positive = moved up, so flip the sign.
        d = e.get("d_current_rank")
        movement = -int(d) if d is not None else 0

        rows.append(
            {
                "name": e["name"],
                "rank": int(e["current_rank"]),
                "movement": movement,
                "tier_a": _to_he(picks["tierA"], teams_en2he, "team", missing),
                "tier_a_pts": b["tierA"],
                "tier_b": _to_he(picks["tierB"], teams_en2he, "team", missing),
                "tier_b_pts": b["tierB"],
                "tier_c": _to_he(picks["tierC"], teams_en2he, "team", missing),
                "tier_c_pts": b["tierC"],
                "tier_d": _to_he(picks["tierD"], teams_en2he, "team", missing),
                "tier_d_pts": b["tierD"],
                "scorer": _to_he(picks["scoring"], teams_en2he, "team", missing),
                "scorer_pts": b["scoring"],
                "conceder": _to_he(picks["conceding"], teams_en2he, "team", missing),
                "conceder_pts": b["conceding"],
                "topscorer": _to_he(picks["top_scorer"], players_en2he, "player", missing),
                "topscorer_pts": b["top_scorer"],
                "total": e["current_points"],
                "updated_at": now_iso,
            }
        )

    return rows, missing


def _get_client(read_only_ok: bool = False):
    """Create a Supabase client. For --check, an anon key is acceptable."""
    url = os.environ.get("SUPABASE_URL", DEFAULT_SUPABASE_URL)
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key and read_only_ok:
        key = os.environ.get("SUPABASE_ANON_KEY")
    if not key:
        names = "SUPABASE_SERVICE_ROLE_KEY" + (" (or SUPABASE_ANON_KEY)" if read_only_ok else "")
        print(f"ERROR: {names} is not set. Export it as an env var.", file=sys.stderr)
        return None, None
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase package missing. Run: pip install supabase", file=sys.stderr)
        return None, None
    return create_client(url, key), url


def check_table(payload: dict) -> int:
    """Read the live table and diff it against what we would write."""
    client, url = _get_client(read_only_ok=True)
    if client is None:
        return 2
    print(f"Connected to {url} -> table '{TABLE}'\n")

    resp = client.table(TABLE).select("*").execute()
    live = resp.data or []
    print(f"Live table: {len(live)} rows")
    if not live:
        print("Table is empty.")
        return 0

    cols = sorted({k for r in live for k in r.keys()})
    print(f"Columns ({len(cols)}): {', '.join(cols)}\n")
    print("Sample live row:")
    print(json.dumps(live[0], ensure_ascii=False, indent=2))

    expected = {
        "name", "rank", "movement", "tier_a", "tier_a_pts", "tier_b", "tier_b_pts",
        "tier_c", "tier_c_pts", "tier_d", "tier_d_pts", "scorer", "scorer_pts",
        "conceder", "conceder_pts", "topscorer", "topscorer_pts", "total", "updated_at",
    }
    present = set(cols)
    missing_cols = expected - present
    extra_cols = present - expected
    print("\n-- column check vs our writer --")
    print(f"  missing in table : {sorted(missing_cols) or 'none'}")
    print(f"  extra in table   : {sorted(extra_cols) or 'none'}")

    ours, _ = build_rows(payload)
    live_names = {r.get("name") for r in live}
    our_names = {r["name"] for r in ours}
    print("\n-- name (primary key) reconciliation --")
    print(f"  live names: {len(live_names)}  |  our names: {len(our_names)}")
    print(f"  in table but not ours : {sorted(live_names - our_names) or 'none'}")
    print(f"  in ours but not table : {sorted(our_names - live_names) or 'none'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the rows that would be written; do not contact Supabase.")
    ap.add_argument("--check", action="store_true",
                    help="Read the live table and diff schema + names vs our output (no write).")
    ap.add_argument("--input", type=Path, default=LIVE_LATEST)
    args = ap.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))

    if args.check:
        return check_table(payload)

    rows, missing = build_rows(payload)

    if missing:
        print("WARNING: no Hebrew mapping for these pick tokens (written as-is):",
              file=sys.stderr)
        for m in sorted(missing):
            print(f"  - {m}", file=sys.stderr)

    print(f"Built {len(rows)} rows from {args.input.name}")

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    client, _ = _get_client(read_only_ok=False)
    if client is None:
        return 2

    resp = client.table(TABLE).upsert(rows, on_conflict="name").execute()
    n = len(resp.data) if getattr(resp, "data", None) else len(rows)
    print(f"Upserted {n} rows into '{TABLE}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
