"""Backtest the match-prediction product: for every completed group game,
reconstruct the model exactly as it stood just before kickoff (the per-match
pre-kickoff calibration snapshot), predict the 1X2 outcome + exact score, and
score it against the actual result with proper scoring rules.

Also compares against (a) the frozen pre-tournament model (to isolate the value
of the per-round ELO/recalibration updates) and (b) a uniform 1/3 baseline.

Writes a self-contained HTML report with SVG visualizations.

Usage: python3 wc2026_bet/scripts/backtest_predictions.py
Output: backtest_report.html (repo root)
"""
from __future__ import annotations

import glob
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "wc2026_bet" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for sibling scripts

from wc2026_bet.calibration import apply_strength_offsets       # noqa: E402
from wc2026_bet.config import HOST_NATIONS                       # noqa: E402
from wc2026_bet.espn import fetch_fixtures                       # noqa: E402
from wc2026_bet.live import load_live_dataset                    # noqa: E402
from wc2026_bet.model import fit_match_model, _factorial         # noqa: E402

import match_odds_api as mo  # noqa: E402  (same scripts dir)

PROC = ROOT / "wc2026_bet" / "data" / "processed"


def parse_cal_ts(path: str) -> datetime:
    ts = Path(path).stem.replace("calibration_", "")
    return datetime.strptime(ts, "%Y-%m-%dT%H%M")


def parse_kick(iso: str) -> datetime:
    return datetime.strptime(iso.replace("Z", ""), "%Y-%m-%dT%H:%M")


def grid(m, i, j, ha):
    li, lj = m.lambdas(i, j, ha)
    k = 10
    g = np.arange(k + 1)
    pi = np.exp(-li) * li ** g / _factorial(g)
    pj = np.exp(-lj) * lj ** g / _factorial(g)
    P = np.outer(pi, pj)
    t = np.ones((k + 1, k + 1))
    t[0, 0] = 1 - li * lj * m.rho
    t[0, 1] = 1 + li * m.rho
    t[1, 0] = 1 + lj * m.rho
    t[1, 1] = 1 - m.rho
    P = P * t
    P /= P.sum()
    ph, pd, pa = np.tril(P, -1).sum(), np.trace(P), np.triu(P, 1).sum()
    a, b = np.unravel_index(int(np.argmax(P)), P.shape)
    return (np.array([ph, pd, pa]) / (ph + pd + pa), (int(a), int(b)),
            float(li), float(lj), float(P.max()), P)


def top_scorelines(P, k):
    """Return the k most-probable (home,away) scorelines from a grid, best first."""
    flat = np.argsort(P, axis=None)[::-1][:k]
    return [tuple(int(x) for x in np.unravel_index(int(f), P.shape)) for f in flat]


TOPK = 10  # how many ranked scorelines we retain per match


def outcome(hg, ag):
    return 0 if hg > ag else (1 if hg == ag else 2)


def rps(p, o):
    onehot = np.eye(3)[o]
    return 0.5 * float(((np.cumsum(p) - np.cumsum(onehot)) ** 2).sum())


def build():
    ds = load_live_dataset()
    elo = {r.team: r.elo for r in ds.teams.itertuples()}
    m0 = fit_match_model(ds.results, elo)

    cal_paths = sorted(glob.glob(str(PROC / "calibration_2026-*.json")))
    cal_dt = [(parse_cal_ts(p), p) for p in cal_paths]
    pretourney_cal = json.load(open(cal_dt[0][1]))
    models: dict[str, object] = {}

    def model_for(path: str):
        if path not in models:
            c = json.load(open(path))
            models[path] = apply_strength_offsets(
                replace(m0, spread=c["strength_spread"]), c.get("strength_offsets", {}))
        return models[path]

    m_pre = apply_strength_offsets(
        replace(m0, spread=pretourney_cal["strength_spread"]),
        pretourney_cal.get("strength_offsets", {}))

    gm = {frozenset((r.home, r.away)): r for r in ds.group_matches.itertuples()}
    ko_pairs = set()
    for mm in ds.bracket:
        pass
    fx = fetch_fixtures()
    odds_hist = mo.load_history()  # per-match market snapshots (empty until captured)
    rows = []
    for f in fx:
        h, a = f.get("home"), f.get("away")
        if not h or not a or not f.get("date"):
            continue
        key = frozenset((h, a))
        if key not in gm:
            continue
        if f.get("home_score") is None or f.get("away_score") is None:
            continue
        r = gm[key]
        kick = parse_kick(f["date"])
        # actual (ESPN home/away orientation)
        hg, ag = int(f["home_score"]), int(f["away_score"])
        # our fixture orientation — index into the MODEL's own team ordering
        i, j = m0.index[r.home], m0.index[r.away]
        ha = 1.0 if (r.home in HOST_NATIONS and r.venue_country == r.home) else 0.0
        # actual in fixture orientation
        if h == r.home:
            fhg, fag = hg, ag
        else:
            fhg, fag = ag, hg
        o = outcome(fhg, fag)
        # pre-kickoff snapshot (latest cal <= kickoff, else earliest)
        before = [p for (dt, p) in cal_dt if dt <= kick]
        snap = before[-1] if before else cal_dt[0][1]
        p_live, mode_live, li, lj, pmode, P = grid(model_for(snap), i, j, ha)
        p_pre, mode_pre, _, _, _, _ = grid(m_pre, i, j, ha)
        p_actual = float(P[fhg, fag]) if (fhg <= 10 and fag <= 10) else 1e-6
        within1 = abs(mode_live[0] - fhg) <= 1 and abs(mode_live[1] - fag) <= 1
        out_from_score = outcome(mode_live[0], mode_live[1]) == o
        topk = top_scorelines(P, TOPK)
        actual_rank = topk.index((fhg, fag)) + 1 if (fhg, fag) in topk else None
        # leakage-free market scorelines: latest odds snapshot observed BEFORE
        # kickoff, oriented to our home/away (flip if the book listed it reversed)
        market_topk = None
        line = mo.pre_kickoff_line(odds_hist, r.home, r.away, kick)
        if line:
            mtop = mo.market_top_scorelines(line, TOPK)
            if line.get("home") != r.home:
                mtop = [(b, a) for (a, b) in mtop]
            market_topk = [list(s) for s in mtop]
        rows.append({
            "match": int(r.match), "home": r.home, "away": r.away,
            "kick": kick.isoformat(), "snap": Path(snap).stem.replace("calibration_", ""),
            "hg": fhg, "ag": fag, "o": o,
            "p_live": [round(x, 4) for x in p_live.tolist()],
            "p_pre": [round(x, 4) for x in p_pre.tolist()],
            "mode": [mode_live[0], mode_live[1]],
            "xg": [round(li, 2), round(lj, 2)],
            "p_mode": round(pmode, 4), "p_actual": round(p_actual, 5),
            "within1": bool(within1), "out_from_score": bool(out_from_score),
            "topk": [list(s) for s in topk], "actual_rank": actual_rank,
            "market_topk": market_topk,
        })
    rows.sort(key=lambda r: r["kick"])
    # round assignment: first 24 kickoffs -> R1, next 24 -> R2, last 24 -> R3
    for idx, r in enumerate(rows):
        r["round"] = 1 if idx < 24 else (2 if idx < 48 else 3)
    # leakage-free base-rate prior: most common scorelines in the historical
    # international corpus the model was trained on (NOT the WC2026 games).
    base_rank = base_rate_scorelines(ds.results)
    return rows, base_rank


