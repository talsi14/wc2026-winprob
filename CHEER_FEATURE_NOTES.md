# "את מי לעודד?" (Who to root for?) — feature handoff notes

Status: **built locally, validated, NOT pushed.** Resume from here.

## Goal
A tab that tells each participant which outcome of each upcoming game helps them.
For every upcoming game (home win / draw / away win), show each entry under the
outcome(s) that improve their **expected prize money**, with the signed ₪ change.

## Locked design decisions
- **Metric:** rank buckets by Δ expected prize. Baseline = the entry's *current
  unconditional* expected prize. So `Δ_outcome = E[prize | outcome] − E[prize]`.
  The three Δs are probability-weighted to ≈0 (always at least one helpful and one
  harmful outcome — they can NEVER all be negative/positive).
- **Default view:** each entry appears once, in its **argmax-Δ** outcome, with that
  (positive) ₪ delta.
- **Focus view:** when the user filters to specific entries, those entries appear in
  **all three** columns, each with its signed Δ.
- **Neutral strip:** per game, entries with `max|Δ| < threshold` (currently **₪1**,
  `CHEER_NEUTRAL_ILS`) go into a collapsible "לא מהותי" strip instead of a column.
- **Two independent filters:** `P(top-3) > 0` and `P(finish last) > 0` (sim-derived).
  These are a practical proxy for "mathematically still alive"; in group stage
  everyone is alive (both = 53/53), narrows as the tournament advances.
- **Today / Tomorrow toggle:** payload carries BOTH days; toggle switches client-side
  (no re-fetch). Default = today if it has unplayed games, else tomorrow; empty side
  disabled. Times shown in **Israel time** (Asia/Jerusalem).
- **Per-game marginal Δ** (holds only that one game fixed, integrates over everything
  else, incl. the other same-day games and the rest of the tournament). NOT joint
  combinations. Re-conditions automatically as games finish (finished games drop off,
  remaining games recomputed given the real result).

