"""Stage 0 - ingest the live 2026 friend-pool from the lovable.app site.

The site (https://friends-bet.lovable.app/) is a thin front-end over a public
Supabase table. We read every entry straight from the REST endpoint (the anon
read key is shipped in the site's JS bundle), translate the Hebrew pick tokens
to our canonical team / player names, and write two files:

  * data/live/pool_entries_2026.csv  - one row per entry, canonical picks
        (name, tierA, tierB, tierC, tierD, scoring, conceding, top_scorer)
  * data/live/entry_points_site.csv  - the site's per-slot points + total +
        updated_at, kept verbatim for the Stage-1 reconciliation check.

Any top-scorer pick that is *not* one of our simulated Golden-Boot candidates
(players.csv) is written to data/live/extra_players.csv with a goal-share
derived from the market Golden-Boot board, so the conditioned simulator can
still model that entry's top-scorer slot.

Asserts the roster size (== EXPECTED_POOL_SIZE) and that every pick token maps,
so the run fails loudly if the site roster or a spelling changes.

Network only touches Supabase; no API key signup required.
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import (DATA_LIVE, DATA_PROCESSED, EXPECTED_POOL_SIZE,
                               POOL_LEADERBOARD_TABLE, POOL_SUPABASE_ANON_KEY,
                               POOL_SUPABASE_URL)
from wc2026_bet.names import resolve_he_player, resolve_he_team

TEAM_SLOTS = ["tier_a", "tier_b", "tier_c", "tier_d", "scorer", "conceder"]
PTS_COLS = ["tier_a_pts", "tier_b_pts", "tier_c_pts", "tier_d_pts",
            "scorer_pts", "conceder_pts", "topscorer_pts", "total"]


def fetch_leaderboard() -> list[dict]:
    if not POOL_SUPABASE_ANON_KEY:
        raise SystemExit(
            "POOL_SUPABASE_ANON_KEY is not set. The roster pull (--entries) needs "
            "the public Supabase anon key. Set it in your environment, e.g.\n"
            "  export POOL_SUPABASE_ANON_KEY='eyJ...'\n"
            "(The scheduled win-probability job does not need this.)")
    url = (f"{POOL_SUPABASE_URL}/rest/v1/{POOL_LEADERBOARD_TABLE}"
           "?select=*&order=rank.asc")
    req = urllib.request.Request(url, headers={
        "apikey": POOL_SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {POOL_SUPABASE_ANON_KEY}",
        "Accept": "application/json",
        "Prefer": "count=exact",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
        content_range = resp.headers.get("content-range", "")
    print(f"Supabase returned {len(rows)} rows (content-range: {content_range})")
    return rows


def _accent_norm(s: str) -> str:
    """Lowercase, drop diacritics, keep alphanumerics (so 'Sané' == 'Sane')."""
    import unicodedata
    d = unicodedata.normalize("NFKD", s.lower())
    d = "".join(c for c in d if not unicodedata.combining(c))
    return "".join(c for c in d if c.isalnum())


def derive_extra_players(missing: dict[str, str]) -> pd.DataFrame:
    """Build players.csv-shaped rows for picked scorers outside our candidate
    set, sourcing expected goals from the market Golden-Boot board.

    ``missing`` maps canonical player name -> team. We fit a single
    expected-goals-per-GB-probability slope ``k`` through the origin on the 30
    existing candidates (which carry both expected_player_goals and a market GB
    prob), then set the new player's expected goals = k * market_p_gb. Share =
    expected_goals / team_goals, clipped to a plausible [0.06, 0.45] band. This
    keeps a co-striker proportional to how the market actually rates him,
    instead of rescaling an unrelated teammate.
    """
    players = pd.read_csv(DATA_PROCESSED / "players.csv")
    mkt = pd.read_csv(DATA_PROCESSED / "market_golden_boot.csv")
    mkt_by_norm = {_accent_norm(r.player): r for r in mkt.itertuples()}

    # least-squares slope through origin: eg ~= k * p_gb (existing candidates).
    cand = players[players["market_p_gb"] > 0]
    p = cand["market_p_gb"].to_numpy(float)
    eg = cand["expected_player_goals"].to_numpy(float)
    k = float((eg * p).sum() / (p * p).sum())

    team_goals_by_team = dict(zip(players["team"], players["expected_team_goals"]))
    default_goals = float(players["expected_team_goals"].median())

    rows = []
    for name, team in missing.items():
        g = mkt_by_norm.get(_accent_norm(name))
        p_gb = float(g.p_gb) if g is not None else 0.005
        team_goals = float(team_goals_by_team.get(team, default_goals))
        eg_new = k * p_gb
        share = float(min(0.45, max(0.06, eg_new / max(team_goals, 1e-6))))
        rows.append({
            "scorer": name, "team": team, "blended_share": share,
            "expected_team_goals": team_goals,
            "expected_player_goals": share * team_goals,
            "p_top_scorer": p_gb, "market_p_gb": p_gb,
        })
    return pd.DataFrame(rows)


def main() -> None:
    rows = fetch_leaderboard()
    assert len(rows) == EXPECTED_POOL_SIZE, (
        f"expected {EXPECTED_POOL_SIZE} entries, got {len(rows)} - roster changed?")

    candidates = set(pd.read_csv(DATA_PROCESSED / "players.csv")["scorer"])
    unmapped: list[str] = []
    entries: list[dict] = []
    points: list[dict] = []
    missing_players: dict[str, str] = {}

    for r in rows:
        name = (r.get("name") or "").strip()
        canon = {}
        for slot in TEAM_SLOTS:
            tok = (r.get(slot) or "").strip()
            c = resolve_he_team(tok)
            if c is None:
                unmapped.append(f"team[{slot}]={tok!r} (entry {name!r})")
            canon[slot] = c
        ptok = (r.get("topscorer") or "").strip()
        pcanon = resolve_he_player(ptok)
        if pcanon is None:
            unmapped.append(f"player={ptok!r} (entry {name!r})")
        entries.append({
            "name": name,
            "tierA": canon["tier_a"], "tierB": canon["tier_b"],
            "tierC": canon["tier_c"], "tierD": canon["tier_d"],
            "scoring": canon["scorer"], "conceding": canon["conceder"],
            "top_scorer": pcanon,
        })
        points.append({"name": name, "rank": r.get("rank"),
                       "movement": r.get("movement"),
                       **{c: r.get(c) for c in PTS_COLS},
                       "updated_at": r.get("updated_at")})
        if pcanon is not None and pcanon not in candidates:
            missing_players[pcanon] = _player_team(pcanon)

    if unmapped:
        raise SystemExit("Unmapped pick tokens (add to he_aliases.json):\n  "
                         + "\n  ".join(unmapped))

    DATA_LIVE.mkdir(parents=True, exist_ok=True)
    ent_df = pd.DataFrame(entries)
    ent_df.to_csv(DATA_LIVE / "pool_entries_2026.csv", index=False)
    pts_df = pd.DataFrame(points)
    pts_df.to_csv(DATA_LIVE / "entry_points_site.csv", index=False)

    extra_path = DATA_LIVE / "extra_players.csv"
    if missing_players:
        extra = derive_extra_players(missing_players)
        extra.to_csv(extra_path, index=False)
    elif extra_path.exists():
        extra_path.unlink()

    print(f"\nWrote {len(ent_df)} entries -> {DATA_LIVE / 'pool_entries_2026.csv'}")
    print(f"Wrote site points     -> {DATA_LIVE / 'entry_points_site.csv'}")
    if missing_players:
        print(f"Extra (non-candidate) top-scorer picks modeled via market GB:")
        for n, t in missing_players.items():
            print(f"   + {n} ({t})")

    # eyeball summary
    print("\n=== Parsed entries (canonical) ===")
    with pd.option_context("display.max_rows", None, "display.width", 200,
                           "display.max_colwidth", 22):
        print(ent_df.to_string(index=True))
    # token-usage sanity: distinct picks per slot
    print("\n=== distinct picks per slot ===")
    for col in ["tierA", "tierB", "tierC", "tierD", "scoring", "conceding", "top_scorer"]:
        vc = ent_df[col].value_counts()
        print(f"\n[{col}] {len(vc)} distinct, top:")
        print(vc.head(6).to_string())


# Minimal canonical team lookup for the 11 pool players (kept tiny + explicit;
# only used to attach a team to a picked scorer outside players.csv).
_PLAYER_TEAM = {
    "Erling Haaland": "Norway", "Harry Kane": "England",
    "Kylian Mbappé": "France", "Lionel Messi": "Argentina",
    "Cristiano Ronaldo": "Portugal", "Vinícius Júnior": "Brazil",
    "Lautaro Martínez": "Argentina", "Lamine Yamal": "Spain",
    "Ousmane Dembélé": "France", "Leroy Sané": "Germany",
    "Mikel Oyarzabal": "Spain",
}


def _player_team(name: str) -> str:
    return _PLAYER_TEAM.get(name, "Unknown")


if __name__ == "__main__":
    main()
