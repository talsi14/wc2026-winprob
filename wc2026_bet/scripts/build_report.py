"""Stage 3 - build the standalone HTML analysis article (report/index.html).

Reads results/ + data/processed/ and emits a single self-contained HTML file
(inline CSS + inline SVG charts, no external/CDN dependencies) telling the full
story: how we model the tournament, why we blend Elo with the market, what the
simulations say, and the two final entries plus their top-10 alternatives.
"""
from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wc2026_bet.config import DATA_PROCESSED, REPORT_DIR, RESULTS_DIR

SLOT_LABEL = {
    "tier_A": "Tier A", "tier_B": "Tier B", "tier_C": "Tier C", "tier_D": "Tier D",
    "scoring": "Scoring team", "conceding": "Conceding team", "top_scorer": "Top scorer",
}
PALETTE = {"safe": "#2563eb", "risky": "#dc2626", "ink": "#0f172a",
           "muted": "#64748b", "grid": "#e2e8f0", "accent": "#0d9488"}
TIER_COLORS = {"A": "#1d4ed8", "B": "#0d9488", "C": "#d97706", "D": "#9333ea"}
OBJ_COLORS = {"SAFE (max payout)": "#2563eb", "RISKY (max P1st)": "#dc2626",
              "max mean": "#0d9488", "max P(top-2)": "#9333ea"}
SLOT_COLORS = {"tier_A": TIER_COLORS["A"], "tier_B": TIER_COLORS["B"],
               "tier_C": TIER_COLORS["C"], "tier_D": TIER_COLORS["D"],
               "scoring": "#0891b2", "conceding": "#db2777", "top_scorer": "#dc2626"}


# --------------------------------------------------------------------------- #
# SVG chart helpers (self-contained, no JS)
# --------------------------------------------------------------------------- #
def svg_hist(hist_a, hist_b, w=720, h=300, pad=40):
    ea, ca = hist_a["edges"], hist_a["counts"]
    eb, cb = hist_b["edges"], hist_b["counts"]
    xmin = min(ea[0], eb[0]); xmax = max(ea[-1], eb[-1])
    ymax = max(max(ca), max(cb))
    def X(v): return pad + (v - xmin) / (xmax - xmin) * (w - 2 * pad)
    def Y(v): return h - pad - v / ymax * (h - 2 * pad)
    def bars(edges, counts, color, op):
        out = []
        for i, c in enumerate(counts):
            x0, x1 = X(edges[i]), X(edges[i + 1])
            out.append(f'<rect x="{x0:.1f}" y="{Y(c):.1f}" width="{max(x1-x0-0.5,0.5):.1f}" '
                       f'height="{h-pad-Y(c):.1f}" fill="{color}" fill-opacity="{op}"/>')
        return "".join(out)
    def vline(v, color):
        return (f'<line x1="{X(v):.1f}" y1="{pad}" x2="{X(v):.1f}" y2="{h-pad}" '
                f'stroke="{color}" stroke-width="2" stroke-dasharray="4 3"/>')
    # corner legend (avoids the two close mean labels colliding on the lines)
    lx, ly = w - pad - 150, pad + 6
    legend = (
        f'<rect x="{lx-8}" y="{ly-4}" width="160" height="40" fill="#ffffff" '
        f'fill-opacity="0.85" stroke="{PALETTE["grid"]}" rx="6"/>'
        f'<rect x="{lx}" y="{ly+1}" width="11" height="11" fill="{PALETTE["safe"]}" fill-opacity="0.55"/>'
        f'<text x="{lx+16}" y="{ly+10}" font-size="11" fill="{PALETTE["ink"]}">safe &#183; mean {hist_a["mean"]:.0f}</text>'
        f'<rect x="{lx}" y="{ly+18}" width="11" height="11" fill="{PALETTE["risky"]}" fill-opacity="0.45"/>'
        f'<text x="{lx+16}" y="{ly+27}" font-size="11" fill="{PALETTE["ink"]}">risky &#183; mean {hist_b["mean"]:.0f}</text>')
    xticks = "".join(
        f'<text x="{X(t):.1f}" y="{h-pad+16}" fill="{PALETTE["muted"]}" font-size="11" '
        f'text-anchor="middle">{t}</text>'
        f'<line x1="{X(t):.1f}" y1="{h-pad}" x2="{X(t):.1f}" y2="{h-pad+4}" stroke="{PALETTE["muted"]}"/>'
        for t in range(0, int(xmax) + 1, 10))
    return f'''<svg viewBox="0 0 {w} {h}" class="chart" role="img">
      <line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="{PALETTE['grid']}"/>
      {bars(ea, ca, PALETTE['safe'], 0.55)}
      {bars(eb, cb, PALETTE['risky'], 0.45)}
      {vline(hist_a['mean'], PALETTE['safe'])}
      {vline(hist_b['mean'], PALETTE['risky'])}
      {xticks}
      {legend}
      <text x="{w/2:.0f}" y="{h-4}" fill="{PALETTE['muted']}" font-size="12" text-anchor="middle">Total bet points</text>
    </svg>'''


def svg_grouped_bar(labels, series, colors, w=720, h=320, pad=46, ymin=0.0,
                    yfmt=lambda v: f"{v:.0%}", tipfmt=lambda v: f"{v:.1%}",
                    rotate=False):
    """series: list of (name, values[]) aligned with labels.

    Bars are drawn from ``ymin`` (use a non-zero baseline for value axes like
    Elo). ``yfmt``/``tipfmt`` format the y-ticks and the hover tooltips.
    """
    vmax = max(max(v for v in vals) for _, vals in series)
    ymax = ymin + (vmax - ymin) * 1.14
    n = len(labels); g = len(series)
    bw = (w - 2 * pad) / n
    sub = bw * 0.8 / g
    def Y(v): return h - pad - (v - ymin) / (ymax - ymin) * (h - 2 * pad)
    bars = []
    for gi, (name, vals) in enumerate(series):
        for i, v in enumerate(vals):
            x = pad + i * bw + bw * 0.1 + gi * sub
            bars.append(f'<rect x="{x:.1f}" y="{Y(v):.1f}" width="{sub*0.9:.1f}" '
                        f'height="{max(h-pad-Y(v),0):.1f}" fill="{colors[gi]}">'
                        f'<title>{escape(name)} &#183; {escape(str(labels[i]))}: {tipfmt(v)}</title></rect>')
    if rotate:
        xt = "".join(f'<text x="{pad+i*bw+bw/2:.1f}" y="{h-pad+14}" font-size="10" '
                     f'fill="{PALETTE["ink"]}" text-anchor="end" '
                     f'transform="rotate(-32 {pad+i*bw+bw/2:.1f} {h-pad+14})">{escape(str(l))}</text>'
                     for i, l in enumerate(labels))
    else:
        xt = "".join(f'<text x="{pad+i*bw+bw/2:.1f}" y="{h-pad+16}" font-size="11" '
                     f'fill="{PALETTE["ink"]}" text-anchor="middle">{escape(str(l))}</text>'
                     for i, l in enumerate(labels))
    yt = "".join(f'<text x="{pad-8}" y="{Y(t)+3:.1f}" font-size="10" fill="{PALETTE["muted"]}" '
                 f'text-anchor="end">{yfmt(t)}</text>'
                 f'<line x1="{pad}" y1="{Y(t):.1f}" x2="{w-pad}" y2="{Y(t):.1f}" stroke="{PALETTE["grid"]}"/>'
                 for t in [ymin + i * (ymax - ymin) / 4 for i in range(5)])
    legend = "".join(f'<rect x="{pad+gi*130}" y="4" width="12" height="12" fill="{colors[gi]}"/>'
                     f'<text x="{pad+gi*130+18}" y="14" font-size="12" fill="{PALETTE["ink"]}">{escape(name)}</text>'
                     for gi, (name, _) in enumerate(series))
    return f'''<svg viewBox="0 0 {w} {h}" class="chart" role="img">{yt}{bars}{xt}{legend}</svg>'''


