"""Keyless ESPN client for the live WC-2026 feed.

ESPN's public ``site.api.espn.com`` soccer endpoints (league ``fifa.world``)
serve the 2026 World Cup with no API key. We use three:

  * scoreboard?dates=YYYYMMDD  -> fixtures + live/final scores + status
  * standings?season=2026      -> 12 groups x 4 teams (rank, pts, GF, GA, advanced)
  * summary?event=<id>         -> keyEvents -> goal scorers

All team names are mapped to our canonical spelling via ``names.resolve`` (all
48 finalists already resolve). Goal scorers exclude penalty-shootout goals and
own goals (the latter would otherwise mis-credit a defender for the Golden Boot;
team GF/GA come from the official score, not from summing key events).

This module is network-only and used solely by ``scripts/collect_live.py``.
TheSportsDB (free key "3") is a documented fallback but not required.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, timedelta

from .config import ESPN_BASE, ESPN_SEASON, ESPN_STANDINGS
from .names import resolve

# WC 2026 runs 11 Jun - 19 Jul 2026; scan the whole window for fixtures.
WC_START = date(2026, 6, 11)
WC_END = date(2026, 7, 19)


def _get(url: str, tries: int = 3, pause: float = 1.0) -> dict:
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (wc2026-bet live collector)",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:        # noqa: BLE001 - best-effort network
            last = e
            time.sleep(pause * (k + 1))
    raise RuntimeError(f"ESPN GET failed after {tries} tries: {url} ({last})")


def _canon(name: str) -> str | None:
    return resolve(name)


# --------------------------------------------------------------------------- #
# Fixtures + scores
# --------------------------------------------------------------------------- #
def fetch_fixtures(start: date = WC_START, end: date = WC_END) -> list[dict]:
    """Every WC fixture in the window, with canonical teams + score + status.

    Returns dicts: espn_id, date (ISO), state ('pre'|'in'|'post'), completed,
    stage (event 'season'->type or competition notes), home, away, home_score,
    away_score, home_id, away_id. Unscored fixtures keep scores = None.
    """
    out, seen = [], set()
    d = start
    while d <= end:
        url = f"{ESPN_BASE}/scoreboard?dates={d:%Y%m%d}"
        try:
            data = _get(url)
        except RuntimeError:
            data = {"events": []}
        for ev in data.get("events", []):
            eid = ev.get("id")
            if eid in seen:
                continue
            seen.add(eid)
            comp = (ev.get("competitions") or [{}])[0]
            status = (comp.get("status") or ev.get("status") or {}).get("type", {})
            state = status.get("state")            # pre / in / post
            completed = bool(status.get("completed"))
            home = away = None
            hs = as_ = None
            hid = aid = None
            for c in comp.get("competitors", []):
                nm = _canon((c.get("team") or {}).get("displayName", ""))
                sc = c.get("score")
                sc = int(sc) if (sc is not None and str(sc).strip() != "") else None
                if c.get("homeAway") == "home":
                    home, hs, hid = nm, sc, (c.get("team") or {}).get("id")
                else:
                    away, as_, aid = nm, sc, (c.get("team") or {}).get("id")
            notes = comp.get("notes") or []
            stage = notes[0].get("headline") if notes else ev.get("name")
            out.append({
                "espn_id": eid, "date": ev.get("date"), "state": state,
                "completed": completed, "stage": stage,
                "home": home, "away": away,
                "home_score": hs, "away_score": as_,
                "home_id": hid, "away_id": aid,
            })
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------------- #
# Group standings
# --------------------------------------------------------------------------- #
def _stat(entry: dict, name: str, default=0.0) -> float:
    for s in entry.get("stats", []):
        if s.get("name") == name:
            return s.get("value", default)
    return default


def fetch_standings(our_groups: dict[str, list[str]]) -> dict[str, list[dict]]:
    """12 groups -> ordered standings rows. Maps each ESPN group to OUR group
    letter by team-set overlap (not by trusting the label), so positions line up
    with groups.csv. Each row: team, rank, played, points, gf, ga, gd, advanced.

    ``our_groups`` is Dataset.groups (letter -> [team,...]).
    """
    data = _get(f"{ESPN_STANDINGS}?season={ESPN_SEASON}")
    set_to_letter = {frozenset(v): k for k, v in our_groups.items()}
    out: dict[str, list[dict]] = {}
    for child in data.get("children", []):
        entries = (child.get("standings") or {}).get("entries", [])
        rows = []
        for e in entries:
            t = _canon((e.get("team") or {}).get("displayName", ""))
            rows.append({
                "team": t,
                "rank": int(_stat(e, "rank", 0)),
                "played": int(_stat(e, "gamesPlayed", 0)),
                "points": int(_stat(e, "points", 0)),
                "gf": int(_stat(e, "pointsFor", 0)),
                "ga": int(_stat(e, "pointsAgainst", 0)),
                "gd": int(_stat(e, "pointDifferential", 0)),
                "advanced": bool(_stat(e, "advanced", 0)),
            })
        letter = set_to_letter.get(frozenset(r["team"] for r in rows))
        if letter is None:
            # fall back to ESPN's own label ("Group A" -> "A")
            nm = child.get("abbreviation") or child.get("name") or ""
            letter = nm.replace("Group", "").strip()[:1]
        rows.sort(key=lambda r: r["rank"] or 99)
        out[letter] = rows
    return out


# --------------------------------------------------------------------------- #
# Goal scorers (Golden-Boot crediting)
# --------------------------------------------------------------------------- #
def fetch_goal_scorers(espn_id: str) -> list[dict]:
    """Valid open-play / in-match-penalty goal scorers for one event.

    Excludes penalty-shootout goals (``shootout``) and own goals (which credit
    the opposition). Each item: scorer (raw ESPN display name), team_id, minute.
    Returns [] if the summary has no key events yet.
    """
    data = _get(f"{ESPN_BASE}/summary?event={espn_id}")
    out = []
    for e in data.get("keyEvents") or []:
        if not e.get("scoringPlay"):
            continue
        if e.get("shootout"):
            continue
        ttext = (e.get("type") or {}).get("text", "") or ""
        if e.get("ownGoal") or "own goal" in ttext.lower():
            continue
        parts = e.get("participants") or []
        if not parts:
            continue
        scorer = (parts[0].get("athlete") or {}).get("displayName")
        if not scorer:
            continue
        out.append({
            "scorer": scorer,
            "team_id": (e.get("team") or {}).get("id"),
            "minute": (e.get("clock") or {}).get("displayValue"),
        })
    return out