def metrics(rows, key):
    agg = {"n": 0, "rps": 0.0, "ll": 0.0, "brier": 0.0, "hit": 0, "exact": 0, "gae": 0.0}
    per_round = {1: dict(agg), 2: dict(agg), 3: dict(agg)}
    for r in rows:
        p = np.array(r[key])
        o = r["o"]
        oneh = np.eye(3)[o]
        rp = rps(p, o)
        ll = -np.log(max(p[o], 1e-12))
        br = float(((p - oneh) ** 2).sum())
        hit = int(np.argmax(p) == o)
        exact = int(r["mode"][0] == r["hg"] and r["mode"][1] == r["ag"]) if key == "p_live" else 0
        gae = abs((r["xg"][0] + r["xg"][1]) - (r["hg"] + r["ag"])) if key == "p_live" else 0.0
        for d in (agg, per_round[r["round"]]):
            d["n"] += 1
            d["rps"] += rp
            d["ll"] += ll
            d["brier"] += br
            d["hit"] += hit
            d["exact"] += exact
            d["gae"] += gae
    def fin(d):
        n = max(d["n"], 1)
        return {"n": d["n"], "rps": d["rps"] / n, "ll": d["ll"] / n,
                "brier": d["brier"] / n, "hit": d["hit"] / n,
                "exact": d["exact"] / n, "gae": d["gae"] / n}
    return {"overall": fin(agg), "by_round": {k: fin(v) for k, v in per_round.items()}}


def reliability(rows, key, nbins=10):
    xs, ys = [], []  # predicted prob, observed indicator across all (match,outcome)
    for r in rows:
        p = r[key]
        oneh = [0, 0, 0]
        oneh[r["o"]] = 1
        for k in range(3):
            xs.append(p[k]); ys.append(oneh[k])
    xs = np.array(xs); ys = np.array(ys)
    bins = np.linspace(0, 1, nbins + 1)
    out = []
    for b in range(nbins):
        m = (xs >= bins[b]) & (xs < bins[b + 1] if b < nbins - 1 else xs <= bins[b + 1])
        if m.sum() >= 3:
            out.append({"pred": float(xs[m].mean()), "obs": float(ys[m].mean()),
                        "n": int(m.sum())})
    # expected calibration error
    ece = sum(o["n"] * abs(o["pred"] - o["obs"]) for o in out) / max(len(xs), 1)
    return out, ece


def conf_bands(rows, key):
    bands = [(0.33, 0.45), (0.45, 0.55), (0.55, 0.70), (0.70, 1.01)]
    out = []
    for lo, hi in bands:
        n = c = 0
        for r in rows:
            p = np.array(r[key]); pm = p.max()
            if lo <= pm < hi:
                n += 1; c += int(np.argmax(p) == r["o"])
        if n:
            out.append({"lo": lo, "hi": hi, "n": n, "acc": c / n, "pred": (lo + hi) / 2})
    return out


def uniform_metrics(rows):
    rp = ll = 0.0
    for r in rows:
        rp += rps(np.array([1 / 3, 1 / 3, 1 / 3]), r["o"])
        ll += -np.log(1 / 3)
    n = len(rows)
    return {"rps": rp / n, "ll": ll / n, "hit": 1 / 3}


def exact_metrics(rows):
    """Metrics for the exact-score product."""
    agg = {"n": 0, "exact": 0, "within1": 0, "outacc": 0,
           "gll": 0.0, "gae": 0.0, "pmode": 0.0}
    per_round = {1: dict(agg), 2: dict(agg), 3: dict(agg)}
    for r in rows:
        exact = int(r["mode"][0] == r["hg"] and r["mode"][1] == r["ag"])
        for d in (agg, per_round[r["round"]]):
            d["n"] += 1
            d["exact"] += exact
            d["within1"] += int(r["within1"])
            d["outacc"] += int(r["out_from_score"])
            d["gll"] += -np.log(max(r["p_actual"], 1e-6))
            d["gae"] += abs((r["mode"][0] + r["mode"][1]) - (r["hg"] + r["ag"]))
            d["pmode"] += r["p_mode"]

    def fin(d):
        n = max(d["n"], 1)
        return {"n": d["n"], "exact": d["exact"] / n, "within1": d["within1"] / n,
                "outacc": d["outacc"] / n, "gll": d["gll"] / n,
                "gae": d["gae"] / n, "pmode": d["pmode"] / n}
    return {"overall": fin(agg), "by_round": {k: fin(v) for k, v in per_round.items()}}


