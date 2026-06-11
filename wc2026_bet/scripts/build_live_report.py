"""Stage 5 - render the live win-probability report (report/live.html).

Self-contained dark HTML: a sortable probability table plus inline-SVG
visualizations driven by results/live_latest.json (and every historical
data/live/win_probabilities_*.json for the over-time race).

Usage: python3 scripts/build_live_report.py [--me "טלסי"]
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import DATA_LIVE, REPORT_DIR, RESULTS_DIR

GOLD, SILVER, BRONZE = "#f5c518", "#cbd5e1", "#b08d57"
ACCENT, INK, MUT = "#38bdf8", "#e2e8f0", "#94a3b8"
GRID = "#1e293b"


def clip(s, n=22):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# Perceptually-uniform "viridis" stops (dark blue -> teal -> green -> yellow):
# reads far better than single-hue alpha on a dark background.
_VIRIDIS = [(0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)),
            (0.75, (94, 201, 98)), (1.0, (253, 231, 37))]


def viridis(t: float) -> str:
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    for (t0, c0), (t1, c1) in zip(_VIRIDIS, _VIRIDIS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            r = c0[0] + (c1[0] - c0[0]) * f
            g = c0[1] + (c1[1] - c0[1]) * f
            b = c0[2] + (c1[2] - c0[2]) * f
            return f"rgb({r:.0f},{g:.0f},{b:.0f})"
    return "rgb(253,231,37)"


# --------------------------------------------------------------------------- #
# SVG primitives
# --------------------------------------------------------------------------- #
def svg_open(w, h):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
            f'style="max-width:{w}px" font-family="Inter,system-ui,sans-serif">')


def svg_stacked_hbar(rows, w=860, rowh=30, pad_l=190, pad_r=70, vmax=None):
    """rows = [(name, [(value,color,tip),...], total, highlight)]."""
    vmax = vmax or max((r[2] for r in rows), default=1) * 1.02
    h = len(rows) * rowh + 30
    sc = (w - pad_l - pad_r) / vmax if vmax else 1
    out = [svg_open(w, h)]
    for i, (name, segs, total, hl) in enumerate(rows):
        y = 18 + i * rowh
        fill = "#f8fafc" if hl else INK
        weight = 700 if hl else 400
        out.append(f'<text x="{pad_l-8}" y="{y+15}" text-anchor="end" '
                   f'font-size="12.5" fill="{fill}" font-weight="{weight}">{escape(clip(name))}</text>')
        x = pad_l
        for val, color, tip in segs:
            bw = val * sc
            if bw > 0.4:
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{bw:.1f}" height="{rowh-10}" '
                           f'rx="2" fill="{color}"><title>{escape(tip)}</title></rect>')
            x += bw
        out.append(f'<text x="{x+6:.1f}" y="{y+15}" font-size="12" fill="{MUT}">{total:.0f}</text>')
        if hl:
            out.append(f'<rect x="2" y="{y-3}" width="{w-4}" height="{rowh-4}" rx="4" '
                       f'fill="none" stroke="{ACCENT}" stroke-width="1.5" opacity="0.7"/>')
    out.append("</svg>")
    return "".join(out)


def svg_fan(rows, w=880, rowh=26, pad_l=190, pad_r=50):
    """rows = [(name, p10, p50, p90, current, highlight)]."""
    lo = min(r[1] for r in rows)
    hi = max(r[3] for r in rows)
    rng = (hi - lo) or 1
    h = len(rows) * rowh + 44
    sc = (w - pad_l - pad_r) / rng
    X = lambda v: pad_l + (v - lo) * sc
    out = [svg_open(w, h)]
    # axis ticks
    for k in range(5):
        v = lo + rng * k / 4
        x = X(v)
        out.append(f'<line x1="{x:.1f}" y1="14" x2="{x:.1f}" y2="{h-22}" stroke="{GRID}"/>')
        out.append(f'<text x="{x:.1f}" y="{h-8}" text-anchor="middle" font-size="11" fill="{MUT}">{v:.0f}</text>')
    for i, (name, p10, p50, p90, cur, hl) in enumerate(rows):
        y = 22 + i * rowh
        fill = "#f8fafc" if hl else INK
        out.append(f'<text x="{pad_l-8}" y="{y+4}" text-anchor="end" font-size="12" '
                   f'fill="{fill}" font-weight="{700 if hl else 400}">{escape(clip(name))}</text>')
        out.append(f'<line x1="{X(p10):.1f}" y1="{y}" x2="{X(p90):.1f}" y2="{y}" '
                   f'stroke="{ACCENT if hl else "#475569"}" stroke-width="{5 if hl else 4}" '
                   f'stroke-linecap="round" opacity="0.85"><title>{escape(name)}: P10 {p10:.0f} / P50 {p50:.0f} / P90 {p90:.0f}</title></line>')
        out.append(f'<circle cx="{X(p50):.1f}" cy="{y}" r="3.4" fill="#fff"/>')
        if cur is not None:
            out.append(f'<line x1="{X(cur):.1f}" y1="{y-7}" x2="{X(cur):.1f}" y2="{y+7}" '
                       f'stroke="{GOLD}" stroke-width="2"><title>current locked: {cur:.0f}</title></line>')
    out.append("</svg>")
    return "".join(out)


def svg_heatstrips(rows, N, w=940, rowh=16, pad_l=190):
    """rows = [(name, rank_hist(list len N), highlight)] -> heat strip per entry.

    Each row is normalized to its own modal probability so the *shape* of where
    that entry lands is legible; colour uses a perceptual viridis ramp.
    """
    cellw = (w - pad_l - 12) / N
    top = 22
    h = len(rows) * rowh + top + 10
    out = [svg_open(w, h)]
    for p in (1, 10, 20, 30, 40, 50, N):
        x = pad_l + (p - 0.5) * cellw
        out.append(f'<text x="{x:.1f}" y="13" text-anchor="middle" font-size="10" fill="{MUT}">{p}</text>')
    out.append(f'<text x="{pad_l-8}" y="13" text-anchor="end" font-size="9.5" fill="{MUT}">finish rank →</text>')
    for i, (name, hist, hl) in enumerate(rows):
        y = top + i * rowh
        tot = sum(hist) or 1
        mx = max(hist) / tot or 1
        for p in range(N):
            pr = hist[p] / tot
            if pr <= 0:
                continue
            t = (pr / mx) ** 0.65
            out.append(f'<rect x="{pad_l + p*cellw:.1f}" y="{y}" width="{cellw+0.6:.1f}" '
                       f'height="{rowh-2}" fill="{viridis(t)}"><title>{escape(name)}: '
                       f'P(rank {p+1}) = {pr*100:.1f}%</title></rect>')
        out.append(f'<text x="{pad_l-8}" y="{y+rowh-5}" text-anchor="end" font-size="10" '
                   f'fill="{"#f8fafc" if hl else INK}" font-weight="{700 if hl else 400}">{escape(clip(name))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_colorbar(w=260, h=16, label_lo="rare", label_hi="entry's most-likely rank"):
    out = [svg_open(w + 4, h + 20)]
    out.append(f'<defs><linearGradient id="vir" x1="0" x2="1">'
               + "".join(f'<stop offset="{int(t*100)}%" stop-color="{viridis(t)}"/>'
                         for t in (0, .25, .5, .75, 1)) + '</linearGradient></defs>')
    out.append(f'<rect x="0" y="0" width="{w}" height="{h}" rx="3" fill="url(#vir)"/>')
    out.append(f'<text x="0" y="{h+15}" font-size="10" fill="{MUT}">{escape(label_lo)}</text>')
    out.append(f'<text x="{w}" y="{h+15}" text-anchor="end" font-size="10" fill="{MUT}">{escape(label_hi)}</text>')
    out.append("</svg>")
    return "".join(out)


def _svg_fixed(w, h):
    return (f'<svg viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'style="display:block" font-family="Inter,system-ui,sans-serif">')


def svg_matrix(champs, p_title, entry_names, getp, summary_cols=None,
               cell=50, pad_l=170, head_h=120):
    """Champion-conditional grid as a fixed header + a separately-scrollable body
    so the column labels stay visible while the entry rows scroll.

    ``summary_cols`` = [(header, {entry: value}, "r,g,b"), ...] rendered to the
    right of the champion columns (e.g. overall P(1st), P(in money), P(last)).
    Returns (header_svg, body_svg, width).
    """
    summary_cols = summary_cols or []
    gap, scol = 74, 62
    C = len(champs)
    grid_r = pad_l + C * cell
    sum_x0 = grid_r + gap
    wtot = sum_x0 + len(summary_cols) * scol + 28
    mx = max((getp(c, e) for c in champs for e in entry_names), default=1) or 1
    smax = [max((vals.get(e, 0) for e in entry_names), default=1) or 1
            for _, vals, _ in summary_cols]

    # ---- header (champion labels + title % + summary headers) ---- #
    H = [_svg_fixed(wtot, head_h)]
    for j, c in enumerate(champs):
        x = pad_l + j * cell + cell / 2
        by = head_h - 30
        H.append(f'<text x="{x:.1f}" y="{by}" transform="rotate(-40 {x:.1f} {by})" '
                 f'font-size="12" fill="{INK}">{escape(c)}</text>')
        H.append(f'<text x="{x:.1f}" y="{head_h-12}" text-anchor="middle" font-size="9.5" '
                 f'fill="{MUT}">{p_title.get(c,0)*100:.0f}%</text>')
    H.append(f'<text x="{pad_l-8}" y="{head_h-12}" text-anchor="end" font-size="10" fill="{MUT}">win if champion →</text>')
    for k, (lbl, _vals, rgb) in enumerate(summary_cols):
        x = sum_x0 + k * scol + scol / 2
        by = head_h - 30
        H.append(f'<text x="{x:.1f}" y="{by}" transform="rotate(-40 {x:.1f} {by})" '
                 f'font-size="12" font-weight="700" fill="rgb({rgb})">{escape(lbl)}</text>')
        H.append(f'<text x="{x:.1f}" y="{head_h-12}" text-anchor="middle" font-size="9" fill="{MUT}">overall</text>')
    H.append("</svg>")

    # ---- body (one row per entry) ---- #
    bh = len(entry_names) * 24 + 6
    B = [_svg_fixed(wtot, bh)]
    for i, e in enumerate(entry_names):
        y = i * 24 + 2
        B.append(f'<text x="{pad_l-8}" y="{y+15}" text-anchor="end" font-size="11.5" fill="{INK}">{escape(clip(e,20))}</text>')
        for j, c in enumerate(champs):
            x = pad_l + j * cell
            p = getp(c, e)
            inten = (p / mx) ** 0.6 if mx else 0
            col = f'rgba(245,197,24,{0.06 + 0.9*inten:.3f})' if p > 0 else "rgba(148,163,184,0.05)"
            B.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell-3}" height="21" rx="3" '
                     f'fill="{col}"><title>{escape(e)} wins if {escape(c)} champion: {p*100:.1f}%</title></rect>')
            if p >= 0.04:
                B.append(f'<text x="{x+(cell-3)/2:.1f}" y="{y+15:.1f}" text-anchor="middle" '
                         f'font-size="10" fill="#0b1220" font-weight="600">{p*100:.0f}</text>')
        for k, (lbl, vals, rgb) in enumerate(summary_cols):
            x = sum_x0 + k * scol
            v = vals.get(e, 0.0)
            inten = (v / smax[k]) ** 0.6 if smax[k] else 0
            B.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{scol-4}" height="21" rx="3" '
                     f'fill="rgba({rgb},{0.10 + 0.8*inten:.3f})" stroke="rgba({rgb},0.35)" stroke-width="0.6">'
                     f'<title>{escape(e)} {escape(lbl)}: {v*100:.2f}%</title></rect>')
            B.append(f'<text x="{x+(scol-4)/2:.1f}" y="{y+15:.1f}" text-anchor="middle" '
                     f'font-size="10" fill="#e2e8f0" font-weight="600">{v*100:.1f}%</text>')
    B.append("</svg>")
    return "".join(H), "".join(B), wtot


def svg_bump(rows, w=860, h=None, pad=46):
    """rows = [(name, cur_rank, proj_rank, highlight)] -> two-column slope chart."""
    n = len(rows)
    h = h or n * 17 + 50
    xL, xR = pad + 130, w - pad - 130
    rmax = max(max(r[1], r[2]) for r in rows)
    Y = lambda r: 30 + (r - 1) / (rmax - 1 or 1) * (h - 60)
    out = [svg_open(w, h)]
    out.append(f'<text x="{xL}" y="18" text-anchor="middle" font-size="12" fill="{MUT}">current rank</text>')
    out.append(f'<text x="{xR}" y="18" text-anchor="middle" font-size="12" fill="{MUT}">projected (exp.) rank</text>')
    for name, cr, pr, hl in rows:
        y1, y2 = Y(cr), Y(pr)
        col = ACCENT if hl else ("#64748b" if pr >= cr else "#34d399")
        sw = 2.6 if hl else 1.4
        out.append(f'<line x1="{xL}" y1="{y1:.1f}" x2="{xR}" y2="{y2:.1f}" stroke="{col}" '
                   f'stroke-width="{sw}" opacity="{0.95 if hl else 0.5}"><title>{escape(name)}: {cr:.0f} -> {pr:.0f}</title></line>')
        out.append(f'<circle cx="{xL}" cy="{y1:.1f}" r="3" fill="{col}"/>')
        out.append(f'<circle cx="{xR}" cy="{y2:.1f}" r="3" fill="{col}"/>')
        if hl:
            out.append(f'<text x="{xL-8}" y="{y1+4:.1f}" text-anchor="end" font-size="11" fill="#f8fafc" font-weight="700">{escape(clip(name,16))}</text>')
            out.append(f'<text x="{xR+8}" y="{y2+4:.1f}" font-size="11" fill="#f8fafc" font-weight="700">{escape(clip(name,16))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_lines(timestamps, series, w=860, h=300, pad=52):
    """series = [(name, [values aligned to timestamps], color, highlight)]."""
    n = len(timestamps)
    allv = [v for _, vs, _, _ in series for v in vs if v is not None]
    vmax = max(allv) * 1.05 if allv else 1
    X = lambda i: pad + (i) / (n - 1 or 1) * (w - 2 * pad)
    Y = lambda v: h - pad - v / (vmax or 1) * (h - 2 * pad)
    out = [svg_open(w, h)]
    for k in range(5):
        v = vmax * k / 4
        y = Y(v)
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{pad-6}" y="{y+4:.1f}" text-anchor="end" font-size="10" fill="{MUT}">{v:.0f}</text>')
    for i, ts in enumerate(timestamps):
        out.append(f'<text x="{X(i):.1f}" y="{h-pad+16}" text-anchor="middle" font-size="9.5" fill="{MUT}">{escape(ts[5:])}</text>')
    for name, vs, color, hl in series:
        pts = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs) if v is not None]
        if len(pts) >= 2:
            out.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
                       f'stroke-width="{3 if hl else 1.8}" opacity="{1 if hl else 0.8}"/>')
        for i, v in enumerate(vs):
            if v is not None:
                out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{3.4 if hl else 2.4}" fill="{color}"><title>{escape(name)} @ {escape(timestamps[i])}: {v:.0f}</title></circle>')
        if hl and pts:
            li = max(i for i, v in enumerate(vs) if v is not None)
            out.append(f'<text x="{X(li)+6:.1f}" y="{Y(vs[li])-6:.1f}" font-size="11" fill="{color}" font-weight="700">{escape(clip(name,14))}</text>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# Report assembly
# --------------------------------------------------------------------------- #
def pct(x):
    return f"{x*100:.1f}%"


def groups_block(d) -> str:
    """Group-stage standings cards: played / points / GD / qualify% (P reach R32).
    Top two of each group (by the run_live_update sort) are highlighted."""
    groups = d.get("groups") or {}
    if not groups:
        return ""
    cards = []
    for g in sorted(groups):
        rows = []
        for i, t in enumerate(groups[g]):
            cls = ' class="qual"' if i < 2 else ""
            rows.append(
                f'<tr{cls}><td class="gt">{escape(t["team"])}</td>'
                f'<td>{t["played"]}</td><td>{t["points"]}</td>'
                f'<td>{t["gd"]:+d}</td>'
                f'<td class="gq">{t["p_advance"]*100:.0f}%</td></tr>')
        cards.append(
            f'<div class="gcard"><h3>Group {g}</h3>'
            f'<table class="gtbl"><thead><tr><th>Team</th><th>P</th>'
            f'<th>Pts</th><th>GD</th><th>Qualify</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')
    return (
        '<div class="card"><h2>Group-stage standings &amp; qualification odds</h2>'
        '<p class="sub">Per group: matches played (P), points (Pts), goal '
        'difference (GD) and the simulated probability of reaching the Round of '
        '32 (Qualify). The two highlighted teams are each group\'s leading '
        'qualifiers; standings fill in automatically as real results land.</p>'
        f'<div class="ggrid">{"".join(cards)}</div></div>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", default="", help="optional entry nickname to highlight "
                    "(left blank by default so the report is a neutral, shareable analysis)")
    ap.add_argument("--data", default=str(RESULTS_DIR / "live_latest.json"))
    args = ap.parse_args()
    me = args.me

    d = json.loads(Path(args.data).read_text())
    ents = d["entries"]                       # already sorted by exp_winnings
    N = d["n_entries"]
    by_name = {e["name"]: e for e in ents}
    mine = by_name.get(me)

    # ---------- header ---------- #
    st = d["state"]
    state_line = (f"{st['group_played']}/72 group matches" +
                  (", group stage complete" if st["group_stage_complete"] else "") +
                  f", {st['ko_played']} knockout matches played")
    pre = st["group_played"] == 0 and st["ko_played"] == 0

    # ---------- table ---------- #
    head = [("#", "rank"), ("Entry", "name"), ("Now", "current_points"),
            ("Exp. ₪", "exp_winnings"), ("P(1st)", "P_first"),
            ("In money", "P_top2"), ("P(3rd)", "P_third"), ("P(last)", "P_last"),
            ("Exp. pts", "exp_points"), ("Exp. rank", "exp_rank"), ("Δ₪", "d_exp_winnings")]
    th = "".join(f'<th data-k="{k}" onclick="sortBy(\'{k}\')">{escape(lbl)}</th>' for lbl, k in head)
    trs = []
    for i, e in enumerate(ents, 1):
        hl = e["name"] == me
        dval = e.get("d_exp_winnings")
        dcell = "—" if dval is None else (f'<span style="color:#34d399">+{dval:.0f}</span>' if dval > 0
                                          else (f'<span style="color:#f87171">{dval:.0f}</span>' if dval < 0 else "0"))
        cells = [
            f'<td>{i}</td>',
            f'<td class="nm">{escape(e["name"])}</td>',
            f'<td>{e["current_points"]:.0f}</td>',
            f'<td class="ev">{e["exp_winnings"]:.0f}</td>',
            f'<td>{pct(e["P_first"])}</td>',
            f'<td>{pct(e["P_top2"])}</td>',
            f'<td>{pct(e["P_third"])}</td>',
            f'<td>{pct(e["P_last"])}</td>',
            f'<td>{e["exp_points"]:.1f}</td>',
            f'<td>{e["exp_rank"]:.1f}</td>',
            f'<td>{dcell}</td>',
        ]
        dattrs = " ".join(f'data-{k}="{e.get(k, 0) if e.get(k) is not None else 0}"' for _, k in head if k != "name")
        trs.append(f'<tr class="{"me" if hl else ""}" data-name="{escape(e["name"])}" {dattrs}>' + "".join(cells) + "</tr>")
    table = f'<table id="probtable"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'

    # ---------- EV decomposition (top 18) ---------- #
    topN = ents[:18]
    ev_rows = []
    for e in topN:
        segs = [(e["P_first"] * 1800, GOLD, f'P(1st) {pct(e["P_first"])} ×1800'),
                (e["P_second"] * 750, SILVER, f'P(2nd) {pct(e["P_second"])} ×750'),
                ((e["P_third"] + e["P_last"]) * 50, BRONZE,
                 f'refund (3rd+last) {pct(e["P_third"]+e["P_last"])} ×50')]
        ev_rows.append((e["name"], segs, e["exp_winnings"], e["name"] == me))
    ev_svg = svg_stacked_hbar(ev_rows)

    # ---------- final-points fan (top 15) ---------- #
    fan_rows = [(e["name"], e["score_p10"], e["score_p50"], e["score_p90"],
                 e["current_points"] if not pre else None, e["name"] == me)
                for e in ents[:15]]
    fan_svg = svg_fan(fan_rows)

    # ---------- rank-distribution heat strips (all entries) ---------- #
    strip_rows = [(e["name"], e["rank_hist"], e["name"] == me) for e in ents]
    strip_svg = svg_heatstrips(strip_rows, N)

    # ---------- champion-conditional matrix (top 14 entries) ---------- #
    cm = d["champion_matrix"]
    champs = cm["champions"]
    cm_entries = [e["name"] for e in ents]
    getp = lambda c, e: cm["matrix"].get(c, {}).get(e, 0.0)
    summary_cols = [
        ("P(1st)", {e["name"]: e["P_first"] for e in ents}, "56,189,248"),
        ("In money", {e["name"]: e["P_top2"] for e in ents}, "52,211,153"),
        ("P(last)", {e["name"]: e["P_last"] for e in ents}, "248,113,113"),
    ]
    cm_header, cm_body, cm_w = svg_matrix(champs, cm["p_title"], cm_entries, getp,
                                          summary_cols=summary_cols)
    cm_body_maxh = 18 * 24 + 6   # show ~18 rows, scroll for the rest

    # ---------- group-stage standings + qualify% ---------- #
    groups_blk = groups_block(d)

    # ---------- projected vs current bump ---------- #
    # current rank from site (ties -> stable); projected = exp_rank ordering
    cur_rank = {e["name"]: (e.get("current_rank") or (i + 1)) for i, e in enumerate(sorted(ents, key=lambda x: -x["current_points"]))}
    proj_order = sorted(ents, key=lambda e: e["exp_rank"])
    proj_rank = {e["name"]: i + 1 for i, e in enumerate(proj_order)}
    bump_rows = sorted([(e["name"], cur_rank[e["name"]], proj_rank[e["name"]], e["name"] == me) for e in ents],
                       key=lambda r: r[2])
    bump_svg = svg_bump(bump_rows)

    # ---------- win-prob race over time ---------- #
    hist_files = sorted(DATA_LIVE.glob("win_probabilities_*.json"))
    timestamps, snaps = [], []
    for f in hist_files:
        try:
            j = json.loads(f.read_text())
            timestamps.append(j["timestamp"])
            snaps.append({e["name"]: e for e in j["entries"]})
        except Exception:
            continue
    race_block = ""
    if len(timestamps) >= 2:
        palette = ["#38bdf8", "#f5c518", "#34d399", "#f472b6", "#a78bfa", "#fb923c", "#22d3ee", "#facc15"]
        leaders = [e["name"] for e in ents[:8]]
        if me and me not in leaders:
            leaders = leaders[:7] + [me]
        series = []
        for k, nm in enumerate(leaders):
            vs = [snap.get(nm, {}).get("exp_winnings") for snap in snaps]
            series.append((nm, vs, palette[k % len(palette)], nm == me))
        race_block = (f'<div class="card"><h2>Win-probability race over time</h2>'
                      f'<p class="sub">Expected winnings (₪) per update for the current top-8 entries, '
                      f'one line per snapshot.</p>{svg_lines(timestamps, series)}</div>')
    else:
        race_block = (f'<div class="card"><h2>Win-probability race over time</h2>'
                      f'<p class="sub">Only one snapshot so far ({escape(timestamps[0]) if timestamps else "—"}). '
                      f'The line chart populates as you re-run <code>run_live_update.py</code> at later timestamps.</p></div>')

    # ---------- your-entry panel ---------- #
    me_block = ""
    if mine:
        rank_now = next((i + 1 for i, e in enumerate(ents) if e["name"] == me), None)
        pk = mine["picks"]
        # best champion to root for
        best_champ = max(champs, key=lambda c: getp(c, me)) if champs else None
        picks_html = "".join(
            f'<div class="pick"><span>{escape(lbl)}</span><b>{escape(pk[key])}</b></div>'
            for lbl, key in [("Tier A", "tierA"), ("Tier B", "tierB"), ("Tier C", "tierC"),
                             ("Tier D", "tierD"), ("Scoring", "scoring"),
                             ("Conceding", "conceding"), ("Top scorer", "top_scorer")])
        me_block = f'''<div class="card me-card">
          <h2>Your entry · {escape(me)}</h2>
          <div class="kpis">
            <div class="kpi"><div class="v">{rank_now}/{N}</div><div class="l">EV rank (pool)</div></div>
            <div class="kpi"><div class="v">₪{mine["exp_winnings"]:.0f}</div><div class="l">expected winnings</div></div>
            <div class="kpi"><div class="v">{pct(mine["P_first"])}</div><div class="l">P(win pool)</div></div>
            <div class="kpi"><div class="v">{pct(mine["P_top2"])}</div><div class="l">P(in the money)</div></div>
            <div class="kpi"><div class="v">{pct(mine["P_last"])}</div><div class="l">P(last → refund)</div></div>
            <div class="kpi"><div class="v">{mine["exp_points"]:.1f}</div><div class="l">expected final pts</div></div>
          </div>
          <div class="picks">{picks_html}</div>
          {f'<p class="sub">Root for <b>{escape(best_champ)}</b> to win the World Cup — that maximises your pool-win odds ({pct(getp(best_champ, me))} given that champion).</p>' if best_champ else ''}
        </div>'''

    # ---------- compose ---------- #
    css = """
    :root{--accent:#38bdf8}
    *{box-sizing:border-box}
    body{margin:0;background:#0b1220;color:#e2e8f0;font-family:Inter,system-ui,Segoe UI,sans-serif;line-height:1.5}
    .wrap{max-width:1120px;margin:0 auto;padding:28px 22px 80px}
    h1{font-size:1.7rem;margin:0 0 4px}
    h2{font-size:1.15rem;margin:0 0 6px}
    .sub{color:#94a3b8;font-size:.86rem;margin:.2rem 0 1rem}
    .meta{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 22px}
    .chip{background:#111c30;border:1px solid #1e293b;border-radius:999px;padding:6px 14px;font-size:.8rem;color:#cbd5e1}
    .chip b{color:#fff}
    .card{background:#0f1a2e;border:1px solid #1e293b;border-radius:14px;padding:20px 22px;margin:16px 0;box-shadow:0 2px 14px rgba(0,0,0,.25)}
    table{border-collapse:collapse;width:100%;font-size:.83rem}
    th,td{padding:7px 9px;text-align:right;border-bottom:1px solid #18243b;white-space:nowrap}
    th:nth-child(2),td:nth-child(2){text-align:left}
    th{cursor:pointer;color:#94a3b8;font-weight:600;position:sticky;top:0;background:#0f1a2e;user-select:none}
    th:hover{color:#fff}
    td.nm{font-weight:600;color:#f1f5f9}
    td.ev{color:#f5c518;font-weight:700}
    tbody tr:hover{background:#13233c}
    tr.me{background:rgba(56,189,248,.12)}
    tr.me td.nm{color:#7dd3fc}
    .tablewrap{max-height:560px;overflow:auto;border-radius:10px}
    .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.78rem;color:#94a3b8;margin:6px 0 12px}
    .legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:middle}
    .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:8px 0 16px}
    .kpi{background:#111c30;border:1px solid #1e293b;border-radius:10px;padding:12px;text-align:center}
    .kpi .v{font-size:1.3rem;font-weight:800;color:#fff}
    .kpi .l{font-size:.7rem;color:#94a3b8;margin-top:3px}
    .me-card{border-color:#38bdf8}
    .picks{display:grid;grid-template-columns:repeat(7,1fr);gap:8px}
    .pick{background:#0b1626;border:1px solid #1e293b;border-radius:8px;padding:8px;text-align:center}
    .pick span{display:block;font-size:.66rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em}
    .pick b{font-size:.82rem;color:#e2e8f0}
    code{background:#111c30;padding:1px 6px;border-radius:5px;font-size:.82em}
    .ggrid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:6px}
    .gcard{background:#0b1626;border:1px solid #1e293b;border-radius:12px;padding:12px 14px}
    .gcard h3{margin:0 0 6px;font-size:.95rem;color:#f1f5f9}
    table.gtbl{width:100%;border-collapse:collapse;font-size:.8rem}
    table.gtbl th{font-size:.62rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.03em;text-align:center;padding:2px 3px;font-weight:600}
    table.gtbl th:first-child{text-align:left}
    table.gtbl td{padding:4px 3px;text-align:center;border-top:1px solid #18243b;color:#cbd5e1;font-variant-numeric:tabular-nums}
    table.gtbl td.gt{text-align:left;font-weight:600;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:112px;border-left:3px solid transparent;padding-left:7px}
    table.gtbl td.gq{font-weight:700;color:#38bdf8}
    table.gtbl tr.qual td{background:rgba(52,211,153,.10)}
    table.gtbl tr.qual td.gt{border-left-color:#34d399;color:#fff}
    @media(max-width:760px){.kpis{grid-template-columns:repeat(3,1fr)}.picks{grid-template-columns:repeat(2,1fr)}.ggrid{grid-template-columns:repeat(2,1fr)}}
    """
    js = """
    let sortState={};
    function sortBy(k){
      const tb=document.querySelector('#probtable tbody');
      const rows=[...tb.querySelectorAll('tr')];
      const asc=sortState[k]=!sortState[k];
      rows.sort((a,b)=>{
        if(k==='name'){const x=a.dataset.name,y=b.dataset.name;return asc?x.localeCompare(y):y.localeCompare(x);}
        const x=parseFloat(a.dataset[k]||0),y=parseFloat(b.dataset[k]||0);return asc?x-y:y-x;});
      rows.forEach(r=>tb.appendChild(r));
    }
    """
    legend = (f'<div class="legend">'
              f'<span><i style="background:{GOLD}"></i>1st · ₪1800</span>'
              f'<span><i style="background:{SILVER}"></i>2nd · ₪750</span>'
              f'<span><i style="background:{BRONZE}"></i>3rd / last · ₪50 refund</span></div>')

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 pool · live win probabilities</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">
<h1>Live win-probability tracker · WC 2026 friends pool</h1>
<p class="sub">{N} entries · {d['n_sims']:,} conditioned simulations · headline metric = expected winnings under the prize-split tiebreak.</p>
<div class="meta">
  <span class="chip">Snapshot <b>{escape(d['timestamp'])}</b></span>
  <span class="chip">State: <b>{escape(state_line)}</b></span>
  <span class="chip">Pot <b>₪2,650</b> (1800 / 750 / 50 / 50)</span>
  <span class="chip">Title spread <b>{d['calibration']['strength_spread']:.2f}</b> · GB scale <b>{d['calibration']['golden_boot_scale']:.2f}</b></span>
</div>
{me_block}
<div class="card"><h2>Probability table</h2>
<p class="sub">Click any header to sort. Ranked by expected winnings (₪). {"Pre-tournament baseline — all entries currently 0 pts." if pre else ""}</p>
<div class="tablewrap">{table}</div></div>

<div class="card"><h2>Expected winnings — where the money comes from</h2>
<p class="sub">Expected winnings = an entry's average payout over all {d['n_sims']:,} simulations
= P(1st)×₪1800 + P(2nd)×₪750 + (P(3rd)+P(last))×₪50. Each bar splits that total into
its prize sources; contrarian entries earn most of theirs from the 1st-place gold. The 53 bars sum to the ₪2,650 pot.</p>
{legend}{ev_svg}</div>

<div class="card"><h2>Final-points fan (top 15)</h2>
<p class="sub">Simulated final-score spread (P10–P90, white dot = median{"" if pre else ", gold tick = current locked points"}).</p>{fan_svg}</div>

{race_block}

<div class="card"><h2>Rank-distribution heat strips (all {N} entries)</h2>
<p class="sub">Each row shows where an entry lands across all {d['n_sims']:,} sims (left = 1st place, right = {N}th). Rows are ordered by expected winnings and normalized to each entry's own peak, so the shape shows whether an entry is a sharp contender or a broad mid-pack bet.</p>
<div style="margin:0 0 10px">{svg_colorbar()}</div>{strip_svg}</div>

<div class="card"><h2>Champion-conditional pool winner</h2>
<p class="sub">"Who do I root for?" — gold cells = P(entry wins the pool | that team wins the World Cup); the % under each champion is its title probability. The three right-hand columns are each entry's overall P(1st), P(in the money = top-2) and P(last). Showing the top 18 by expected winnings; scroll within the panel for the rest.</p>
<div style="overflow-x:auto"><div style="width:{cm_w}px">{cm_header}
<div style="max-height:{cm_body_maxh}px;overflow-y:auto">{cm_body}</div></div></div></div>

{groups_blk}

<div class="card"><h2>Projected vs current standings</h2>
<p class="sub">Today's points-rank (left) → projected expected-final rank (right). Green lines climb, grey lines slip.</p>
<div style="overflow:auto">{bump_svg}</div></div>

<p class="sub" style="text-align:center;margin-top:30px">Generated {escape(d['generated_at'])} · re-run <code>scripts/run_live_update.py</code> then <code>scripts/build_live_report.py</code> to refresh.</p>
</div><script>{js}</script></body></html>"""

    out = REPORT_DIR / "live.html"
    out.write_text(html)
    print(f"Wrote {out}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