def svg_hbar(labels, values, color, w=720, rowh=26, pad=160, fmt="{:.1%}", vmax=None):
    h = rowh * len(labels) + 30
    vmax = vmax or max(values) * 1.1
    def W(v): return v / vmax * (w - pad - 70)
    rows = []
    for i, (l, v) in enumerate(zip(labels, values)):
        y = 12 + i * rowh
        rows.append(
            f'<text x="{pad-8}" y="{y+rowh*0.65:.0f}" font-size="12" fill="{PALETTE["ink"]}" '
            f'text-anchor="end">{escape(str(l))}</text>'
            f'<rect x="{pad}" y="{y:.0f}" width="{W(v):.1f}" height="{rowh*0.7:.0f}" fill="{color}" rx="3"/>'
            f'<text x="{pad+W(v)+6:.1f}" y="{y+rowh*0.6:.0f}" font-size="11" fill="{PALETTE["muted"]}">{fmt.format(v)}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(rows)}</svg>'


def svg_contrib(rows, w=720, rowh=24, lw=210):
    """Diverging horizontal bar: each row is (label, value, color), drawn from
    a zero baseline (negative left, positive right). Used to decompose an
    entry's expected points slot by slot."""
    h = rowh * len(rows) + 18
    vals = [v for _, v, _ in rows]
    vmin = min(0.0, min(vals)); vmax = max(0.0, max(vals))
    span = (vmax - vmin) or 1.0
    left_b, right_b = lw + 6, w - 52
    barW = right_b - left_b
    def X(v): return left_b + (v - vmin) / span * barW
    zero = X(0.0)
    bars = [f'<line x1="{zero:.1f}" y1="4" x2="{zero:.1f}" y2="{h-14:.0f}" stroke="{PALETTE["grid"]}"/>']
    for i, (label, v, color) in enumerate(rows):
        y = 8 + i * rowh
        x = X(v)
        bx, bw = (zero, x - zero) if v >= 0 else (x, zero - x)
        bars.append(
            f'<text x="{lw}" y="{y+11:.0f}" font-size="11" fill="{PALETTE["ink"]}" '
            f'text-anchor="end">{escape(label)}</text>'
            f'<rect x="{bx:.1f}" y="{y:.0f}" width="{max(bw,0.5):.1f}" height="15" fill="{color}" rx="2"/>')
        if v >= 0:
            bars.append(f'<text x="{x+5:.1f}" y="{y+11:.0f}" font-size="10" '
                        f'fill="{PALETTE["muted"]}" text-anchor="start">+{v:.1f}</text>')
        else:
            bars.append(f'<text x="{x-5:.1f}" y="{y+11:.0f}" font-size="10" '
                        f'fill="{PALETTE["muted"]}" text-anchor="end">{v:.1f}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(bars)}</svg>'


def _grp_class(g):
    return "g_" + "".join(ch if ch.isalnum() else "_" for ch in str(g))


def svg_scatter(points, color_map, w=700, h=440, pad=60, xlab="", ylab="",
                xfmt=lambda v: f"{v:.0f}", yfmt=lambda v: f"{v:.0f}",
                label_set=None, ref_diagonal=False, quadrant=False,
                size_range=None, invert_y=False, tier_filter=False, legend="tr"):
    """Rich scatter.

    points: list of dicts with keys x, y, label, group, optional size, tip.
    color_map: ordered {group: color}; also drives the legend.
    label_set: labels that get a text annotation (all points still hover).
    size_range: (min_val, max_val) to map an optional ``size`` key to radius.
    ref_diagonal: draw a y=x reference line (same-unit axes).
    quadrant: draw dashed median lines.
    tier_filter: tag points with a group class so JS can toggle them.
    """
    label_set = label_set or set()
    xs = [p["x"] for p in points]; ys = [p["y"] for p in points]
    xmin, xmax = min(xs), max(xs); ymin, ymax = min(ys), max(ys)
    if ref_diagonal:                       # square the axes so y=x is a true 45deg
        lo = min(xmin, ymin); hi = max(xmax, ymax)
        xmin = ymin = lo; xmax = ymax = hi
    xpad = (xmax - xmin) * 0.08 or 1; ypad = (ymax - ymin) * 0.08 or 1
    xlo, xhi = xmin - xpad, xmax + xpad
    ylo, yhi = ymin - ypad, ymax + ypad

    def X(v): return pad + (v - xlo) / (xhi - xlo) * (w - 2 * pad)
    def Y(v):
        f = (v - ylo) / (yhi - ylo)
        if invert_y:
            f = 1 - f
        return h - pad - f * (h - 2 * pad)

    def radius(p):
        if not size_range or "size" not in p:
            return 4.6
        lo, hi = size_range
        t = (p["size"] - lo) / (hi - lo) if hi > lo else 0.5
        return 3.5 + max(0.0, min(1.0, t)) * 6.5

    # grid + ticks
    grid = []
    for i in range(5):
        xv = xlo + i * (xhi - xlo) / 4
        yv = ylo + i * (yhi - ylo) / 4
        gx = X(xv); gy = Y(yv)
        grid.append(f'<line x1="{gx:.1f}" y1="{pad}" x2="{gx:.1f}" y2="{h-pad}" stroke="{PALETTE["grid"]}" stroke-opacity="0.6"/>'
                    f'<text x="{gx:.1f}" y="{h-pad+16}" font-size="10" fill="{PALETTE["muted"]}" text-anchor="middle">{xfmt(xv)}</text>'
                    f'<line x1="{pad}" y1="{gy:.1f}" x2="{w-pad}" y2="{gy:.1f}" stroke="{PALETTE["grid"]}" stroke-opacity="0.6"/>'
                    f'<text x="{pad-8}" y="{gy+3:.1f}" font-size="10" fill="{PALETTE["muted"]}" text-anchor="end">{yfmt(yv)}</text>')

    extra = ""
    if quadrant:
        mx = X(sorted(xs)[len(xs) // 2]); my = Y(sorted(ys)[len(ys) // 2])
        extra += (f'<line x1="{mx:.1f}" y1="{pad}" x2="{mx:.1f}" y2="{h-pad}" stroke="{PALETTE["muted"]}" stroke-dasharray="4 3" stroke-opacity="0.5"/>'
                  f'<line x1="{pad}" y1="{my:.1f}" x2="{w-pad}" y2="{my:.1f}" stroke="{PALETTE["muted"]}" stroke-dasharray="4 3" stroke-opacity="0.5"/>')
    if ref_diagonal:
        extra += f'<line x1="{X(xlo):.1f}" y1="{Y(xlo):.1f}" x2="{X(xhi):.1f}" y2="{Y(xhi):.1f}" stroke="{PALETTE["muted"]}" stroke-dasharray="5 4" stroke-opacity="0.7"/>'

    pts = []
    label_items = []
    for p in points:
        cx, cy = X(p["x"]), Y(p["y"])
        color = color_map.get(p["group"], PALETTE["accent"])
        gcls = _grp_class(p["group"])
        cls = f' class="{gcls}"' if tier_filter else ""
        tip = p.get("tip", f'{p["label"]} ({xfmt(p["x"])}, {yfmt(p["y"])})')
        pts.append(f'<g{cls}><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius(p):.1f}" '
                   f'fill="{color}" fill-opacity="0.82" stroke="#fff" stroke-width="0.6">'
                   f'<title>{escape(tip)}</title></circle></g>')
        if p["label"] and p["label"] in label_set:
            label_items.append((cx, cy, p["label"], gcls if tier_filter else None))

    # de-collide labels: greedy vertical nudge with leader lines, only against
    # labels that overlap horizontally (keeps dense clusters legible).
    label_items.sort(key=lambda t: t[1])
    placed = []                      # (x0, x1, ly)
    GAP, FS = 12.0, 10
    for cx, cy, text, gcls in label_items:
        anchor, dx = ("end", -7) if cx > w * 0.74 else ("start", 7)
        est_w = len(text) * 5.6 + 8
        x0 = (cx + dx - est_w) if anchor == "end" else (cx + dx)
        x1 = x0 + est_w
        ly = cy + 3
        moved = True
        while moved:
            moved = False
            for px0, px1, py in placed:
                # only treat as a collision if nudging actually advances ly
                # (guards a float-epsilon case where py + GAP == ly -> infinite loop)
                if (abs(ly - py) < GAP and not (x0 > px1 + 2 or x1 < px0 - 2)
                        and py + GAP > ly + 1e-6):
                    ly = py + GAP
                    moved = True
        ly = max(pad + FS, min(h - pad - 2, ly))
        placed.append((x0, x1, ly))
        lead = ""
        if abs(ly - (cy + 3)) > 7:   # leader line back to the point
            lx2 = (x1 if anchor == "end" else x0)
            lead = (f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx2:.1f}" y2="{ly-3:.1f}" '
                    f'stroke="{PALETTE["muted"]}" stroke-width="0.6" stroke-opacity="0.55"/>')
        wrap0 = f'<g class="{gcls}">' if gcls else "<g>"
        pts.append(f'{wrap0}{lead}<text x="{cx+dx:.1f}" y="{ly:.1f}" font-size="{FS}" '
                   f'fill="{PALETTE["ink"]}" text-anchor="{anchor}">{escape(text)}</text></g>')

    lw = 8 + max((len(str(g)) for g in color_map), default=4) * 7 + 22
    lh = len(color_map) * 17 + 8
    lbx = (pad + 6) if legend[1] == "l" else (w - pad - lw - 4)
    lby = (pad - 4) if legend[0] == "t" else (h - pad - lh - 4)
    legrows = []
    for i, (g, c) in enumerate(color_map.items()):
        ly = lby + 15 + i * 17
        legrows.append(f'<rect x="{lbx+8}" y="{ly-9}" width="11" height="11" fill="{c}" rx="2"/>'
                       f'<text x="{lbx+23}" y="{ly}" font-size="11" fill="{PALETTE["ink"]}">{escape(str(g))}</text>')
    legbox = (f'<g><rect x="{lbx}" y="{lby}" width="{lw}" height="{lh}" '
              f'fill="#fff" fill-opacity="0.85" stroke="{PALETTE["grid"]}" rx="6"/>{"".join(legrows)}</g>')

    return f'''<svg viewBox="0 0 {w} {h}" class="chart" role="img">
      {"".join(grid)}
      <line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="{PALETTE['muted']}"/>
      <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h-pad}" stroke="{PALETTE['muted']}"/>
      {extra}
      {"".join(pts)}
      {legbox}
      <text x="{(pad+w-pad)/2:.0f}" y="{h-6}" font-size="12" fill="{PALETTE['muted']}" text-anchor="middle">{escape(xlab)}</text>
      <text x="16" y="{(pad+h-pad)/2:.0f}" font-size="12" fill="{PALETTE['muted']}" text-anchor="middle" transform="rotate(-90 16 {(pad+h-pad)/2:.0f})">{escape(ylab)}</text>
    </svg>'''


# --------------------------------------------------------------------------- #
# Table helpers
# --------------------------------------------------------------------------- #
def table(headers, rows, cls=""):
    th = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    trs = []
    for r in rows:
        tds = "".join(f"<td>{c}</td>" for c in r)
        trs.append(f"<tr>{tds}</tr>")
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def pct(x): return f"{x*100:.1f}%"


def entry_pick_row(picks):
    order = ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding", "top_scorer"]
    return " · ".join(f'<b>{escape(picks[k])}</b>' for k in order)


def rank_table(rows):
    head = ["#", "Tier A", "Tier B", "Tier C", "Tier D", "Scoring", "Conceding",
            "Top scorer", "Mean", "P10", "P(1st)", "P(top2)", "EV net"]
    body = []
    for i, r in enumerate(rows, 1):
        p = r["picks"]
        body.append([i, p["tier_A"], p["tier_B"], p["tier_C"], p["tier_D"],
                     p["scoring"], p["conceding"], p["top_scorer"],
                     f'{r["mean_score"]:.1f}', f'{r["p10"]:.0f}',
                     pct(r["p_first"]), pct(r["p_top2"]),
                     f'{r["ev_net"]:+.0f}'])
    return table(head, body, "ranktbl")


def render_groups(groups):
    cards = []
    for g in groups:
        rows = []
        for j, t in enumerate(g["teams"]):
            cls = "q" if j < 2 else "out"
            star = ' <span class="star">&#9733;</span>' if t["pick"] else ""
            name = f'<b>{escape(t["team"])}</b>' if t["pick"] else escape(t["team"])
            rows.append(f'<tr class="{cls}"><td>{name}{star}</td>'
                        f'<td class="num">{t["p_qual"]*100:.0f}%</td></tr>')
        cards.append(
            f'<div class="grp"><div class="grp-h">Group {g["group"]}'
            f'<span class="grp-sub">qualify&nbsp;%</span></div>'
            f'<table>{"".join(rows)}</table></div>')
    return f'<div class="groups-grid">{"".join(cards)}</div>'


def render_bracket(rounds):
    cols = []
    for rnd in rounds:
        cards = []
        for m in rnd["matches"]:
            def side(team, pick, won):
                star = ' &#9733;' if pick else ""
                c = "bw" if won else "bl"
                return f'<div class="{c}">{escape(team)}{star}</div>'
            hw = m["winner"] == m["home"]
            cards.append('<div class="match">'
                         + side(m["home"], m["home_pick"], hw)
                         + side(m["away"], m["away_pick"], not hw)
                         + '</div>')
        cols.append(f'<div class="bk-col"><h4>{escape(rnd["label"])}</h4>{"".join(cards)}</div>')
    return f'<div class="bracket">{"".join(cols)}</div>'


def render_scorers(scorers):
    rows = []
    for i, s in enumerate(scorers, 1):
        star = ' <span class="star">&#9733;</span>' if s["pick"] else ""
        name = f'<b>{escape(s["player"])}</b>' if s["pick"] else escape(s["player"])
        rows.append(f'<tr><td>{i}</td><td>{name}{star}</td><td>{escape(s["team"])}</td>'
                    f'<td class="num">{s["goals"]:.1f}</td><td class="num">{s["p_gb"]*100:.0f}%</td></tr>')
    return ('<table class="scorers"><thead><tr><th>#</th><th>Player</th><th>Team</th>'
            '<th>Exp. goals</th><th>P(Boot)</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def render_scenario(key, scen, label, total_sims):
    if key == "overall":
        note = (f"The unconditional average across all {scen['n_sims']:,} simulations - "
                "the field-agnostic &ldquo;chalk&rdquo; tournament, ignoring the bet and rivals.")
    else:
        share = scen["n_sims"] / total_sims
        note = (f"Conditioned on this entry finishing <b>in the money (top-2)</b>: "
                f"{scen['n_sims']:,} simulations ({share:.1%} of all runs). "
                "This is what the tournament most plausibly looks like <em>when this bet pays off</em>.")
    champ_star = ' &#9733;' if scen.get("champion_pick") else ""
    active = " active" if key == "overall" else ""
    return f'''<div id="scen-{key}" class="scenario{active}">
      <div class="scen-headline">
        <div class="trophy">&#127942;</div>
        <div><div class="champ">Champion: <b>{escape(scen["champion"])}</b>{champ_star}
          <span class="vs">def. {escape(scen["runner_up"])} in the final</span></div>
          <div class="scen-note">{note}</div></div>
      </div>
      <h3>Projected knockout bracket</h3>
      {render_bracket(scen["rounds"])}
      <div class="two-col" style="margin-top:18px">
        <div><h3>Group-stage standings (qualifiers highlighted)</h3>{render_groups(scen["groups"])}</div>
        <div><h3>Top-5 scorers</h3>{render_scorers(scen["scorers"])}
          <p style="font-size:.8rem;color:var(--muted)">&#9733; marks this entry&rsquo;s own picks.</p></div>
      </div>
    </div>'''


def main():
    R = RESULTS_DIR
    D = DATA_PROCESSED
    ent = json.loads((R / "entries.json").read_text())
    scen_data = json.loads((R / "scenarios.json").read_text())
    cal = json.loads((D / "calibration.json").read_text())
    elo = pd.read_csv(D / "elo.csv")
    mkt_out = pd.read_csv(D / "market_outright.csv")
    team = pd.read_csv(R / "team_summary.csv")
    players = pd.read_csv(R / "player_summary.csv")
    attr = {n: pd.read_csv(R / f"attractiveness_{n}.csv")
            for n in ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding", "top_scorer"]}

    safe, risky = ent["safe_entry"], ent["risky_entry"]
    cfg = ent["config"]

    # ---- charts ------------------------------------------------------------ #
    hist_svg = svg_hist(ent["safe_hist"], ent["risky_hist"])

    # title prob: sim vs opta vs market (top 8 by sim)
    top8 = team.head(8)["team"].tolist()
    sim_p = {r.team: r.P_title for r in team.itertuples()}
    opta = cal.get("anchors") or {}
    mkt = {r.team: r.implied_prob for r in mkt_out.itertuples()}
    cmp_series = [
        ("Our sim", [sim_p.get(t, 0) for t in top8]),
        ("Opta", [opta.get(t, 0) for t in top8]),
        ("Market", [mkt.get(t, 0) for t in top8]),
    ]
    cmp_svg = svg_grouped_bar(top8, cmp_series,
                              [PALETTE["safe"], PALETTE["accent"], PALETTE["muted"]])

    # Elo blend chart (top 12 by blended) - real Elo values on a 1850+ baseline
    e12 = elo.head(12)
    blend_svg = svg_grouped_bar(
        e12["team"].tolist(),
        [("eloratings.net", e12["elo_eloratings"].tolist()),
         ("blended (used)", e12["elo_blended"].tolist())],
        [PALETTE["muted"], PALETTE["safe"]], h=320, pad=52, ymin=1850,
        yfmt=lambda v: f"{v:.0f}", tipfmt=lambda v: f"{v:.0f}", rotate=True)

    # advancement bar (top 16 by title)
    adv = team.head(16)
    adv_svg = svg_hbar(adv["team"].tolist(), adv["P_title"].tolist(),
                       PALETTE["safe"], fmt="{:.1%}")
    # golden boot
    gb = players.head(12)
    gb_svg = svg_hbar(gb["scorer"].tolist(), gb["P_golden_boot"].tolist(),
                      PALETTE["risky"], fmt="{:.1%}", pad=170)

    # ownership (what the field picks) - tier A
    own_A = ent["ownership"]["tier_A"]
    ownA_sorted = sorted(own_A.items(), key=lambda kv: -kv[1])[:9]
    ownA_svg = svg_hbar([k for k, _ in ownA_sorted], [v for _, v in ownA_sorted],
                        PALETTE["accent"], fmt="{:.0%}", pad=120)

    # ownership - top scorer (the field crowds onto the obvious Golden Boot names)
    own_TS = ent["ownership"]["top_scorer"]
    ownTS_sorted = sorted(own_TS.items(), key=lambda kv: -kv[1])[:9]
    ownTS_svg = svg_hbar([k for k, _ in ownTS_sorted], [v for _, v in ownTS_sorted],
                         PALETTE["risky"], fmt="{:.0%}", pad=150)

    # per-entry points decomposition (where each entry's expected points come from)
    SLOT_ORDER = ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding", "top_scorer"]
    attr_mean = {n: {r.candidate: float(r.mean) for r in attr[n].itertuples()}
                 for n in SLOT_ORDER}

    def contrib_rows(e):
        out = []
        for k in SLOT_ORDER:
            pick = e["picks"][k]
            mean = attr_mean[k].get(pick, 0.0)
            out.append((f"{SLOT_LABEL[k]}: {pick}", mean, SLOT_COLORS[k]))
        return out

    contrib_safe = svg_contrib(contrib_rows(safe))
    contrib_risky = svg_contrib(contrib_rows(risky))

    # attractiveness mini-tables (n=None -> show every candidate in the slot)
    def attr_table(name, cols, n=None):
        df = attr[name] if n is None else attr[name].head(n)
        head = [c.replace("_", " ") for c in cols]
        body = []
        for r in df.itertuples():
            row = []
            for c in cols:
                v = getattr(r, c)
                if c in ("title_prob", "adv_prob", "gb_prob"):
                    row.append(pct(v))
                elif isinstance(v, float):
                    row.append(f"{v:.2f}")
                else:
                    row.append(escape(str(v)))
            body.append(row)
        return table(head, body, "mini")

    scroll = lambda t: f'<div class="scrollbox">{t}</div>'
    tierA_tbl = attr_table("tier_A", ["candidate", "group", "mean", "p90", "title_prob"])
    tierB_tbl = attr_table("tier_B", ["candidate", "group", "mean", "p90", "adv_prob"])
    tierC_tbl = attr_table("tier_C", ["candidate", "group", "mean", "p90", "adv_prob"])
    tierD_tbl = attr_table("tier_D", ["candidate", "group", "mean", "p90", "adv_prob"])
    score_tbl = scroll(attr_table("scoring", ["candidate", "mean", "exp_gf"]))
    conc_tbl = scroll(attr_table("conceding", ["candidate", "mean", "exp_ga"]))
    ts_tbl = scroll(attr_table("top_scorer", ["candidate", "team", "mean", "gb_prob"]))

    # ---- visual explorations: per-team tier table + derived metrics -------- #
    STAGE_IDX = {"round_Group stage": 0, "round_Round of 32": 1,
                 "round_Round of 16": 2, "round_Quarter-final": 3,
                 "round_Semi-final": 4, "round_Final": 5, "round_Champion": 6}
    tm = team.copy()
    tm["avg_stage"] = sum(tm[c] * i for c, i in STAGE_IDX.items())
    tinfo = tm.set_index("team")

    tier_rows = []
    for L in ["A", "B", "C", "D"]:
        df = attr[f"tier_{L}"]
        for r in df.itertuples():
            t = r.candidate
            if t not in tinfo.index:
                continue
            ti = tinfo.loc[t]
            tier_rows.append({
                "team": t, "tier": L, "mean": float(r.mean), "std": float(r.std),
                "title": float(ti["P_title"]), "stage": float(ti["avg_stage"]),
                "gf": float(ti["exp_gf"]), "ga": float(ti["exp_ga"]),
                "games": float(ti["exp_games"])})

    # labels to annotate: the high-value band (top teams by expected points
    # contribution - the chart's Y metric) + both entries' own picks. We label
    # generously down the value axis so no high-contribution team is left
    # anonymous, and rely on de-collision in svg_scatter to stay readable.
    entry_team_picks = set()
    for e in (safe, risky):
        for k in ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding"]:
            entry_team_picks.add(e["picks"][k])
    top_by_mean = {r["team"] for r in sorted(tier_rows, key=lambda x: -x["mean"])[:16]}
    team_label_set = top_by_mean | entry_team_picks

    # A. expected points contribution vs title probability
    chartA = svg_scatter(
        [{"x": r["title"], "y": r["mean"], "label": r["team"], "group": r["tier"],
          "tip": f'{r["team"]} (Tier {r["tier"]}): {r["mean"]:.1f} pts, title {r["title"]*100:.1f}%'}
         for r in tier_rows],
        TIER_COLORS, xlab="Title probability", ylab="Expected points contribution",
        xfmt=lambda v: f"{v*100:.0f}%", yfmt=lambda v: f"{v:.0f}",
        label_set=team_label_set, tier_filter=True, legend="br")

    # B. expected points contribution vs average stage reached
    chartB = svg_scatter(
        [{"x": r["stage"], "y": r["mean"], "label": r["team"], "group": r["tier"],
          "tip": f'{r["team"]} (Tier {r["tier"]}): {r["mean"]:.1f} pts, avg stage {r["stage"]:.2f}'}
         for r in tier_rows],
        TIER_COLORS, xlab="Average stage reached (0=group ... 6=champion)",
        ylab="Expected points contribution",
        xfmt=lambda v: f"{v:.1f}", yfmt=lambda v: f"{v:.0f}",
        label_set=team_label_set, tier_filter=True, legend="br")

    # C. expected goals for vs against (totals), size = games, quadrant medians
    games_vals = [r["games"] for r in tier_rows]
    chartC = svg_scatter(
        [{"x": r["gf"], "y": r["ga"], "label": r["team"], "group": r["tier"],
          "size": r["games"],
          "tip": f'{r["team"]} (Tier {r["tier"]}): GF {r["gf"]:.1f}, GA {r["ga"]:.1f}, {r["games"]:.1f} games'}
         for r in tier_rows],
        TIER_COLORS, xlab="Expected goals FOR (tournament total)",
        ylab="Expected goals AGAINST (tournament total)",
        xfmt=lambda v: f"{v:.0f}", yfmt=lambda v: f"{v:.0f}",
        label_set=team_label_set, quadrant=True,
        size_range=(min(games_vals), max(games_vals)), tier_filter=True, legend="tl")

    # E. contrarian value map: tier-slot ownership vs expected points contribution
    own_by_tier = {L: ent["ownership"][f"tier_{L}"] for L in ["A", "B", "C", "D"]}
    # on the contrarian map, field ownership (X) is a key axis - also label the
    # most heavily-owned "chalk" teams so the crowded picks aren't anonymous.
    own_ranked = sorted(tier_rows,
                        key=lambda r: -own_by_tier[r["tier"]].get(r["team"], 0.0))
    ownE_label_set = team_label_set | {r["team"] for r in own_ranked[:10]}
    chartE = svg_scatter(
        [{"x": own_by_tier[r["tier"]].get(r["team"], 0.0), "y": r["mean"],
          "label": r["team"], "group": r["tier"],
          "tip": f'{r["team"]} (Tier {r["tier"]}): {r["mean"]:.1f} pts, field ownership {own_by_tier[r["tier"]].get(r["team"],0.0)*100:.0f}%'}
         for r in tier_rows],
        TIER_COLORS, xlab="Field ownership (how often rivals pick it)",
        ylab="Expected points contribution",
        xfmt=lambda v: f"{v*100:.0f}%", yfmt=lambda v: f"{v:.0f}",
        label_set=ownE_label_set, tier_filter=True, legend="br")

    # F. risk vs reward: volatility (std) vs mean contribution
    chartF = svg_scatter(
        [{"x": r["std"], "y": r["mean"], "label": r["team"], "group": r["tier"],
          "tip": f'{r["team"]} (Tier {r["tier"]}): mean {r["mean"]:.1f}, std {r["std"]:.1f}'}
         for r in tier_rows],
        TIER_COLORS, xlab="Volatility (std of points)",
        ylab="Expected points contribution",
        xfmt=lambda v: f"{v:.1f}", yfmt=lambda v: f"{v:.0f}",
        label_set=team_label_set, tier_filter=True, legend="br")

    # D. entry risk-return frontier
    entry_sets = [("safe_top10", "SAFE (max payout)"), ("risky_top10", "RISKY (max P1st)"),
                  ("mean_top10", "max mean"), ("ptop2_top10", "max P(top-2)")]
    entry_pts = []
    chosen_labels = {"\u2605 SAFE", "\u2605 RISKY"}
    for key, gname in entry_sets:
        for i, e in enumerate(ent[key]):
            lbl = ""
            if key == "safe_top10" and i == 0:
                lbl = "\u2605 SAFE"
            elif key == "risky_top10" and i == 0:
                lbl = "\u2605 RISKY"
            entry_pts.append({
                "x": e["mean_score"], "y": e["p_first"], "label": lbl, "group": gname,
                "size": e["ev_net"], "tip": (f'{gname} #{i+1}: {e["picks"]["tier_A"]} / '
                f'{e["picks"]["top_scorer"]} | mean {e["mean_score"]:.1f}, '
                f'P(1st) {e["p_first"]*100:.1f}%, EV {e["ev_net"]:+.0f}')})
    ev_vals = [p["size"] for p in entry_pts]
    chartD = svg_scatter(
        entry_pts, OBJ_COLORS, xlab="Mean bet points (reward)",
        ylab="P(finish 1st)", xfmt=lambda v: f"{v:.0f}",
        yfmt=lambda v: f"{v*100:.0f}%", label_set=chosen_labels,
        size_range=(min(ev_vals), max(ev_vals)), legend="br")

    # G. Golden Boot scatter
    gb_top = players.head(14)
    gb_labels = set(gb_top.head(7)["scorer"]) | {safe["picks"]["top_scorer"],
                                                 risky["picks"]["top_scorer"]}
    chartG = svg_scatter(
        [{"x": float(r.exp_goals), "y": float(r.P_golden_boot), "label": r.scorer,
          "group": "Player",
          "tip": f'{r.scorer} ({r.team}): {r.exp_goals:.1f} goals, Boot {r.P_golden_boot*100:.0f}%'}
         for r in gb_top.itertuples()],
        {"Player": PALETTE["risky"]}, xlab="Expected goals",
        ylab="P(Golden Boot)", xfmt=lambda v: f"{v:.1f}",
        yfmt=lambda v: f"{v*100:.0f}%", label_set=gb_labels)

    # H. calibration scatter: market/Opta vs simulated title prob
    cal_pts = []
    for t in mkt:
        if t in sim_p:
            cal_pts.append({"x": mkt[t], "y": sim_p[t], "label": t,
                            "group": "Team",
                            "tip": f'{t}: market {mkt[t]*100:.1f}%, sim {sim_p[t]*100:.1f}%'})
    cal_label_set = {p["label"] for p in sorted(cal_pts, key=lambda p: -p["y"])[:8]}
    chartH = svg_scatter(
        cal_pts, {"Team": PALETTE["accent"]}, xlab="Market title probability",
        ylab="Simulated title probability", xfmt=lambda v: f"{v*100:.0f}%",
        yfmt=lambda v: f"{v*100:.0f}%", label_set=cal_label_set, ref_diagonal=True,
        legend="tl")

    # team summary table (top 16)
    tsum_cols = ["team", "P_advance_R32", "P_QF", "P_SF", "P_final", "P_title"]
    tsum_rows = []
    for r in team.head(16).itertuples():
        tsum_rows.append([escape(r.team), pct(r.P_advance_R32), pct(r.P_QF),
                          pct(r.P_SF), pct(r.P_final), pct(r.P_title)])
    tsum_tbl = table(["Team", "R32", "QF", "SF", "Final", "Title"], tsum_rows, "datatbl")

    # calibration trace table
    trace = cal.get("trace") or []
    fit_teams = cal.get("fit_teams") or []
    cal_rows = []
    for tr in trace:
        cal_rows.append([f'{tr["spread"]:.2f}', f'{tr["sse"]:.5f}'])
    cal_tbl = table(["spread", "SSE vs Opta"], cal_rows, "mini")

    # ---- scenario section -------------------------------------------------- #
    scen_labels = scen_data["labels"]
    scen_all = scen_data["scenarios"]
    total_sims = scen_all["overall"]["n_sims"]
    order = ["overall", "safe", "risky", "mean", "ptop2"]
    options = "".join(f'<option value="{k}">{escape(scen_labels[k])}</option>' for k in order)
    scen_divs = "".join(render_scenario(k, scen_all[k], scen_labels[k], total_sims) for k in order)

    def metric_card(e, kind, title, sub):
        color = PALETTE[kind]
        return f'''<div class="entry-card" style="border-top:4px solid {color}">
          <div class="entry-head" style="color:{color}">{title}</div>
          <div class="entry-sub">{sub}</div>
          <table class="picks">
            {"".join(f"<tr><td class='slot'>{SLOT_LABEL[k]}</td><td class='pick'>{escape(e['picks'][k])}</td></tr>" for k in ['tier_A','tier_B','tier_C','tier_D','scoring','conceding','top_scorer'])}
          </table>
          <div class="metrics">
            <div><span>{e['mean_score']:.1f}</span><label>mean pts</label></div>
            <div><span>{e['p10']:.0f}–{e['p90']:.0f}</span><label>P10–P90</label></div>
            <div><span>{pct(e['p_first'])}</span><label>P(1st)</label></div>
            <div><span>{pct(e['p_top2'])}</span><label>P(top-2)</label></div>
            <div><span>{e['ev_net']:+.0f}</span><label>EV net (ILS)</label></div>
          </div>
        </div>'''

    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Cup 2026 - How We Built Our Two Bets</title>
<style>
  :root {{ --safe:{PALETTE['safe']}; --risky:{PALETTE['risky']}; --ink:{PALETTE['ink']};
           --muted:{PALETTE['muted']}; --grid:{PALETTE['grid']}; --accent:{PALETTE['accent']}; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         color:var(--ink); line-height:1.65; margin:0; background:#f8fafc; }}
  .wrap {{ max-width:920px; margin:0 auto; padding:0 22px 80px; background:#fff; }}
  header.hero {{ background:linear-gradient(135deg,#0f172a,#1e3a8a); color:#fff; padding:54px 22px 40px; }}
  header.hero .inner {{ max-width:920px; margin:0 auto; }}
  header.hero h1 {{ font-size:2.1rem; margin:0 0 8px; line-height:1.15; }}
  header.hero p {{ color:#cbd5e1; margin:4px 0; }}
  h2 {{ margin-top:48px; font-size:1.5rem; border-bottom:2px solid var(--grid); padding-bottom:6px; }}
  h3 {{ margin-top:28px; font-size:1.15rem; color:#1e293b; }}
  p {{ margin:12px 0; }}
  .lead {{ font-size:1.12rem; color:#334155; }}
  .entries {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin:24px 0; }}
  .entry-card {{ background:#fff; border:1px solid var(--grid); border-radius:12px; padding:18px;
                box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .entry-head {{ font-weight:700; font-size:1.2rem; }}
  .entry-sub {{ color:var(--muted); font-size:.9rem; margin-bottom:10px; }}
  table.picks {{ width:100%; border-collapse:collapse; margin:6px 0 12px; }}
  table.picks td {{ padding:4px 6px; border-bottom:1px solid #f1f5f9; font-size:.93rem; }}
  table.picks td.slot {{ color:var(--muted); width:42%; }}
  table.picks td.pick {{ font-weight:600; }}
  .metrics {{ display:grid; grid-template-columns:repeat(5,1fr); gap:6px; text-align:center; }}
  .metrics div span {{ display:block; font-weight:700; font-size:1.02rem; }}
  .metrics div label {{ font-size:.66rem; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }}
  .chart {{ width:100%; height:auto; background:#fff; border:1px solid var(--grid);
           border-radius:10px; margin:14px 0; padding:8px; }}
  table.datatbl, table.mini, table.ranktbl {{ width:100%; border-collapse:collapse; margin:14px 0; font-size:.86rem; }}
  table.datatbl th, table.mini th, table.ranktbl th {{ background:#f1f5f9; text-align:left; padding:7px 8px;
        position:sticky; top:0; font-size:.78rem; text-transform:uppercase; letter-spacing:.02em; color:#475569; }}
  table.datatbl td, table.mini td, table.ranktbl td {{ padding:6px 8px; border-bottom:1px solid #f1f5f9; }}
  table.ranktbl tr:nth-child(odd) td {{ background:#fbfdff; }}
  table.ranktbl tr:first-child td {{ font-weight:600; }}
  .scrollbox {{ max-height:330px; overflow-y:auto; border:1px solid var(--grid); border-radius:8px; }}
  .scrollbox table {{ margin:0; }}
  .scrollbox th {{ position:sticky; top:0; }}
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  .callout {{ background:#eff6ff; border-left:4px solid var(--safe); padding:12px 16px; border-radius:0 8px 8px 0; margin:16px 0; }}
  .callout.warn {{ background:#fef2f2; border-color:var(--risky); }}
  .tag {{ display:inline-block; background:#e0e7ff; color:#3730a3; border-radius:999px;
         padding:2px 10px; font-size:.74rem; font-weight:600; margin-right:6px; }}
  footer {{ color:var(--muted); font-size:.84rem; margin-top:50px; border-top:1px solid var(--grid); padding-top:18px; }}
  code {{ background:#f1f5f9; padding:1px 5px; border-radius:4px; font-size:.85em; }}
  /* scenarios */
  .scen-picker {{ position:sticky; top:0; z-index:5; background:#fff; padding:12px 0; border-bottom:1px solid var(--grid); margin-bottom:6px; }}
  .scen-picker select {{ font-size:1rem; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; background:#f8fafc; font-weight:600; color:var(--ink); max-width:100%; }}
  .scenario {{ display:none; }}
  .scenario.active {{ display:block; animation:fade .25s ease; }}
  @keyframes fade {{ from {{ opacity:0; transform:translateY(4px); }} to {{ opacity:1; transform:none; }} }}
  .scen-headline {{ display:flex; gap:14px; align-items:center; background:#f8fafc; border:1px solid var(--grid); border-radius:12px; padding:14px 18px; margin:8px 0 8px; }}
  .scen-headline .trophy {{ font-size:2rem; }}
  .scen-headline .champ {{ font-size:1.2rem; }}
  .scen-headline .champ .vs {{ color:var(--muted); font-size:.92rem; font-weight:400; margin-left:8px; }}
  .scen-note {{ color:#475569; font-size:.86rem; margin-top:3px; }}
  .bracket {{ display:flex; gap:12px; overflow-x:auto; padding:6px 2px 14px; }}
  .bk-col {{ min-width:138px; flex:0 0 auto; display:flex; flex-direction:column; justify-content:space-around; gap:6px; }}
  .bk-col h4 {{ margin:0 0 4px; font-size:.66rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); text-align:center; }}
  .match {{ border:1px solid var(--grid); border-radius:7px; overflow:hidden; font-size:.74rem; background:#fff; }}
  .match .bw {{ padding:3px 7px; font-weight:700; color:var(--ink); background:#eff6ff; }}
  .match .bl {{ padding:3px 7px; color:var(--muted); border-top:1px solid #f1f5f9; }}
  .groups-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }}
  .grp {{ border:1px solid var(--grid); border-radius:8px; padding:6px 8px; font-size:.78rem; }}
  .grp-h {{ font-weight:700; font-size:.74rem; color:#334155; display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px; margin-bottom:3px; }}
  .grp-sub {{ font-weight:400; color:var(--muted); font-size:.62rem; }}
  .grp table {{ width:100%; border-collapse:collapse; }}
  .grp td {{ padding:2px 0; }}
  .grp td.num {{ text-align:right; color:var(--muted); }}
  .grp tr.q td {{ color:var(--ink); }}
  .grp tr.q td:first-child {{ border-left:3px solid var(--accent); padding-left:5px; }}
  .grp tr.out td {{ color:#94a3b8; }}
  .star {{ color:#d97706; }}
  table.scorers {{ width:100%; border-collapse:collapse; font-size:.86rem; }}
  table.scorers th {{ background:#f1f5f9; text-align:left; padding:6px 8px; font-size:.72rem; text-transform:uppercase; color:#475569; }}
  table.scorers td {{ padding:5px 8px; border-bottom:1px solid #f1f5f9; }}
  table.scorers td.num {{ text-align:right; }}
  /* visual explorations */
  .viz {{ border:1px solid var(--grid); border-radius:12px; padding:14px 16px; background:#fff; }}
  .viz h3 {{ margin:0 0 2px; font-size:1rem; }}
  .viz .cap {{ color:var(--muted); font-size:.82rem; margin:0 0 8px; }}
  .tierfilter {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0 14px; }}
  .tierfilter span.lbl {{ color:var(--muted); font-size:.82rem; }}
  .tierfilter button {{ font:inherit; font-size:.8rem; font-weight:600; cursor:pointer;
        border:1px solid var(--grid); border-radius:999px; padding:4px 12px; background:#f8fafc; color:var(--ink); }}
  .tierfilter button.off {{ opacity:.4; text-decoration:line-through; }}
  .tierfilter button[data-tier="A"] {{ border-color:#1d4ed8; }}
  .tierfilter button[data-tier="B"] {{ border-color:#0d9488; }}
  .tierfilter button[data-tier="C"] {{ border-color:#d97706; }}
  .tierfilter button[data-tier="D"] {{ border-color:#9333ea; }}
  @media (max-width:680px) {{ .entries,.two-col {{ grid-template-columns:1fr; }} .metrics {{ grid-template-columns:repeat(3,1fr); }} .groups-grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head>
<body>
<header class="hero"><div class="inner">
  <h1>Mundial 2026: How We Engineered Our Two Bets</h1>
  <p>A {cfg['n_sims']:,}-simulation, market-calibrated model for the friends' World Cup pool.</p>
  <p><span class="tag">Elo + market prior</span><span class="tag">Dixon-Coles Poisson</span>
     <span class="tag">Monte Carlo</span><span class="tag">field-aware optimizer</span></p>
</div></header>
<div class="wrap">

<p class="lead">The bet asks for seven picks - four tier teams, a high-scoring team, a leaky
"conceding" team and the Golden-Boot winner - scored across the whole tournament. With 40-60
rival entries (many of them AI-assisted this year), winning is as much about <em>being different</em>
as about being right. We built two entries: a <b style="color:var(--safe)">SAFE</b> one that
maximises expected payout, and a <b style="color:var(--risky)">RISKY</b>, contrarian one built to
maximise the probability of finishing first.</p>

<h2>The two entries</h2>
<div class="entries">
  {metric_card(safe, "safe", "SAFE - max expected payout", "Highest mean &amp; expected pool winnings; a strong, reliable floor.")}
  {metric_card(risky, "risky", "RISKY - max P(1st), contrarian", f"Low field overlap (ownership sum {risky['field_ownership_sum']:.2f}); built to win outright.")}
</div>
<p>Both entries <b>stack a single contender</b> across the Tier-A slot, the scoring slot and that
team's star striker. This is the model's central finding: because deep tournament runs compound
points across several slots, correlated "stacks" dominate diversified entries in expectation.
The safe entry stacks <b>Argentina + Haaland</b>; the risky entry stacks <b>France + Mbappé</b> -
a side the chalk-heavy field underweights.</p>

<h3>Where the points come from</h3>
<p>Each entry's expected score, decomposed across all seven slots. This is the engine behind the
headline mean: deep-running Tier-A and scoring stacks dominate, the "conceding" slot quietly pays
off when your leaky-or-deep pick keeps playing, and the top-scorer slot is the smallest, most
volatile contributor.</p>
<div class="two-col">
  <div><h3 style="margin-top:0;color:var(--safe)">SAFE - {safe['mean_score']:.0f} pts</h3>{contrib_safe}</div>
  <div><h3 style="margin-top:0;color:var(--risky)">RISKY - {risky['mean_score']:.0f} pts</h3>{contrib_risky}</div>
</div>

<h3>Score distributions (50k simulations)</h3>
{hist_svg}
<p>The safe entry sits further right (higher mean and ceiling); the risky entry trades a little
mean for a payoff profile that is <em>de-correlated from the favourites</em>, which is what lifts
its win probability per unit of field ownership.</p>

<h2>1 · Team strength: Elo, corrected by the market</h2>
<p>We start from authoritative <a href="https://www.eloratings.net">eloratings.net</a> ratings for
all 48 finalists. But pure Elo lags the betting market for a few "brand" teams whose squad quality
outruns recent results - exactly the <b>Germany, France, England and Brazil</b> discrepancy. We
therefore blend in de-vigged outright-winner odds (the way Opta does), mapping market win-probability
onto the Elo scale by regression and mixing 55% market / 45% Elo for teams that have odds.</p>
<div class="callout">
  <b>Worked example - Germany &amp; Norway.</b> eloratings put Germany 11th (1923, behind Colombia
  and Ecuador) and Norway 12th (1912). The market makes Germany a top-7 side (≈6.7% to win) and
  agrees Norway is mid-pack (≈2.8%). The blend lifts Germany to 1962 and nudges Norway to 1914 -
  market-consistent without over-reacting.
</div>
{blend_svg}

<h2>2 · The match &amp; tournament model</h2>
<p>Team strengths feed a <b>Dixon-Coles bivariate Poisson</b> model (attack/defence ratings fit on
time-decayed historical internationals, with a low-score-draw correction and host advantage). A
global strength-spread multiplier is calibrated so simulated title odds match Opta; the grid search
selected <b>spread = {cfg['strength_spread']:.2f}</b>. We then Monte-Carlo the entire 104-match
tournament {cfg['n_sims']:,} times - group stage, all tie-breakers, the eight best third-placed
teams, and the knockout bracket (extra time + a strength-aware shootout model).</p>

<h3>Calibration: our simulation vs Opta vs the market</h3>
{cmp_svg}
<div class="two-col">
  <div>{tsum_tbl}<p style="font-size:.8rem;color:var(--muted)">Simulated run-depth probabilities (top 16 by title odds).</p></div>
  <div>{cal_tbl}<p style="font-size:.8rem;color:var(--muted)">Spread grid search - squared error vs Opta anchors ({", ".join(fit_teams[:6])}…).</p></div>
</div>

<h3>Title probabilities &amp; Golden Boot</h3>
<div class="two-col">
  <div><h3 style="margin-top:0">Most likely champions</h3>{adv_svg}</div>
  <div><h3 style="margin-top:0">Golden Boot race</h3>{gb_svg}</div>
</div>

<h2>3 · Which pick is most attractive, slot by slot</h2>
<p>For every slot we compute each candidate's <b>full points distribution across all 50k sims</b>
(mean, ceiling at P90, and the relevant advancement/title probability). This captures the bet's
quirks: the "conceding" slot rewards teams that go <em>deep</em> (more games = more goals against),
not just weak teams; the scoring slot rewards deep-running attackers.</p>
<div class="two-col">
  <div><h3>Tier A</h3>{tierA_tbl}</div>
  <div><h3>Tier B</h3>{tierB_tbl}</div>
  <div><h3>Tier C</h3>{tierC_tbl}</div>
  <div><h3>Tier D</h3>{tierD_tbl}</div>
  <div><h3>Scoring team</h3>{score_tbl}</div>
  <div><h3>Conceding team</h3>{conc_tbl}</div>
  <div><h3>Top scorer</h3>{ts_tbl}</div>
  <div><h3>What the field picks (Tier A ownership)</h3>{ownA_svg}</div>
  <div><h3>Top-scorer ownership (the crowded Golden Boot)</h3>{ownTS_svg}</div>
</div>
<div class="callout warn">
  <b>The contrarian edge.</b> The modelled field piles ~47% of Tier-A picks onto Spain and crowds
  onto Haaland/Kane for the Golden Boot. To win <em>outright</em> you must beat all of them, so the
  optimizer rewards backing a different elite stack (Argentina, then France) where a deep run leaves
  you alone at the top.
</div>

<h2>3b · Visual explorations</h2>
<p>The same numbers, drawn out. Team scatters are coloured by tier (use the filter to isolate one);
every point has a hover tooltip, and the standout teams plus our own picks are labelled. Use these to
sanity-check the picks: we want high points-contribution, deep runs, and - for the risky entry -
low field ownership.</p>
<div class="tierfilter">
  <span class="lbl">Show tiers:</span>
  <button data-tier="A" onclick="toggleTier('A')">Tier A</button>
  <button data-tier="B" onclick="toggleTier('B')">Tier B</button>
  <button data-tier="C" onclick="toggleTier('C')">Tier C</button>
  <button data-tier="D" onclick="toggleTier('D')">Tier D</button>
</div>
<div class="two-col">
  <div class="viz"><h3>A · Points vs title probability</h3>
    <p class="cap">Expected points contribution against each team's chance of winning the cup.</p>{chartA}</div>
  <div class="viz"><h3>B · Points vs how deep they run</h3>
    <p class="cap">Average stage reached (0 = group exit … 6 = champion) drives points more than raw quality.</p>{chartB}</div>
  <div class="viz"><h3>C · Goals for vs goals against</h3>
    <p class="cap">Tournament totals (what the scoring/conceding slots actually score); point size = expected games, so deep teams sit upper-right. Dashed lines are the medians.</p>{chartC}</div>
  <div class="viz"><h3>E · Contrarian value map</h3>
    <p class="cap">Field ownership (X) vs points (Y). Upper-left is the sweet spot: strong, but rarely picked.</p>{chartE}</div>
  <div class="viz"><h3>F · Risk vs reward per pick</h3>
    <p class="cap">Volatility (std) against expected points - the safe entry hugs the low-std side.</p>{chartF}</div>
  <div class="viz"><h3>D · Entry risk-return frontier</h3>
    <p class="cap">Every ranked candidate entry: mean points (X) vs P(1st) (Y), coloured by objective; our chosen SAFE/RISKY entries are labelled. Point size = net EV.</p>{chartD}</div>
  <div class="viz"><h3>G · Golden Boot scatter</h3>
    <p class="cap">Expected goals against Golden-Boot probability for the leading scorers.</p>{chartG}</div>
  <div class="viz"><h3>H · Calibration check</h3>
    <p class="cap">Market title odds (X) vs our simulation (Y). Points near the dashed y=x line agree with the market.</p>{chartH}</div>
</div>

<h2>4 · The optimizer &amp; the field</h2>
<p>An entry's score distribution is the per-simulation sum of its seven chosen columns, so
correlations are exact (two teams that can meet show negative covariance; doubling a team adds
variance). The ~{cfg['field']['n_entries']}-entry field is modelled <em>empirically</em>, fit to the
pool's own past entries (Euro 2024 + Qatar 2022): the crowd favorite-chases rather than
EV-optimises, piling about {cfg['field']['tier_top_share']:.0%} of tier picks onto the strongest
team, doubling its scoring pick onto an own tier team ~{cfg['field']['doubling_rate']:.0%} of the
time, and stacking the Golden-Boot chalk ({cfg['field']['top_scorer_top_share']:.0%} on the market
favourite). We then run a correlation-aware coordinate ascent with top-K refinement to optimise
expected payout (safe) or P(1st) with a contrarian tilt (risky).</p>

<h2>5 · Ranked alternatives</h2>
<h3 style="color:var(--safe)">SAFE - top 10 by expected payout</h3>
{rank_table(ent["safe_top10"])}
<h3 style="color:var(--risky)">RISKY - top 10 by P(1st), contrarian</h3>
{rank_table(ent["risky_top10"])}
<h3>Reference: top 10 by raw mean points</h3>
{rank_table(ent["mean_top10"])}
<h3>Reference: top 10 by P(top-2)</h3>
{rank_table(ent["ptop2_top10"])}

<h2>Methodology notes &amp; reproducibility</h2>
<p>Everything is split into two stages so the analysis can be re-run offline.
<code>scripts/collect_data.py</code> fetches and freezes all raw inputs into <code>data/processed/</code>
(team draw, schedule, corrected knockout bracket, blended Elo, market odds, player goal shares).
<code>scripts/run_analysis.py</code> consumes only those files to fit the model, calibrate, simulate,
and optimise; <code>scripts/build_report.py</code> renders this page. Key knobs live in
<code>config.py</code> (scoring rules, ridge penalties, field mixture, calibration spread).</p>
<ul>
  <li><b>Strength spread</b> = {cfg['strength_spread']:.2f} (calibrated to Opta).</li>
  <li><b>Golden-Boot scale</b> = {cfg['golden_boot_scale']:.2f} (aligns simulated top-scorer odds to market).</li>
  <li><b>Simulations</b> = {cfg['n_sims']:,} full tournaments.</li>
</ul>

<h2>6 · What the tournament most plausibly looks like</h2>
<p>Finally, a projection of the whole tournament - group standings, the full knockout bracket and
the top-5 scorers. <b>Overall</b> is the unconditional average across all {cfg['n_sims']:,}
simulations. Each entry's view is conditioned on <em>that entry finishing in the money</em>, so you
can see the world in which each bet pays off (the entry's own picks are marked with &#9733;). Use the
selector to switch scenarios.</p>
<div class="scen-picker">
  <label>Scenario:&nbsp;
    <select id="scenSelect" onchange="showScen(this.value)">{options}</select>
  </label>
</div>
{scen_divs}
<script>
  function showScen(k){{
    document.querySelectorAll('.scenario').forEach(function(e){{e.classList.remove('active');}});
    var el=document.getElementById('scen-'+k); if(el) el.classList.add('active');
  }}
  var tierOn={{A:true,B:true,C:true,D:true}};
  function toggleTier(t){{
    tierOn[t]=!tierOn[t];
    document.querySelectorAll('.tierfilter button[data-tier="'+t+'"]').forEach(function(b){{
      b.classList.toggle('off', !tierOn[t]);
    }});
    document.querySelectorAll('.viz svg .g_'+t).forEach(function(g){{
      g.style.display = tierOn[t] ? '' : 'none';
    }});
  }}
</script>

<footer>
  <p>Model and report generated for the friends' Mundial 2026 pool. Probabilities are model estimates,
  not guarantees - the whole point of the bet is that the ball is round. Data: eloratings.net,
  market outright odds (DraftKings via FOX/ESPN), Opta title projections, historical internationals.</p>
</footer>
</div></body></html>'''

    out = REPORT_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
