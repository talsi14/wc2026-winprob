"""Stage 3b - build the two-entry (pair) strategy article (report/pairs.html).

Reads results/pair_entries.json + results/pair_coverage.json (from
run_pair_analysis.py) plus the shared results/ CSVs, and renders a single
self-contained HTML page explaining why the right decision is a *pair* of
entries optimized jointly, and which pair to play. Reuses the SVG/table helpers
and palettes from build_report.py and adds a few pair-specific visualizations.
"""
from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wc2026_bet.config import DATA_PROCESSED, REPORT_DIR, RESULTS_DIR

from build_report import (PALETTE, SLOT_COLORS, SLOT_LABEL, TIER_COLORS, pct,
                          svg_contrib, svg_hbar, svg_scatter, table)

SLOT_ORDER = ["tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding", "top_scorer"]
# coverage-quadrant palette (re-used across the joint-margin / union charts)
Q_BOTH = "#7c3aed"      # both entries in the money
Q_A = "#2563eb"         # only entry 1
Q_B = "#dc2626"         # only entry 2
Q_NONE = "#94a3b8"      # neither


def svg_density(ax, by, union, w=720, h=470, pad=60, nb=42):
    """2D binned density of the joint money-line margins (entry score minus the
    field's 2nd-best). Zero lines are the money-lines; the four quadrants are
    both-miss / A-only / B-only / both-in-money. Bins are coloured by quadrant
    and opacity-scaled by count (sqrt) so ~2.5k points read as a cloud."""
    xs, ys = ax, by
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    def rng(a, b):
        s = (b - a) * 0.06 or 1.0
        return a - s, b + s
    xlo, xhi = rng(xmin, xmax)
    ylo, yhi = rng(ymin, ymax)
    xlo, xhi = min(xlo, -1.0), max(xhi, 1.0)
    ylo, yhi = min(ylo, -1.0), max(yhi, 1.0)

    def X(v): return pad + (v - xlo) / (xhi - xlo) * (w - 2 * pad)
    def Y(v): return h - pad - (v - ylo) / (yhi - ylo) * (h - 2 * pad)

    grid = [[0] * nb for _ in range(nb)]
    for x, y in zip(xs, ys):
        ix = min(nb - 1, max(0, int((x - xlo) / (xhi - xlo) * nb)))
        iy = min(nb - 1, max(0, int((y - ylo) / (yhi - ylo) * nb)))
        grid[iy][ix] += 1
    mx = max(max(r) for r in grid) or 1
    cw = (w - 2 * pad) / nb
    ch = (h - 2 * pad) / nb
    rects = []
    for iy in range(nb):
        for ix in range(nb):
            c = grid[iy][ix]
            if not c:
                continue
            xc = xlo + (ix + 0.5) / nb * (xhi - xlo)
            yc = ylo + (iy + 0.5) / nb * (yhi - ylo)
            col = (Q_BOTH if (xc > 0 and yc > 0) else Q_NONE if (xc < 0 and yc < 0)
                   else Q_A if (xc > 0) else Q_B)
            op = 0.10 + 0.80 * (c / mx) ** 0.5
            x0 = pad + ix * cw
            y0 = h - pad - (iy + 1) * ch
            rects.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{cw+0.6:.1f}" '
                         f'height="{ch+0.6:.1f}" fill="{col}" fill-opacity="{op:.3f}"/>')
    x0l, y0l = X(0), Y(0)
    zero = (f'<line x1="{x0l:.1f}" y1="{pad}" x2="{x0l:.1f}" y2="{h-pad}" stroke="{PALETTE["ink"]}" stroke-dasharray="5 4" stroke-opacity="0.8"/>'
            f'<line x1="{pad}" y1="{y0l:.1f}" x2="{w-pad}" y2="{y0l:.1f}" stroke="{PALETTE["ink"]}" stroke-dasharray="5 4" stroke-opacity="0.8"/>')

    def qlabel(tx, ty, anchor, title, val, col):
        return (f'<text x="{tx:.0f}" y="{ty:.0f}" font-size="11.5" font-weight="700" '
                f'fill="{col}" text-anchor="{anchor}">{escape(title)}</text>'
                f'<text x="{tx:.0f}" y="{ty+15:.0f}" font-size="11" fill="{PALETTE["muted"]}" '
                f'text-anchor="{anchor}">{val*100:.1f}% of sims</text>')
    labels = (
        qlabel(w - pad - 6, pad + 14, "end", "Both in the money", union["both"], Q_BOTH)
        + qlabel(w - pad - 6, h - pad - 24, "end", "Only Entry 1 cashes", union["a_only"], Q_A)
        + qlabel(pad + 6, pad + 14, "start", "Only Entry 2 cashes", union["b_only"], Q_B)
        + qlabel(pad + 6, h - pad - 24, "start", "Neither cashes", union["neither"], Q_NONE))
    ticks = []
    for i in range(5):
        xv = xlo + i * (xhi - xlo) / 4
        yv = ylo + i * (yhi - ylo) / 4
        ticks.append(f'<text x="{X(xv):.1f}" y="{h-pad+16}" font-size="10" fill="{PALETTE["muted"]}" text-anchor="middle">{xv:+.0f}</text>'
                     f'<text x="{pad-8}" y="{Y(yv)+3:.1f}" font-size="10" fill="{PALETTE["muted"]}" text-anchor="end">{yv:+.0f}</text>')
    return f'''<svg viewBox="0 0 {w} {h}" class="chart" role="img">
      <rect x="{pad}" y="{pad}" width="{w-2*pad}" height="{h-2*pad}" fill="#fff"/>
      {"".join(rects)}{zero}{"".join(ticks)}{labels}
      <line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="{PALETTE['muted']}"/>
      <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h-pad}" stroke="{PALETTE['muted']}"/>
      <text x="{w/2:.0f}" y="{h-6}" font-size="12" fill="{PALETTE['muted']}" text-anchor="middle">Entry 1 margin over the money-line (points)</text>
      <text x="16" y="{h/2:.0f}" font-size="12" fill="{PALETTE['muted']}" text-anchor="middle" transform="rotate(-90 16 {h/2:.0f})">Entry 2 margin over the money-line</text>
    </svg>'''