def base_rate_scorelines(results):
    """Rank scorelines by historical frequency in the training corpus (weighted).
    Leakage-free: these are pre-2026 internationals, not the games we score."""
    from collections import Counter
    c = Counter()
    for r in results.itertuples():
        try:
            hg, ag, w = int(r.hg), int(r.ag), float(getattr(r, "weight", 1.0))
        except (ValueError, TypeError):
            continue
        if hg <= 10 and ag <= 10:
            c[(hg, ag)] += w
    return [list(sc) for sc, _ in c.most_common(TOPK)]


def topx_curve(rows, base_rank, maxx=8):
    """Hit-rate@X for X=1..maxx: model top-X (per-match) vs base-rate top-X
    (fixed) vs the market top-X (per-match, over games with a pre-kickoff line).

    Returns (curve, market_coverage). The 'market' key is None until per-match
    odds have been captured (see match_odds_api)."""
    n = len(rows)
    base_set = [tuple(s) for s in base_rank]
    mkt_rows = [r for r in rows if r.get("market_topk")]
    out = []
    for x in range(1, maxx + 1):
        m_hit = sum(1 for r in rows
                    if any([r["hg"], r["ag"]] == s for s in r["topk"][:x])) / n
        bx = set(base_set[:x])
        b_hit = sum(1 for r in rows if (r["hg"], r["ag"]) in bx) / n
        if mkt_rows:
            mk_hit = sum(1 for r in mkt_rows
                         if any([r["hg"], r["ag"]] == s
                                for s in r["market_topk"][:x])) / len(mkt_rows)
        else:
            mk_hit = None
        out.append({"x": x, "model": m_hit, "base": b_hit, "market": mk_hit})
    return out, len(mkt_rows)


def exact_baselines(rows):
    """Naive constant-scoreline baselines + uniform-grid log-loss."""
    from collections import Counter
    actual = Counter((r["hg"], r["ag"]) for r in rows)
    n = len(rows)
    # exact-hit of always predicting a fixed scoreline
    fixed = {}
    for sc in [(1, 0), (1, 1), (2, 1), (0, 0)]:
        fixed[f"{sc[0]}-{sc[1]}"] = actual.get(sc, 0) / n
    best_sc, best_ct = actual.most_common(1)[0]
    return {"fixed": fixed,
            "best_const": {"score": f"{best_sc[0]}-{best_sc[1]}", "hit": best_ct / n},
            "uniform_gll": float(np.log(36))}  # ~ln of a 6x6 grid


def scoreline_dist(rows, topn=8):
    """Predicted-mode vs actual scoreline frequency (top N by combined count)."""
    from collections import Counter
    pred = Counter(f'{r["mode"][0]}-{r["mode"][1]}' for r in rows)
    act = Counter(f'{r["hg"]}-{r["ag"]}' for r in rows)
    keys = sorted(set(pred) | set(act), key=lambda k: -(pred[k] + act[k]))[:topn]
    return [{"score": k, "pred": pred[k], "act": act[k]} for k in keys]


# --------------------------------------------------------------------------- #
# SVG rendering (self-contained, no external deps)
# --------------------------------------------------------------------------- #
C_LIVE, C_PRE, C_UNI = "#2563eb", "#94a3b8", "#d4d4d8"
C_GOOD, C_BAD, C_GRID, C_TXT, C_MUT = "#16a34a", "#dc2626", "#e5e7eb", "#1f2937", "#6b7280"


def svg_reliability(points, ece):
    W = H = 300
    pad = 42
    x0, y0, x1, y1 = pad, H - pad, W - 12, 12
    def sx(v): return x0 + v * (x1 - x0)
    def sy(v): return y0 + v * (y1 - y0)
    s = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui" font-size="10">']
    # grid + axes
    for g in range(0, 11, 2):
        v = g / 10
        s.append(f'<line x1="{sx(v):.1f}" y1="{y0}" x2="{sx(v):.1f}" y2="{y1}" stroke="{C_GRID}"/>')
        s.append(f'<line x1="{x0}" y1="{sy(v):.1f}" x2="{x1}" y2="{sy(v):.1f}" stroke="{C_GRID}"/>')
        s.append(f'<text x="{sx(v):.1f}" y="{y0+14}" fill="{C_MUT}" text-anchor="middle">{v:.1f}</text>')
        s.append(f'<text x="{x0-6}" y="{sy(v)+3:.1f}" fill="{C_MUT}" text-anchor="end">{v:.1f}</text>')
    # perfect calibration diagonal
    s.append(f'<line x1="{sx(0)}" y1="{sy(0)}" x2="{sx(1)}" y2="{sy(1)}" stroke="{C_MUT}" stroke-dasharray="4 3"/>')
    # connecting line + points
    pth = " ".join(f'{sx(p["pred"]):.1f},{sy(p["obs"]):.1f}' for p in points)
    s.append(f'<polyline points="{pth}" fill="none" stroke="{C_LIVE}" stroke-width="1.5"/>')
    for p in points:
        rad = 3 + (p["n"] ** 0.5)
        s.append(f'<circle cx="{sx(p["pred"]):.1f}" cy="{sy(p["obs"]):.1f}" r="{rad:.1f}" '
                 f'fill="{C_LIVE}" fill-opacity="0.55" stroke="{C_LIVE}"/>')
    s.append(f'<text x="{(x0+x1)/2:.0f}" y="{H-4}" fill="{C_TXT}" text-anchor="middle" font-size="11">Predicted probability</text>')
    s.append(f'<text x="12" y="{(y0+y1)/2:.0f}" fill="{C_TXT}" text-anchor="middle" font-size="11" transform="rotate(-90 12 {(y0+y1)/2:.0f})">Observed frequency</text>')
    s.append(f'<text x="{x1}" y="{y1+10}" fill="{C_MUT}" text-anchor="end">ECE={ece*100:.1f}%</text>')
    s.append('</svg>')
    return "".join(s)


