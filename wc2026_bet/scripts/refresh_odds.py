"""Stage 1b - refresh the market odds snapshots for a live timestamp.

Best-effort: attempt to fetch each documented odds source, save a raw snapshot
under data/live/odds_raw/, and rebuild the processed market CSVs via the
existing parse/build helpers in collect_data.py. Sportsbook pages are commonly
bot-blocked / JS-rendered, so any source that fails to fetch **falls back to the
last good snapshot** already in data/raw; we log exactly which sources were
refreshed vs fell back into data/live/odds_status_<TS>.json and snapshot the
resulting market CSVs into data/live/market_*_<TS>.csv for reproducibility.

To genuinely refresh a board, drop an updated markdown table into the matching
data/raw/market_*_2026-06.md file (same format as the existing snapshots) and
re-run; the advance / Golden-Boot CSVs are rebuilt from it automatically.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import DATA_LIVE, DATA_PROCESSED

import collect_data as cd  # noqa: E402  (same scripts dir)
import eloratings_live as el  # noqa: E402
import kalshi_odds as ko  # noqa: E402

# Documented odds sources (same URLs recorded in collect_data.manifest).
SOURCES = {
    "si_outright": "https://www.si.com/betting/every-teams-championship-group-odds-for-the-2026-world-cup-spain-and-france-top-odds-list-01kt4yygesqb",
    "fox_advance": "https://www.foxsports.com/stories/soccer/2026-world-cup-odds-teams-favored-advance-knockout-stage",
    "rotowire_gb": "https://www.rotowire.com/soccer/article/2026-world-cup-golden-boot-odds-full-player-list-mbappe-kane-haaland-108917",
    "opta_title": "https://theanalyst.com/articles/who-will-win-2026-fifa-world-cup-predictions-opta-supercomputer",
    "elo": "https://www.international-football.net/elo-ratings-table?day=30&month=05&year=2026",
}


def try_fetch(name: str, url: str, raw_dir: Path) -> dict:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (wc2026-bet odds refresh)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
        (raw_dir / f"{name}.html").write_bytes(body)
        return {"source": name, "url": url, "status": "fetched",
                "bytes": len(body)}
    except Exception as e:  # noqa: BLE001
        return {"source": name, "url": url, "status": "fallback",
                "error": str(e)[:160]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M"))
    args = ap.parse_args()
    ts = args.ts

    raw_dir = DATA_LIVE / "odds_raw" / ts
    raw_dir.mkdir(parents=True, exist_ok=True)

    statuses = [try_fetch(n, u, raw_dir) for n, u in SOURCES.items()]
    for s in statuses:
        print(f"  {s['source']:14s} {s['status']}"
              + (f" ({s['bytes']}B)" if s.get("bytes") else f"  [{s.get('error','')}]"))

    # Per-run EMA-weighted live eloratings -> the strength prior for the blend.
    weighted_elo = el.update_weighted_eloratings()

    kalshi_status = {"source": "kalshi_title", "status": "fallback"}
    try:
        ko.refresh_kalshi_title_odds(eloratings=weighted_elo)
        kalshi_status = {"source": "kalshi_title", "status": "fetched",
                         "url": f"https://kalshi.com/markets/kxmenworldcup/mens-world-cup-winner/{ko.EVENT_TICKER.lower()}"}
        print(f"  kalshi_title   fetched")
    except Exception as e:  # noqa: BLE001
        kalshi_status = {"source": "kalshi_title", "status": "fallback",
                         "error": str(e)[:160]}
        print(f"  kalshi_title   fallback  [{kalshi_status['error']}]")
    statuses.append(kalshi_status)

    # Rebuild the de-vigged advance + Golden-Boot boards from the (possibly
    # refreshed) raw markdown; these reproduce data/processed if the markdown is
    # unchanged. Outright / Opta title boards come from collect_data's curated
    # dicts and are snapshotted as-is.
    adv = cd.build_market_advance()
    gb = cd.build_market_golden_boot()
    adv.to_csv(DATA_PROCESSED / "market_advance.csv", index=False)
    gb.to_csv(DATA_PROCESSED / "market_golden_boot.csv", index=False)
    print(f"  rebuilt market_advance ({len(adv)} teams) + "
          f"market_golden_boot ({len(gb)} players) from raw markdown")

    # Per-timestamp snapshots of the resulting processed market CSVs.
    for nm in ("market_advance", "market_golden_boot", "market_outright",
               "market_title_odds"):
        src = DATA_PROCESSED / f"{nm}.csv"
        if src.exists():
            shutil.copy(src, DATA_LIVE / f"{nm}_{ts}.csv")

    refreshed = [s["source"] for s in statuses if s["status"] == "fetched"]
    fellback = [s["source"] for s in statuses if s["status"] != "fetched"]
    status = {"timestamp": ts,
              "collected_at": datetime.now(timezone.utc).isoformat(),
              "refreshed": refreshed, "fell_back": fellback,
              "sources": statuses,
              "note": ("Title winner odds refreshed from Kalshi before each run; "
                       "advance / Golden Boot from data/raw markdown (drop an "
                       "updated table there to move those lines).")}
    (DATA_LIVE / f"odds_status_{ts}.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False))
    print(f"  refreshed: {refreshed or 'none'}; fell back: {fellback or 'none'}")
    print(f"Wrote odds status -> {DATA_LIVE / f'odds_status_{ts}.json'}")


if __name__ == "__main__":
    main()