def svg_stacked_bar(rows, w=720, rowh=40, pad=170, scale=None, legend=None,
                    fmt=lambda v: f"{v:.0%}", label_min=0.06):
    """Horizontal stacked bars. rows = [(row_label, [(seg_label, value, color), ...])].
    Bars share a common ``scale`` (max row total if None). ``legend`` overrides
    the auto legend (list of (label, color))."""
    h = rowh * len(rows) + 46
    maxtot = scale or max((sum(v for _, v, _ in segs) for _, segs in rows), default=1) or 1
    barW = w - pad - 64
    out = []
    for i, (label, segs) in enumerate(rows):
        y = 14 + i * rowh
        out.append(f'<text x="{pad-10}" y="{y+rowh*0.45:.0f}" font-size="12" fill="{PALETTE["ink"]}" '
                   f'text-anchor="end">{escape(str(label))}</text>')
        x = pad
        tot = 0.0
        for seg_label, v, color in segs:
            ww = v / maxtot * barW
            tot += v
            out.append(f'<rect x="{x:.1f}" y="{y:.0f}" width="{max(ww,0):.1f}" height="{rowh*0.62:.0f}" '
                       f'fill="{color}"><title>{escape(seg_label)}: {fmt(v)}</title></rect>')
            if v >= label_min:
                out.append(f'<text x="{x+ww/2:.1f}" y="{y+rowh*0.42:.0f}" font-size="10.5" '
                           f'fill="#fff" font-weight="600" text-anchor="middle">{fmt(v)}</text>')
            x += ww
        out.append(f'<text x="{x+6:.1f}" y="{y+rowh*0.42:.0f}" font-size="10.5" '
                   f'fill="{PALETTE["muted"]}">{fmt(tot)}</text>')
    leg = legend if legend is not None else (
        [(sl, c) for sl, _, c in rows[0][1]] if rows else [])
    lx = pad
    legrow = []
    for j, (sl, c) in enumerate(leg):
        legrow.append(f'<rect x="{lx:.0f}" y="{h-20}" width="11" height="11" fill="{c}" rx="2"/>'
                      f'<text x="{lx+16:.0f}" y="{h-11}" font-size="11" fill="{PALETTE["ink"]}">{escape(sl)}</text>')
        lx += 22 + len(sl) * 6.6
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(out)}{"".join(legrow)}</svg>'


def coverage_matrix(rows):
    """Scenario-coverage table. rows = [{champion, p_champ, rank_a, rank_b, p_inmoney}].
    Median ranks are colour-scaled (greener = better/closer to 1st)."""
    def rank_cell(r):
        # 1 (great) -> green ; >=8 (poor) -> red
        t = max(0.0, min(1.0, (r - 1) / 7.0))
        g = (int(220 - t * 120), int(245 - t * 70), int(225 - t * 95))
        return (f'<td style="background:rgb{g};text-align:center;font-weight:600">'
                f'{r:.0f}</td>')
    body = []
    for r in rows:
        carrier = "Entry 1" if r["rank_a"] < r["rank_b"] else "Entry 2"
        body.append(
            f'<tr><td style="font-weight:600">{escape(r["champion"])}</td>'
            f'<td style="text-align:center">{r["p_champ"]*100:.1f}%</td>'
            f'{rank_cell(r["rank_a"])}{rank_cell(r["rank_b"])}'
            f'<td style="text-align:center">{r["p_inmoney"]*100:.0f}%</td>'
            f'<td style="text-align:center;color:{Q_A if carrier=="Entry 1" else Q_B};font-weight:600">{carrier}</td></tr>')
    head = ("<tr><th>If the champion is…</th><th>P(champion)</th><th>Entry 1 median rank</th>"
            "<th>Entry 2 median rank</th><th>Pair in money</th><th>Who carries</th></tr>")
    return f'<table class="datatbl">{head}<tbody>{"".join(body)}</tbody></table>'


STAGE_W = {"round_Group stage": 0, "round_Round of 32": 1, "round_Round of 16": 2,
           "round_Quarter-final": 3, "round_Semi-final": 4, "round_Final": 5,
           "round_Champion": 6}