def svg_grouped_bars(title, groups, series, ylabel, fmt="{:.3f}", lower_better=True):
    """groups: list of labels; series: list of (name,color,[values])."""
    W, H = 360, 240
    pad_l, pad_b, pad_t = 44, 34, 16
    x0, y0, x1, y1 = pad_l, H - pad_b, W - 12, pad_t
    vmax = max(v for _, _, vals in series for v in vals) * 1.15 or 1
    def sy(v): return y0 - (v / vmax) * (y0 - y1)
    s = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui" font-size="10">']
    for g in range(0, 6):
        v = vmax * g / 5
        s.append(f'<line x1="{x0}" y1="{sy(v):.1f}" x2="{x1}" y2="{sy(v):.1f}" stroke="{C_GRID}"/>')
        s.append(f'<text x="{x0-5}" y="{sy(v)+3:.1f}" fill="{C_MUT}" text-anchor="end">{fmt.format(v)}</text>')
    ng, ns = len(groups), len(series)
    gw = (x1 - x0) / ng
    bw = gw * 0.7 / ns
    for gi, gl in enumerate(groups):
        gx = x0 + gi * gw + gw * 0.15
        for si, (name, color, vals) in enumerate(series):
            v = vals[gi]
            bx = gx + si * bw
            s.append(f'<rect x="{bx:.1f}" y="{sy(v):.1f}" width="{bw-2:.1f}" height="{y0-sy(v):.1f}" fill="{color}"/>')
            s.append(f'<text x="{bx+bw/2-1:.1f}" y="{sy(v)-3:.1f}" fill="{C_TXT}" text-anchor="middle" font-size="9">{fmt.format(v)}</text>')
        s.append(f'<text x="{gx+gw*0.35:.1f}" y="{y0+13}" fill="{C_TXT}" text-anchor="middle">{gl}</text>')
    s.append(f'<text x="12" y="{(y0+y1)/2:.0f}" fill="{C_TXT}" text-anchor="middle" font-size="11" transform="rotate(-90 12 {(y0+y1)/2:.0f})">{ylabel}</text>')
    s.append('</svg>')
    return "".join(s)


def svg_confbands(bands):
    W, H = 360, 240
    pad_l, pad_b, pad_t = 40, 46, 16
    x0, y0, x1, y1 = pad_l, H - pad_b, W - 12, pad_t
    def sy(v): return y0 - v * (y0 - y1)
    s = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui" font-size="10">']
    for g in range(0, 6):
        v = g / 5
        s.append(f'<line x1="{x0}" y1="{sy(v):.1f}" x2="{x1}" y2="{sy(v):.1f}" stroke="{C_GRID}"/>')
        s.append(f'<text x="{x0-5}" y="{sy(v)+3:.1f}" fill="{C_MUT}" text-anchor="end">{int(v*100)}%</text>')
    n = len(bands)
    gw = (x1 - x0) / n
    for i, b in enumerate(bands):
        gx = x0 + i * gw + gw * 0.18
        w = gw * 0.28
        # predicted midpoint (expected) as outline, actual as fill
        s.append(f'<rect x="{gx:.1f}" y="{sy(b["pred"]):.1f}" width="{w:.1f}" height="{y0-sy(b["pred"]):.1f}" fill="none" stroke="{C_MUT}" stroke-dasharray="3 2"/>')
        col = C_GOOD if abs(b["acc"] - b["pred"]) < 0.1 else C_BAD
        s.append(f'<rect x="{gx+w+2:.1f}" y="{sy(b["acc"]):.1f}" width="{w:.1f}" height="{y0-sy(b["acc"]):.1f}" fill="{col}" fill-opacity="0.8"/>')
        lbl = f'{int(b["lo"]*100)}-{int(min(b["hi"],1)*100)}%'
        s.append(f'<text x="{gx+w:.1f}" y="{y0+13}" fill="{C_TXT}" text-anchor="middle">{lbl}</text>')
        s.append(f'<text x="{gx+w:.1f}" y="{y0+25}" fill="{C_MUT}" text-anchor="middle">n={b["n"]}</text>')
    s.append('</svg>')
    return "".join(s)


def svg_simple_bars(groups, values, colors, fmt="{:.0f}%", vmax=None):
    """Single-series bar chart (one bar per group)."""
    W, H = 360, 240
    pad_l, pad_b, pad_t = 40, 40, 16
    x0, y0, x1, y1 = pad_l, H - pad_b, W - 12, pad_t
    vmax = (vmax or max(values) * 1.18) or 1
    def sy(v): return y0 - (v / vmax) * (y0 - y1)
    s = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui" font-size="10">']
    for g in range(0, 6):
        v = vmax * g / 5
        s.append(f'<line x1="{x0}" y1="{sy(v):.1f}" x2="{x1}" y2="{sy(v):.1f}" stroke="{C_GRID}"/>')
        s.append(f'<text x="{x0-5}" y="{sy(v)+3:.1f}" fill="{C_MUT}" text-anchor="end">{fmt.format(v)}</text>')
    n = len(groups)
    gw = (x1 - x0) / n
    bw = gw * 0.6
    for i, (gl, v, col) in enumerate(zip(groups, values, colors)):
        bx = x0 + i * gw + (gw - bw) / 2
        s.append(f'<rect x="{bx:.1f}" y="{sy(v):.1f}" width="{bw:.1f}" height="{y0-sy(v):.1f}" fill="{col}" rx="3"/>')
        s.append(f'<text x="{bx+bw/2:.1f}" y="{sy(v)-4:.1f}" fill="{C_TXT}" text-anchor="middle" font-size="10" font-weight="600">{fmt.format(v)}</text>')
        for li, ln in enumerate(gl.split("\n")):
            s.append(f'<text x="{bx+bw/2:.1f}" y="{y0+13+li*11}" fill="{C_TXT}" text-anchor="middle">{ln}</text>')
    s.append('</svg>')
    return "".join(s)


