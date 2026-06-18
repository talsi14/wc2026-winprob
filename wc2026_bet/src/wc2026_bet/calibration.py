"""Calibrate the global strength-spread against Opta title probabilities.

The attack/defence fit sets the *shape* of team strength; a single global
``strength_spread`` multiplier controls how separated the favourites are. We
grid-search the spread that minimises squared error between simulated title
probabilities and Opta's published numbers for the teams we have anchors for.

Also computes ``golden_boot_scale`` - the factor that aligns our simulated
P(player wins Golden Boot) with the market/Bayesian top-scorer probabilities
(we only simulate listed candidates, so we slightly over-state each one; the
scale corrects the Golden-Boot bonus EV).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .data_io import Dataset
from .model import MatchModel
from .simulate import Simulator


def simulate_title_probs(ds: Dataset, model: MatchModel, n_sims: int, seed: int):
    sim = Simulator(ds, model, seed=seed)
    O = sim.run(n_sims)
    win = O["won_cup"].mean(0)
    return {t: win[i] for i, t in enumerate(ds.team_list)}, O


def calibrate_spread(
    ds: Dataset, model: MatchModel,
    spreads=np.linspace(0.80, 1.25, 10), n_sims: int = 30_000, seed: int = 7,
) -> dict:
    # Prefer the live Kalshi+Opta blended title anchor (column ``title_prob``,
    # written by kalshi_odds.write_blended_title_anchors); fall back to the
    # static Opta prior when only the cold-start collect_data file is present.
    col = "title_prob" if "title_prob" in ds.market.columns else "opta_title_prob"
    anchors = {r.team: getattr(r, col) for r in ds.market.itertuples()}
    anchors = {t: float(p) for t, p in anchors.items()
               if p is not None and p == p}        # drop blanks / NaN
    # Use the clearly title-relevant anchors (top teams) for the spread fit.
    fit_teams = [t for t in anchors if anchors[t] >= 0.03]

    best = None
    trace = []
    for s in spreads:
        m = replace(model, spread=float(s))
        probs, _ = simulate_title_probs(ds, m, n_sims, seed)
        sse = sum((probs[t] - anchors[t]) ** 2 for t in fit_teams)
        trace.append({"spread": float(s), "sse": float(sse),
                      "probs": {t: float(probs[t]) for t in fit_teams}})
        if best is None or sse < best["sse"]:
            best = {"spread": float(s), "sse": float(sse)}
    return {"best_spread": best["spread"], "best_sse": best["sse"],
            "fit_teams": fit_teams, "anchors": anchors, "trace": trace}


def compute_golden_boot_scale(ds: Dataset, O: dict) -> float:
    """Align simulated P(GB) totals with the market/Bayesian top-scorer probs."""
    gb = O["golden_boot"]
    S = O["n_sims"]
    counts = np.bincount(gb, minlength=len(ds.players))
    sim_p = counts / S
    market_p = ds.players["p_top_scorer"].to_numpy(float)
    sim_total = sim_p.sum()
    market_total = market_p.sum()
    if sim_total <= 0:
        return 1.0
    return float(market_total / sim_total)


# --------------------------------------------------------------------------- #
# Per-team strength calibration to the market "to advance" board
# --------------------------------------------------------------------------- #
def _logit(p):
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def apply_strength_offsets(model: MatchModel, offsets: dict) -> MatchModel:
    """Return a model whose finalist attack/defence are shifted by a per-team
    log-strength offset (split equally so a team's offensive/defensive *style*
    is preserved). ``offsets`` maps team name -> offset in raw (pre-spread)
    log-strength units; +ve = stronger.
    """
    att = model.attack.copy()
    deff = model.defence.copy()
    for t, off in offsets.items():
        i = model.index.get(t)
        if i is None:
            continue
        att[i] += 0.5 * off
        deff[i] += 0.5 * off
    return replace(model, attack=att, defence=deff)


def calibrate_team_strengths(
    ds: Dataset, model: MatchModel, market_advance,
    n_sims: int = 15_000, rounds: int = 8, lr: float = 0.30,
    clip: float = 1.2, freeze_above: float = 0.80, seed: int = 11,
) -> dict:
    """Iterative fixed-point on per-team strength so simulated P(advance to R32)
    matches the de-vigged market "to advance" odds - for mid/low teams only.

    Each round: simulate, then nudge each calibrated team's offset by
    ``lr * (logit(market) - logit(sim))``.

    Crucially we ONLY calibrate teams whose market advance probability is below
    ``freeze_above``. Teams the market has advancing safely (the title
    contenders + strong mids, all already in the outright-odds blend) are left
    untouched: advancement is saturated and near-insensitive to strength for
    them, so matching it would demand large strength cuts that wreck the
    Opta-calibrated *title* race (e.g. it otherwise drags Spain's title prob
    from ~16% to ~5%). The correction therefore concentrates exactly where the
    outright blend is uninformative - the +250000-floored minnows (Panama, etc.).
    Returns offsets + a trace.
    """
    from .simulate import Simulator

    target = {r.team: float(r.p_advance) for r in market_advance.itertuples()}
    calib = [t for t in ds.team_list if target[t] < freeze_above]
    offsets = {t: 0.0 for t in ds.team_list}
    trace = []
    for it in range(rounds):
        m = apply_strength_offsets(model, offsets)
        O = Simulator(ds, m, seed=seed + it).run(n_sims)
        adv = O["advanced"].mean(0)
        worst = 0.0
        for i, t in enumerate(ds.team_list):
            if t not in calib:
                continue
            err = _logit(target[t]) - _logit(adv[i])
            offsets[t] = float(np.clip(offsets[t] + lr * err, -clip, clip))
            worst = max(worst, abs(target[t] - adv[i]))
        trace.append({"round": it, "max_abs_advance_err": round(worst, 4)})
    return {"offsets": offsets, "trace": trace, "n_calibrated": len(calib)}


# --------------------------------------------------------------------------- #
# Per-player goal-share calibration to the market Golden Boot board
# --------------------------------------------------------------------------- #
def golden_boot_target(ds: Dataset, market_weight: float = 0.85) -> np.ndarray:
    """Target P(player is the Golden Boot among our candidates), summing to 1.

    Blends the de-vigged market Golden-Boot probability (``market_p_gb``) with
    the model's own top-scorer prior (``p_top_scorer``); players absent from the
    market board fall back to their model prior. The result is the marginal the
    simulated Golden Boot is calibrated to, so the top-scorer *ordering* follows
    the market (Mbappe/Kane >= Haaland) rather than the sim's share-driven argmax.
    """
    mkt = ds.players["market_p_gb"].to_numpy(float).copy()
    prior = ds.players["p_top_scorer"].to_numpy(float).copy()
    prior = np.clip(prior, 1e-4, None)
    # fill off-board players with their model prior, scaled to the board's level
    if (mkt > 0).any():
        lvl = mkt[mkt > 0].mean() / prior[mkt > 0].mean()
        mkt = np.where(mkt > 0, mkt, prior * lvl)
    else:
        mkt = prior
    mkt = mkt / mkt.sum()
    prior = prior / prior.sum()
    blend = mkt ** market_weight * prior ** (1 - market_weight)
    return blend / blend.sum()


def calibrate_player_shares(
    ds: Dataset, O: dict, target_p: np.ndarray, market_weight: float = 0.7,
) -> np.ndarray:
    """Per-player goal-share factors so each candidate's *expected tournament
    goals* track the market Golden-Boot ordering.

    Matching the Golden-Boot marginal directly is ill-posed (it is an argmax /
    tail event, so forcing it drives shares to extremes). Instead we target
    **expected goals**, a well-posed quantity: blend the model's expected goals
    with a market-proportional expectation (``target_p`` scaled to the same total
    goal mass), preserve the total, and back out the share. The simulated Golden
    Boot - an argmax over these goals - then orders by the market (Mbappe/Kane >=
    Haaland) while magnitudes stay realistic. Returns a factor array to multiply
    ``blended_share`` by.
    """
    team_idx = np.array([ds.team_index[t] for t in ds.players["team"]])
    team_gf = O["gf"][:, team_idx].mean(0)             # E[team goals] per player
    base = ds.players["blended_share"].to_numpy(float)
    eg_model = np.maximum(team_gf * base, 1e-6)
    total = eg_model.sum()

    eg_market = target_p / target_p.sum() * total      # market-proportional EG
    eg_target = eg_model ** (1 - market_weight) * eg_market ** market_weight
    eg_target *= total / eg_target.sum()               # preserve total goal mass

    share_target = np.clip(eg_target / np.maximum(team_gf, 1e-6), 1e-3, 0.92)
    return share_target / base