def entry_card(e, idx, color, pair):
    rows = "".join(
        f"<tr><td class='slot'>{SLOT_LABEL[k]}</td><td class='pick'>{escape(e['picks'][k])}</td></tr>"
        for k in SLOT_ORDER)
    return f'''<div class="entry-card" style="border-top:4px solid {color}">
      <div class="entry-head" style="color:{color}">Entry {idx}</div>
      <div class="entry-sub">one half of the recommended pair</div>
      <table class="picks">{rows}</table>
      <div class="metrics">
        <div><span>{e['mean_score']:.1f}</span><label>mean pts</label></div>
        <div><span>{e['p10']:.0f}–{e['p90']:.0f}</span><label>P10–P90</label></div>
        <div><span>{pct(e['p_first'])}</span><label>P(1st) solo</label></div>
        <div><span>{pct(e['p_top2'])}</span><label>P(top-2) solo</label></div>
        <div><span>{e['own_total']:.2f}</span><label>field overlap</label></div>
      </div>
    </div>'''


def team_charts(attr, team):
    tiers, tmean = {}, {}
    for letter in "ABCD":
        for r in attr[f"tier_{letter}"].itertuples():
            tiers[r.candidate] = letter
            tmean[r.candidate] = float(r.mean)
    team = team.copy()
    team["avg_stage"] = sum(team[c] * w for c, w in STAGE_W.items())
    color_map = {f"Tier {L}": TIER_COLORS[L] for L in "ABCD"}
    rows = []
    for r in team.itertuples():
        t = r.team
        if t not in tiers:
            continue
        rows.append({"team": t, "tier": tiers[t], "pts": tmean[t], "title": r.P_title,
                     "stage": r.avg_stage, "gf": r.exp_gf, "ga": r.exp_ga,
                     "games": r.exp_games})
    return rows, color_map