def svg_topx_lines(curve, series, khi=None):
    """Cumulative hit-rate@X line chart. series: [(name,color,key)]."""
    W, H = 380, 250
    pad_l, pad_b, pad_t = 42, 34, 14
    x0, y0, x1, y1 = pad_l, H - pad_b, W - 14, pad_t
    xs = [c["x"] for c in curve]
    xmin, xmax = min(xs), max(xs)
    vmax = max(c[k] for c in curve for _, _, k in series) * 1.15 or 1
    def sx(x): return x0 + (x - xmin) / max(xmax - xmin, 1) * (x1 - x0)
    def sy(v): return y0 - (v / vmax) * (y0 - y1)
    s = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui" font-size="10">']
    for g in range(0, 6):
        v = vmax * g / 5
        s.append(f'<line x1="{x0}" y1="{sy(v):.1f}" x2="{x1}" y2="{sy(v):.1f}" stroke="{C_GRID}"/>')
        s.append(f'<text x="{x0-5}" y="{sy(v)+3:.1f}" fill="{C_MUT}" text-anchor="end">{v*100:.0f}%</text>')
    for c in curve:
        s.append(f'<text x="{sx(c["x"]):.1f}" y="{y0+13}" fill="{C_TXT}" text-anchor="middle">{c["x"]}</text>')
    if khi is not None and xmin <= khi <= xmax:
        s.append(f'<line x1="{sx(khi):.1f}" y1="{y1}" x2="{sx(khi):.1f}" y2="{y0}" stroke="{C_LIVE}" stroke-dasharray="3 3" stroke-opacity=".5"/>')
    for name, col, key in series:
        pth = " ".join(f'{sx(c["x"]):.1f},{sy(c[key]):.1f}' for c in curve)
        s.append(f'<polyline points="{pth}" fill="none" stroke="{col}" stroke-width="2"/>')
        for c in curve:
            s.append(f'<circle cx="{sx(c["x"]):.1f}" cy="{sy(c[key]):.1f}" r="3" fill="{col}"/>')
        last = curve[-1]
        s.append(f'<text x="{sx(last["x"]):.1f}" y="{sy(last[key])-6:.1f}" fill="{col}" text-anchor="end" font-weight="600">{last[key]*100:.0f}%</text>')
    s.append(f'<text x="{(x0+x1)/2:.0f}" y="{H-3}" fill="{C_TXT}" text-anchor="middle" font-size="11">X = number of scoreline guesses allowed</text>')
    s.append('</svg>')
    return "".join(s)


OUTCOME_TXT = ["home win", "draw", "away win"]


