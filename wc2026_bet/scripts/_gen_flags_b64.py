"""One-off: build wc2026_bet/assets/flags_b64.json (team -> base64 PNG data URI).

Fetched from flagcdn.com (w80 PNGs) once and committed, so the report build
needs no network and the page stays self-contained. Re-run only if the team /
ISO set changes.

Usage: python3 scripts/_gen_flags_b64.py
"""
from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

WC_ROOT = Path(__file__).resolve().parents[1]
OUT = WC_ROOT / "assets" / "flags_b64.json"

# Canonical team name -> flagcdn code. Mirrors _TEAM_ISO in build_friends_report
# (lower-cased) plus the GB sub-flags for England / Scotland.
CODES = {
    "United States": "us", "Canada": "ca", "Mexico": "mx", "Panama": "pa",
    "Curaçao": "cw", "Haiti": "ht", "Argentina": "ar", "Brazil": "br",
    "Uruguay": "uy", "Colombia": "co", "Paraguay": "py", "Ecuador": "ec",
    "France": "fr", "Spain": "es", "Germany": "de", "Portugal": "pt",
    "Netherlands": "nl", "Belgium": "be", "Croatia": "hr", "Switzerland": "ch",
    "Austria": "at", "Norway": "no", "Sweden": "se", "Turkey": "tr",
    "Czech Republic": "cz", "Bosnia and Herzegovina": "ba", "Morocco": "ma",
    "Senegal": "sn", "Egypt": "eg", "Algeria": "dz", "Tunisia": "tn",
    "Ghana": "gh", "Ivory Coast": "ci", "Cape Verde": "cv", "South Africa": "za",
    "DR Congo": "cd", "Japan": "jp", "South Korea": "kr", "Iran": "ir",
    "Australia": "au", "Saudi Arabia": "sa", "Qatar": "qa", "Jordan": "jo",
    "Uzbekistan": "uz", "Iraq": "iq", "New Zealand": "nz",
    "England": "gb-eng", "Scotland": "gb-sct",
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    flags: dict[str, str] = {}
    for team, code in sorted(CODES.items()):
        url = f"https://flagcdn.com/w80/{code}.png"
        raw = urllib.request.urlopen(url, timeout=30).read()
        flags[team] = "data:image/png;base64," + base64.b64encode(raw).decode()
        print(f"  {team:30s} {code:7s} {len(raw):>6d} B")
    OUT.write_text(json.dumps(flags, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"\nwrote {OUT}  ({len(flags)} flags, {OUT.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