def main():
    R, D = RESULTS_DIR, DATA_PROCESSED
    pe = json.loads((R / "pair_entries.json").read_text())
    cov = json.loads((R / "pair_coverage.json").read_text())
    team = pd.read_csv(R / "team_summary.csv")
    players = pd.read_csv(R / "player_summary.csv")
    attr = {n: pd.read_csv(R / f"attractiveness_{n}.csv") for n in SLOT_ORDER}
    cfg = pe["config"]

    tgtA, tgtB = pe["targets"]["A"], pe["targets"]["B"]
    eA, eB = tgtA["entries"]
    pairA = tgtA["pair"]
    base = pe["baseline"]
    cA = cov["A"]
    same = [eA["picks"], eB["picks"]] == [e["picks"] for e in tgtB["entries"]]

    # Optional personal-preference variant (Entry 2: Spain -> Argentina).
    var = tgtA.get("variant_argentina")
    cVar = cov.get("A_argentina")
    has_variant = var is not None and cVar is not None

    attr_mean = {n: {r.candidate: float(r.mean) for r in attr[n].itertuples()} for n in SLOT_ORDER}

    def contrib_rows(e):
        return [(f"{SLOT_LABEL[k]}: {e['picks'][k]}", attr_mean[k].get(e['picks'][k], 0.0),
                 SLOT_COLORS[k]) for k in SLOT_ORDER]

    # ---- per-variant fragments (cards / KPIs / coverage / replacements) ----- #
    def variant_fragments(entries, pairm, covv, repls):
        e1, e2 = entries
        cards = ('<div class="entries">'
                 + entry_card(e1, 1, PALETTE["safe"], pairm)
                 + entry_card(e2, 2, PALETTE["risky"], pairm)
                 + '</div>')
        contrib2 = svg_contrib(contrib_rows(e2))
        u, bu = covv["union"], covv["baseline"]["union"]
        density = svg_density(covv["scatter"]["a"], covv["scatter"]["b"], u)
        union = svg_stacked_bar(
            [("Optimized pair", [("Only Entry 1", u["a_only"], Q_A), ("Both", u["both"], Q_BOTH),
                                 ("Only Entry 2", u["b_only"], Q_B), ("Neither", u["neither"], Q_NONE)]),
             ("Naive duo (two best singles)",
              [("Only Entry 1", bu["a_only"], Q_A), ("Both", bu["both"], Q_BOTH),
               ("Only Entry 2", bu["b_only"], Q_B), ("Neither", bu["neither"], Q_NONE)])],
            scale=1.0, rowh=46,
            legend=[("Only Entry 1 in money", Q_A), ("Both in money", Q_BOTH),
                    ("Only Entry 2", Q_B), ("Neither", Q_NONE)])
        champ_rows = sorted(covv["champions"], key=lambda c: -c["p_champ"])
        champ = svg_stacked_bar(
            [(f'{c["champion"]} ({c["p_champ"]*100:.0f}%)',
              [("Entry 1 cashes", c["carry_a"], Q_A), ("Entry 2 cashes", c["carry_b"], Q_B)])
             for c in champ_rows],
            scale=max(c["carry_a"] + c["carry_b"] for c in champ_rows) * 1.02, rowh=30, pad=150,
            legend=[("Entry 1 in money", Q_A), ("Entry 2 in money", Q_B)])
        scen = coverage_matrix([{"champion": s["champion"],
                                 "p_champ": _pchamp(champ_rows, s["champion"]),
                                 "rank_a": s["median_rank_a"], "rank_b": s["median_rank_b"],
                                 "p_inmoney": s["p_inmoney"]} for s in covv["scenario_matrix"]])
        m = covv["marginal"]
        marg_first = svg_hbar(["Best single entry", "The pair (≥1 first)"],
                              [m["best_single_p_first"], m["pair_p_first"]],
                              PALETTE["safe"], fmt="{:.1%}", pad=160, rowh=30)
        marg_ev = svg_hbar(["Best single entry", "The pair (sum)"],
                           [m["best_single_ev"], m["pair_ev"]],
                           PALETTE["accent"], fmt="{:.0f}", pad=160, rowh=30)
        marginal = (f'<div class="two-col">'
                    f'<div class="viz"><h3>P(finish 1st)</h3>{marg_first}</div>'
                    f'<div class="viz"><h3>Expected payout (ILS)</h3>{marg_ev}</div></div>')
        repl_html = replacement_section({"replacements": repls}, e1, e2)
        cmp_html = comparison_block(pairm, base, covv)
        return {"cards": cards, "contrib2": contrib2, "density": density, "union": union,
                "champ": champ, "scen": scen, "marginal": marginal,
                "repl": repl_html, "kpis": kpi_block(pairm, covv), "cmp": cmp_html,
                "pair": pairm, "cov": covv, "e2": e2}

    frags = {"spain": variant_fragments([eA, eB], pairA, cA, tgtA["replacements"])}
    if has_variant:
        frags["argentina"] = variant_fragments(var["entries"], var["pair"], cVar,
                                                var["replacements"])
    contrib1 = svg_contrib(contrib_rows(eA))

    # ---- reused team-result scatters --------------------------------------- #
    trows, cmap = team_charts(attr, team)
    pair_teams = set()
    for e in (eA, eB):
        for k in ("tier_A", "tier_B", "tier_C", "tier_D", "scoring", "conceding"):
            pair_teams.add(e["picks"][k])
    top_pts = sorted(trows, key=lambda r: -r["pts"])[:12]
    lab = {r["team"] for r in top_pts} | pair_teams

    def pts(rows, xk, yk, sz=True):
        return [{"x": r[xk], "y": r[yk], "label": r["team"], "group": f"Tier {r['tier']}",
                 "size": r["games"] if sz else None,
                 "tip": f"{r['team']} · {r['pts']:.1f} pts · title {r['title']*100:.1f}% · ~{r['games']:.1f} games"}
                for r in rows]
    chartA = svg_scatter(pts(trows, "title", "pts"), cmap, xlab="P(win the cup)",
                         ylab="Expected points contribution", xfmt=lambda v: f"{v*100:.0f}%",
                         label_set=lab, size_range=(min(r["games"] for r in trows), max(r["games"] for r in trows)),
                         legend="br")
    chartB = svg_scatter(pts(trows, "stage", "pts"), cmap, xlab="Average stage reached (0 group … 6 champion)",
                         ylab="Expected points contribution", xfmt=lambda v: f"{v:.1f}",
                         label_set=lab, legend="br")
    chartC = svg_scatter(pts(trows, "gf", "ga"), cmap, xlab="Expected goals FOR (tournament)",
                         ylab="Expected goals AGAINST", label_set=lab, quadrant=True,
                         size_range=(min(r["games"] for r in trows), max(r["games"] for r in trows)),
                         invert_y=True, legend="tr")
    gb = players.head(12)
    gb_svg = svg_hbar(gb["scorer"].tolist(), gb["P_golden_boot"].tolist(),
                      PALETTE["risky"], fmt="{:.1%}", pad=170)

    # ---- pair frontier (always shows BOTH the recommended pair and, if present,
    #      the Argentina-swap alternative, so they can be compared directly) --- #
    fr_pts = []
    for f in pe["frontier"]:
        grp = "Search: max EV" if f["target"] == "A" else "Search: max P(win)"
        fr_pts.append({"x": f["ev"], "y": f["p_first"], "label": "", "group": grp})
    fr_pts.append({"x": pairA["pair_ev_gross"], "y": pairA["p_at_least_one_first"],
                   "label": "★ Recommended pair (Spain)", "group": "★ Recommended pair (Spain)",
                   "tip": "Optimal pair — Entry 2 anchored on Spain"})
    fr_pts.append({"x": base["pair"]["pair_ev_gross"], "y": base["pair"]["p_at_least_one_first"],
                   "label": "Naive duo", "group": "Naive duo",
                   "tip": "Two best independent singles"})
    fr_cmap = {"★ Recommended pair (Spain)": "#d97706", "Naive duo": PALETTE["muted"],
               "Search: max EV": PALETTE["safe"], "Search: max P(win)": PALETTE["risky"]}
    fr_labels = {"★ Recommended pair (Spain)", "Naive duo"}
    if has_variant:
        vp = var["pair"]
        fr_pts.append({"x": vp["pair_ev_gross"], "y": vp["p_at_least_one_first"],
                       "label": "◆ Argentina swap (Entry 2)", "group": "◆ Argentina swap (Entry 2)",
                       "tip": "Same pair but Entry 2 anchored on Argentina"})
        fr_cmap["◆ Argentina swap (Entry 2)"] = "#0ea5e9"
        fr_labels.add("◆ Argentina swap (Entry 2)")
    frontier_svg = svg_scatter(fr_pts, fr_cmap, xlab="Expected pair payout (gross ILS)",
                               ylab="P(at least one finishes 1st)", xfmt=lambda v: f"{v:.0f}",
                               yfmt=lambda v: f"{v*100:.0f}%",
                               label_set=fr_labels, legend="bl")

    body = render_body(cfg, eA, eB, pairA, base, tgtB, cA, same, frags, has_variant, var,
                       contrib1, chartA, chartB, chartC, gb_svg, frontier_svg)

    html = PAGE_HEAD + body + PAGE_TAIL
    out = REPORT_DIR / "pairs.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(html)/1024:.0f} KB)")


