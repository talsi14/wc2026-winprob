"""Monte Carlo tournament engine - vectorized across all simulations.

One call simulates the whole 104-match tournament ``n_sims`` times and records,
per simulation and per team: matches won (regulation/ET vs penalty shootout),
group-stage draws, penalty-shootout losses, goals for/against, group finishing
position, whether it advanced to the R32, the deepest round it reached, and
whether it made/won the final. Plus per-player goals and the Golden Boot winner.

The whole group stage and each knockout round are processed as numpy array ops
over the simulation axis; only the (cheap) best-thirds slot lookup loops over
the <=495 distinct group-advancement combinations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .bracket import precompute_thirds_table, third_slots
from .config import (GROUPS, HOST_NATIONS, MAX_PLAYER_GOAL_SHARE,
                     MAX_PLAYER_GOALS, PEN_EDGE, ROUND_FINAL, ROUND_QF,
                     ROUND_R16, ROUND_R32, ROUND_SF, ROUND_WINNER)
from .data_io import Dataset
from .model import MatchModel

# bracket round_code -> "reached" level on our ROUND_* scale.
_REACH = {1: ROUND_R32, 2: ROUND_R16, 3: ROUND_QF, 4: ROUND_SF,
          5: ROUND_SF, 6: ROUND_FINAL}


@dataclass
class KnownState:
    """Already-decided tournament facts that the simulator fixes (conditions on)
    instead of sampling. All team references are 0..47 global indices and all
    arrays/dicts are pre-resolved against a Dataset by ``from_state``.

    Empty (the default) reproduces the unconditioned pre-tournament behaviour.
    """
    group_scores: dict[int, tuple[int, int]] = field(default_factory=dict)   # match_no -> (home_g, away_g), schedule orientation
    group_stage_complete: bool = False
    official_pos: dict[str, list[int]] = field(default_factory=dict)         # group -> [idx pos1..4]
    advanced_thirds_groups: list[str] = field(default_factory=list)          # groups whose 3rd advanced (<=8)
    ko_results: list[tuple] = field(default_factory=list)                    # (home_idx, away_idx, hg, ag, winner_idx|-1)
    player_known: np.ndarray | None = None                                   # [P] known goals per candidate (ds.players order)

    @classmethod
    def empty(cls) -> "KnownState":
        return cls()

    @classmethod
    def from_state(cls, ds: Dataset, state: dict) -> "KnownState":
        tidx = ds.team_index
        group_scores = {int(m): (int(v[0]), int(v[1]))
                        for m, v in state.get("group_scores", {}).items()}
        complete = bool(state.get("group_stage_complete"))
        official_pos: dict[str, list[int]] = {}
        if complete:
            for g, order in state.get("official_order", {}).items():
                official_pos[g] = [tidx[t] for t in order]
        adv_thirds = list(state.get("advanced_thirds_groups", []))
        ko = []
        for kr in state.get("ko_results", []):
            h, a = tidx.get(kr["home"]), tidx.get(kr["away"])
            if h is None or a is None:
                continue
            w = kr.get("winner")
            ko.append((h, a, int(kr["home_goals"]), int(kr["away_goals"]),
                       tidx.get(w, -1) if w else -1))
        P = len(ds.players)
        pk = np.zeros(P, dtype=np.int64)
        name_to_p = {n: i for i, n in enumerate(ds.players["scorer"])}
        for nm, g in state.get("player_goals", {}).items():
            if nm in name_to_p:
                pk[name_to_p[nm]] = int(g)
        return cls(group_scores=group_scores, group_stage_complete=complete,
                   official_pos=official_pos, advanced_thirds_groups=adv_thirds,
                   ko_results=ko, player_known=pk)


class Simulator:
    def __init__(self, ds: Dataset, model: MatchModel, seed: int = 26):
        self.ds = ds
        self.model = model
        self.rng = np.random.default_rng(seed)
        self.n_teams = len(ds.team_list)
        self.tidx = ds.team_index

        # Per-finalist strength arrays (spread already folded in).
        s = model.spread
        self.ATT = np.array([model.attack[model.index[t]] for t in ds.team_list]) * s
        self.DEF = np.array([model.defence[model.index[t]] for t in ds.team_list]) * s
        self.mu = model.intercept
        self.H = model.home_adv

        # Group fixtures: (home_idx, away_idx, home_adv_flag) + schedule match no.
        self.fixtures = []
        self.fixture_match = []
        for r in ds.group_matches.itertuples():
            hf = 1.0 if (r.home in HOST_NATIONS and r.venue_country == r.home) else 0.0
            self.fixtures.append((self.tidx[r.home], self.tidx[r.away], hf))
            self.fixture_match.append(int(r.match))

        # Group -> the 4 team indices.
        self.group_teams = {g: [self.tidx[t] for t in ds.groups[g]] for g in GROUPS}
        # Reverse maps for head-to-head tie-break bookkeeping: global team idx ->
        # its group letter and its position 0..3 within that group's 4x4 H2H table.
        self.team_group: dict[int, str] = {}
        self.team_locpos: dict[int, int] = {}
        for g in GROUPS:
            for p, ti in enumerate(self.group_teams[g]):
                self.team_group[ti] = g
                self.team_locpos[ti] = p

        # Bracket bookkeeping.
        self.thirds_table = precompute_thirds_table(ds.bracket)
        self.third_slot_defs = third_slots(ds.bracket)   # in match order
        # map (match, side) -> slot position 0..7
        self.slot_pos = {(s["match"], s["side"]): i
                         for i, s in enumerate(self.third_slot_defs)}

        # Players for golden-boot allocation.
        self.player_team_idx = np.array(
            [self.tidx[t] for t in ds.players["team"]])
        self.player_share = ds.players["blended_share"].to_numpy(float)
        self.player_names = list(ds.players["scorer"])

    # ---- low-level samplers ------------------------------------------------ #
    def _poisson_pair(self, hi, ai, hf):
        li = np.exp(self.mu + self.ATT[hi] - self.DEF[ai] + self.H * hf)
        lj = np.exp(self.mu + self.ATT[ai] - self.DEF[hi])
        return self.rng.poisson(li), self.rng.poisson(lj), li, lj

    def _play_knockout(self, hi, ai):
        """Vectorized knockout: 90' -> ET -> penalties. Returns (gh,ga,winner,pen)."""
        gh, ga, li, lj = self._poisson_pair(hi, ai, 0.0)
        tied = gh == ga
        if tied.any():
            et_h = self.rng.poisson(li * (30.0 / 90.0))
            et_a = self.rng.poisson(lj * (30.0 / 90.0))
            gh = gh + np.where(tied, et_h, 0)
            ga = ga + np.where(tied, et_a, 0)
        still = gh == ga
        # penalties
        diff = (self.ATT[hi] - self.DEF[ai]) - (self.ATT[ai] - self.DEF[hi])
        p_home = 0.5 + PEN_EDGE * np.tanh(diff)
        pen_home_win = self.rng.random(len(hi)) < p_home
        winner = np.where(gh > ga, hi, np.where(ga > gh, ai,
                          np.where(pen_home_win, hi, ai)))
        loser = np.where(winner == hi, ai, hi)
        return gh, ga, winner, loser, still

    # ---- main driver ------------------------------------------------------- #
    def run(self, n_sims: int, known: "KnownState | None" = None,
            track_matches: "set[int] | None" = None,
            track_opponents: bool = False,
            track_bracket: bool = False) -> dict:
        known = known or KnownState.empty()
        S, T = n_sims, self.n_teams
        track_matches = track_matches or set()
        # optional per-team knockout-opponent tracking: for each main KO round,
        # symmetric [T,T] count matrices of who met whom (meet) and who won (beat).
        # Lets the report decompose a team's advance odds into "who they face +
        # how likely they are to beat each opponent" instead of a single average.
        KO_ROUNDS = (1, 2, 3, 4, 6)   # R32, R16, QF, SF, Final (skip 3rd-place)
        opp_meet = {rc: np.zeros((T, T), np.int64) for rc in KO_ROUNDS} if track_opponents else {}
        opp_beat = {rc: np.zeros((T, T), np.int64) for rc in KO_ROUNDS} if track_opponents else {}
        # per-sim outcome for the fixtures the caller wants to condition on (the
        # "who to root for" board). Group matches -> 0=home win, 1=draw, 2=away win.
        # Knockout matches -> the winning team's index (2-outcome; no draw), plus
        # the per-sim participants so the caller can map a real fixture to a slot.
        game_outcomes: dict[int, np.ndarray] = {}
        ko_participants: dict[int, tuple] = {}
        # optional full per-sim knockout bracket capture (participants, winner,
        # scoreline and penalty flag for EVERY bracket match). Lets the caller
        # reconstruct one concrete sim's complete bracket (e.g. a "path to
        # victory" scenario). ~6 small int16 arrays [S] per KO match -> cheap.
        bracket_track: dict[int, dict] = {}
        z_i = lambda: np.zeros((S, T), dtype=np.int32)
        reg_wins, group_draws, reg_losses = z_i(), z_i(), z_i()
        pen_wins, pen_losses = z_i(), z_i()
        gf, ga = z_i(), z_i()
        games = z_i()
        gp, ggd, ggf = z_i(), z_i(), z_i()        # group-only pts / gd / gf
        round_reached = z_i()
        advanced = np.zeros((S, T), bool)
        made_final = np.zeros((S, T), bool)
        won_cup = np.zeros((S, T), bool)
        rows = np.arange(S)
        # goals locked in by FIXED matches (same across sims); used so player
        # goals are seeded from known results and only the remainder is sampled.
        gf_known = np.zeros(T, dtype=np.int64)

        # Head-to-head bookkeeping for the FIFA 2026 group tie-break (H2H first).
        # Per group: [S,4,4] tables where entry [s,a,b] is the result of a's match
        # vs b in sim s (goals a scored / points a earned). Only needed when the
        # group stage is still in progress (the completed path uses official_pos).
        track_h2h = not (known.group_stage_complete and known.official_pos)
        hh_gf = {g: np.zeros((S, 4, 4), np.int16) for g in GROUPS} if track_h2h else {}
        hh_pts = {g: np.zeros((S, 4, 4), np.int16) for g in GROUPS} if track_h2h else {}

        # --- group stage (fix played fixtures, sample the rest) ---
        for (hi, ai, hf), mno in zip(self.fixtures, self.fixture_match):
            ks = known.group_scores.get(mno)
            if ks is not None:
                hg, ag = (np.full(S, ks[0], np.int32), np.full(S, ks[1], np.int32))
                gf_known[hi] += ks[0]; gf_known[ai] += ks[1]
            else:
                hg, ag, _, _ = self._poisson_pair(np.full(S, hi), np.full(S, ai), hf)
            gf[:, hi] += hg; ga[:, hi] += ag
            gf[:, ai] += ag; ga[:, ai] += hg
            wi = hg > ag; dr = hg == ag; li_ = hg < ag
            if mno in track_matches:
                game_outcomes[mno] = np.where(wi, 0, np.where(li_, 2, 1)).astype(np.int8)
            reg_wins[:, hi] += wi; group_draws[:, hi] += dr; reg_losses[:, hi] += li_
            reg_wins[:, ai] += li_; group_draws[:, ai] += dr; reg_losses[:, ai] += wi
            games[:, hi] += 1; games[:, ai] += 1
            gp[:, hi] += 3 * wi + dr; gp[:, ai] += 3 * li_ + dr
            ggf[:, hi] += hg; ggf[:, ai] += ag
            ggd[:, hi] += hg - ag; ggd[:, ai] += ag - hg
            if track_h2h:
                g = self.team_group[hi]
                a, b = self.team_locpos[hi], self.team_locpos[ai]
                hh_gf[g][:, a, b] += hg.astype(np.int16)
                hh_gf[g][:, b, a] += ag.astype(np.int16)
                hh_pts[g][:, a, b] += (3 * wi + dr).astype(np.int16)
                hh_pts[g][:, b, a] += (3 * li_ + dr).astype(np.int16)

        group_finish = np.zeros((S, T), dtype=np.int32)
        winner_idx, runner_idx, third_idx = {}, {}, {}

        if known.group_stage_complete and known.official_pos:
            # --- official, deterministic standings + best-thirds slotting ---
            for g in GROUPS:
                pos = known.official_pos[g]               # [idx pos1..4]
                winner_idx[g] = np.full(S, pos[0], np.int64)
                runner_idx[g] = np.full(S, pos[1], np.int64)
                third_idx[g] = np.full(S, pos[2], np.int64)
                for rank in range(4):
                    group_finish[:, pos[rank]] = rank + 1
                advanced[:, pos[0]] = True
                advanced[:, pos[1]] = True
            for g in known.advanced_thirds_groups:
                advanced[:, known.official_pos[g][2]] = True
            combo = tuple(sorted(known.advanced_thirds_groups))
            assign = self.thirds_table.get(combo)
            third_slot_team = np.zeros((8, S), dtype=np.int64)
            if assign is not None:
                for slot_i, g in enumerate(assign):
                    third_slot_team[slot_i, :] = known.official_pos[g][2]
        else:
            # --- sampled standings: FIFA 2026 group tie-break -------------------
            # Within a group, teams level on points are separated by head-to-head
            # first (H2H points -> H2H GD -> H2H GF), then overall GD -> overall GF,
            # then a random draw. (This is the WC2026 change: H2H now precedes
            # overall goal difference.) The 12 third-placed teams are compared
            # across groups by overall pts/GD/GF only -- H2H cannot apply there.
            noise = self.rng.random((S, T)) * 0.1
            overall_key = gp.astype(float) * 1e6 + (ggd.astype(float) + 200) * 1e3 + ggf + noise
            third_key = np.zeros((S, 12))
            di = np.arange(4)
            for gi, g in enumerate(GROUPS):
                ts = np.array(self.group_teams[g])           # 4 global idx
                P = gp[:, ts].astype(np.float64)             # [S,4] overall points
                gfh = hh_gf[g].astype(np.float64)            # [S,4,4] goals a-vs-b
                pth = hh_pts[g].astype(np.float64)           # [S,4,4] pts a-vs-b
                gdh = gfh - gfh.transpose(0, 2, 1)           # [S,4,4] H2H goal diff
                same = P[:, :, None] == P[:, None, :]        # tied on overall points
                same[:, di, di] = False
                mini_pts = (pth * same).sum(2)               # [S,4] H2H mini-league
                mini_gd = (gdh * same).sum(2)
                mini_gf = (gfh * same).sum(2)
                ogd = ggd[:, ts].astype(np.float64)
                ogf = ggf[:, ts].astype(np.float64)
                nz = noise[:, ts]
                # lexsort: last key = highest priority, ascending -> reverse to
                # rank best team first. Priority: pts, H2H pts/GD/GF, overall GD/GF.
                order = np.lexsort(
                    (nz, ogf, ogd, mini_gf, mini_gd, mini_pts, P))[:, ::-1]
                pos_team = ts[order]                         # [S,4] global idx
                winner_idx[g] = pos_team[:, 0]
                runner_idx[g] = pos_team[:, 1]
                third_idx[g] = pos_team[:, 2]
                for rank in range(4):
                    group_finish[rows, pos_team[:, rank]] = rank + 1
                advanced[rows, pos_team[:, 0]] = True        # top 2 always advance
                advanced[rows, pos_team[:, 1]] = True
                third_key[:, gi] = overall_key[rows, pos_team[:, 2]]

            # --- best 8 of 12 third-placed teams advance ---
            third_order = np.argsort(-third_key, axis=1)     # [S,12] group positions
            adv_third_groups = third_order[:, :8]            # best 8 group-indices
            for j in range(8):
                gpos = adv_third_groups[:, j]                # [S] group index 0..11
                tt = np.empty(S, dtype=np.int64)
                for gi, g in enumerate(GROUPS):
                    m = gpos == gi
                    if m.any():
                        tt[m] = third_idx[g][m]
                advanced[rows, tt] = True

            # --- third-slot team assignment (precomputed FIFA-style table) ---
            bit = np.zeros(S, dtype=np.int64)
            for j in range(8):
                np.add.at(bit, rows, (1 << adv_third_groups[:, j]).astype(np.int64))
            third_slot_team = np.zeros((8, S), dtype=np.int64)
            uniq = np.unique(bit)
            for b in uniq:
                mask = bit == b
                combo = tuple(GROUPS[i] for i in range(12) if (b >> i) & 1)
                assign = self.thirds_table[combo]            # group letter per slot
                for slot_i, g in enumerate(assign):
                    third_slot_team[slot_i, mask] = third_idx[g][mask]

        # --- knockouts ---
        def resolve(ref) -> np.ndarray:
            t = ref["type"]
            if t == "group_winner":
                return winner_idx[ref["group"]]
            if t == "group_runner":
                return runner_idx[ref["group"]]
            if t == "match_winner":
                return ko_win[ref["match"]]
            if t == "match_loser":
                return ko_lose[ref["match"]]
            raise ValueError(t)

        # known knockout results keyed by the (unordered) participant pair.
        ko_known = {frozenset((h, a)): (h, a, hgk, agk, wk)
                    for (h, a, hgk, agk, wk) in known.ko_results}

        ko_win: dict[int, np.ndarray] = {}
        ko_lose: dict[int, np.ndarray] = {}
        bracket = sorted(self.ds.bracket, key=lambda m: m["match"])
        for m in bracket:
            mno = m["match"]; rc = m["round_code"]
            # resolve participants
            hr, ar = m["home_ref"], m["away_ref"]
            hi = (third_slot_team[self.slot_pos[(mno, "home_ref")]]
                  if hr["type"] == "third" else resolve(hr))
            ai = (third_slot_team[self.slot_pos[(mno, "away_ref")]]
                  if ar["type"] == "third" else resolve(ar))
            gh, ag, winner, loser, pen = self._play_knockout(hi, ai)
            # --- override with any known (already-played) results ---
            if ko_known:
                for kh, ka, hgk, agk, wk in ko_known.values():
                    m_h = (hi == kh) & (ai == ka)        # sim has home=kh, away=ka
                    m_a = (hi == ka) & (ai == kh)        # orientation swapped
                    gh = np.where(m_h, hgk, np.where(m_a, agk, gh))
                    ag = np.where(m_h, agk, np.where(m_a, hgk, ag))
                    mask = m_h | m_a
                    if wk >= 0 and mask.any():
                        winner = np.where(mask, wk, winner)
                        loser = np.where(mask, np.where(hi == wk, ai, hi), loser)
                        pen = np.where(mask, hgk == agk, pen)
                    if mask.all():                        # deterministic -> lock goals
                        gf_known[kh] += hgk; gf_known[ka] += agk
            # goals
            np.add.at(gf, (rows, hi), gh); np.add.at(ga, (rows, hi), ag)
            np.add.at(gf, (rows, ai), ag); np.add.at(ga, (rows, ai), gh)
            np.add.at(games, (rows, hi), 1); np.add.at(games, (rows, ai), 1)
            # results: winner / loser, split by penalty vs regulation
            wreg = ~pen
            np.add.at(reg_wins, (rows[wreg], winner[wreg]), 1)
            np.add.at(reg_losses, (rows[wreg], loser[wreg]), 1)
            np.add.at(pen_wins, (rows[pen], winner[pen]), 1)
            np.add.at(pen_losses, (rows[pen], loser[pen]), 1)
            # round reached for both participants
            lvl = _REACH[rc]
            cur_h = round_reached[rows, hi]; round_reached[rows, hi] = np.maximum(cur_h, lvl)
            cur_a = round_reached[rows, ai]; round_reached[rows, ai] = np.maximum(cur_a, lvl)
            ko_win[mno] = winner; ko_lose[mno] = loser
            if track_bracket:
                bracket_track[mno] = {
                    "rc": int(rc),
                    "home": hi.astype(np.int16), "away": ai.astype(np.int16),
                    "win": winner.astype(np.int16), "lose": loser.astype(np.int16),
                    "gh": gh.astype(np.int16), "ga": ag.astype(np.int16),
                    "pen": pen.astype(bool),
                }
            if track_opponents and rc in opp_meet:
                M, B = opp_meet[rc], opp_beat[rc]
                np.add.at(M, (hi, ai), 1)           # symmetric: count both perspectives
                np.add.at(M, (ai, hi), 1)
                wh = winner == hi                    # home advanced
                wa = ~wh                             # away advanced (winner is hi or ai)
                np.add.at(B, (hi[wh], ai[wh]), 1)
                np.add.at(B, (ai[wa], hi[wa]), 1)
            if mno in track_matches:
                # winner team index per sim + the two participants (constant
                # across sims once feeders are decided -> lets build_cheer map a
                # real upcoming fixture's (home, away) to this bracket slot).
                game_outcomes[mno] = winner.astype(np.int16)
                ko_participants[mno] = (hi.astype(np.int16), ai.astype(np.int16))
            if rc == 6:  # final
                made_final[rows, hi] = True; made_final[rows, ai] = True
                won_cup[rows, winner] = True
                round_reached[rows, winner] = ROUND_WINNER

        # teams that reached R32 (advanced) but recorded 0 round -> set R32
        adv_r32 = advanced & (round_reached < ROUND_R32)
        round_reached[adv_r32] = ROUND_R32

        # --- player goals + golden boot ---
        # Fix each candidate's known goals; sample the rest from the team's
        # *future* (not-yet-played) goals only, so conditioning is exact.
        team_gf_total = gf[:, self.player_team_idx]               # [S, P]
        team_gf_known = gf_known[self.player_team_idx]            # [P]
        future_team_gf = np.maximum(team_gf_total - team_gf_known[None, :], 0)
        sampled = self.rng.binomial(
            future_team_gf, self.player_share[None, :]).astype(np.int32)
        player_known = (known.player_known if known.player_known is not None
                        else np.zeros(len(self.player_names), dtype=np.int64))
        player_goals = sampled + player_known[None, :].astype(np.int32)
        # plausibility caps: with a fixed share, the binomial tail can hand one
        # star an implausible haul in deep/high-scoring runs. Cap each candidate's
        # per-sim total to a fraction of the team's goals and an absolute ceiling
        # (but never below goals already scored in locked matches).
        cap = np.minimum(np.floor(team_gf_total * MAX_PLAYER_GOAL_SHARE),
                         MAX_PLAYER_GOALS).astype(np.int32)
        cap = np.maximum(cap, player_known[None, :].astype(np.int32))
        player_goals = np.minimum(player_goals, cap)
        gb_noise = self.rng.random(player_goals.shape) * 0.5
        golden_boot = np.argmax(player_goals + gb_noise, axis=1)  # [S] player idx

        return dict(
            n_sims=S,
            reg_wins=reg_wins, group_draws=group_draws, reg_losses=reg_losses,
            pen_wins=pen_wins, pen_losses=pen_losses,
            gf=gf, ga=ga, games=games,
            group_finish=group_finish, advanced=advanced,
            made_final=made_final, won_cup=won_cup, round_reached=round_reached,
            player_goals=player_goals, golden_boot=golden_boot,
            player_names=self.player_names,
            game_outcomes=game_outcomes,
            ko_participants=ko_participants,
            opp_meet=opp_meet, opp_beat=opp_beat,
            bracket_track=bracket_track,
        )
