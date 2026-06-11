"""Dixon-Coles bivariate-Poisson match model.

Team attack/defence ratings are fit by weighted Poisson maximum likelihood on
~920 recent internationals (time-decay x competition-importance weights), with
a ridge penalty anchoring each finalist toward its eloratings.net strength so
sparsely-observed minnows are not over/under-rated. A 1-D Dixon-Coles ``rho``
correction is then fit on low-scoring games to get draw frequencies right.

The fitted parameters drive:
  * ``lambdas(i, j, home_adv)`` -> expected goals for a match, and
  * ``match_probs(i, j)`` -> (P win_i, P draw, P win_j) via the DC-corrected
    scoreline grid (used for calibration / reporting).

A global ``strength_spread`` multiplier (set by calibration) scales the
attack-defence separation so simulated title odds match the market/Opta.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar

from .config import RIDGE_STRENGTH, RIDGE_STYLE
from .names import resolve_any, slug


@dataclass
class MatchModel:
    teams: list[str]                 # all teams in the fit (finalists + others)
    index: dict[str, int]
    attack: np.ndarray               # per-team attack (log-scale)
    defence: np.ndarray              # per-team defence (log-scale)
    intercept: float                 # mu (base log goal-rate)
    home_adv: float                  # H (log-scale home advantage)
    rho: float                       # Dixon-Coles low-score correction
    spread: float = 1.0              # global strength-separation multiplier

    # ---- core rate / probability functions ---------------------------------
    def _eff(self, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.attack[idx] * self.spread, self.defence[idx] * self.spread

    def lambdas(self, i, j, home_adv: float = 0.0):
        """Expected goals (lambda_i, lambda_j); home_adv in {0,1} applies to i."""
        ai, di = self.attack[i] * self.spread, self.defence[i] * self.spread
        aj, dj = self.attack[j] * self.spread, self.defence[j] * self.spread
        li = np.exp(self.intercept + ai - dj + self.home_adv * home_adv)
        lj = np.exp(self.intercept + aj - di)
        return li, lj

    def match_probs(self, i: int, j: int, home_adv: float = 0.0, kmax: int = 12):
        """(P win_i, P draw, P win_j) via the DC-corrected scoreline grid."""
        li, lj = self.lambdas(i, j, home_adv)
        gi = np.arange(kmax + 1)
        pi = np.exp(-li) * li ** gi / _factorial(gi)
        pj = np.exp(-lj) * lj ** gi / _factorial(gi)
        P = np.outer(pi, pj)
        # Dixon-Coles tau correction on the four low-score cells.
        tau = np.ones((kmax + 1, kmax + 1))
        tau[0, 0] = 1 - li * lj * self.rho
        tau[0, 1] = 1 + li * self.rho
        tau[1, 0] = 1 + lj * self.rho
        tau[1, 1] = 1 - self.rho
        P = P * tau
        P /= P.sum()
        win_i = np.tril(P, -1).sum()      # gi > gj
        draw = np.trace(P)
        win_j = np.triu(P, 1).sum()       # gj > gi
        return win_i, draw, win_j


def _factorial(n: np.ndarray) -> np.ndarray:
    from scipy.special import factorial
    return factorial(n)


# --------------------------------------------------------------------------- #
# Fitting
# --------------------------------------------------------------------------- #
def _prepare(results: pd.DataFrame):
    """Build integer-indexed arrays for the fit. Home advantage applies to the
    listed 'home' team for non-friendly matches (friendlies are often neutral).
    """
    teams = sorted(set(results["home"]) | set(results["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    h = results["home"].map(idx).to_numpy()
    a = results["away"].map(idx).to_numpy()
    gh = results["hg"].to_numpy(float)
    ga = results["ag"].to_numpy(float)
    w = results["weight"].to_numpy(float)
    is_friendly = results["league"].str.contains("friendl", case=False, na=False)
    hf = (~is_friendly).astype(float).to_numpy()   # home-adv flag
    return teams, idx, h, a, gh, ga, w, hf


def fit_match_model(
    results: pd.DataFrame,
    elo_by_team: dict[str, float],
    ridge_strength: float = RIDGE_STRENGTH,
    ridge_style: float = RIDGE_STYLE,
) -> MatchModel:
    teams, idx, h, a, gh, ga, w, hf = _prepare(results)
    n = len(teams)

    # Elo-implied overall strength (log scale). We anchor (attack+defence) hard
    # to this, but leave the attack-defence *split* (a team's offensive vs
    # defensive personality) free for the data to determine. Non-finalists with
    # no Elo are simply shrunk toward average.
    elo_vals = np.array([elo_by_team.get(t, np.nan) for t in teams])
    mean_elo = np.nanmean(list(elo_by_team.values()))
    strength = np.where(np.isnan(elo_vals), 0.0, (elo_vals - mean_elo) / 400.0)
    has_anchor = ~np.isnan(elo_vals)
    # rs applies where we have an Elo anchor; weak teams w/o Elo still get rs
    # toward 0 strength so they don't blow up.
    rs = np.full(n, ridge_strength)

    # Param vector: [mu, H, att(n), def(n)]
    def unpack(x):
        mu = x[0]; H = x[1]
        att = x[2:2 + n]; deff = x[2 + n:2 + 2 * n]
        return mu, H, att, deff

    def nll_and_grad(x):
        mu, H, att, deff = unpack(x)
        log_li = mu + att[h] - deff[a] + H * hf
        log_lj = mu + att[a] - deff[h]
        li = np.exp(log_li); lj = np.exp(log_lj)
        # Weighted Poisson NLL (constant log g! dropped).
        nll = np.sum(w * (li - gh * log_li + lj - ga * log_lj))
        ri = w * (li - gh)   # dNLL/dlog_li
        rj = w * (lj - ga)
        g_mu = np.sum(ri + rj)
        g_H = np.sum(ri * hf)
        g_att = np.zeros(n); g_def = np.zeros(n)
        np.add.at(g_att, h, ri); np.add.at(g_att, a, rj)
        np.add.at(g_def, a, -ri); np.add.at(g_def, h, -rj)
        # Split ridge: anchor (att+def) to Elo strength; shrink (att-def) to 0.
        s = att + deff                      # overall strength
        d = att - deff                      # offensive/defensive split
        ds = s - strength                   # strength deviation from Elo
        nll += np.sum(rs * ds ** 2) + ridge_style * np.sum(d ** 2)
        # d/datt = rs*2*ds + ridge_style*2*d ; d/ddef = rs*2*ds - ridge_style*2*d
        g_att += 2 * rs * ds + 2 * ridge_style * d
        g_def += 2 * rs * ds - 2 * ridge_style * d
        grad = np.concatenate([[g_mu, g_H], g_att, g_def])
        return nll, grad

    x0 = np.concatenate([[0.0, 0.2], 0.5 * strength, 0.5 * strength])
    res = minimize(nll_and_grad, x0, jac=True, method="L-BFGS-B",
                   options={"maxiter": 500})
    mu, H, att, deff = unpack(res.x)

    # Fit rho on low-score cells given the fitted lambdas.
    log_li = mu + att[h] - deff[a] + H * hf
    log_lj = mu + att[a] - deff[h]
    li = np.exp(log_li); lj = np.exp(log_lj)
    rho = _fit_rho(gh, ga, li, lj, w)

    return MatchModel(teams=teams, index=idx, attack=att, defence=deff,
                      intercept=float(mu), home_adv=float(H), rho=float(rho))


def _fit_rho(gh, ga, li, lj, w) -> float:
    """1-D MLE of the Dixon-Coles rho on the four low-score cells."""
    low = (gh <= 1) & (ga <= 1)
    gh, ga, li, lj, w = gh[low], ga[low], li[low], lj[low], w[low]

    def neg_ll(rho):
        tau = np.ones_like(li)
        tau = np.where((gh == 0) & (ga == 0), 1 - li * lj * rho, tau)
        tau = np.where((gh == 0) & (ga == 1), 1 + li * rho, tau)
        tau = np.where((gh == 1) & (ga == 0), 1 + lj * rho, tau)
        tau = np.where((gh == 1) & (ga == 1), 1 - rho, tau)
        tau = np.clip(tau, 1e-6, None)
        return -np.sum(w * np.log(tau))

    r = minimize_scalar(neg_ll, bounds=(-0.2, 0.2), method="bounded")
    return float(r.x)