def _pchamp(champ_rows, name):
    for c in champ_rows:
        if c["champion"] == name:
            return c["p_champ"]
    return 0.0


def replacement_section(tgt, eA, eB):
    blocks = []
    for idx, (e, repl, color) in enumerate([(eA, tgt["replacements"][0], PALETTE["safe"]),
                                            (eB, tgt["replacements"][1], PALETTE["risky"])], 1):
        flex_labels, flex_vals = [], []
        trows = []
        for k in SLOT_ORDER:
            slot = repl[k]
            alts = slot["alternatives"]
            best_alt = alts[0]["retained"] if alts else 0.0
            flex_labels.append(SLOT_LABEL[k])
            flex_vals.append(best_alt)
            alt_cells = " · ".join(f'{escape(a["label"])} <span class="ret">{a["retained"]*100:.0f}%</span>'
                                   for a in alts[:3]) or "<span class='muted'>no close swap</span>"
            trows.append([SLOT_LABEL[k], f'<b>{escape(slot["current"])}</b>', alt_cells])
        flex = svg_hbar(flex_labels, flex_vals, color, fmt="{:.0%}", pad=150, rowh=26, vmax=1.0)
        tbl = table(["Slot", "Current pick", "Best swap-ins (value retained)"], trows, "datatbl repl")
        blocks.append(f'''<h3 style="color:{color}">Entry {idx} — how locked is each slot?</h3>
        <p class="cap">Bars show the pair-objective value retained by the <em>best alternative</em> in
        each slot (100% = a free swap; low = the current pick is hard to replace). The table lists the
        top swap-ins and the value they keep.</p>{flex}{tbl}''')
    return "".join(blocks)


def kpi_block(pairm, covv):
    return f'''<div class="kpis">
  <div class="kpi"><span>{pct(pairm["p_at_least_one_first"])}</span><label>P(at least one wins)</label></div>
  <div class="kpi"><span>{pct(pairm["p_at_least_one_top2"])}</span><label>P(at least one cashes)</label></div>
  <div class="kpi"><span>{pairm["pair_ev_net"]:+.0f}</span><label>expected profit (ILS, net)</label></div>
  <div class="kpi"><span>{covv["win_corr"]:+.2f}</span><label>winning correlation</label></div>
</div>'''


def comparison_block(pairm, base, covv):
    win_up = pairm["p_at_least_one_first"] - base["pair"]["p_at_least_one_first"]
    para = (f'<p>Versus the old "best safe + best risky" duo, the jointly-optimized pair lifts the '
            f'chance that one of your entries wins from '
            f'{base["pair"]["p_at_least_one_first"]*100:.1f}% to '
            f'<b>{pairm["p_at_least_one_first"]*100:.1f}%</b> (a {win_up*100:+.1f} pt move) and turns '
            f'the two entries\' winning correlation from {covv["baseline"]["win_corr"]:+.2f} to '
            f'<b>{covv["win_corr"]:+.2f}</b> — they win in genuinely different tournaments.</p>')
    cmp = table(
        ["Metric", "Recommended pair", "Naive duo (two best singles)"],
        [["Expected pair payout (gross)", f'{pairm["pair_ev_gross"]:.0f} ILS', f'{base["pair"]["pair_ev_gross"]:.0f} ILS'],
         ["Expected pair profit (net of 2×fee)", f'{pairm["pair_ev_net"]:+.0f} ILS', f'{base["pair"]["pair_ev_net"]:+.0f} ILS'],
         ["P(at least one finishes 1st)", pct(pairm["p_at_least_one_first"]), pct(base["pair"]["p_at_least_one_first"])],
         ["P(at least one in the money)", pct(pairm["p_at_least_one_top2"]), pct(base["pair"]["p_at_least_one_top2"])],
         ["P(1-2 lockout, both top-2)", pct(pairm["p_lockout"]), pct(base["pair"]["p_lockout"])],
         ["Correlation of winning", f'{covv["win_corr"]:+.2f}', f'{covv["baseline"]["win_corr"]:+.2f}']],
        "datatbl")
    return para + cmp


