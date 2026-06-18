"""Live World Cup winner odds from Kalshi (public API, no auth).

Fetched before each pipeline run so title-implied strength priors track the
prediction market instead of the pre-tournament FanDuel snapshot.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from wc2026_bet.config import DATA_PROCESSED
from wc2026_bet.names import resolve, slug

import collect_data as cd  # noqa: E402  (same scripts dir)

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
EVENT_TICKER = "KXMENWORLDCUP-26"
SERIES_TICKER = "KXMENWORLDCUP"
# Kalshi markets opened May 2025, but the chart starts at May 1, 2026 so the
# graph focuses on the run-up to (and during) the tournament instead of a long
# flat year of pre-tournament pricing.
CHART_START_TS = int(datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).timestamp())
HISTORY_FILE = Path(__file__).resolve().parents[1] / "data" / "history" / "kalshi_title_history.json"
CHART_TOP_N = 8
UA = "Mozilla/5.0 (wc2026-bet kalshi refresh)"
# Weight on the LIVE Kalshi de-vigged title odds when blending with Opta's
# (static, pre-tournament) supercomputer title probabilities to form the
# spread-calibration anchor. 0 = pure Opta (old behaviour), 1 = pure Kalshi.
KALSHI_TITLE_WEIGHT = 0.5


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _market_yes_prob(market: dict) -> float:
    """Mid-price YES probability from a Kalshi binary market."""
    bid = float(market.get("yes_bid_dollars") or 0)
    ask = float(market.get("yes_ask_dollars") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    last = float(market.get("last_price_dollars") or 0)
    if last > 0:
        return last
    return ask or bid or 0.0


def _devig(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        return probs
    return {t: p / total for t, p in probs.items()}


def _implied_to_american(p: float) -> int:
    if p <= 0:
        return 999999
    return int(round(100.0 / p - 100.0))


def fetch_title_markets() -> list[dict]:
    url = (f"{KALSHI_API}/markets?event_ticker={EVENT_TICKER}&limit=100")
    return _fetch_json(url).get("markets") or []


def parse_live_title_odds(markets: list[dict]) -> tuple[dict[str, float], dict[str, str]]:
    """Return (de-vigged implied prob by team, ticker by team)."""
    raw: dict[str, float] = {}
    tickers: dict[str, str] = {}
    for m in markets:
        team = resolve(m.get("yes_sub_title") or "")
        if not team:
            continue
        p = _market_yes_prob(m)
        if p <= 0:
            continue
        raw[team] = p
        tickers[team] = m["ticker"]
    return _devig(raw), tickers


def apply_title_odds_to_processed(implied: dict[str, float],
                                source: str = "kalshi",
                                eloratings: dict[str, float] | None = None) -> None:
    """Rewrite teams.csv, elo.csv, market_outright.csv with live title odds.

    ``eloratings`` (canonical name -> Elo) is the strength prior fed into the
    market blend; defaults to the static May-30 baseline. Pass the per-run
    EMA-weighted live ratings (eloratings_live.update_weighted_eloratings) to
    let tournament form gradually move the prior.
    """
    elo_base = dict(eloratings) if eloratings else dict(cd.ELORATINGS_2026)
    blended, market_elo, _ = cd.blend_elo_with_implied(elo_base, implied)
    elo_by_slug = {slug(t): float(blended[t]) for t in cd.CANONICAL_TEAMS}
    base_by_slug = {slug(t): float(elo_base[t]) for t in cd.CANONICAL_TEAMS}

    teams = pd.read_csv(DATA_PROCESSED / "teams.csv")
    for i, row in teams.iterrows():
        t = row["team"]
        s = row["slug"]
        if t in implied:
            teams.at[i, "market_prob"] = round(implied[t], 4)
            teams.at[i, "elo_market"] = round(market_elo[t], 1) if t in market_elo else ""
        if s in base_by_slug:
            teams.at[i, "elo_eloratings"] = round(base_by_slug[s], 1)
        if s in elo_by_slug:
            teams.at[i, "elo"] = round(elo_by_slug[s], 1)
    teams.to_csv(DATA_PROCESSED / "teams.csv", index=False)

    elo_df = pd.read_csv(DATA_PROCESSED / "elo.csv")
    for i, row in elo_df.iterrows():
        t = row["team"]
        s = row["slug"]
        if t in implied:
            elo_df.at[i, "market_prob"] = round(implied[t], 4)
            elo_df.at[i, "elo_market_implied"] = (
                round(market_elo[t], 1) if t in market_elo else "")
        if s in base_by_slug:
            elo_df.at[i, "elo_eloratings"] = round(base_by_slug[s], 1)
        if s in elo_by_slug:
            elo_df.at[i, "elo_blended"] = round(elo_by_slug[s], 1)
    elo_df.to_csv(DATA_PROCESSED / "elo.csv", index=False)

    out_rows = [
        {"team": t,
         "american_odds": _implied_to_american(implied[t]),
         "implied_prob": round(implied[t], 4),
         "elo_market_implied": round(market_elo[t], 1) if t in market_elo else "",
         "source": source}
        for t in sorted(implied, key=lambda x: -implied[x])
    ]
    pd.DataFrame(out_rows).to_csv(DATA_PROCESSED / "market_outright.csv", index=False)


def write_blended_title_anchors(implied: dict[str, float],
                                weight: float = KALSHI_TITLE_WEIGHT) -> None:
    """Rewrite market_title_odds.csv with a Kalshi+Opta blended title anchor.

    The spread calibration (calibration.calibrate_spread) fits the global
    strength-separation knob to these per-team title probabilities. Blending the
    live Kalshi de-vig with Opta's static prior keeps a model-based stabiliser
    while letting the live market move the title *shape* each run.

    Columns: team, opta_title_prob, kalshi_title_prob, title_prob (blended).
    """
    opta = cd.OPTA_TITLE_PROB
    teams = sorted(set(implied) | set(opta), key=lambda t: -implied.get(t, 0.0))
    rows = []
    for t in teams:
        k = implied.get(t)
        o = opta.get(t)
        if k is not None and o is not None:
            blended = weight * k + (1 - weight) * o
        elif k is not None:
            blended = k
        else:
            blended = o
        rows.append({
            "team": t,
            "opta_title_prob": round(o, 4) if o is not None else "",
            "kalshi_title_prob": round(k, 4) if k is not None else "",
            "title_prob": round(float(blended), 4),
        })
    pd.DataFrame(rows).to_csv(DATA_PROCESSED / "market_title_odds.csv", index=False)


def fetch_candlesticks(ticker: str, start_ts: int, end_ts: int) -> list[dict]:
    url = (f"{KALSHI_API}/series/{SERIES_TICKER}/markets/{ticker}/candlesticks"
           f"?period_interval=1440&start_ts={start_ts}&end_ts={end_ts}")
    for attempt in range(3):
        try:
            data = _fetch_json(url)
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(0.35 * (attempt + 1))
                continue
            return []
    pts = []
    for c in data.get("candlesticks") or []:
        price = c.get("price") or {}
        p = price.get("close_dollars") or price.get("mean_dollars")
        if p is None:
            continue
        pts.append({"ts": c["end_period_ts"], "p": round(float(p), 4)})
    return pts


def refresh_kalshi_history(implied: dict[str, float],
                           tickers: dict[str, str]) -> dict:
    """Fetch daily Kalshi title history for charting; persist to data/history/."""
    end_ts = int(time.time())
    top = sorted(implied, key=lambda t: -implied[t])[:CHART_TOP_N]
    series = []
    for team in top:
        ticker = tickers.get(team)
        if not ticker:
            continue
        pts = fetch_candlesticks(ticker, CHART_START_TS, end_ts)
        if not pts:
            continue
        series.append({"team": team, "ticker": ticker, "points": pts})
        time.sleep(0.15)
    payload = {
        "event_ticker": EVENT_TICKER,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": f"https://kalshi.com/markets/kxmenworldcup/mens-world-cup-winner/{EVENT_TICKER.lower()}",
        "series": series,
    }
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def refresh_kalshi_title_odds(eloratings: dict[str, float] | None = None) -> dict:
    """Pull live Kalshi winner odds and update processed team priors.

    ``eloratings`` is the (optionally EMA-weighted live) strength prior blended
    with the market title odds; defaults to the static May-30 baseline.
    """
    markets = fetch_title_markets()
    implied, tickers = parse_live_title_odds(markets)
    if len(implied) < 20:
        raise RuntimeError(f"Kalshi returned too few teams ({len(implied)})")
    apply_title_odds_to_processed(implied, eloratings=eloratings)
    write_blended_title_anchors(implied)
    cal_cache = DATA_PROCESSED / "calibration.json"
    if cal_cache.exists():
        cal_cache.unlink()
        print("  invalidated cached calibration (Kalshi title odds updated)")
    hist = refresh_kalshi_history(implied, tickers)
    top3 = sorted(implied, key=lambda t: -implied[t])[:3]
    summary = ", ".join(f"{t} {implied[t]:.1%}" for t in top3)
    print(f"  kalshi title odds ({len(implied)} teams): {summary}")
    print(f"  kalshi history -> {HISTORY_FILE} ({len(hist['series'])} series)")
    return {"implied": implied, "tickers": tickers, "history": hist}
