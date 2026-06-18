"""STAGE 1 - data collection.

Reads the raw sources cloned under ``data/raw`` and derives clean, analysis-
ready tables in ``data/processed``. This is the ONLY stage that depends on the
external sources; ``run_analysis.py`` consumes the processed files offline.

Raw sources (cloned into data/raw, recorded in manifest.json):
  * hicruben/world-cup-2026-prediction-model : 920 international results
    (2023-2026) + calibrated Elo for finalists.
  * 0xNadr/wc2026 : official Dec-2025 draw, full 104-match schedule with the
    real knockout bracket, and per-player Golden-Boot probabilities.

Outputs (data/processed):
  teams.csv, groups.csv, schedule_groups.csv, bracket.json,
  results.csv, elo.csv, players.csv, market_title_odds.csv, manifest.json
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import (DATA_PROCESSED, DATA_RAW, HOST_NATIONS,
                               MATCH_IMPORTANCE, REFERENCE_DATE,
                               TIME_DECAY_HALFLIFE_YEARS)
from wc2026_bet.names import (CANONICAL_TEAMS, _norm, resolve, resolve_any,
                              slug)
from wc2026_bet.tiers import TEAM_TIER

HICRUBEN = DATA_RAW / "hicruben"
NADR = DATA_RAW / "nadr"
SCHEDULE_JSON = NADR / "web" / "public" / "schedule.json"
RESULTS_JSON = HICRUBEN / "data" / "results.json"
ELO_JSON = HICRUBEN / "data" / "elo-calibrated.json"
GOLDEN_BOOT_CSV = NADR / "output" / "golden_boot_probabilities.csv"

# Market-odds snapshots (saved under data/raw for provenance; see each file's
# header for source URL / board / fetch date).
MARKET_ADVANCE_MD = DATA_RAW / "market_advance_2026-06.md"
MARKET_GOLDEN_BOOT_MD = DATA_RAW / "market_golden_boot_2026-06.md"


def parse_md_odds(path: Path) -> list[tuple]:
    """Parse a leading markdown ``| ... |`` table of American odds.

    Returns a list of the non-header data rows as tuples of stripped cells.
    Stops at the first blank line after the table so trailing prose / second
    tables (e.g. group-winner odds) are ignored.
    """
    rows, in_table = [], False
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            # skip header row and the |---|---| separator
            if set("".join(cells)) <= set("-: "):
                continue
            if cells and cells[-1].lstrip("+-").isdigit():
                rows.append(tuple(cells))
                in_table = True
        elif in_table and not s:
            break
    return rows

# Confederation of each finalist (from the official allocation).
CONFEDERATION = {
    "United States": "CONCACAF", "Canada": "CONCACAF", "Mexico": "CONCACAF",
    "Panama": "CONCACAF", "Curaçao": "CONCACAF", "Haiti": "CONCACAF",
    "Argentina": "CONMEBOL", "Brazil": "CONMEBOL", "Uruguay": "CONMEBOL",
    "Colombia": "CONMEBOL", "Paraguay": "CONMEBOL", "Ecuador": "CONMEBOL",
    "France": "UEFA", "England": "UEFA", "Spain": "UEFA", "Germany": "UEFA",
    "Portugal": "UEFA", "Netherlands": "UEFA", "Belgium": "UEFA",
    "Croatia": "UEFA", "Switzerland": "UEFA", "Austria": "UEFA",
    "Norway": "UEFA", "Scotland": "UEFA", "Sweden": "UEFA", "Turkey": "UEFA",
    "Czech Republic": "UEFA", "Bosnia and Herzegovina": "UEFA",
    "Morocco": "CAF", "Senegal": "CAF", "Egypt": "CAF", "Algeria": "CAF",
    "Tunisia": "CAF", "Ghana": "CAF", "Ivory Coast": "CAF", "Cape Verde": "CAF",
    "South Africa": "CAF", "DR Congo": "CAF",
    "Japan": "AFC", "South Korea": "AFC", "Iran": "AFC", "Australia": "AFC",
    "Saudi Arabia": "AFC", "Qatar": "AFC", "Jordan": "AFC", "Uzbekistan": "AFC",
    "Iraq": "AFC", "New Zealand": "OFC",
}

# Opta supercomputer pre-tournament title probabilities (used as a calibration
# anchor). Source: theanalyst.com "Who Will Win the 2026 FIFA World Cup?"
# (10,000-sim pre-tournament run, fetched 2026-06).
OPTA_TITLE_PROB = {
    "Spain": 0.161, "France": 0.130, "England": 0.112, "Argentina": 0.104,
    "Portugal": 0.070, "Brazil": 0.066,
    "United States": 0.0121, "Mexico": 0.0099, "Canada": 0.0052,
}

# City-suffix -> venue country (host nation) for the home-advantage feature.
COUNTRY_SUFFIX = {"USA": "United States", "CAN": "Canada", "MEX": "Mexico"}

# Authoritative World Football Elo ratings as of 30 May 2026 (eloratings.net,
# via international-football.net). Saved raw in data/raw/eloratings_2026-05-30.md.
# Canonical, consistent across all 48 finalists - used as the model's strength
# prior (anchor for the attack/defence fit).
ELORATINGS_2026 = {
    "Spain": 2165, "Argentina": 2113, "France": 2081, "England": 2020,
    "Brazil": 1984, "Portugal": 1984, "Colombia": 1975, "Netherlands": 1961,
    "Ecuador": 1935, "Croatia": 1930, "Germany": 1923, "Norway": 1912,
    "Japan": 1904, "Turkey": 1902, "Uruguay": 1892, "Switzerland": 1889,
    "Senegal": 1878, "Mexico": 1868, "Belgium": 1867, "Paraguay": 1833,
    "Austria": 1827, "Morocco": 1822, "Canada": 1784, "Australia": 1775,
    "Scotland": 1770, "Iran": 1764, "South Korea": 1756, "Algeria": 1743,
    "Panama": 1737, "Uzbekistan": 1727, "Czech Republic": 1726,
    "United States": 1721, "Sweden": 1719, "Egypt": 1699, "Jordan": 1690,
    "Ivory Coast": 1676, "DR Congo": 1655, "Tunisia": 1636, "Iraq": 1608,
    "Bosnia and Herzegovina": 1591, "New Zealand": 1585, "Saudi Arabia": 1566,
    "Cape Verde": 1549, "Haiti": 1532, "South Africa": 1517, "Ghana": 1503,
    "Curaçao": 1433, "Qatar": 1423,
}
assert set(ELORATINGS_2026) == set(CANONICAL_TEAMS), (
    set(CANONICAL_TEAMS) ^ set(ELORATINGS_2026))

# Market outright-winner odds (American format) as of June 2026. Source: SI /
# FanDuel "Every Team's Championship Odds for the 2026 World Cup" (raw snapshot:
# data/raw/market_outright_2026-06.md), cross-checked vs FOX/ESPN/DraftKings.
# eloratings.net rates a few "brand" teams (Germany, France, England, Brazil)
# below the market because their squad quality outruns recent results; we blend
# these market odds into the strength prior the way Opta does. The 15 teams the
# book floors at +250000 (uninformative tail) are dropped here - their strength
# is pinned instead by the "to advance" calibration (calibrate_team_strengths).
MARKET_ODDS_AMERICAN = {
    "Spain": 420, "France": 460, "England": 650, "Brazil": 850,
    "Portugal": 1000, "Argentina": 1000, "Germany": 1300, "Netherlands": 1600,
    "Belgium": 2200, "Norway": 3500, "Colombia": 4000, "Japan": 4500,
    "Morocco": 6000, "United States": 6000, "Uruguay": 6000, "Mexico": 6500,
    "Switzerland": 6500, "Croatia": 7000, "Turkey": 8000, "Ecuador": 10000,
    "Senegal": 12500, "Austria": 12500, "Canada": 17500, "Sweden": 17500,
    "Ivory Coast": 17500, "Paraguay": 20000, "Egypt": 25000, "Scotland": 30000,
    "Bosnia and Herzegovina": 40000, "Ghana": 60000, "Czech Republic": 60000,
    "South Korea": 70000, "Iran": 100000,
}


def american_to_implied(odds: int) -> float:
    """American odds -> implied win probability (with bookmaker margin)."""
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / (-odds + 100.0)


def blend_elo_with_implied(elo: dict[str, float], implied: dict[str, float],
                          market_weight: float = 0.55):
    """Blend eloratings with market-implied win probs (Opta-style).

    ``implied`` maps team name -> de-vigged P(title). Returns
    (blended_elo, market_implied_elo, implied) keyed by team name.
    """
    import numpy as np

    teams = [t for t in implied if t in elo and implied[t] > 0]
    if len(teams) < 8:
        return dict(elo), {}, implied
    x = np.log(np.array([implied[t] for t in teams]))
    y = np.array([elo[t] for t in teams])
    a, b = np.polyfit(x, y, 1)              # elo ~ a*log(p) + b
    market_elo = {t: float(a * np.log(implied[t]) + b) for t in teams}
    blended = {}
    for t, e in elo.items():
        if t in market_elo:
            blended[t] = (1 - market_weight) * e + market_weight * market_elo[t]
        else:
            blended[t] = e
    return blended, market_elo, implied


def blend_elo_with_market(elo: dict[str, float], market_weight: float = 0.55):
    """Blend eloratings with a market-implied Elo (Opta-style).

    A team's market implied probability is mapped onto the Elo scale by
    regressing eloratings on log(implied prob) over the teams that have odds;
    the blended prior is ``(1-w)*elo + w*market_elo`` for those teams and plain
    eloratings for the rest. Returns (blended, market_implied_elo, implied_prob).
    """
    implied = {t: american_to_implied(o) for t, o in MARKET_ODDS_AMERICAN.items()}
    return blend_elo_with_implied(elo, implied, market_weight)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def importance_of(league: str) -> float:
    """Map a competition name to an Elo-style importance weight."""
    l = league.lower()
    if "world cup" in l and "qualif" in l:
        return 0.65
    if "world cup" in l:
        return 1.00
    if "euro" in l and "qualif" in l:
        return 0.55
    if "euro champ" in l:
        return 0.85
    if "nations league" in l:
        return 0.55
    if "copa america" in l:
        return 0.85
    if "africa cup of nations" in l and "qualif" not in l:
        return 0.75
    if "asian cup" in l or "afc asian" in l:
        return 0.70
    if "gold cup" in l:
        return 0.65
    if "friendl" in l:
        return 0.30
    return 0.45


def git_meta(repo: Path) -> dict:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        when = subprocess.check_output(
            ["git", "-C", str(repo), "log", "-1", "--format=%ci"], text=True).strip()
        url = subprocess.check_output(
            ["git", "-C", str(repo), "remote", "get-url", "origin"], text=True).strip()
        return {"url": url, "commit": commit, "commit_date": when}
    except Exception as e:  # pragma: no cover
        return {"error": str(e)}


def compute_elo(matches: list[dict]) -> dict[str, float]:
    """World-Football-Elo style ratings from chronological results.

    K is scaled by competition importance; a goal-difference multiplier rewards
    decisive wins. Everyone starts at 1500. Returns slug -> rating.
    """
    K0 = 40.0
    rating: dict[str, float] = defaultdict(lambda: 1500.0)
    for m in sorted(matches, key=lambda x: x["ts"]):
        h = resolve_any(m["homeName"])
        a = resolve_any(m["awayName"])
        hg, ag = m["hg"], m["ag"]
        if hg is None or ag is None:
            continue
        sh = slug(h) if resolve(m["homeName"]) else h
        sa = slug(a) if resolve(m["awayName"]) else a
        Ra, Rb = rating[sh], rating[sa]
        exp_h = 1.0 / (1.0 + 10 ** ((Rb - Ra) / 400.0))
        res_h = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        gd = abs(hg - ag)
        if gd <= 1:
            mult = 1.0
        elif gd == 2:
            mult = 1.5
        elif gd == 3:
            mult = 1.75
        else:
            mult = 1.75 + (gd - 3) / 8.0
        k = K0 * importance_of(m["leagueName"]) * mult
        delta = k * (res_h - exp_h)
        rating[sh] = Ra + delta
        rating[sa] = Rb - delta
    return dict(rating)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def load_schedule() -> dict:
    return json.loads(SCHEDULE_JSON.read_text())


def build_groups_and_schedule(sched: dict):
    """Return (groups: {grp:[teams]}, group_matches: DataFrame)."""
    groups: dict[str, list[str]] = defaultdict(list)
    rows = []
    for m in sched["matches"]:
        g = m.get("group")
        if not g:
            continue
        home = resolve(m["home"]) or m["home"]
        away = resolve(m["away"]) or m["away"]
        for t in (home, away):
            if t not in groups[g]:
                groups[g].append(t)
        city = m.get("city", "")
        suffix = city.split(",")[-1].strip() if "," in city else ""
        venue_country = COUNTRY_SUFFIX.get(suffix, "")
        rows.append({
            "match": m["match"], "group": g, "home": home, "away": away,
            "venue": m.get("venue", ""), "city": city,
            "venue_country": venue_country,
        })
    groups = {g: groups[g] for g in sorted(groups)}
    for g, ts in groups.items():
        assert len(ts) == 4, f"group {g} has {len(ts)} teams: {ts}"
    return groups, pd.DataFrame(rows).sort_values("match").reset_index(drop=True)


def parse_slot(ref: str) -> dict:
    """Parse a knockout slot reference into a structured source."""
    ref = ref.strip()
    if ref.startswith("Winner ") and ref[7:].isdigit():
        return {"type": "match_winner", "match": int(ref[7:])}
    if ref.startswith("Loser ") and ref[6:].isdigit():
        return {"type": "match_loser", "match": int(ref[6:])}
    if ref.startswith("Winner "):
        return {"type": "group_winner", "group": ref[7:].strip()}
    if ref.startswith("Runner-up "):
        return {"type": "group_runner", "group": ref[10:].strip()}
    if ref.startswith("3rd "):
        groups = [g.strip() for g in ref[4:].split("/")]
        return {"type": "third", "eligible": groups}
    raise ValueError(f"unparseable slot ref: {ref!r}")


ROUND_CODE = {
    "Round of 32": 1, "Round of 16": 2, "Quarter-final": 3,
    "Semi-final": 4, "Third place": 5, "Final": 6,
}

# Official 2026 knockout bracket. Source: Wikipedia "2026 FIFA World Cup
# knockout stage" + FIFA.com (retrieved 2026-06). The bundled nadr schedule.json
# had several knockout-slot errors (e.g. match 73 listed "Winner A" instead of
# "Runner-up A", and matches 77/78, 81/82, 83/84, 86/87/88 were scrambled), so
# we encode the authoritative bracket here and only borrow venues from the
# schedule by match number.
OFFICIAL_BRACKET = [
    # (match, stage, home_ref, away_ref)
    (73, "Round of 32", "Runner-up A", "Runner-up B"),
    (74, "Round of 32", "Winner E", "3rd A/B/C/D/F"),
    (75, "Round of 32", "Winner F", "Runner-up C"),
    (76, "Round of 32", "Winner C", "Runner-up F"),
    (77, "Round of 32", "Winner I", "3rd C/D/F/G/H"),
    (78, "Round of 32", "Runner-up E", "Runner-up I"),
    (79, "Round of 32", "Winner A", "3rd C/E/F/H/I"),
    (80, "Round of 32", "Winner L", "3rd E/H/I/J/K"),
    (81, "Round of 32", "Winner D", "3rd B/E/F/I/J"),
    (82, "Round of 32", "Winner G", "3rd A/E/H/I/J"),
    (83, "Round of 32", "Runner-up K", "Runner-up L"),
    (84, "Round of 32", "Winner H", "Runner-up J"),
    (85, "Round of 32", "Winner B", "3rd E/F/G/I/J"),
    (86, "Round of 32", "Winner J", "Runner-up H"),
    (87, "Round of 32", "Winner K", "3rd D/E/I/J/L"),
    (88, "Round of 32", "Runner-up D", "Runner-up G"),
    (89, "Round of 16", "Winner 74", "Winner 77"),
    (90, "Round of 16", "Winner 73", "Winner 75"),
    (91, "Round of 16", "Winner 76", "Winner 78"),
    (92, "Round of 16", "Winner 79", "Winner 80"),
    (93, "Round of 16", "Winner 83", "Winner 84"),
    (94, "Round of 16", "Winner 81", "Winner 82"),
    (95, "Round of 16", "Winner 86", "Winner 88"),
    (96, "Round of 16", "Winner 85", "Winner 87"),
    (97, "Quarter-final", "Winner 89", "Winner 90"),
    (98, "Quarter-final", "Winner 93", "Winner 94"),
    (99, "Quarter-final", "Winner 91", "Winner 92"),
    (100, "Quarter-final", "Winner 95", "Winner 96"),
    (101, "Semi-final", "Winner 97", "Winner 98"),
    (102, "Semi-final", "Winner 99", "Winner 100"),
    (103, "Third place", "Loser 101", "Loser 102"),
    (104, "Final", "Winner 101", "Winner 102"),
]


def build_bracket(sched: dict) -> list[dict]:
    # venue lookup from the schedule (match number -> venue/city), for reporting
    venue_by_match = {m["match"]: m for m in sched["matches"]}
    bracket = []
    for mno, stage, home_ref, away_ref in OFFICIAL_BRACKET:
        sm = venue_by_match.get(mno, {})
        city = sm.get("city", "")
        suffix = city.split(",")[-1].strip() if "," in city else ""
        bracket.append({
            "match": mno, "stage": stage,
            "round_code": ROUND_CODE[stage],
            "home_ref": parse_slot(home_ref),
            "away_ref": parse_slot(away_ref),
            "venue": sm.get("venue", ""), "city": city,
            "venue_country": COUNTRY_SUFFIX.get(suffix, ""),
        })
    return bracket


def build_results(raw: dict) -> pd.DataFrame:
    ref = date.fromisoformat(REFERENCE_DATE)
    finalists = set(CANONICAL_TEAMS)
    rows = []
    for m in raw["matches"]:
        if m["hg"] is None or m["ag"] is None:
            continue
        d = date.fromisoformat(m["date"])
        age_years = (ref - d).days / 365.25
        imp = importance_of(m["leagueName"])
        decay = 0.5 ** (age_years / TIME_DECAY_HALFLIFE_YEARS)
        home_c = resolve(m["homeName"])
        away_c = resolve(m["awayName"])
        rows.append({
            "date": m["date"], "ts": m["ts"],
            "home": home_c or resolve_any(m["homeName"]),
            "away": away_c or resolve_any(m["awayName"]),
            "hg": m["hg"], "ag": m["ag"],
            "league": m["leagueName"], "importance": imp,
            "age_years": round(age_years, 3),
            "weight": round(decay * imp, 5),
            "home_finalist": (home_c in finalists),
            "away_finalist": (away_c in finalists),
        })
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)


def build_market_advance() -> pd.DataFrame:
    """De-vigged market probability to advance to the Round of 32, all 48 teams.

    Each team is a separate yes/no market; we de-vig by normalizing the implied
    probabilities so they sum to 32 (exactly 32 of 48 teams advance).
    """
    rows = parse_md_odds(MARKET_ADVANCE_MD)
    raw = {}
    for team, odds in rows:
        t = resolve(team) or team
        raw[t] = american_to_implied(int(odds))
    missing = set(CANONICAL_TEAMS) - set(raw)
    assert not missing, f"advance odds missing teams: {missing}"
    scale = 32.0 / sum(raw.values())
    return pd.DataFrame([
        {"team": t, "american_odds": int(o),
         "implied_raw": round(american_to_implied(int(o)), 4),
         "p_advance": round(min(0.999, raw[resolve(t) or t] * scale), 4)}
        for t, o in ((resolve(tm) or tm, od) for tm, od in rows)
    ]).sort_values("p_advance", ascending=False).reset_index(drop=True)


def build_market_golden_boot() -> pd.DataFrame:
    """De-vigged market P(win Golden Boot) per player (normalized to sum 1)."""
    rows = parse_md_odds(MARKET_GOLDEN_BOOT_MD)
    recs = []
    for player, country, odds in rows:
        recs.append({"player": player, "country": resolve(country) or country,
                     "american_odds": int(odds),
                     "implied_raw": american_to_implied(int(odds))})
    tot = sum(r["implied_raw"] for r in recs)
    for r in recs:
        r["p_gb"] = r["implied_raw"] / tot
        r["implied_raw"] = round(r["implied_raw"], 4)
        r["p_gb"] = round(r["p_gb"], 5)
    return pd.DataFrame(recs).sort_values("p_gb", ascending=False).reset_index(drop=True)


def build_players(market_gb: pd.DataFrame) -> pd.DataFrame:
    gb = pd.read_csv(GOLDEN_BOOT_CSV)
    gb["team"] = gb["team"].apply(lambda t: resolve(t) or t)
    keep = ["scorer", "team", "blended_share", "expected_team_goals",
            "expected_player_goals", "p_top_scorer"]
    gb = gb[keep].copy()
    # Keep only finalist players.
    gb = gb[gb["team"].isin(CANONICAL_TEAMS)].reset_index(drop=True)

    # Attach the de-vigged market Golden-Boot probability by normalized name.
    mkt = {_norm(r.player): r.p_gb for r in market_gb.itertuples()}
    gb["market_p_gb"] = gb["scorer"].apply(lambda s: mkt.get(_norm(s), 0.0))
    return gb


def main() -> None:
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    sched = load_schedule()

    groups, group_matches = build_groups_and_schedule(sched)
    bracket = build_bracket(sched)
    raw_results = json.loads(RESULTS_JSON.read_text())
    results = build_results(raw_results)
    elo_eloratings = dict(ELORATINGS_2026)                       # by team name
    blended, market_elo, implied = blend_elo_with_market(elo_eloratings)
    elo = {slug(t): float(blended[t]) for t in CANONICAL_TEAMS}   # prior used by model
    raw_elo = compute_elo(raw_results["matches"])  # home-grown, for comparison
    market_advance = build_market_advance()
    market_gb = build_market_golden_boot()
    players = build_players(market_gb)

    # teams.csv
    team_to_group = {t: g for g, ts in groups.items() for t in ts}
    team_rows = []
    for t in CANONICAL_TEAMS:
        team_rows.append({
            "team": t, "slug": slug(t),
            "confederation": CONFEDERATION[t],
            "host": t in HOST_NATIONS,
            "tier": TEAM_TIER[t],
            "group": team_to_group[t],
            "elo": round(elo[slug(t)], 1),                 # blended prior (used by model)
            "elo_eloratings": round(elo_eloratings[t], 1),
            "elo_market": round(market_elo[t], 1) if t in market_elo else "",
            "market_prob": round(implied[t], 4) if t in implied else "",
        })
    teams = pd.DataFrame(team_rows)

    # groups.csv (long form)
    grp_rows = [{"group": g, "team": t, "pos": i + 1}
                for g, ts in groups.items() for i, t in enumerate(ts)]
    groups_df = pd.DataFrame(grp_rows)

    # elo.csv (finalists: blended prior + eloratings + market + home-grown)
    elo_df = pd.DataFrame([
        {"team": t, "slug": slug(t),
         "elo_blended": round(elo[slug(t)], 1),
         "elo_eloratings": round(elo_eloratings[t], 1),
         "elo_market_implied": round(market_elo[t], 1) if t in market_elo else "",
         "market_prob": round(implied[t], 4) if t in implied else "",
         "elo_raw_computed": round(raw_elo.get(slug(t), float("nan")), 1)}
        for t in CANONICAL_TEAMS
    ]).sort_values("elo_blended", ascending=False).reset_index(drop=True)

    # market_outright.csv
    market_out = pd.DataFrame([
        {"team": t, "american_odds": MARKET_ODDS_AMERICAN[t],
         "implied_prob": round(implied[t], 4),
         "elo_market_implied": round(market_elo[t], 1)}
        for t in MARKET_ODDS_AMERICAN
    ]).sort_values("implied_prob", ascending=False).reset_index(drop=True)

    # market_title_odds.csv
    market = pd.DataFrame(
        [{"team": k, "opta_title_prob": v} for k, v in OPTA_TITLE_PROB.items()])

    # write everything
    teams.to_csv(DATA_PROCESSED / "teams.csv", index=False)
    groups_df.to_csv(DATA_PROCESSED / "groups.csv", index=False)
    group_matches.to_csv(DATA_PROCESSED / "schedule_groups.csv", index=False)
    (DATA_PROCESSED / "bracket.json").write_text(json.dumps(bracket, indent=2))
    results.to_csv(DATA_PROCESSED / "results.csv", index=False)
    elo_df.to_csv(DATA_PROCESSED / "elo.csv", index=False)
    players.to_csv(DATA_PROCESSED / "players.csv", index=False)
    market.to_csv(DATA_PROCESSED / "market_title_odds.csv", index=False)
    market_out.to_csv(DATA_PROCESSED / "market_outright.csv", index=False)
    market_advance.to_csv(DATA_PROCESSED / "market_advance.csv", index=False)
    market_gb.to_csv(DATA_PROCESSED / "market_golden_boot.csv", index=False)

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "reference_date": REFERENCE_DATE,
        "sources": {
            "hicruben_world-cup-2026-prediction-model": git_meta(HICRUBEN),
            "0xNadr_wc2026": git_meta(NADR),
            "opta_title_prob": {
                "url": "https://theanalyst.com/articles/who-will-win-2026-fifa-world-cup-predictions-opta-supercomputer",
                "note": "Pre-tournament 10k-sim title probabilities, top teams + hosts.",
            },
            "eloratings_net": {
                "url": "https://www.international-football.net/elo-ratings-table?day=30&month=05&year=2026",
                "as_of": "2026-05-30",
                "file": "data/raw/eloratings_2026-05-30.md",
                "note": "World Football Elo for all 48 finalists (strength prior).",
            },
            "market_outright_odds": {
                "url": "https://www.si.com/betting/every-teams-championship-group-odds-for-the-2026-world-cup-spain-and-france-top-odds-list-01kt4yygesqb",
                "as_of": "2026-06",
                "file": "data/raw/market_outright_2026-06.md",
                "note": "Outright-winner odds (FanDuel via SI) for the 33 informative teams; blended into the prior (Opta-style) to correct Elo's lag on brand teams (Germany/France/England/Brazil). The 15 floored (+250000) minnows are dropped.",
            },
            "market_advance_odds": {
                "url": "https://www.foxsports.com/stories/soccer/2026-world-cup-odds-teams-favored-advance-knockout-stage",
                "as_of": "2026-06-04",
                "file": "data/raw/market_advance_2026-06.md",
                "note": "To-advance-to-R32 odds (DraftKings via FOX) for all 48 teams; de-vigged to sum to 32. The key weak-team strength signal (calibrate_team_strengths target).",
            },
            "market_golden_boot_odds": {
                "url": "https://www.rotowire.com/soccer/article/2026-world-cup-golden-boot-odds-full-player-list-mbappe-kane-haaland-108917",
                "as_of": "2026-06-01",
                "file": "data/raw/market_golden_boot_2026-06.md",
                "note": "Golden Boot odds (DraftKings via RotoWire) for 142 players; de-vigged to sum 1; blended onto players.csv as market_p_gb (top-scorer calibration target).",
            },
            "official_bracket": {
                "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage",
                "note": "Authoritative R32-Final bracket; the bundled schedule.json had scrambled knockout slots, corrected here.",
            },
        },
        "outputs": {
            "teams.csv": len(teams), "groups.csv": len(groups_df),
            "schedule_groups.csv": len(group_matches),
            "bracket.json": len(bracket), "results.csv": len(results),
            "elo.csv": len(elo_df), "players.csv": len(players),
            "market_title_odds.csv": len(market),
            "market_advance.csv": len(market_advance),
            "market_golden_boot.csv": len(market_gb),
        },
    }
    (DATA_PROCESSED / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # console summary
    print("Stage 1 complete. Processed files written to", DATA_PROCESSED)
    print(f"  teams.csv            {len(teams):>5} rows")
    print(f"  groups.csv           {len(groups_df):>5} rows (12 groups x 4)")
    print(f"  schedule_groups.csv  {len(group_matches):>5} group matches")
    print(f"  bracket.json         {len(bracket):>5} knockout matches")
    print(f"  results.csv          {len(results):>5} historical internationals")
    print(f"  elo.csv              {len(elo_df):>5} teams rated")
    print(f"  players.csv          {len(players):>5} candidate scorers")
    print(f"  market_title_odds    {len(market):>5} anchor probabilities")
    print(f"  market_advance.csv   {len(market_advance):>5} teams (to-R32 odds)")
    print(f"  market_golden_boot   {len(market_gb):>5} players (GB odds)")
    print("\nMarket P(advance) - lowest 6 (the weak-team signal):")
    for _, r in market_advance.tail(6).iterrows():
        print(f"  {r['team']:<16} {r['p_advance']:.0%}")
    nmatch = (players["market_p_gb"] > 0).sum()
    print(f"\nGolden Boot: {nmatch}/{len(players)} candidate scorers matched to market board.")
    print("\nTop-10 finalists by Elo:")
    top = teams.sort_values("elo", ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"  {r['team']:<16} {r['elo']:>7.1f}  (tier {r['tier']}, group {r['group']})")


if __name__ == "__main__":
    main()