def render_body(cfg, eA, eB, pairA, base, tgtB, cA, same, frags, has_variant, var,
                contrib1, chartA, chartB, chartC, gb_svg, frontier_svg):
    fee = cfg["entry_fee"]
    p1, p2 = cfg["prize_first_frac"], cfg["prize_second_frac"]
    n_ent = cfg["field"]["n_entries"]
    agree = ("Optimizing for raw win probability returns the <b>identical</b> pair — so there is no "
             "trade-off to manage here." if same else
             "The win-maximizing search lands on a slightly different second entry; we still recommend "
             "the pair below, which is strong on both fronts.")

    def vary(key):
        """Wrap a fragment in Spain/Argentina toggle layers (or return as-is)."""
        if not has_variant:
            return frags["spain"][key]
        return (f'<div class="vary spain">{frags["spain"][key]}</div>'
                f'<div class="vary argentina">{frags["argentina"][key]}</div>')

    def cov_sentence(v):
        f = frags[v]
        m, u = f["cov"]["marginal"], f["cov"]["union"]
        return (f'<p>Our pair\'s best single entry wins {m["best_single_p_first"]*100:.1f}% of the '
                f'time; together they win {m["pair_p_first"]*100:.1f}% — almost additive, because the '
                f'overlap (both win) is only {u["both"]*100:.2f}%.</p>')
    cov_sent = (cov_sentence("spain") if not has_variant else
                f'<div class="vary spain">{cov_sentence("spain")}</div>'
                f'<div class="vary argentina">{cov_sentence("argentina")}</div>')

    toggle_bar = ""
    if has_variant:
        sw = var["swap"]
        toggle_bar = f'''<div class="toggle-bar"><span class="tlabel">Entry 2 anchor</span>
  <button data-v="spain" class="active" onclick="setVar('spain')">{escape(sw["from"])} · recommended</button>
  <button data-v="argentina" onclick="setVar('argentina')">{escape(sw["to"])} · my pick</button>
  <span class="thint">swaps {escape(sw["from"])}→{escape(sw["to"])} in Entry 2 (tier-A + scoring); everything else identical</span>
</div>'''

    return f'''
<header class="hero"><div class="inner">
  <div class="tag">World Cup 2026 · friends' pool</div>
  <h1>Two entries, one decision: the pair that covers the most winning worlds</h1>
  <p>We are allowed two entries. The pool pays only 1st ({p1:.0%}) and 2nd ({p2:.0%}); 3rd and last
  are refunds. So the real question is not "what are my two best guesses?" but
  <b>which <em>pair</em> of entries jointly maximizes my chance of cashing</b> against ~{n_ent} rivals.</p>
</div></header>
{toggle_bar}
<div class="wrap">

<h2>Executive summary</h2>
<p class="lead">Pick the two entries as a <b>portfolio</b>. Because each prize is capped, a second entry
is only worth its slot if it <em>wins in the worlds the first one loses</em>. Optimizing the pair
jointly does exactly that — it backs two strong, <b>de-correlated</b> title routes and fades the
crowd's favourite.</p>

{vary("cards")}

{vary("kpis")}

<div class="callout"><b>Two targets, one answer.</b> We optimized the pair two ways — (A) maximize
<em>expected pair profit</em> and (B) maximize <em>P(at least one wins)</em>. {agree} This is a direct
consequence of the {p1:.0%}/{p2:.0%} two-place payout: getting an entry into the top two is almost the
whole game, so "make money" and "win" pull in the same direction for a pair.</p></div>

{vary("cmp")}

<h2>1 · Why a pair, not two singles</h2>
<p>Think in terms of <b>coverage</b>. Each entry "wins" in some subset of the ~{cfg['n_sims']:,} simulated
tournaments. With two entries your chance of cashing is the <em>union</em> of their winning worlds:</p>
<p style="text-align:center;font-size:1.05rem"><code>P(win) = P(A wins) + P(B wins) − P(both win)</code></p>
<p>If the two entries win in the <em>same</em> worlds, the overlap term is large and the second entry adds
little. If they win in <em>different</em> worlds, the overlap is near zero and the second entry nearly
<b>doubles</b> your coverage. That is why the right notion of "different" is not how many picks differ on
paper (Hamming distance) but <b>how little their winning-indicators correlate</b>.</p>
{cov_sent}
<div class="callout warn"><b>The {p1:.0%}/{p2:.0%} wrinkle.</b> Because 2nd place still pays {p2:.0%},
the very best outcome is a <b>1-2 lockout</b> — both your entries in the top two, collecting the whole
pot. Joint optimization is happy to chase that when it's cheap, but it will not sacrifice coverage for a
rare lockout. So it decorrelates first, and co-places only when a single tournament world is strong for
both.</div>

<h2>2 · Methodology</h2>
<p>Everything sits on the <em>same</em> engine as the <a href="index.html">single-entry report</a>:
authoritative Elo blended with market outright odds, a Dixon-Coles bivariate-Poisson match model,
and <b>{cfg['n_sims']:,}</b> full-tournament Monte-Carlo simulations (group stage → 8-best-thirds →
knockout), seeded identically so every team number matches. For each simulation we already know every
entry's points, so an entry's score is just the per-sim sum of its seven chosen columns — correlations
between picks are exact.</p>
<p>The new part is <b>joint scoring</b>: we drop both of our entries into the same pool as the modelled
~{n_ent}-rival field and rank everyone <em>together</em>, every simulation. The pair objective is then
either the summed prize (Target A) or the indicator that at least one entry is 1st (Target B). We search
with <b>alternating coordinate ascent</b> — fix entry B, optimize each of A's seven slots for the pair
objective, then fix A and optimize B, repeat to convergence — from multiple seeds (the single-entry EV
and win optima, plus contrarian and random starts). No diversity penalty is added by hand;
de-correlation falls out of the objective.</p>

<h2>3 · The building blocks: team expected results</h2>
<p>Before the pair, the per-team inputs (identical to the main report). Scatters are coloured by tier;
hover any point. We want picks that are high up (points), deep-running, and — for the second entry — in
parts of the bracket the field underweights.</p>
<div class="two-col">
  <div class="viz"><h3>A · Points vs title probability</h3>
    <p class="cap">Expected points contribution vs each team's chance of winning the cup; point size = expected games.</p>{chartA}</div>
  <div class="viz"><h3>B · Points vs how deep they run</h3>
    <p class="cap">Average stage reached drives points more than raw quality.</p>{chartB}</div>
  <div class="viz"><h3>C · Goals for vs goals against</h3>
    <p class="cap">Tournament totals; size = expected games. Up-and-right = high-scoring deep runs (good for the scoring slot).</p>{chartC}</div>
  <div class="viz"><h3>Golden Boot race</h3>
    <p class="cap">Top-scorer probabilities for the leading marksmen.</p>{gb_svg}</div>
</div>

<h2>4 · The recommended pair, slot by slot</h2>
<p>Where each entry's expected points come from. Entry 1 anchors on one elite stack; Entry 2 is built to
score in the <em>other</em> tournaments.</p>
<div class="two-col">
  <div class="viz"><h3 style="color:var(--safe)">Entry 1 — points decomposition</h3>{contrib1}</div>
  <div class="viz"><h3 style="color:var(--risky)">Entry 2 — points decomposition</h3>{vary("contrib2")}</div>
</div>

<h2>5 · Coverage: how the pair blankets the bracket</h2>
<h3>Joint money-line margins</h3>
<p>Each dot is one simulation: Entry 1's margin over the field's "money-line" (the 2nd-best rival) on the
x-axis, Entry 2's on the y-axis. The dashed lines are the money-line; the four quadrants are who cashes.
A good pair fills the <b>off-diagonal</b> quadrants (one cashes when the other doesn't) and avoids piling
everything into "neither".</p>
{vary("density")}

<h3>Coverage union — versus a correlated duo</h3>
<p>The same four outcomes as probabilities, for our pair versus the naive "two best singles" duo. Bigger
coloured (in-money) region and a smaller "Both" overlap mean better, cheaper coverage.</p>
{vary("union")}

<h3>Who carries the duo, by champion</h3>
<p>For each likely champion, the chance each entry is in the money. The two entries light up under
<em>different</em> winners — that is the decorrelation, made concrete.</p>
{vary("champ")}

<h3>Scenario coverage matrix</h3>
<p>Median finishing rank of each entry conditional on who wins the cup (greener = closer to 1st), with the
entry that rescues the pair flagged.</p>
{vary("scen")}

<h3>The pair frontier</h3>
<p>Every candidate pair the search explored, plotted as expected pair payout vs P(at least one wins). The
recommended pair sits at the top-right; the <span style="color:#0ea5e9;font-weight:600">◆ Argentina swap</span>
(Entry 2 anchored on Argentina instead of Spain) is marked too, so you can see exactly what the personal
preference costs — the toggle at the top of the page switches every chart between the two.</p>
{frontier_svg}

<h3>The marginal value of the second entry</h3>
<p>What the partner adds on top of the best single entry — on both win probability and expected payout.</p>
{vary("marginal")}

<h2>6 · Replacement options</h2>
<p>If you want to tweak a pick (taste, a late injury, a hunch), these are the swaps that keep the pair
strongest. For each slot we hold the partner entry and the other six slots fixed and re-rank candidates by
the pair objective.</p>
{vary("repl")}

<h2>Notes, caveats &amp; reproducibility</h2>
<ul>
  <li>Same seed, model and calibration as <code>report/index.html</code>; team numbers are identical.</li>
  <li>The ~{n_ent}-entry field is modelled <em>empirically</em> from the pool's own past entries
      (Euro 2024 + Qatar 2022): a favorite-chasing crowd, not EV-optimisers — real rivals will
      differ, so treat ownership as indicative.</li>
  <li>Prizes: 1st = {p1:.0%}, 2nd = {p2:.0%} of the pot; 3rd and last are refunds. Pair payout uses the
      full ladder over both entries' finishing ranks.</li>
  <li>Pipeline: <code>scripts/run_pair_analysis.py</code> (engine in
      <code>src/wc2026_bet/pairs.py</code>) → <code>scripts/build_pairs_report.py</code>. No data
      re-collection.</li>
</ul>
</div>'''


