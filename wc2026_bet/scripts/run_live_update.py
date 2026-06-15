"""Stage 2-4 - the live win-probability engine (reads data/live + data/processed).

For a given timestamp it: refreshes / reuses the calibrated power ranking,
conditions the 50K-sim engine on the frozen tournament state, scores all 53
real entries per sim, ranks them against each other, applies the prize ladder
with the prize-splitting tiebreak, and writes per-entry probabilities + the
deltas vs the previous timestamp.

Outputs:
  data/live/win_probabilities_<TS>.json   (full, per-entry + champion matrix)
  results/live_latest.json                (stable pointer for the report/site)
  data/processed/calibration_<TS>.json     (the power-ranking snapshot used)

Usage:
  python3 scripts/run_live_update.py [--ts ...] [--state data/live/state_X.json]
                                     [--sims 50000] [--recalibrate]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.calibration import (apply_strength_offsets,
                                    calibrate_player_shares, calibrate_spread,
                                    calibrate_team_strengths,
                                    compute_golden_boot_scale,
                                    golden_boot_target)
from wc2026_bet.config import (DATA_LIVE, DATA_PROCESSED, N_SIMULATIONS,
                               RESULTS_DIR, prize_vector)
from wc2026_bet.contributions import build_contributions
from wc2026_bet.data_io import apply_share_factors, load_calibration
from wc2026_bet.live import (current_points_breakdown, load_entries,
                             load_live_dataset, rank_and_metrics, score_entries)
from wc2026_bet.model import fit_match_model
from wc2026_bet.simulate import KnownState, Simulator


def jdump(obj, path):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def build_calibration(ds, model0, ts: str, recalibrate: bool) -> dict:
    """Reuse the cached power ranking (fast) unless --recalibrate. Either way,
    snapshot it to calibration_<TS>.json so each run is reproducible."""
    cache = DATA_PROCESSED / "calibration.json"
    if cache.exists() and not recalibrate:
        cal = load_calibration()
        print(f"Power ranking: cached (spread={cal['strength_spread']:.3f}, "
              f"{len(cal.get('strength_offsets', {}))} offsets). "
              "Use --recalibrate to re-fit vs refreshed odds.")
    else:
        print("Recalibrating power ranking vs refreshed odds ...")
        cs = calibrate_spread(ds, model0, n_sims=20_000)
        spread = cs["best_spread"]
        model_s = replace(model0, spread=spread)
        cstr = calibrate_team_strengths(ds, model_s, ds.market_advance,
                                        n_sims=12_000, rounds=8)
        offsets = cstr["offsets"]
        model_so = apply_strength_offsets(model_s, offsets)
        Ocal = Simulator(ds, model_so, seed=99).run(20_000)
        factor = calibrate_player_shares(ds, Ocal, golden_boot_target(ds))
        share_factor = {n: float(f) for n, f in zip(ds.players["scorer"], factor)}
        cal = {"strength_spread": spread, "strength_offsets": offsets,
               "player_share_factor": share_factor,
               "advance_trace": cstr["trace"], "best_sse": cs["best_sse"]}
        jdump(cal, cache)
        print(f"  best spread={spread:.3f}; "
              f"advance max|err| -> {cstr['trace'][-1]['max_abs_advance_err']:.3f}")
    jdump(cal, DATA_PROCESSED / f"calibration_{ts}.json")
    return cal


def champion_matrix(ranks, O, ds, names, n_champ: int = 10) -> dict:
    """P(entry wins the pool | team X is champion) for the leading champions.
    ``names`` is the entry order matching the columns of ``ranks``; the matrix is
    keyed by entry name so the report can re-sort entries freely."""
    title = O["won_cup"].mean(0)
    champs = [ds.team_list[i] for i in np.argsort(-title)[:n_champ] if title[i] > 0]
    mat = {}
    for c in champs:
        ci = ds.team_index[c]
        mask = O["won_cup"][:, ci]
        if mask.sum() < 20:
            continue
        cond = (ranks[mask] == 1).mean(0)            # [N] P(entry first | champ c)
        mat[c] = {nm: round(float(cond[i]), 4) for i, nm in enumerate(names)}
    return {"champions": list(mat.keys()),
            "p_title": {c: round(float(title[ds.team_index[c]]), 4) for c in mat},
            "matrix": mat}


def previous_metrics(ts: str) -> dict | None:
    """Most recent win_probabilities_*.json strictly before this ts (by name)."""
    files = sorted(DATA_LIVE.glob("win_probabilities_*.json"))
    prev = [f for f in files if f.stem.replace("win_probabilities_", "") < ts]
    if not prev:
        return None
    data = json.loads(prev[-1].read_text())
    return {e["name"]: e for e in data["entries"]}


IL_TZ = ZoneInfo("Asia/Jerusalem")
CHEER_NEUTRAL_ILS = 1.0          # |Delta| below this -> "doesn't matter" for that game


def select_cheer_games(ds, played: set[int]) -> tuple[list[dict], set[int]]:
    """Pick today's & tomorrow's (Israel time) unplayed fixtures - group AND
    knockout - for the "who to root for" board.

    A fixture maps to a *group* match if its (home, away) pair is one of the 72
    group fixtures; otherwise, if both teams are real (i.e. a knockout matchup
    whose participants are already decided), it is a *knockout* game with two
    outcomes (no draw). Returns the per-day structure (without per-entry deltas
    yet) and the set of internal match numbers to condition the simulation on:
    the specific group matches, plus - when any KO game is on the board - every
    bracket slot, so build_cheer can map each real KO fixture to its slot via
    the simulated participants. Degrades to nothing if ESPN is unreachable."""
    today = datetime.now(IL_TZ).date()
    tomorrow = today + timedelta(days=1)
    try:
        from wc2026_bet.espn import fetch_fixtures
        fx = fetch_fixtures(start=today - timedelta(days=1),
                            end=tomorrow + timedelta(days=1))
    except Exception as exc:                       # network/parse: degrade gracefully
        print(f"cheer: fixture fetch failed ({exc}); skipping board")
        return [], set()

    gpair: dict[tuple[str, str], int] = {}         # group (home,away) -> match no
    for r in ds.group_matches.itertuples():
        gpair[(r.home, r.away)] = int(r.match)
        gpair[(r.away, r.home)] = int(r.match)
    teams = set(ds.team_index)
    bracket_mnos = {int(m["match"]) for m in ds.bracket}

    buckets = {"today": [], "tomorrow": []}
    track: set[int] = set()
    need_ko = False
    for f in fx:
        home, away = f.get("home"), f.get("away")
        if not home or not away or home not in teams or away not in teams:
            continue                                # placeholder/undecided -> skip
        if f.get("completed") or f.get("state") == "post" or not f.get("date"):
            continue                                # decided already -> nothing to root for
        try:
            ko = datetime.fromisoformat(f["date"].replace("Z", "+00:00")).astimezone(IL_TZ)
        except ValueError:
            continue
        key = "today" if ko.date() == today else "tomorrow" if ko.date() == tomorrow else None
        if key is None:
            continue
        mno = gpair.get((home, away))
        if mno is not None:                         # group fixture
            if mno in played:
                continue
            buckets[key].append({"mno": mno, "home": home, "away": away, "type": "group",
                                 "ko": ko.strftime("%H:%M"), "_sort": ko.isoformat()})
            track.add(mno)
        else:                                       # knockout fixture (teams decided)
            buckets[key].append({"mno": None, "home": home, "away": away, "type": "ko",
                                 "ko": ko.strftime("%H:%M"), "_sort": ko.isoformat()})
            need_ko = True
    if need_ko:
        track |= bracket_mnos                       # record every KO slot for mapping

    days = []
    for key, date in (("today", today), ("tomorrow", tomorrow)):
        games = sorted(buckets[key], key=lambda g: g.pop("_sort"))
        days.append({"key": key, "date": date.isoformat(), "games": games})
    return days, track


def build_cheer(ds, days: list[dict], track: set[int], O: dict, M: dict,
                names: list[str]) -> dict:
    """Conditional expected-prize deltas per entry per tracked game, by bucketing
    the existing simulation paths on each game's realized outcome. One sim, exact
    MC conditional expectations. Group matches have 3 outcomes (home/draw/away);
    knockout matches have 2 (home wins / away wins - the sim resolves ET/pens to a
    winner). Each game's delta vector is stored under str(mno); its length (2 or 3)
    matches the game 'type', so the renderer knows how many columns to draw."""
    ranks = M["ranks"]                              # [S,N]
    S, N = ranks.shape
    pv = np.asarray(prize_vector(N), dtype=np.float64)
    winnings = pv[ranks - 1]                         # [S,N] ILS per sim
    base = winnings.mean(0)                          # [N] unconditional E[prize]
    go = O.get("game_outcomes", {})
    kopart = O.get("ko_participants", {})

    deltas: dict[str, dict[str, list[float]]] = {nm: {} for nm in names}

    def buckets(masks: list[np.ndarray]) -> tuple[list[float], list]:
        p, cond = [], []
        for m in masks:
            cnt = int(m.sum())
            p.append(round(cnt / S, 4))
            cond.append(winnings[m].mean(0) if cnt else None)
        return p, cond

    def store(mno: int, p: list[float], cond: list) -> None:
        for e, nm in enumerate(names):
            deltas[nm][str(mno)] = [round(float(cond[k][e] - base[e]), 1)
                                    if cond[k] is not None else 0.0
                                    for k in range(len(cond))]

    def find_ko_mno(t1: int, t2: int) -> tuple[int | None, float]:
        """Bracket slot whose simulated participants are this {t1,t2} pair."""
        best, best_frac = None, 0.0
        for mno, (hi, ai) in kopart.items():
            cover = float((((hi == t1) & (ai == t2)) | ((hi == t2) & (ai == t1))).mean())
            if cover > best_frac:
                best, best_frac = mno, cover
        return (best, best_frac) if best_frac >= 0.5 else (None, best_frac)

    for day in days:
        for g in day["games"]:
            if g.get("type") == "ko":
                t1, t2 = ds.team_index.get(g["home"]), ds.team_index.get(g["away"])
                mno, frac = find_ko_mno(t1, t2) if (t1 is not None and t2 is not None) else (None, 0.0)
                if mno is None or mno not in go:     # feeders not settled yet
                    g["mno"], g["p"], g["pending"] = -1, [0.0, 0.0], True
                    continue
                winner = go[mno]
                p, cond = buckets([winner == t1, winner == t2])
                g["mno"], g["p"] = int(mno), p
                store(mno, p, cond)
            else:
                o = go.get(g["mno"])
                if o is None:
                    g["p"] = [0.0, 0.0, 0.0]
                    continue
                p, cond = buckets([o == 0, o == 1, o == 2])
                g["p"] = p
                store(g["mno"], p, cond)
    return {"neutral_threshold": CHEER_NEUTRAL_ILS, "days": days, "deltas": deltas}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M"))
    ap.add_argument("--state", default=str(DATA_LIVE / "state_latest.json"))
    ap.add_argument("--sims", type=int, default=N_SIMULATIONS)
    ap.add_argument("--recalibrate", action="store_true")
    args = ap.parse_args()
    ts = args.ts

    ds = load_live_dataset()
    entries = load_entries()
    elo = {r.team: r.elo for r in ds.teams.itertuples()}
    model0 = fit_match_model(ds.results, elo)

    cal = build_calibration(ds, model0, ts, args.recalibrate)
    apply_share_factors(ds, cal.get("player_share_factor", {}))
    model = apply_strength_offsets(
        replace(model0, spread=cal["strength_spread"]),
        cal.get("strength_offsets", {}))

    state = json.loads(Path(args.state).read_text())
    known = KnownState.from_state(ds, state)
    print(f"Conditioning on state {ts}: group {state.get('n_group_played',0)}/72 "
          f"played, KO {state.get('n_ko_played',0)}, "
          f"complete={state.get('group_stage_complete')}")

    cheer_days, cheer_track = select_cheer_games(ds, {int(k) for k in (state.get("group_scores") or {})})
    if cheer_track:
        print(f"cheer board: tracking {len(cheer_track)} upcoming game(s) "
              f"(today+tomorrow, Israel time)")

    print(f"Running {args.sims:,} conditioned simulations ...")
    O = Simulator(ds, model, seed=2026).run(args.sims, known=known,
                                            track_matches=cheer_track,
                                            track_opponents=True)
    gb_scale = compute_golden_boot_scale(ds, O)
    contrib = build_contributions(ds, O, golden_boot_scale=gb_scale)

    scores = score_entries(ds, contrib, O, entries)
    M = rank_and_metrics(scores)
    chmat = champion_matrix(M["ranks"], O, ds, list(entries["name"]))
    cheer = build_cheer(ds, cheer_days, cheer_track, O, M, list(entries["name"]))

    # real current (locked) points from the actual results so far, via the
    # canonical scoring engine (replaces the pool site's buggy/lagging totals).
    bd_map = current_points_breakdown(ds, state, entries)
    name_idx = {r.name: i for i, r in enumerate(entries.itertuples())}
    totals = {nm: round(float(bd_map[nm]["total"]), 1) for nm in name_idx}
    # rank by current points; ties broken by model P(1st) so the leader is the
    # strongest among equals (sequential 1..N for a clean leaderboard).
    cur_order = sorted(name_idx, key=lambda n: (-totals[n],
                                                -float(M["P_first"][name_idx[n]]), n))
    cur_rank = {n: i + 1 for i, n in enumerate(cur_order)}

    # per-group standings: played/points/GD computed directly from the RECORDED
    # results (group_scores) - the same facts that condition the simulation -
    # rather than ESPN's standings endpoint, which can lag several minutes behind
    # the final whistle and would otherwise show stale 0/0/0 rows (with an already
    # updated qualify%) in the minutes right after a game ends.
    adv = O["advanced"].mean(0)                       # [T] P(advance to R32)
    cur_stats: dict[str, dict] = {t: {"played": 0, "points": 0, "gd": 0}
                                  for gteams in ds.groups.values() for t in gteams}
    match_ha = {int(r.match): (r.home, r.away) for r in ds.group_matches.itertuples()}
    for mno_s, sc in (state.get("group_scores") or {}).items():
        try:
            mno = int(mno_s); hg, ag = int(sc[0]), int(sc[1])
        except (TypeError, ValueError, IndexError):
            continue
        if mno not in match_ha:
            continue
        home, away = match_ha[mno]
        for team, gf, ga in ((home, hg, ag), (away, ag, hg)):
            d = cur_stats.setdefault(team, {"played": 0, "points": 0, "gd": 0})
            d["played"] += 1
            d["gd"] += gf - ga
            d["points"] += 3 if gf > ga else (1 if gf == ga else 0)
    groups_payload: dict[str, list] = {}
    for g in sorted(ds.groups):
        lst = []
        for t in ds.groups[g]:
            c = cur_stats.get(t, {})
            lst.append({"team": t,
                        "played": int(c.get("played", 0)),
                        "points": int(c.get("points", 0)),
                        "gd": int(c.get("gd", 0)),
                        "p_advance": round(float(adv[ds.team_index[t]]), 4)})
        # current points/GD first; qualify% breaks ties (and orders pre-tournament)
        lst.sort(key=lambda x: (-x["points"], -x["gd"], -x["p_advance"]))
        groups_payload[g] = lst

    # per-team stage-reaching profile from the same simulation:
    #   exact[k] = P(deepest round == k) for k in 0..6  -> a true distribution (sums to 1)
    #             [group exit, R32, R16, QF, SF, final(runner-up), champion]
    #   reach[l] = P(round_reached >= l) for l in 1..6  -> cumulative "reach at least"
    #             [R32, R16, QF, SF, final, champion]
    rr = O["round_reached"]                           # [S, T] ints 0..6
    # knockout-opponent decomposition (who each team is likely to face per round,
    # and how often they beat them) -> explains the advance odds as a mixture of
    # opponents rather than a single average match.
    idx2team = {i: t for t, i in ds.team_index.items()}
    opp_meet, opp_beat = O.get("opp_meet") or {}, O.get("opp_beat") or {}
    KO_LABELS = [(1, "R32"), (2, "R16"), (3, "QF"), (4, "SF"), (6, "Final")]
    TOP_OPP = 5
    S_sims = rr.shape[0]

    def ko_breakdown(i: int) -> list:
        out = []
        for rc, label in KO_LABELS:
            M = opp_meet.get(rc)
            if M is None:
                continue
            row = M[i]
            total = int(row.sum())
            if total <= 0:
                continue
            beat_row = opp_beat[rc][i]
            order = sorted((j for j in range(len(row)) if row[j] > 0),
                           key=lambda j: -int(row[j]))[:TOP_OPP]
            opps = [{"t": idx2team[j],
                     "meet": round(int(row[j]) / total, 4),
                     "beat": round(int(beat_row[j]) / int(row[j]), 4)} for j in order]
            out.append({"r": label,
                        "p_play": round(total / S_sims, 4),
                        "pass": round(int(beat_row.sum()) / total, 4),
                        "opp": opps})
        return out

    stages_payload = []
    for t, i in ds.team_index.items():
        col = rr[:, i]
        exact = [round(float((col == k).mean()), 5) for k in range(7)]
        reach = [round(float((col >= lvl).mean()), 5) for lvl in range(1, 7)]
        stages_payload.append({"team": t, "exact": exact, "reach": reach,
                               "exp": round(float(col.mean()), 4),
                               "ko": ko_breakdown(i)})
    stages_payload.sort(key=lambda r: -r["exp"])     # strongest first (default order)

    prev = previous_metrics(ts)
    N = len(entries)
    out_entries = []
    for e, r in enumerate(entries.itertuples()):
        nm = r.name
        bd = bd_map[nm]
        rec = {
            "name": nm,
            "picks": {"tierA": r.tierA, "tierB": r.tierB, "tierC": r.tierC,
                      "tierD": r.tierD, "scoring": r.scoring,
                      "conceding": r.conceding, "top_scorer": r.top_scorer},
            "current_points": totals[nm],
            "current_rank": cur_rank[nm],
            "pts_breakdown": {
                "tierA": round(float(bd["tier_a"]), 1),
                "tierB": round(float(bd["tier_b"]), 1),
                "tierC": round(float(bd["tier_c"]), 1),
                "tierD": round(float(bd["tier_d"]), 1),
                "scoring": round(float(bd["scoring_team"]), 1),
                "conceding": round(float(bd["conceding_team"]), 1),
                "top_scorer": round(float(bd["top_scorer"]), 1),
            },
            "exp_winnings": round(float(M["exp_winnings"][e]), 1),
            "P_first": round(float(M["P_first"][e]), 4),
            "P_second": round(float(M["P_second"][e]), 4),
            "P_top2": round(float(M["P_top2"][e]), 4),
            "P_third": round(float(M["P_third"][e]), 4),
            "P_top3": round(float(M["P_top2"][e] + M["P_third"][e]), 4),
            "P_last": round(float(M["P_last"][e]), 4),
            "exp_points": round(float(M["exp_points"][e]), 2),
            "exp_rank": round(float(M["exp_rank"][e]), 2),
            "score_p10": round(float(M["score_p10"][e]), 1),
            "score_p50": round(float(M["score_p50"][e]), 1),
            "score_p90": round(float(M["score_p90"][e]), 1),
            "rank_hist": [int(x) for x in M["rank_hist"][e]],
        }
        if prev and nm in prev:
            p = prev[nm]
            rec["d_exp_winnings"] = round(rec["exp_winnings"] - p.get("exp_winnings", 0), 1)
            rec["d_P_top2"] = round(rec["P_top2"] - p.get("P_top2", 0), 4)
            rec["d_exp_rank"] = round(rec["exp_rank"] - p.get("exp_rank", 0), 2)
            if p.get("current_rank") is not None:
                rec["d_current_rank"] = rec["current_rank"] - p["current_rank"]
        out_entries.append(rec)

    # sort by expected winnings (headline), then P_top2
    out_entries.sort(key=lambda x: (-x["exp_winnings"], -x["P_top2"]))

    payload = {
        "timestamp": ts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_sims": args.sims,
        "n_entries": N,
        "prize_ladder": {"1st": 1800, "2nd": 750, "3rd": 50, "last": 50,
                         "tiebreak": "tied entries split the summed prize of the positions they occupy"},
        "state": {"group_played": state.get("n_group_played", 0),
                  "ko_played": state.get("n_ko_played", 0),
                  "group_stage_complete": state.get("group_stage_complete", False),
                  "player_goals": state.get("player_goals", {})},
        "calibration": {"strength_spread": cal["strength_spread"],
                        "golden_boot_scale": round(gb_scale, 3)},
        "champion_matrix": chmat,
        "groups": groups_payload,
        "stages": stages_payload,
        "scorers": state.get("all_scorers") or [],
        "team_played": state.get("team_played") or {},
        "cheer": cheer,
        "entries": out_entries,
    }
    jdump(payload, DATA_LIVE / f"win_probabilities_{ts}.json")
    jdump(payload, RESULTS_DIR / "live_latest.json")
    print(f"\nWrote win_probabilities_{ts}.json + results/live_latest.json")

    print("\n=== Top 8 by expected winnings (ILS) ===")
    print(f"{'entry':<24}{'EV ILS':>8}{'P(1st)':>8}{'P(top2)':>9}{'expRank':>9}")
    for rec in out_entries[:8]:
        print(f"{rec['name'][:23]:<24}{rec['exp_winnings']:>8.0f}"
              f"{rec['P_first']*100:>7.1f}%{rec['P_top2']*100:>8.1f}%"
              f"{rec['exp_rank']:>9.1f}")


if __name__ == "__main__":
    main()
