"""Per-match market odds snapshotter (the-odds-api) for a leakage-free market
benchmark of the match-prediction products.

The project only ever stored *tournament-level* markets (title / advance / Golden
Boot), so there was no way to benchmark per-match predictions against the book.
This module captures each fixture's **1X2 (h2h) + totals (over/under)** line and
persists a timestamped snapshot, so the backtest can reconstruct the pre-kickoff
market scoreline distribution with **no leakage** (only snapshots observed strictly
before a game's kickoff are ever used).

the-odds-api does not offer a correct-score market for the World Cup, so the market
scoreline grid is derived from 1X2 + totals via a supremacy/total Poisson solve
(``implied_scoreline_grid``) — the standard bookmaker-consistent construction.

Two capture modes (both leakage-free; snapshot time < kickoff is enforced downstream):
  * live/upcoming  — call before each upcoming kickoff (knockouts). This is the
    forward-looking path wired into ``refresh_odds.py``.
  * historical     — ``/v4/historical`` endpoint returns the board *as of* a past
    timestamp, so completed group games can be backfilled cleanly (paid tier).

Auth: reads the API key from the ``ODDS_API_KEY`` env var. If unset, every entry
point degrades gracefully (logs + no-op) so the pipeline never breaks.

Usage:
  ODDS_API_KEY=... python3 wc2026_bet/scripts/match_odds_api.py            # live snapshot
  ODDS_API_KEY=... python3 wc2026_bet/scripts/match_odds_api.py --date 2026-06-15T18:00:00Z
  ODDS_API_KEY=... python3 wc2026_bet/scripts/match_odds_api.py --backfill-kickoffs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import DATA_LIVE  # noqa: E402
from wc2026_bet.names import resolve     # noqa: E402

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "soccer_fifa_world_cup"
DEFAULT_REGIONS = "uk,eu,us"
DEFAULT_MARKETS = "h2h,totals"
UA = "Mozilla/5.0 (wc2026-bet match-odds)"

HISTORY_DIR = Path(__file__).resolve().parents[1] / "data" / "history"
HISTORY_FILE = HISTORY_DIR / "match_odds_history.jsonl"
SNAP_DIR = DATA_LIVE / "match_odds"


def _key() -> str | None:
    k = os.environ.get("ODDS_API_KEY", "").strip()
    return k or None


def _fetch_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# --------------------------------------------------------------------------- #
# Parsing / de-vigging a single event across its bookmakers
# --------------------------------------------------------------------------- #
def _devig(prices: dict[str, float]) -> dict[str, float] | None:
    """Decimal odds -> de-vigged (normalised) implied probabilities."""
    imp = {k: 1.0 / v for k, v in prices.items() if v and v > 1.0}
    tot = sum(imp.values())
    if len(imp) < 2 or tot <= 0:
        return None
    return {k: v / tot for k, v in imp.items()}


def parse_event(ev: dict) -> dict | None:
    """Consensus (cross-bookmaker) 1X2 + totals for one fixture.

    Averages each book's de-vigged 1X2; for totals, takes the median featured
    line and averages the de-vigged Over probability at that line.
    """
    home_raw = ev.get("home_team") or ""
    away_raw = ev.get("away_team") or ""
    home, away = resolve(home_raw), resolve(away_raw)
    if not home or not away or home == away:
        return None

    h2h_probs: list[dict[str, float]] = []
    tot_points: list[float] = []
    tot_over: dict[float, list[float]] = {}
    for bk in ev.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            key = mk.get("key")
            outs = {o.get("name"): o for o in mk.get("outcomes") or []}
            if key == "h2h":
                prices = {}
                for nm, o in outs.items():
                    tag = ("draw" if nm == "Draw"
                           else "home" if resolve(nm) == home
                           else "away" if resolve(nm) == away else None)
                    if tag:
                        prices[tag] = float(o.get("price") or 0)
                dv = _devig(prices) if len(prices) == 3 else None
                if dv:
                    h2h_probs.append(dv)
            elif key == "totals":
                over = outs.get("Over")
                under = outs.get("Under")
                if over and under and over.get("point") is not None:
                    pt = float(over["point"])
                    dv = _devig({"over": float(over.get("price") or 0),
                                 "under": float(under.get("price") or 0)})
                    if dv:
                        tot_points.append(pt)
                        tot_over.setdefault(pt, []).append(dv["over"])

    if not h2h_probs:
        return None
    n = len(h2h_probs)
    p_home = sum(d["home"] for d in h2h_probs) / n
    p_draw = sum(d["draw"] for d in h2h_probs) / n
    p_away = sum(d["away"] for d in h2h_probs) / n

    total_line = p_over = None
    if tot_points:
        total_line = float(median(tot_points))
        overs = tot_over.get(total_line) or [v for vs in tot_over.values() for v in vs]
        p_over = sum(overs) / len(overs)

    return {
        "home": home, "away": away,
        "commence_time": ev.get("commence_time"),
        "p_home": round(p_home, 4), "p_draw": round(p_draw, 4),
        "p_away": round(p_away, 4),
        "total_line": total_line,
        "p_over": round(p_over, 4) if p_over is not None else None,
        "n_books": n,
    }


# --------------------------------------------------------------------------- #
# Market-implied scoreline grid (1X2 + total -> Poisson supremacy solve)
# --------------------------------------------------------------------------- #
def implied_scoreline_grid(p_home, p_draw, p_away, total_line, k=10, rho=0.0):
    """Return an (k+1)x(k+1) home/away scoreline probability matrix consistent
    with the market's 1X2 split and expected total goals.

    Independent-Poisson with a fixed total ``T``: solve for supremacy
    ``d = lam_home - lam_away`` so the grid's 1X2 best matches the market. If the
    total is missing we fall back to a WC-average total (flagged by caller).
    """
    import math

    import numpy as np
    T = float(total_line) if total_line else 2.6
    T = max(T, 0.2)
    g = np.arange(k + 1)
    fact = np.array([math.factorial(int(x)) for x in g], dtype=float)

    def grid_for(d):
        lh = max((T + d) / 2.0, 1e-3)
        la = max((T - d) / 2.0, 1e-3)
        pi = np.exp(-lh) * lh ** g / fact
        pj = np.exp(-la) * la ** g / fact
        P = np.outer(pi, pj)
        if rho:
            t = np.ones((k + 1, k + 1))
            t[0, 0] = 1 - lh * la * rho
            t[0, 1] = 1 + lh * rho
            t[1, 0] = 1 + la * rho
            t[1, 1] = 1 - rho
            P = P * t
        return P / P.sum()

    def probs(P):
        return (np.tril(P, -1).sum(), np.trace(P), np.triu(P, 1).sum())

    target = np.array([p_home, p_draw, p_away], float)
    target = target / target.sum()
    lo, hi = -T, T
    best_d, best_err, best_P = 0.0, 1e9, None
    for _ in range(40):  # ternary-ish golden search on squared 1X2 error
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        e1 = float(((np.array(probs(grid_for(m1))) - target) ** 2).sum())
        e2 = float(((np.array(probs(grid_for(m2))) - target) ** 2).sum())
        for d, e in ((m1, e1), (m2, e2)):
            if e < best_err:
                best_err, best_d = e, d
        if e1 < e2:
            hi = m2
        else:
            lo = m1
    best_P = grid_for(best_d)
    return best_P


def market_top_scorelines(entry: dict, k: int):
    """Top-k market scorelines (home,away) for a stored history entry."""
    import numpy as np
    P = implied_scoreline_grid(entry["p_home"], entry["p_draw"], entry["p_away"],
                               entry.get("total_line"))
    flat = np.argsort(P, axis=None)[::-1][:k]
    return [tuple(int(x) for x in np.unravel_index(int(f), P.shape)) for f in flat]


# --------------------------------------------------------------------------- #
# Fetch + persist
# --------------------------------------------------------------------------- #
def fetch_live(regions=DEFAULT_REGIONS, markets=DEFAULT_MARKETS) -> list[dict]:
    key = _key()
    if not key:
        return []
    q = urllib.parse.urlencode({"apiKey": key, "regions": regions,
                                "markets": markets, "oddsFormat": "decimal"})
    data = _fetch_json(f"{API_BASE}/sports/{SPORT}/odds?{q}")
    return [pe for ev in (data or []) if (pe := parse_event(ev))]


def fetch_historical(date_iso: str, regions=DEFAULT_REGIONS,
                     markets=DEFAULT_MARKETS) -> list[dict]:
    """Board as of ``date_iso`` (ISO8601, e.g. 2026-06-15T18:00:00Z)."""
    key = _key()
    if not key:
        return []
    q = urllib.parse.urlencode({"apiKey": key, "regions": regions,
                                "markets": markets, "oddsFormat": "decimal",
                                "date": date_iso})
    resp = _fetch_json(f"{API_BASE}/historical/sports/{SPORT}/odds?{q}")
    data = resp.get("data") if isinstance(resp, dict) else resp
    return [pe for ev in (data or []) if (pe := parse_event(ev))]


def _append_history(rows: list[dict], snapshot_ts: str) -> int:
    if not rows:
        return 0
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    # de-dup on (home, away, commence_time, snapshot_ts)
    seen = set()
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text().splitlines():
            try:
                d = json.loads(line)
                seen.add((d["home"], d["away"], d["commence_time"], d["snapshot_ts"]))
            except (json.JSONDecodeError, KeyError):
                continue
    n = 0
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        for r in rows:
            kk = (r["home"], r["away"], r["commence_time"], snapshot_ts)
            if kk in seen:
                continue
            f.write(json.dumps({**r, "snapshot_ts": snapshot_ts,
                                "source": "the-odds-api"}, ensure_ascii=False) + "\n")
            seen.add(kk)
            n += 1
    return n


def snapshot(ts: str | None = None, date_iso: str | None = None,
             regions=DEFAULT_REGIONS, markets=DEFAULT_MARKETS) -> dict:
    """Fetch (live or historical) and persist a per-match odds snapshot.

    Returns a status dict; a no-op (status='skipped') when ODDS_API_KEY is unset
    so callers in the pipeline never fail.
    """
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    if not _key():
        return {"status": "skipped", "reason": "ODDS_API_KEY unset", "n": 0}
    try:
        if date_iso:
            rows = fetch_historical(date_iso, regions, markets)
            snap_ts = date_iso
        else:
            rows = fetch_live(regions, markets)
            snap_ts = datetime.now(timezone.utc).isoformat()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError) as e:
        return {"status": "error", "error": str(e)[:200], "n": 0}

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"{ts}.json").write_text(
        json.dumps({"snapshot_ts": snap_ts, "regions": regions,
                    "markets": markets, "events": rows},
                   indent=2, ensure_ascii=False))
    added = _append_history(rows, snap_ts)
    return {"status": "fetched", "n": len(rows), "added_to_history": added,
            "snapshot_ts": snap_ts}


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    out = []
    for line in HISTORY_FILE.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def pre_kickoff_line(history: list[dict], home: str, away: str,
                     kickoff: datetime) -> dict | None:
    """Latest snapshot for a fixture observed strictly BEFORE kickoff (no leakage)."""
    def _parse(ts):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    ko = kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=timezone.utc)
    cands = []
    for d in history:
        if {d.get("home"), d.get("away")} != {home, away}:
            continue
        st = _parse(d.get("snapshot_ts"))
        if st and st < ko:
            cands.append((st, d))
    if not cands:
        return None
    return max(cands, key=lambda x: x[0])[1]


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot per-match WC odds (the-odds-api)")
    ap.add_argument("--date", help="historical snapshot ISO ts (e.g. 2026-06-15T18:00:00Z)")
    ap.add_argument("--regions", default=DEFAULT_REGIONS)
    ap.add_argument("--markets", default=DEFAULT_MARKETS)
    ap.add_argument("--backfill-kickoffs", action="store_true",
                    help="historical snapshot ~2h before each completed fixture's kickoff")
    args = ap.parse_args()

    if not _key():
        print("ODDS_API_KEY unset — nothing to do. "
              "Set it (env var / GitHub secret) to capture per-match odds.")
        return

    if args.backfill_kickoffs:
        from wc2026_bet.espn import fetch_fixtures
        seen_ts = set()
        total = 0
        for f in fetch_fixtures():
            d = f.get("date")
            if not d or f.get("home_score") is None:
                continue
            try:
                ko = datetime.fromisoformat(d.replace("Z", ""))
            except ValueError:
                continue
            snap = (ko.replace(tzinfo=timezone.utc) - timedelta(hours=2))
            iso = snap.strftime("%Y-%m-%dT%H:%M:%SZ")
            if iso in seen_ts:
                continue
            seen_ts.add(iso)
            st = snapshot(ts=snap.strftime("%Y-%m-%dT%H%M"), date_iso=iso,
                          regions=args.regions, markets=args.markets)
            total += st.get("added_to_history", 0)
            print(f"  {iso}: {st['status']} n={st.get('n', 0)} +{st.get('added_to_history', 0)}")
        print(f"backfill done: +{total} fixture-snapshots -> {HISTORY_FILE}")
        return

    st = snapshot(date_iso=args.date, regions=args.regions, markets=args.markets)
    print(f"match odds snapshot: {st}")


if __name__ == "__main__":
    main()