PAGE_HEAD = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Cup 2026 — The Pair That Covers the Most Winning Worlds</title>
<style>
  :root { --safe:#2563eb; --risky:#dc2626; --ink:#0f172a; --muted:#64748b; --grid:#e2e8f0; --accent:#0d9488; }
  * { box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         color:var(--ink); line-height:1.65; margin:0; background:#f8fafc; }
  .wrap { max-width:920px; margin:0 auto; padding:0 22px 80px; background:#fff; }
  header.hero { background:linear-gradient(135deg,#0f172a,#1e3a8a); color:#fff; padding:54px 22px 40px; }
  header.hero .inner { max-width:920px; margin:0 auto; }
  header.hero h1 { font-size:2.05rem; margin:8px 0; line-height:1.18; }
  header.hero p { color:#cbd5e1; margin:8px 0 0; }
  h2 { margin-top:48px; font-size:1.5rem; border-bottom:2px solid var(--grid); padding-bottom:6px; }
  h3 { margin-top:26px; font-size:1.13rem; color:#1e293b; }
  p { margin:12px 0; }
  .lead { font-size:1.12rem; color:#334155; }
  .entries { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin:22px 0; }
  .entry-card { background:#fff; border:1px solid var(--grid); border-radius:12px; padding:18px;
               box-shadow:0 1px 3px rgba(0,0,0,.06); }
  .entry-head { font-weight:700; font-size:1.2rem; }
  .entry-sub { color:var(--muted); font-size:.9rem; margin-bottom:10px; }
  table.picks { width:100%; border-collapse:collapse; margin:6px 0 12px; }
  table.picks td { padding:4px 6px; border-bottom:1px solid #f1f5f9; font-size:.93rem; }
  table.picks td.slot { color:var(--muted); width:46%; }
  table.picks td.pick { font-weight:600; }
  .metrics { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; text-align:center; }
  .metrics div span { display:block; font-weight:700; font-size:1rem; }
  .metrics div label { font-size:.62rem; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
  .kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:20px 0; }
  .kpi { background:#0f172a; color:#fff; border-radius:12px; padding:16px; text-align:center; }
  .kpi span { display:block; font-size:1.7rem; font-weight:800; }
  .kpi label { font-size:.72rem; color:#cbd5e1; text-transform:uppercase; letter-spacing:.03em; }
  .chart { width:100%; height:auto; background:#fff; border:1px solid var(--grid);
           border-radius:10px; margin:14px 0; padding:8px; }
  table.datatbl { width:100%; border-collapse:collapse; margin:14px 0; font-size:.88rem; }
  table.datatbl th { background:#f1f5f9; text-align:left; padding:8px; font-size:.76rem;
        text-transform:uppercase; letter-spacing:.02em; color:#475569; }
  table.datatbl td { padding:7px 8px; border-bottom:1px solid #f1f5f9; }
  table.repl td:last-child { color:#475569; }
  .ret { color:#0d9488; font-weight:600; font-size:.85em; }
  .muted { color:var(--muted); }
  .two-col { display:grid; grid-template-columns:1fr 1fr; gap:20px; }
  .callout { background:#eff6ff; border-left:4px solid var(--safe); padding:12px 16px; border-radius:0 8px 8px 0; margin:16px 0; }
  .callout.warn { background:#fef2f2; border-color:var(--risky); }
  .tag { display:inline-block; background:#1e40af; color:#dbeafe; border-radius:999px;
         padding:3px 12px; font-size:.74rem; font-weight:600; }
  .viz { border:1px solid var(--grid); border-radius:12px; padding:14px 16px; background:#fff; }
  .viz h3 { margin:0 0 2px; font-size:1rem; }
  .viz .cap, p.cap { color:var(--muted); font-size:.82rem; margin:0 0 8px; }
  code { background:#f1f5f9; padding:1px 5px; border-radius:4px; font-size:.85em; }
  a { color:var(--safe); }
  footer { color:var(--muted); font-size:.84rem; margin-top:50px; border-top:1px solid var(--grid); padding-top:18px; }
  /* Spain / Argentina variant toggle */
  .toggle-bar { position:sticky; top:0; z-index:50; display:flex; flex-wrap:wrap; align-items:center;
        gap:10px; background:#0b1220; color:#e2e8f0; padding:10px 22px; border-bottom:1px solid #1e293b;
        box-shadow:0 2px 8px rgba(0,0,0,.25); }
  .toggle-bar .tlabel { font-size:.74rem; text-transform:uppercase; letter-spacing:.05em; color:#94a3b8; font-weight:700; }
  .toggle-bar button { background:#1e293b; color:#cbd5e1; border:1px solid #334155; border-radius:999px;
        padding:6px 16px; font-size:.92rem; font-weight:600; cursor:pointer; transition:all .15s; }
  .toggle-bar button:hover { border-color:#64748b; }
  .toggle-bar button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  .toggle-bar .thint { font-size:.78rem; color:#64748b; margin-left:auto; }
  .vary { display:none; }
  body[data-variant="spain"] .vary.spain { display:block; }
  body[data-variant="argentina"] .vary.argentina { display:block; }
  @media (max-width:760px){ .two-col,.entries,.kpis{ grid-template-columns:1fr; } .toggle-bar .thint{ display:none; } }
</style></head><body data-variant="spain">'''

PAGE_TAIL = '''
<footer>
  <p>World Cup 2026 friends' pool · pair strategy analysis. Built from frozen data and
  seeded simulations; same model as the single-entry report. Estimates, not guarantees —
  football is football.</p>
</footer>
<script>
function setVar(v){
  document.body.dataset.variant = v;
  document.querySelectorAll('.toggle-bar button').forEach(function(b){
    b.classList.toggle('active', b.dataset.v === v);
  });
}
</script>
</body></html>'''


if __name__ == "__main__":
    main()
