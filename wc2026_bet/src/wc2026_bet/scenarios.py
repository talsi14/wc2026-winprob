"""Most-plausible tournament projections from a subset of simulations.

Given a boolean mask over simulations we build a single, internally-consistent
"chalk" projection that reflects that subset's distribution:

  * Group standings  - teams ordered by mean finishing position; we report each
                       team's P(win group) and P(qualify) within the subset.
  * Knockout bracket - the modal qualifiers are seeded into the real 2026 R32
                       slots (incl. the best-thirds assignment), then each tie is
                       advanced to the side with the greater conditional run-depth
                       (mean round reached), all the way to the champion.
  * Top-5 scorers    - by mean goals within the subset, with P(Golden Boot).

For "overall" the mask is all sims (the unconditional, average tournament). For
an entry it is the sims where that entry finishes in the money (top-2), i.e.
"what the world looks like when this bet pays off".
"""
from __future__ import annotations

import numpy as np

from .bracket import precompute_thirds_table, third_slots
from .config import GROUPS

ROUND_LABEL = {1: "Round of 32", 2: "Round of 16", 3: "Quarter-final",
               4: "Semi-final", 6: "Final"}


def entry_top2_mask(opt, field, entry, seed: int = 0) -> np.ndarray:
    """Sims where ``entry`` finishes 1st or 2nd against the modelled field."""
    s = opt.entry_score(entry)
    rng = np.random.default_rng(seed)
    c = s + rng.uniform(0, 1e-3, size=s.shape).astype(s.dtype)
    above = (field.scores > c[:, None]).sum(1)
    return (above + 1) <= 2


def build_scenario(ds, O, mask, picks=None, player=None) -> dict:
    tl = ds.team_list
    ti = ds.team_index
    sel = np.asarray(mask, bool)
    n = int(sel.sum())
    gfin = O["group_finish"][sel]
    depth = O["round_reached"][sel].mean(0)
    advp = O["advanced"][sel].mean(0)
    pg = O["player_goals"][sel]
    gbi = O["golden_boot"][sel]
    pickset = set(picks or [])

    # ---- group standings (ordered by mean finish) ------------------------- #
    grp_order = {}
    groups = []
    for g in GROUPS:
        idxs = [ti[t] for t in ds.groups[g]]
        stats = []
        for t_i in idxs:
            fin = gfin[:, t_i]
            stats.append((t_i, float(fin.mean()), float((fin == 1).mean()),
                          float((fin <= 2).mean())))
        stats.sort(key=lambda r: r[1])
        grp_order[g] = [s[0] for s in stats]
        groups.append({"group": g, "teams": [
            {"team": tl[s[0]], "p_first": s[2], "p_qual": s[3],
             "pick": tl[s[0]] in pickset} for s in stats]})

    # ---- seed R32: modal winners/runners + best-8 thirds ------------------ #
    winner_idx = {g: grp_order[g][0] for g in GROUPS}
    runner_idx = {g: grp_order[g][1] for g in GROUPS}
    third_team = {g: grp_order[g][2] for g in GROUPS}
    top8 = tuple(sorted(sorted(GROUPS, key=lambda g: -advp[third_team[g]])[:8]))
    assign = precompute_thirds_table(ds.bracket)[top8]
    slots = third_slots(ds.bracket)
    slot_pos = {(s["match"], s["side"]): i for i, s in enumerate(slots)}
    third_slot_team = [third_team[assign[i]] for i in range(8)]

    # ---- advance deterministically by conditional run-depth ---------------- #
    ko_win, ko_lose = {}, {}

    def resolve(ref):
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

    rounds = {}
    for m in sorted(ds.bracket, key=lambda x: x["match"]):
        mno, rc = m["match"], m["round_code"]
        hr, ar = m["home_ref"], m["away_ref"]
        hi = (third_slot_team[slot_pos[(mno, "home_ref")]]
              if hr["type"] == "third" else resolve(hr))
        ai = (third_slot_team[slot_pos[(mno, "away_ref")]]
              if ar["type"] == "third" else resolve(ar))
        win = hi if depth[hi] >= depth[ai] else ai
        ko_win[mno], ko_lose[mno] = win, (ai if win == hi else hi)
        if rc in ROUND_LABEL:
            rounds.setdefault(rc, []).append({
                "home": tl[hi], "away": tl[ai], "winner": tl[win],
                "home_pick": tl[hi] in pickset, "away_pick": tl[ai] in pickset})

    final = next(m for m in ds.bracket if m["match"] == 104)
    champ_i = ko_win[104]
    runner_i = ko_lose[104]

    # ---- top-5 scorers ----------------------------------------------------- #
    mean_goals = pg.mean(0)
    gb_p = np.bincount(gbi, minlength=len(O["player_names"])) / max(n, 1)
    pteams = list(ds.players["team"])
    order = np.argsort(-mean_goals)[:5]
    scorers = [{"player": O["player_names"][i], "team": pteams[i],
                "goals": float(mean_goals[i]), "p_gb": float(gb_p[i]),
                "pick": (player == O["player_names"][i])} for i in order]

    return {
        "n_sims": n,
        "champion": tl[champ_i], "runner_up": tl[runner_i],
        "champion_pick": tl[champ_i] in pickset,
        "groups": groups,
        "rounds": [{"code": rc, "label": ROUND_LABEL[rc], "matches": rounds[rc]}
                   for rc in sorted(rounds)],
        "scorers": scorers,
    }