## Heuristic (the cheap, exact one)
ONE simulation, then **bucket the existing per-sim `winnings` matrix by each tracked
game's realized outcome** → `E[prize | outcome]` for every game × outcome at once.
Same cost as one normal run. Exact MC conditional expectation in the limit.
Caveat: low-probability buckets (e.g. a heavy favorite's "draw") are noisy at 50k —
**bump `--sims` (~200k) on match-days**.

## Files changed
### `wc2026_bet/src/wc2026_bet/simulate.py`
- `run(self, n_sims, known=None, track_matches: set[int]|None=None)`.
- In the group loop, for `mno in track_matches`, record per-sim outcome
  `0=home win, 1=draw, 2=away win` into `game_outcomes[mno]` (np.int8 [S]).
- Returns `game_outcomes` in the result dict. (See "Knockout support" below — KO
  matches are also tracked now, recording the winner index + participants.)

### `wc2026_bet/scripts/run_live_update.py`
- Constants: `IL_TZ = ZoneInfo("Asia/Jerusalem")`, `CHEER_NEUTRAL_ILS = 1.0`.
- `select_cheer_games(ds, played)` → `(days, track)`:
  - Fetches ESPN fixtures for `today-1 .. tomorrow+1` (4-day window; canonical team
    names match the dataset). Degrades gracefully (returns `[], set()`) if unreachable.
  - Maps fixtures→internal group match numbers by `(home, away)` (and reversed).
    Skips played (`group_scores`) and already-completed (ESPN `post`/completed) games.
  - Buckets unplayed games into `today` / `tomorrow` by Israel-local kickoff date.
  - `days = [{key, date, games:[{mno, home, away, ko:"HH:MM", _sort}]}]` (sorted by kickoff).
- `build_cheer(days, track, O, M, names)`:
  - `winnings = prize_vector(N)[ranks-1]` (`ranks` is `[S,N]` from `rank_and_metrics`).
  - `base = winnings.mean(0)`. For each tracked game, `cond[k] = winnings[outcome==k].mean(0)`,
    `delta[k] = round(cond[k]-base, 1)`. Attaches outcome probs `g["p"]=[p0,p1,p2]`.
  - Returns `{neutral_threshold, days, deltas:{name:{mno:[d0,d1,d2]}}}`.
- In `main()`: compute `cheer_days, cheer_track` before the sim; pass
  `track_matches=cheer_track` to `Simulator.run`; `cheer = build_cheer(...)`.
- Added `"P_top3"` per entry (= P_top2 + P_third). Added `"cheer": cheer` to payload.
- Added `prize_vector` to the config import.

### `wc2026_bet/scripts/build_friends_report.py`
- `_TEAM_ISO` (canonical team → ISO2), `_FLAG_OVERRIDE` (England/Scotland), `_flag(team)`
  → emoji flag. (The old mockup `_cheer_games`/`_CHEER_FALLBACK` were REMOVED.)
- `cheer_html(data)` is now **data-driven**: reads `data["cheer"]`, enriches each game
  with Hebrew names (`_team_he_map`) + flags, builds `pmap` from entries' `P_top3`/`P_last`,
  and embeds everything as JSON in `<script id="rfData" type="application/json">`.
  The static HTML only has the filters + `<div id="rfGames">` (chips rendered by JS).
- `CHEER_JS` is now a **renderer** reading `#rfData`: day toggle, default vs focus mode,
  neutral strip, `rfTop3`/`rfLast` filters, searchable multi-select participant filter,
  multi-highlight. (Old `rfMoney` toggle removed.)
- `CHEER_CSS`: added `.rfdaytoggle/.rfday`, `.rfprob`, `.rfdelta.pos/.neg`, `.rfneutral`.

## Payload schema (live_latest.json["cheer"])
```
{
  "neutral_threshold": 1.0,
  "days": [
    {"key":"today","date":"2026-06-14","games":[
       {"mno":6,"home":"Brazil","away":"Morocco","ko":"01:00","p":[0.45,0.28,0.27]}, ...]},
    {"key":"tomorrow","date":"2026-06-15","games":[...]}
  ],
  "deltas": { "<entry name>": { "<mno>": [d_homewin, d_draw, d_awaywin], ... }, ... }
}
```
Outcome index everywhere: **0 = home win, 1 = draw, 2 = away win.**
Column mapping in UI: win1 = home (t1), draw, win2 = away (t2). RTL → home is rightmost.

## Validation done
- Δs are probability-weighted to ≈0 per game (e.g. Mister London, Brazil×Morocco:
  `[-1.7, +4.4, -1.7]`, p·Δ ≈ 0). Confirmed correct rendering (name↔value stay paired).
- Build no longer needs network (data comes from payload).
- `node --check` on the inline JS bundle passes; mock-DOM render produces chips, deltas,
  neutral strips, prob labels, day toggle.
- Ran `scripts/run_live_update.py --sims 30000` once to populate the real payload.

## Knockout support (DONE — 2026-06-14)
KO games now work alongside group games. They have **2 outcomes** (home wins /
away wins; the sim resolves ET+penalties to a winner — no draw).
- `simulate.py`: in the KO loop, for `mno in track_matches`, record
  `game_outcomes[mno] = winner` (team index per sim, int16) and
  `ko_participants[mno] = (hi, ai)`. Returned in the result dict.
- `select_cheer_games`: now iterates ESPN fixtures directly. A fixture is a
  *group* game if its (home,away) is one of the 72 group pairs; otherwise, if both
  teams are real (a decided KO matchup), it's a *knockout* game. When any KO game is
  on the board it adds **all 32 bracket slots** to `track` so build_cheer can map.
  Undecided KO fixtures (ESPN placeholders) are skipped (teams not canonical).
- `build_cheer(ds, …)`: `find_ko_mno(t1,t2)` picks the bracket slot whose simulated
  participants are that pair (deterministic once feeders are decided; needs frac≥0.5,
  else the game is marked `pending` → UI placeholder). KO deltas are length-2,
  prob-weighted to ~0. Validated with a real conditioned sim (groups complete):
  slot mapped at frac=1.000, deltas ~₪40–60 (KO matters far more than a group game).
- Renderer: KO games draw **two columns + a big centred ✕** (`.rfbuckets.ko`,
  `.rfvs`), a "נוקאאוט" badge, and a pending placeholder. The `render()` loop is now
  outcome-count-agnostic (`nOut = isKo?2:3`).
- Payload note: a game now carries `"type": "group"|"ko"` and (for KO) `"pending"`;
  its delta vector length (2 or 3) matches the type. Outcome index for KO:
  **0 = home/team1 wins, 1 = away/team2 wins.**

## Relative emphasis (DONE)
Within each game, a thin **heat bar** under each chip has width = `|Δ| / max|Δ| in
that game` (`.rfbar`, green/red by sign). Shows who the game matters *most* to even
when absolute ₪ is small. Default mode → bars are positive (best-outcome placement);
focus mode → signed. Pure client-side; no payload change.

## sims default raised to 200k (DONE)
`run_live_pipeline.py --sims` default 50k → **200k**. Timed: sim+score 50k≈1.7s,
200k≈7.3s — a few seconds, and the heavy pipeline only runs on a new result. This
stabilises low-probability buckets (a heavy favourite's loss/draw).

## Open / next items
- Δ expected-rank idea **dropped**: it's just as flat as ₪ in the group stage (the
  smallness is real, not a display artefact). Direction + relative-emphasis is the
  answer; magnitudes grow naturally in the knockouts.
- Optional **"as of <timestamp>"** stamp on the tab (makes a stale browser cache
  obvious; a stale frame caused a false "−1.7 in all three outcomes" report).
- **"In money" definition**: currently `P>0` from a finite sim (can miss razor-thin
  paths); a sound ceiling/floor mathematical-elimination test was discussed but deferred.
- Not pushed yet — local inspection first (standing instruction).
