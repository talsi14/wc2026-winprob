"""Stage 1 - snapshot the live tournament state from the ESPN keyless feed.

Builds ``data/live/state_<TS>.json`` capturing everything that has already
happened (so the conditioned simulator can fix it and sample only the
remainder), and reconciles each entry's *locked* points against the site.

state_<TS>.json schema (all team / player names canonical):
  timestamp, collected_at
  group_stage_complete : bool
  group_scores         : { "<match_no>": [home_goals, away_goals] }   # played group fixtures, schedule orientation
  standings            : { "A": [ {team,rank,played,points,gf,ga,gd,advanced} x4 ], ... }
  official_order       : { "A": [team1,team2,team3,team4], ... }       # only when group complete
  advanced_thirds_groups : [grp, ...]                                  # the (<=8) groups whose 3rd advanced
  ko_results           : [ {home,away,home_goals,away_goals,winner,shootout} ]
  player_goals         : { "<canonical scorer>": goals }               # candidates only, open-play+penalty, no own/shootout
  all_scorers          : [ {scorer, team, goals} ]                     # every scorer (Golden-Boot board), sorted desc
  team_played          : { team: {gf,ga,games} }                       # from completed matches
  n_live               : int                                           # matches currently in progress
  live_team_played     : { team: {gf,ga,games} }                       # completed + in-progress (widgets only)
  live_scorers         : [ {scorer, team, goals} ]                     # completed + in-progress (widgets only)

Usage:  python3 scripts/collect_live.py [--ts 2026-06-20T1200]
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet import espn
from wc2026_bet.config import DATA_LIVE, DATA_PROCESSED
from wc2026_bet.data_io import load_dataset
from wc2026_bet.live import known_team_stats
from wc2026_bet.scoring import Entry, score_entry


def _norm(s: str) -> str:
    d = unicodedata.normalize("NFKD", (s or "").lower())
    d = "".join(c for c in d if not unicodedata.combining(c))
    return "".join(c for c in d if c.isalnum())


def _candidate_lookup() -> dict[str, str]:
    """accent-normalized scorer name -> canonical, over candidates + extras."""
    out = {}
    for f in (DATA_PROCESSED / "players.csv", DATA_LIVE / "extra_players.csv"):
        if f.exists():
            for nm in pd.read_csv(f)["scorer"]:
                out[_norm(nm)] = nm
    return out


def _is_played(fx: dict) -> bool:
    return bool(fx.get("completed")) or fx.get("state") == "post"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M"),
                    help="timestamp label for this snapshot")
    args = ap.parse_args()
    ts = args.ts

    ds = load_dataset()

    print("Fetching fixtures ...")
    fixtures = espn.fetch_fixtures()
    print(f"  {len(fixtures)} fixtures in window")
    print("Fetching standings ...")
    standings = espn.fetch_standings(ds.groups)

    # ---- map group fixtures to schedule match numbers (unordered pair) ----- #
    sched = ds.group_matches
    pair_to_match = {}
    for r in sched.itertuples():
        pair_to_match[frozenset((r.home, r.away))] = (r.match, r.home, r.away)

    group_scores: dict[str, list[int]] = {}
    ko_results: list[dict] = []
    team_played: dict[str, dict] = {}
    cand_lookup = _candidate_lookup()
    player_goals: dict[str, int] = {}
    # full tournament scorer board (every scorer, not just pick candidates):
    #   key -> {"scorer": display name, "team": canonical team, "goals": n}
    all_scorers: dict[str, dict] = {}

    # LIVE tallies = completed matches PLUS goals already scored in *ongoing*
    # matches. These feed only the three display widgets (top scoring/conceding
    # team, top scorer) via the slim 5-min refresh; the simulator still conditions
    # exclusively on the completed-only fields below, so partial scores never leak
    # into the win-probability model.
    live_team_played: dict[str, dict] = {}
    live_all_scorers: dict[str, dict] = {}
    live_teams: set[str] = set()                    # teams in a match ongoing right now
    n_live = 0

    def bump_played(team, gf, ga):
        d = team_played.setdefault(team, {"gf": 0, "ga": 0, "games": 0})
        d["gf"] += gf; d["ga"] += ga; d["games"] += 1

    def bump_live(team, gf, ga):
        d = live_team_played.setdefault(team, {"gf": 0, "ga": 0, "games": 0})
        d["gf"] += gf; d["ga"] += ga; d["games"] += 1

    played_group, played_ko = 0, 0
    for fx in fixtures:
        if fx["home"] is None or fx["away"] is None:
            continue
        if fx["home_score"] is None or fx["away_score"] is None:
            continue
        played = _is_played(fx)
        live = fx.get("state") == "in"
        if not (played or live):
            continue
        hg, ag = fx["home_score"], fx["away_score"]
        key = frozenset((fx["home"], fx["away"]))
        # team-id -> canonical team for this fixture (to attribute each scorer)
        id2team = {str(fx.get("home_id")): fx["home"], str(fx.get("away_id")): fx["away"]}
        # goal scorers (works for in-progress matches too)
        try:
            scorers = espn.fetch_goal_scorers(fx["espn_id"])
        except RuntimeError:
            scorers = []

        # --- live board (includes this match whether ongoing or finished) ---
        bump_live(fx["home"], hg, ag)
        bump_live(fx["away"], ag, hg)
        for s in scorers:
            disp = cand_lookup.get(_norm(s["scorer"])) or s["scorer"]
            team = id2team.get(str(s.get("team_id"))) or ""
            lr = live_all_scorers.setdefault(disp, {"scorer": disp, "team": team, "goals": 0})
            lr["goals"] += 1
            if not lr["team"] and team:
                lr["team"] = team
        if live and not played:
            n_live += 1
            live_teams.update((fx["home"], fx["away"]))
            continue                                  # ongoing -> no completed-only updates

        # --- completed-only fields (condition the simulator) ---
        bump_played(fx["home"], hg, ag)
        bump_played(fx["away"], ag, hg)
        for s in scorers:
            canon = cand_lookup.get(_norm(s["scorer"]))
            if canon:
                player_goals[canon] = player_goals.get(canon, 0) + 1
            # full board: prefer the canonical (Hebrew-mappable) name when known
            disp = canon or s["scorer"]
            team = id2team.get(str(s.get("team_id"))) or ""
            row = all_scorers.setdefault(disp, {"scorer": disp, "team": team, "goals": 0})
            row["goals"] += 1
            if not row["team"] and team:
                row["team"] = team

        if key in pair_to_match:
            mno, shome, saway = pair_to_match[key]
            # re-orient to schedule home/away
            if fx["home"] == shome:
                group_scores[str(mno)] = [hg, ag]
            else:
                group_scores[str(mno)] = [ag, hg]
            played_group += 1
        else:
            winner = fx["home"] if hg > ag else (fx["away"] if ag > hg else None)
            ko_results.append({
                "home": fx["home"], "away": fx["away"],
                "home_goals": hg, "away_goals": ag,
                "winner": winner, "shootout": hg == ag,
            })
            played_ko += 1

    group_stage_complete = played_group >= len(sched)

    official_order, advanced_thirds_groups = {}, []
    if group_stage_complete:
        for g, rows in standings.items():
            ordered = sorted(rows, key=lambda r: r["rank"] or 99)
            official_order[g] = [r["team"] for r in ordered]
            for r in ordered:
                if r["rank"] == 3 and r["advanced"]:
                    advanced_thirds_groups.append(g)

    state = {
        "timestamp": ts,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "group_stage_complete": group_stage_complete,
        "n_group_played": played_group,
        "n_ko_played": played_ko,
        "group_scores": group_scores,
        "standings": standings,
        "official_order": official_order,
        "advanced_thirds_groups": advanced_thirds_groups,
        "ko_results": ko_results,
        "player_goals": player_goals,
        "all_scorers": sorted(all_scorers.values(),
                              key=lambda r: (-r["goals"], r["scorer"])),
        "team_played": team_played,
        # live widget tallies (completed + in-progress) for the slim refresh
        "n_live": n_live,
        "live_team_played": live_team_played,
        "live_teams": sorted(live_teams),           # teams currently playing (for the red dot)
        "live_scorers": sorted(live_all_scorers.values(),
                               key=lambda r: (-r["goals"], r["scorer"])),
    }

    out = DATA_LIVE / f"state_{ts}.json"
    out.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    # stable pointer to the newest snapshot
    (DATA_LIVE / "state_latest.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"\nWrote {out}")
    print(f"  group fixtures played: {played_group}/{len(sched)}  "
          f"knockout played: {played_ko}  group_stage_complete={group_stage_complete}")
    if player_goals:
        top = sorted(player_goals.items(), key=lambda kv: -kv[1])[:8]
        print("  candidate goals so far:", ", ".join(f"{n}={g}" for n, g in top))

    reconcile(ds, state)


# --------------------------------------------------------------------------- #
# Reconciliation: recompute locked points from known results, diff vs the site
# --------------------------------------------------------------------------- #
def reconcile(ds, state) -> None:
    entries = pd.read_csv(DATA_LIVE / "pool_entries_2026.csv")
    site_path = DATA_LIVE / "entry_points_site.csv"
    if not site_path.exists():
        return
    site = pd.read_csv(site_path).set_index("name")
    team_tier = {r.team: r.tier for r in ds.teams.itertuples()}
    stats = known_team_stats(ds, state)
    gf = {t: state["team_played"].get(t, {}).get("gf", 0) for t in ds.team_list}
    ga = {t: state["team_played"].get(t, {}).get("ga", 0) for t in ds.team_list}
    pg = state["player_goals"]

    # Guard against a stale reference snapshot: entry_points_site.csv is only
    # refreshed by ingest_pool_entries_2026.py (--entries / Supabase). If it is
    # all-zero while real results have already been played, the diff below is
    # meaningless - flag the staleness instead of crying "mismatch" 53 times.
    site_total = float(site["total"].fillna(0).abs().sum()) if "total" in site else 0.0
    matches_played = int(state.get("n_group_played", 0)) + int(state.get("n_ko_played", 0))
    site_when = str(site["updated_at"].iloc[0]) if "updated_at" in site and len(site) else "?"
    if site_total == 0.0 and matches_played > 0:
        print(f"  reconciliation: SKIPPED - site snapshot is stale/all-zero "
              f"(updated_at={site_when}) but {matches_played} matches are already "
              "played. Re-pull with --entries to refresh entry_points_site.csv.")
        return

    mism = 0
    for r in entries.itertuples():
        e = Entry(r.tierA, r.tierB, r.tierC, r.tierD, r.scoring, r.conceding, r.top_scorer)
        bd = score_entry(e, stats, gf, ga, pg, golden_boot="", team_tier=team_tier)
        ours = round(bd["total"], 1)
        theirs = float(site.loc[r.name, "total"]) if r.name in site.index else None
        if theirs is not None and abs(ours - theirs) > 1e-6:
            mism += 1
            if mism <= 8:
                print(f"  RECON mismatch: {r.name!r} ours={ours} site={theirs}")
    if mism == 0:
        print("  reconciliation: all entries match the site's locked points.")
    else:
        print(f"  reconciliation: {mism} entries differ from the site "
              "(expected if the site's bonus timing differs mid-stage).")


if __name__ == "__main__":
    main()