def render_html(rows, mlive, mpre, muni, rel, ece, bands, emet, ebase, sdist,
                curve, topk, base_rank, mkt_cov=0):
    ov_l, ov_p = mlive["overall"], mpre["overall"]
    ex = emet["overall"]
    tk = next((c for c in curve if c["x"] == topk), curve[-1])
    base_str = ", ".join(f'{s[0]}-{s[1]}' for s in base_rank[:topk])
    has_market = mkt_cov > 0 and tk.get("market") is not None

    def stat(v, lbl, sub=""):
        return (f'<div class="stat"><div class="v">{v}</div>'
                f'<div class="l">{lbl}</div>{f"<div class=s>{sub}</div>" if sub else ""}</div>')

    def legend(series):
        return "".join(f'<span class="lg"><i style="background:{c}"></i>{n}</span>' for n, c, _ in series)

    # ------- Outcome (1X2) product table ------- #
    otr = []
    for r in rows:
        p = r["p_live"]
        res = f'{r["hg"]}-{r["ag"]}'
        pick = int(np.argmax(p))
        correct = pick == r["o"]
        mark = f'<span style="color:{C_GOOD}">correct</span>' if correct else f'<span style="color:{C_BAD}">miss</span>'
        otr.append(
            f'<tr><td>R{r["round"]}</td><td class="t">{r["home"]} v {r["away"]}</td>'
            f'<td>{p[0]*100:.0f}/{p[1]*100:.0f}/{p[2]*100:.0f}</td>'
            f'<td>{OUTCOME_TXT[pick]}</td>'
            f'<td>{OUTCOME_TXT[r["o"]]} <span style="color:{C_MUT}">({res})</span></td>'
            f'<td>{mark}</td></tr>')
    obody = "".join(otr)

    # ------- Exact-score product table ------- #
    etr = []
    for r in rows:
        pred = f'{r["mode"][0]}-{r["mode"][1]}'
        res = f'{r["hg"]}-{r["ag"]}'
        exact = r["mode"][0] == r["hg"] and r["mode"][1] == r["ag"]
        if exact:
            mk = f'<span style="color:{C_GOOD}">exact</span>'
        elif r["within1"]:
            mk = f'<span style="color:#ca8a04">±1</span>'
        else:
            mk = f'<span style="color:{C_BAD}">off</span>'
        oc = "✓" if r["out_from_score"] else "✗"
        occ = C_GOOD if r["out_from_score"] else C_BAD
        rk = r["actual_rank"]
        rk_txt = f'#{rk}' if rk else f'&gt;{TOPK}'
        rk_col = C_GOOD if (rk and rk <= topk) else C_MUT
        topx_str = ", ".join(f'{s[0]}-{s[1]}' for s in r["topk"][:topk])
        etr.append(
            f'<tr><td>R{r["round"]}</td><td class="t">{r["home"]} v {r["away"]}</td>'
            f'<td>{r["xg"][0]:.1f}–{r["xg"][1]:.1f}</td>'
            f'<td><b>{pred}</b> <span style="color:{C_MUT}">{r["p_mode"]*100:.0f}%</span></td>'
            f'<td class="t" style="color:{C_MUT};font-size:11px">{topx_str}</td>'
            f'<td>{res}</td><td>{mk}</td>'
            f'<td style="color:{rk_col}">{rk_txt}</td>'
            f'<td style="color:{occ}">{oc}</td></tr>')
    ebody = "".join(etr)

    # ------- Outcome charts ------- #
    rounds = ["R1", "R2", "R3"]
    rps_series = [("Pre-kickoff model", C_LIVE, [mlive["by_round"][k]["rps"] for k in (1, 2, 3)]),
                  ("Pre-tournament model", C_PRE, [mpre["by_round"][k]["rps"] for k in (1, 2, 3)])]
    metric_groups = ["RPS", "Log-loss"]
    metric_series = [
        ("Pre-kickoff", C_LIVE, [ov_l["rps"], ov_l["ll"]]),
        ("Pre-tournament", C_PRE, [ov_p["rps"], ov_p["ll"]]),
        ("Uniform 1/3", C_UNI, [muni["rps"], muni["ll"]]),
    ]

    # ------- Exact-score charts ------- #
    topx_series = [("Our model (top-X per match)", C_LIVE, "model"),
                   ("Base-rate prior (X most common)", C_PRE, "base")]
    if has_market:
        topx_series.insert(1, ("Market (bookmaker top-X)", C_GOOD, "market"))
    mkt_sub = f" · market {tk['market']*100:.0f}%" if has_market else ""
    if has_market:
        market_note = (
            f'<div class="note" style="background:#f0fdf4;border-color:#bbf7d0;color:#166534">'
            f'<b>Market benchmark active.</b> {mkt_cov}/{len(rows)} games have a '
            f'pre‑kickoff bookmaker line (1X2 + totals → market scoreline grid). '
            f'Only snapshots observed <b>strictly before kickoff</b> are used, so there '
            f'is no leakage. At X={topk} the model hits {tk["model"]*100:.0f}% vs the '
            f'market\u2019s {tk["market"]*100:.0f}% and the base‑rate prior\u2019s '
            f'{tk["base"]*100:.0f}%.</div>')
    else:
        market_note = (
            f'<div class="note" style="background:#eff6ff;border-color:#bfdbfe;color:#1e40af">'
            f'Why base‑rate and not a bookmaker line? A true <b>market</b> correct‑score '
            f'benchmark needs each game\u2019s <b>pre‑kickoff closing odds</b>. This project '
            f'never stored per‑match odds (only tournament‑level markets), and pulling them '
            f'now for finished games would leak the result. The base‑rate prior (historical '
            f'scoreline frequencies) is the honest, leakage‑free stand‑in. '
            f'<b>To activate the market line:</b> set <code>ODDS_API_KEY</code> and capture '
            f'per‑match odds (<code>match_odds_api.py</code>) before upcoming kickoffs — the '
            f'green Market curve then appears automatically.</div>')
    sd_groups = [d["score"] for d in sdist]
    sd_series = [("Model predicted", C_LIVE, [d["pred"] for d in sdist]),
                 ("Actually happened", C_GOOD, [d["act"] for d in sdist])]
    exround_groups = rounds
    exround_series = [("Exact hit", C_LIVE, [emet["by_round"][k]["exact"] * 100 for k in (1, 2, 3)]),
                      ("Within ±1", "#fbbf24", [emet["by_round"][k]["within1"] * 100 for k in (1, 2, 3)])]

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WC2026 — Match Prediction Backtest</title>
<style>
 :root{{--txt:{C_TXT};--mut:{C_MUT};--live:{C_LIVE};--good:{C_GOOD};--bad:{C_BAD};}}
 *{{box-sizing:border-box}}
 body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--txt);background:#f8fafc;line-height:1.5}}
 .wrap{{max-width:1060px;margin:0 auto;padding:32px 22px 64px}}
 h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 12px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}}
 p.sub{{color:var(--mut);margin:0 0 18px;font-size:14px}}
 .grid{{display:grid;gap:16px}} .g2{{grid-template-columns:1fr 1fr}} .g4{{grid-template-columns:repeat(4,1fr)}}
 @media(max-width:760px){{.g2,.g4{{grid-template-columns:1fr}}}}
 .card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px}}
 .card h3{{margin:0 0 10px;font-size:13px;font-weight:600;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}}
 .stat{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px}}
 .stat .v{{font-size:26px;font-weight:700}} .stat .l{{font-size:12px;color:var(--mut);margin-top:2px}} .stat .s{{font-size:11px;color:var(--good);margin-top:2px}}
 .lg{{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--mut);margin-right:14px}}
 .lg i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
 table{{width:100%;border-collapse:collapse;font-size:12.5px}}
 th,td{{padding:6px 8px;text-align:center;border-bottom:1px solid #f0f0f0}} td.t,th.t{{text-align:left}}
 th{{position:sticky;top:0;background:#fff;color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em;cursor:pointer}}
 .tblwrap{{max-height:520px;overflow:auto;border:1px solid #e5e7eb;border-radius:12px;background:#fff}}
 .note{{background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:12px 14px;font-size:13px;color:#9a3412}}
 code{{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}}
 .foot{{color:var(--mut);font-size:12px;margin-top:36px}}
 .tabs{{display:inline-flex;gap:6px;background:#eef2f7;border:1px solid #e5e7eb;border-radius:12px;padding:5px;margin:8px 0 4px}}
 .tab{{border:0;background:transparent;font:inherit;font-size:15px;font-weight:600;color:var(--mut);padding:9px 18px;border-radius:9px;cursor:pointer;transition:.15s}}
 .tab.on{{background:#fff;color:var(--txt);box-shadow:0 1px 3px rgba(0,0,0,.1)}}
 .tab .em{{margin-right:7px}}
 section.prod{{display:none}} section.prod.on{{display:block}}
 .lead{{background:linear-gradient(180deg,#fff,#f8fafc);border:1px solid #e5e7eb;border-left:4px solid var(--live);border-radius:12px;padding:14px 18px;margin:0 0 20px;font-size:14px}}
 .lead b{{color:var(--txt)}}
</style></head><body><div class="wrap">
<h1>Match‑prediction backtest — two products</h1>
<p class="sub">FIFA World Cup 2026 · {ov_l['n']} completed group‑stage matches. Every game is scored with the model reconstructed <b>exactly as it stood just before that game's kickoff</b> (per‑match calibration snapshot, incl. per‑round ELO updates). Source: internal sim · {datetime.now().strftime('%Y-%m-%d %H:%M')} local.</p>

<div class="tabs" role="tablist">
 <button class="tab on" data-p="outcome"><span class="em">🏆</span>Outcome predictor</button>
 <button class="tab" data-p="exact"><span class="em">🎯</span>Exact‑score predictor</button>
</div>

<!-- ============================ PRODUCT 1: OUTCOME ============================ -->
<section class="prod on" id="prod-outcome">
<div class="lead"><b>Product 1 — Who wins?</b> Predict the match result as <b>home win / draw / away win</b> (1X2). This is the sportsbook‑style call: forgiving of the exact scoreline, judged on getting the direction and the probabilities right.</div>

<div class="grid g4">
 {stat(f"{ov_l['hit']*100:.0f}%", "Outcome hit-rate", f"top pick correct · vs 33% chance")}
 {stat(f"{ov_l['rps']:.3f}", "RPS", f"vs {muni['rps']:.3f} uniform · lower better")}
 {stat(f"{ov_l['ll']:.3f}", "Log-loss", f"vs {muni['ll']:.3f} uniform · lower better")}
 {stat(f"{ece*100:.1f}%", "Calibration error (ECE)", f"lower = probabilities honest")}
</div>

<h2>Skill vs baselines</h2>
<div class="grid g2">
 <div class="card"><h3>Headline scoring rules</h3>{legend(metric_series)}
  {svg_grouped_bars("m", metric_groups, metric_series, "score (lower is better)")}</div>
 <div class="card"><h3>Calibration reliability — do our probabilities mean what they say?</h3>
  {svg_reliability(rel, ece)}
  <p style="font-size:12px;color:{C_MUT};margin:6px 0 0">Each point = a probability decile across all home/draw/away calls; on the diagonal = perfectly calibrated. Bubble size = sample count.</p></div>
</div>

<h2>Does updating ELO after each round help?</h2>
<p class="sub">Same games, two models: the <b style="color:{C_LIVE}">pre‑kickoff</b> model (per‑round EMA ELO + recalibration) vs the <b style="color:{C_PRE}">frozen pre‑tournament</b> model. Lower RPS = sharper, better‑calibrated forecasts.</p>
<div class="grid g2">
 <div class="card"><h3>RPS by matchday</h3>{legend(rps_series)}
  {svg_grouped_bars("r", rounds, rps_series, "RPS (lower is better)")}</div>
 <div class="card"><h3>Favorite reliability — predicted vs actual win rate</h3>
  <span class="lg"><i style="background:{C_MUT}"></i>predicted (band mid)</span><span class="lg"><i style="background:{C_GOOD}"></i>actual correct</span>
  {svg_confbands(bands)}
  <p style="font-size:12px;color:{C_MUT};margin:6px 0 0">Grouped by how confident the top pick was. Green ≈ dashed outline means well‑calibrated confidence.</p></div>
</div>

<h2>Every match — outcome call vs result</h2>
<p class="sub">Probabilities shown home/draw/away (%). "Call" is the highest‑probability outcome. Click a header to sort.</p>
<div class="tblwrap"><table class="sortbl"><thead><tr>
 <th>Rd</th><th class="t">Match</th><th>H/D/A %</th><th>Call</th><th>Actual</th><th>Result</th>
</tr></thead><tbody>{obody}</tbody></table></div>
</section>

<!-- ============================ PRODUCT 2: EXACT SCORE ============================ -->
<section class="prod" id="prod-exact">
<div class="lead"><b>Product 2 — What's the exact score?</b> Offer the <b>top‑X most‑likely exact scorelines</b> and count it a hit if any one lands (X is configurable; X=1 is the single best guess). A far harder bet than 1X2, so the fair yardstick is a <b>leakage‑free base‑rate prior</b> — the X globally most common scorelines — not 50%.</div>

<div class="grid g4">
 {stat(f"{tk['model']*100:.0f}%", f"Top-{topk} hit-rate", f"one of {topk} guesses right · base {tk['base']*100:.0f}%{mkt_sub}")}
 {stat(f"{ex['exact']*100:.0f}%", "Exact hit-rate (X=1)", f"single best score right")}
 {stat(f"{ex['within1']*100:.0f}%", "Within ±1 goal", f"each side within one goal")}
 {stat(f"{ex['outacc']*100:.0f}%", "Right result from score", f"predicted score's W/D/L correct")}
</div>

<h2>Top‑X hit‑rate vs the market/base‑rate benchmark</h2>
<div class="grid g2">
 <div class="card"><h3>Hit-rate when allowed X scoreline guesses</h3>{legend(topx_series)}
  {svg_topx_lines(curve, topx_series, khi=topk)}
  <p style="font-size:12px;color:{C_MUT};margin:6px 0 0">Model picks each match's own top‑X grid cells; the <b>base‑rate prior</b> always guesses the X most common historical scorelines (X={topk}: {base_str}). The gap = context skill. Dashed line marks the configured X={topk}.</p></div>
 <div class="card"><h3>Predicted vs actual scoreline mix</h3>{legend(sd_series)}
  {svg_grouped_bars("s", sd_groups, sd_series, "number of matches", fmt="{:.0f}")}
  <p style="font-size:12px;color:{C_MUT};margin:6px 0 0">The model leans to tidy low scores (1‑0, 1‑1, 2‑1); reality has a fatter tail of higher/odd scores it can't nail.</p></div>
</div>
{market_note}

<h2>How the exact-score product does over time</h2>
<div class="grid g2">
 <div class="card"><h3>Exact & within-±1 hit-rate by matchday</h3>{legend(exround_series)}
  {svg_grouped_bars("e", exround_groups, exround_series, "hit-rate (%)", fmt="{:.0f}")}</div>
 <div class="card"><h3>Is the model's own confidence honest?</h3>
  <div style="display:flex;gap:24px;align-items:baseline;margin:8px 0">
   <div><div style="font-size:30px;font-weight:700;color:{C_LIVE}">{ex['pmode']*100:.0f}%</div><div style="font-size:12px;color:{C_MUT}">avg probability it assigned to its top score</div></div>
   <div><div style="font-size:30px;font-weight:700">{ex['exact']*100:.0f}%</div><div style="font-size:12px;color:{C_MUT}">how often that top score actually hit</div></div>
  </div>
  <p style="font-size:12px;color:{C_MUT};margin:6px 0 0">If these two are close, the model isn't over‑ or under‑selling its single‑score confidence. A typical top‑score probability is only ~1‑in‑8, which is why exact prediction is intrinsically hard.</p></div>
</div>

<h2>Every match — exact-score prediction vs result</h2>
<p class="sub">"Pred" is the top‑1 scoreline (+prob); "Top‑{topk}" lists the {topk} guesses offered. <span style="color:{C_GOOD}">exact</span> = top‑1 spot on, <span style="color:#ca8a04">±1</span> = each side within a goal. "Rank" = where the real score sat in the model's ranking (<span style="color:{C_GOOD}">green</span> = inside top‑{topk}). Last column = did top‑1 imply the right winner. Click a header to sort.</p>
<div class="tblwrap"><table class="sortbl"><thead><tr>
 <th>Rd</th><th class="t">Match</th><th>xG</th><th>Pred (prob)</th><th class="t">Top-{topk} guesses</th><th>Actual</th><th>Top-1 acc</th><th>Rank</th><th>Result?</th>
</tr></thead><tbody>{ebody}</tbody></table></div>
</section>

<div class="note">Honest caveats: only {ov_l['n']} matches (wide error bars — treat gaps &lt; ~0.02 RPS as noise). The EMA is gentle (35% live weight) and the prior is already market‑blended, so pre‑kickoff vs pre‑tournament differences are expected to be small. The real product bar is <b>beating the closing market line</b>, which needs per‑match moneyline odds we don't yet store. Group stage skews toward mismatches, so knockout skill will look harder.</div>

<p class="foot">Methodology: outcome probabilities and exact scores come from the Dixon‑Coles corrected scoreline grid of the calibrated Poisson model. RPS = ranked probability score (ordinal H/D/A). Log‑loss = −ln P(actual). Grid log‑loss = −ln P(exact scoreline). ECE = expected calibration error. Pre‑kickoff model = latest <code>calibration_&lt;ts&gt;.json</code> snapshot with timestamp ≤ kickoff.</p>

<script>
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{{
 document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));
 const p=t.dataset.p;
 document.querySelectorAll('section.prod').forEach(s=>s.classList.toggle('on',s.id==='prod-'+p));
 window.scrollTo({{top:0,behavior:'smooth'}});
}});
document.querySelectorAll('table.sortbl').forEach(tbl=>{{
 tbl.querySelectorAll('th').forEach((th,i)=>{{th.onclick=()=>{{
  const tb=tbl.tBodies[0];const rows=[...tb.rows];
  const asc=th._asc=!th._asc;
  rows.sort((a,b)=>{{const x=a.cells[i].innerText,y=b.cells[i].innerText;
   const nx=parseFloat(x),ny=parseFloat(y);
   if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;
   return asc?x.localeCompare(y):y.localeCompare(x);}});
  rows.forEach(r=>tb.appendChild(r));}};}});
}});
</script>
</div></body></html>"""
    return html


def main():
    import argparse
    ap = argparse.ArgumentParser(description="WC2026 match-prediction backtest")
    ap.add_argument("--topk", type=int, default=3,
                    help="X for the headline top-X exact-score hit-rate (default 3)")
    ap.add_argument("--maxx", type=int, default=8,
                    help="max X plotted on the top-X curve (default 8)")
    args = ap.parse_args()
    topk = max(1, min(args.topk, TOPK))
    maxx = max(topk, min(args.maxx, TOPK))

    rows, base_rank = build()
    mlive = metrics(rows, "p_live")
    mpre = metrics(rows, "p_pre")
    muni = uniform_metrics(rows)
    rel, ece = reliability(rows, "p_live")
    bands = conf_bands(rows, "p_live")
    emet = exact_metrics(rows)
    ebase = exact_baselines(rows)
    sdist = scoreline_dist(rows)
    curve, mkt_cov = topx_curve(rows, base_rank, maxx)
    html = render_html(rows, mlive, mpre, muni, rel, ece, bands, emet, ebase,
                       sdist, curve, topk, base_rank, mkt_cov)
    out = ROOT / "backtest_report.html"
    out.write_text(html, encoding="utf-8")
    ex = emet["overall"]
    tk = next(c for c in curve if c["x"] == topk)
    print(f"n={mlive['overall']['n']}")
    print(f"OUTCOME  RPS={mlive['overall']['rps']:.4f} LL={mlive['overall']['ll']:.4f} "
          f"hit={mlive['overall']['hit']*100:.1f}% ECE={ece*100:.2f}%")
    print(f"EXACT    exact(X=1)={ex['exact']*100:.1f}% within1={ex['within1']*100:.1f}% "
          f"out_from_score={ex['outacc']*100:.1f}%")
    print(f"TOP-X    " + " ".join(f'X{c["x"]}:{c["model"]*100:.0f}%/{c["base"]*100:.0f}%'
                                   for c in curve) + "  (model/base)")
    mk = f" market={tk['market']*100:.1f}%" if tk.get("market") is not None else ""
    print(f"HEADLINE top-{topk}: model={tk['model']*100:.1f}% base={tk['base']*100:.1f}%{mk}")
    print(f"base-rate top-{maxx}: " + ", ".join(f'{s[0]}-{s[1]}' for s in base_rank[:maxx]))
    print(f"market coverage: {mkt_cov}/{len(rows)} games with pre-kickoff line")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
