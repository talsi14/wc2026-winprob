"""Inject the win-probability sections into the friends-pool report page.

Adds two pieces into the existing (hand-maintained) light-theme RTL page at
``friends_bet/report/index.html`` *without* clobbering it:

  1. A plain-language Hebrew explanation: how the analysis is built, how it will
     update as results accumulate, and why Spain-anchored entries win rarely.
  2. The "Champion-conditional pool winner" matrix (rows = entries, columns =
     possible world champions + overall P(1st) / in-money / P(last)), rendered
     client-side as a light-theme HTML table from results/live_latest.json.

Both pieces are wrapped in sentinel markers so this script is idempotent and
re-runnable whenever a fresh snapshot is produced.

Usage: python3 scripts/build_friends_report.py
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import os
import re
import sys
from pathlib import Path

from i18n_strings import i18n_css, i18n_js

WC_ROOT = Path(__file__).resolve().parents[1]          # .../wc2026_bet
DATA_PROCESSED = WC_ROOT / "data" / "processed"
DATA_LIVE = WC_ROOT / "data" / "live"
DATA_HISTORY = WC_ROOT / "data" / "history"
# The shareable page lives in a sibling ``friends_bet`` folder. By default we
# resolve it relative to the parent of wc2026_bet (the repo root), and allow an
# explicit override via FRIENDS_REPORT_OUT so the pipeline is portable.
OUT = Path(os.environ.get(
    "FRIENDS_REPORT_OUT",
    str(Path(__file__).resolve().parents[2] / "friends_bet" / "report" / "index.html"),
))

CHAMP_HE = {
    "Spain": "ספרד", "France": "צרפת", "Argentina": "ארגנטינה", "England": "אנגליה",
    "Portugal": "פורטוגל", "Netherlands": "הולנד", "Brazil": "ברזיל",
    "Germany": "גרמניה", "Norway": "נורווגיה", "Colombia": "קולומביה",
}

# Teams not present in he_aliases.json (nobody picked them) - filled in manually
# so the group tables can show every team in Hebrew.
TEAM_HE_EXTRA = {
    "Bosnia and Herzegovina": "בוסניה והרצגובינה", "Paraguay": "פרגוואי",
    "Ecuador": "אקוודור", "Saudi Arabia": "ערב הסעודית",
    "Algeria": "אלג'יריה", "Ghana": "גאנה",
}


def _team_he_map() -> dict:
    """English canonical -> Hebrew, inverted from he_aliases.json + extras."""
    f = WC_ROOT / "data" / "processed" / "he_aliases.json"
    en2he = {}
    if f.exists():
        teams = json.loads(f.read_text()).get("teams", {})
        en2he = {v: k for k, v in teams.items()}
    en2he.update(TEAM_HE_EXTRA)
    return en2he


def groups_html(data: dict) -> str:
    """Per-group standings cards: played / points / GD / qualify% (P reach R32).
    Top two of each group (by the run_live_update sort) are highlighted."""
    groups = data.get("groups") or {}
    if not groups:
        return ""
    he = _team_he_map()
    cards = []
    for g in sorted(groups):
        rows = []
        for i, t in enumerate(groups[g]):
            nm = _te(t["team"], he)
            cls = " class=\"qual\"" if i < 2 else ""
            rows.append(
                f'<tr{cls}><td class="gt">{nm}</td>'
                f'<td>{t["played"]}</td><td>{t["points"]}</td>'
                f'<td dir="ltr">{t["gd"]:+d}</td>'
                f'<td class="gq">{t["p_advance"]*100:.0f}%</td></tr>')
        cards.append(
            f'<div class="gcard"><div class="gh"><span data-i18n="groups.group">בית</span> {g}</div>'
            f'<table class="gtbl"><thead><tr>'
            f'<th data-i18n="groups.team">נבחרת</th>'
            f'<th data-i18n="groups.played">מ׳</th>'
            f'<th data-i18n="groups.pts">נק׳</th>'
            f'<th data-i18n="groups.gd">הפרש</th>'
            f'<th data-i18n="groups.advance">העפלה</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')
    return (
        '\n  <section>\n'
        '    <h2 style="margin-top:6px" data-i18n="groups.title">טבלאות הבתים — סיכויי העפלה</h2>\n'
        '    <p class="sub" data-i18n="groups.sub" data-i18n-html>לכל בית: מספר משחקים ששוחקו (מ׳), '
        'נקודות (נק׳), הפרש שערים, וההסתברות להעפיל לשלב הנוק‑אאוט לפי הסימולציה (העפלה). '
        'שתי הנבחרות המודגשות הן המועמדות המובילות להעפלה מכל בית.</p>\n'
        f'    <div class="ggrid">{"".join(cards)}</div>\n'
        '  </section>\n')

def _player_he_map() -> dict:
    """English canonical player -> Hebrew, inverted from he_aliases.json."""
    f = WC_ROOT / "data" / "processed" / "he_aliases.json"
    en2he = {}
    if f.exists():
        for he, en in (json.loads(f.read_text()).get("players", {})).items():
            en2he.setdefault(en, he)          # first (canonical) spelling wins
    return en2he


def _te(en: str, he_map: dict | None = None) -> str:
    """Team name span — switches Hebrew/English with the lang toggle."""
    he = (he_map or _team_he_map()).get(en, en)
    return (f'<span class="i18nte" data-en="{html_mod.escape(en, quote=True)}">'
            f'{html_mod.escape(he)}</span>')


def _tp(en: str, pl_map: dict | None = None) -> str:
    """Player name span — switches Hebrew/English with the lang toggle."""
    he = (pl_map or _player_he_map()).get(en, en)
    return (f'<span class="i18npl" data-en="{html_mod.escape(en, quote=True)}">'
            f'{html_mod.escape(he)}</span>')


def _g(x) -> str:
    """Compact number: 3.0 -> '3', 2.5 -> '2.5'."""
    return f"{x:g}"


def podium_html(data: dict) -> str:
    """Podium for the live standings: 1st / 2nd / 3rd + the last place, each with
    its prize, in the lovable-style 4-card layout (gold centre, elevated)."""
    ents = data.get("entries") or []
    by_rank = {e.get("current_rank"): e for e in ents if e.get("current_rank")}
    if not by_rank:
        return ""
    n = data.get("n_entries", len(ents))
    prize = {1: 1800, 2: 750, 3: 50, n: 50}
    # visual order: silver, gold (centre/elevated), bronze, last
    spec = [(2, "silver", "🥈"), (1, "gold", "🥇"), (3, "bronze", "🥉"), (n, "last", "💩")]
    cards = []
    for rk, cls, medal in spec:
        e = by_rank.get(rk)
        if not e:
            continue
        cards.append(
            f'<div class="pcard {cls}"><div class="medal">{medal}</div>'
            f'<div class="pname" title="{e["name"]}">{e["name"]}</div>'
            f'<div class="ppts">{_g(e["current_points"])} <small data-i18n="pts.abbr">נק׳</small></div>'
            f'<div class="pprize">₪{prize.get(rk, 0):,}</div></div>')
    return (
        '\n  <section class="podwrap">\n'
        '    <h2 class="bigsec real" data-i18n="podium.title">טבלת הדירוג</h2>\n'
        f'    <div class="podium">{"".join(cards)}</div>\n  </section>\n')


def standings_table_html(data: dict) -> str:
    """Full standings table: rank, change, name, points, P(1st), in-money, and the
    7 picks — each pick annotated with the points it has earned so far."""
    ents = data.get("entries") or []
    if not ents:
        return ""
    team_he, pl_he = _team_he_map(), _player_he_map()
    rows_sorted = sorted(ents, key=lambda e: e.get("current_rank") or 1e9)

    def chg(e) -> str:
        d = e.get("d_current_rank")
        if not d:
            return '<span class="chg-eq">–</span>'
        return (f'<span class="chg-up">▲{-d}</span>' if d < 0
                else f'<span class="chg-dn">▼{d}</span>')

    def pick(name_en, pts, player=False) -> str:
        he = _tp(name_en, pl_he) if player else _te(name_en, team_he)
        return f'<td class="pick">{he} <small>({_g(pts)})</small></td>'

    trs = []
    for e in rows_sorted:
        p, bd = e["picks"], e.get("pts_breakdown", {})
        trs.append(
            f'<tr><td class="rk">{e["current_rank"]}</td>'
            f'<td>{chg(e)}</td>'
            f'<td class="nm" title="{e["name"]}">{e["name"]}</td>'
            f'<td class="pts">{_g(e["current_points"])}</td>'
            + pick(p["tierA"], bd.get("tierA", 0))
            + pick(p["tierB"], bd.get("tierB", 0))
            + pick(p["tierC"], bd.get("tierC", 0))
            + pick(p["tierD"], bd.get("tierD", 0))
            + pick(p["scoring"], bd.get("scoring", 0))
            + pick(p["conceding"], bd.get("conceding", 0))
            + pick(p["top_scorer"], bd.get("top_scorer", 0), player=True)
            + f'<td class="p1">{e["P_first"]*100:.1f}%</td>'
            + f'<td class="pm">{e["P_top2"]*100:.1f}%</td>'
            + '</tr>')
    head = ('<tr>'
            '<th data-i18n="th.rank">מקום</th><th data-i18n="th.change">שינוי</th>'
            '<th class="nm" data-i18n="th.name">שם</th><th data-i18n="th.pts">נק׳</th>'
            '<th data-i18n="th.tierA">דרג א׳</th><th data-i18n="th.tierB">דרג ב׳</th>'
            '<th data-i18n="th.tierC">דרג ג׳</th><th data-i18n="th.tierD">דרג ד׳</th>'
            '<th data-i18n="th.scoring">כובשת</th><th data-i18n="th.conceding">סופגת</th>'
            '<th data-i18n="th.top_scorer">מלך שערים</th>'
            '<th data-i18n="th.win">זכייה</th><th data-i18n="th.in_money">תוך הכסף</th></tr>')
    return (
        '\n  <section>\n'
        '    <p class="sub" style="margin-top:4px" data-i18n="standings.sub" data-i18n-html>'
        'כל הטפסים מדורגים לפי הניקוד בפועל. '
        'העמודות <b>זכייה</b> ו<b>תוך הכסף</b> הן הסתברויות מהסימולציה (מקום 1, ומקום 1–2). '
        'בכל בחירה מוצג בסוגריים מספר הנקודות שצברה עד כה.</p>\n'
        '    <button type="button" class="racebtn" data-race="leaderboard" '
        'data-i18n="race.btn.leaderboard">מרוץ הנקודות — 10 המובילים</button>\n'
        f'    <div class="standwrap"><table class="standtbl"><thead>{head}</thead>'
        f'<tbody>{"".join(trs)}</tbody></table></div>\n  </section>\n')


# thin white-line icons for the leader widgets (match the dark-card screenshot)
_IC_CROWN = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l4 4 5-6 5 6 4-4-2 12H5L3 7z"/></svg>')
_IC_SHIELD = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
              'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6l7-3z"/>'
              '<line x1="12" y1="8.5" x2="12" y2="13"/><circle cx="12" cy="15.8" r=".7" fill="currentColor"/></svg>')
_IC_GAUGE = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
             'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>'
             '<circle cx="12" cy="12" r="4"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/></svg>')


def leaders_html(data: dict) -> str:
    """Three live-leader widgets - top scoring team / top conceding team / current
    top scorer - styled like the lovable dark cards. Clicking a card opens a
    hovering, scrollable table of that category's full ranking; teams/scorers
    picked by participants are bolded. Shows 'טרם זמין' until results exist."""
    team_he, pl_he = _team_he_map(), _player_he_map()
    tp = data.get("team_played") or {}
    scorers = data.get("scorers") or []
    ents = data.get("entries") or []
    sel_scoring = {e["picks"]["scoring"] for e in ents}
    sel_conceding = {e["picks"]["conceding"] for e in ents}
    sel_scorer = {e["picks"]["top_scorer"] for e in ents}
    live_teams = set(data.get("live_teams") or [])     # teams playing right now
    _dot = ('<span class="lt-dot" data-i18n-title="live.match"></span>')

    def live_mark(team):
        return _dot if team in live_teams else ''

    played = [(t, int(v.get("gf", 0)), int(v.get("ga", 0)))
              for t, v in tp.items() if int(v.get("games", 0)) > 0]
    gf_rank = sorted(played, key=lambda x: (-x[1], x[0]))
    ga_rank = sorted(played, key=lambda x: (-x[2], x[0]))

    def team_rows(rank, val_i, sel):
        body = ""
        for row in rank:
            t = row[0]
            hit = ' class="hit"' if t in sel else ''
            body += (f'<tr{hit}><td class="nm">{_te(t, team_he)}{live_mark(t)}</td>'
                     f'<td class="v">{row[val_i]}</td></tr>')
        return body or '<tr><td class="nm" colspan="2" data-i18n="na">טרם זמין</td></tr>'

    def scorer_rows():
        body = ""
        for s in scorers:
            raw_tm = s.get("team", "") or ""
            hit = ' class="hit"' if s["scorer"] in sel_scorer else ''
            body += (f'<tr{hit}><td class="nm">{_tp(s["scorer"], pl_he)}{live_mark(raw_tm)}</td>'
                     f'<td class="tm">{_te(raw_tm, team_he)}</td>'
                     f'<td class="v">{s["goals"]}</td></tr>')
        return body or '<tr><td class="nm" colspan="3" data-i18n="na">טרם זמין</td></tr>'

    def lead_team(rank, val_i, player=False):
        if not rank:
            return ('<span data-i18n="na">טרם זמין</span>', "—")
        row = rank[0]
        if player:
            return (_tp(row[0], pl_he), f"({row[val_i]})")
        return (_te(row[0], team_he), f"({row[val_i]})")

    sc_name, sc_val = lead_team(gf_rank, 1)
    cc_name, cc_val = lead_team(ga_rank, 2)
    if scorers:
        ks_name = _tp(scorers[0]["scorer"], pl_he)
        ks_val = f'({scorers[0]["goals"]})'
    else:
        ks_name, ks_val = '<span data-i18n="na">טרם זמין</span>', "—"

    cards = [
        ("scorer", _IC_CROWN, "leader.top_scorer", ks_name, ks_val,
         f'<table class="ltbl"><tbody>{scorer_rows()}</tbody></table>'),
        ("conceding", _IC_SHIELD, "leader.conceding", cc_name, cc_val,
         f'<table class="ltbl"><tbody>{team_rows(ga_rank, 2, sel_conceding)}</tbody></table>'),
        ("scoring", _IC_GAUGE, "leader.scoring", sc_name, sc_val,
         f'<table class="ltbl"><tbody>{team_rows(gf_rank, 1, sel_scoring)}</tbody></table>'),
    ]
    live = bool(data.get("live_widgets"))
    live_dot = ('<span class="lc-live" data-i18n-title="live.tooltip">'
                '<span class="lc-pulse"></span><span data-i18n="live.badge">חי</span></span>') if live else ''
    out = ""
    for cls, ic, title_key, name, val, tbl in cards:
        out += (f'<div class="lcard {cls}" tabindex="0">'
                f'<div class="lc-top"><span class="lc-ic">{ic}</span>'
                f'<span class="lc-title" data-i18n="{title_key}"></span>{live_dot}</div>'
                f'<div class="lc-val">{name}</div>'
                f'<div class="lc-sub">{val}</div>'
                f'<div class="lpop">{tbl}</div></div>')
    return f'\n  <section class="leaders">{out}</section>\n'


LEADERS_JS = """
(function(){
  const cards = Array.from(document.querySelectorAll('.lcard'));
  if(!cards.length) return;
  cards.forEach(card=>{
    card.addEventListener('click', function(ev){
      if (ev.target.closest('.lpop')){ ev.stopPropagation(); return; }  // keep open while using the table
      const isOpen = card.classList.contains('open');
      cards.forEach(c=>c.classList.remove('open'));
      if(!isOpen) card.classList.add('open');
      ev.stopPropagation();
    });
  });
  document.addEventListener('click', ()=> cards.forEach(c=>c.classList.remove('open')));
})();
"""


HTML_START, HTML_END = "<!-- WINPROB:START -->", "<!-- WINPROB:END -->"
JS_START, JS_END = "/* WINPROB:JS:START */", "/* WINPROB:JS:END */"
CSS_START, CSS_END = "/* WINPROB:CSS:START */", "/* WINPROB:CSS:END */"
WHATIF_START, WHATIF_END = "<!-- WHATIF:START -->", "<!-- WHATIF:END -->"
ODDS_START, ODDS_END = "<!-- ODDS:START -->", "<!-- ODDS:END -->"
CHEER_START, CHEER_END = "<!-- CHEER:START -->", "<!-- CHEER:END -->"
STAGES_START, STAGES_END = "<!-- STAGES:START -->", "<!-- STAGES:END -->"


def replace_region(html: str, start: str, end: str, content: str) -> str:
    """Replace the text between persistent ``start``/``end`` markers in place.

    Idempotent: re-running the build always overwrites the prior content. Uses a
    function replacement so backslashes in ``content`` are inserted literally.
    """
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    repl = f"{start}\n{content}\n{end}"
    if not pat.search(html):
        raise SystemExit(f"markers {start!r}..{end!r} not found in the base page")
    return pat.sub(lambda _m: repl, html, count=1)


N_GROUP_MATCHES = 72   # 12 groups x 6
N_KO_MATCHES = 32      # R32(16)+R16(8)+QF(4)+SF(2)+3rd(1)+final(1)


def _fmt_ts(ts: str | None) -> str:
    """'2026-06-11T1952' (UTC label) -> '11/06/2026 19:52 UTC'."""
    if not ts:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.strptime(ts, "%Y-%m-%dT%H%M")
        return dt.strftime("%d/%m/%Y %H:%M") + " UTC"
    except ValueError:
        return str(ts)


def coverage_html(data: dict) -> str:
    """A freshness/coverage strip: when the snapshot was taken and which real
    results are already baked into it (driven by live_latest.json['state'])."""
    st = data.get("state", {}) or {}
    gp = st.get("group_played") or 0
    kp = st.get("ko_played") or 0
    complete = bool(st.get("group_stage_complete"))
    goals = sum((st.get("player_goals") or {}).values())
    when = _fmt_ts(data.get("timestamp"))

    if gp == 0 and kp == 0:
        body_key = "coverage.pre"
        body_vars = "{}"
    else:
        body_key = "coverage.live"
        stage_key = "coverage.stage_done" if complete else "coverage.stage_live"
        body_vars = json.dumps({
            "gp": gp, "total_gp": N_GROUP_MATCHES, "kp": kp, "total_ko": N_KO_MATCHES,
            "goals": goals, "stage": "",
        }, ensure_ascii=False)
        # stage label is itself i18n — inject placeholder replaced client-side
    return (f'<div class="freshness">'
            f'<span class="fresh-when"><span data-i18n="coverage.when">עודכן:</span> {when}</span>'
            f'<span class="fresh-body" data-i18n-fmt="{body_key}" data-i18n-html '
            f'data-i18n-vars=\'{body_vars}\' data-stage-key="{stage_key if gp or kp else ""}"></span></div>')


def explanation_html(n_ent: int, n_sims: int, coverage: str = "") -> str:
    sim_vars = json.dumps({"n_ent": n_ent, "n_sims": f"{n_sims:,}"}, ensure_ascii=False)
    return f"""
  <h2 class="bigsec" data-i18n="sim.title">סימולציית סיכויי זכיה מתעדכנת</h2>
  {coverage}

  <section>
    <h2 style="margin-top:6px" data-i18n="sim.how">איך נבנה הניתוח</h2>
    <p class="sub" data-i18n="sim.how.sub">נתונים + סימולציה — בשפה פשוטה.</p>
    <p data-i18n-fmt="sim.data" data-i18n-html data-i18n-vars='{sim_vars}'></p>
    <p data-i18n-fmt="sim.mc" data-i18n-html data-i18n-vars='{sim_vars}'></p>
    <div class="callout" data-i18n="sim.update" data-i18n-html></div>
    <div class="callout" style="border-right-color:var(--amber); background:#fffbeb;"
         data-i18n="sim.spain" data-i18n-html></div>
  </section>

  <section>
    <h2 style="margin-top:6px" data-i18n="matrix.title">סיכויי ניצחון בהתערבות - מותנה בזהות האלופה</h2>
    <p class="sub" data-i18n="matrix.sub" data-i18n-html></p>
    <button type="button" class="racebtn" data-race="p1" data-i18n="race.btn.p1">מרוץ סיכויי הזכייה — 10 המובילים</button>
    <div class="scrollbox"><div id="cmMatrix"></div></div>
    <p class="sub" style="margin-top:8px" data-i18n="matrix.gold" data-i18n-html></p>
  </section>
"""


def js_block(champs, champs_he, p_title, matrix, order, winprob) -> str:
    payload = {
        "champs": champs,
        "champsHe": champs_he,
        "pTitle": p_title,
        "matrix": matrix,
        "order": order,        # entry names, best expected winnings first
        "winprob": winprob,    # name -> [P_first, P_top2, P_last]
    }
    data = json.dumps(payload, ensure_ascii=False)
    return """
const CMDATA = __DATA__;
function renderMatrix(){
  const I = window.I18N;
  const t = k => I.t(k);
  const T = en => I.team(en);
  const d = CMDATA, host = document.getElementById('cmMatrix');
  if(!host || !d) return;
  const C = d.champs, getp = (c,e)=> (d.matrix[c]&&d.matrix[c][e])||0;
  let mx = 0; for(const c of C) for(const e of d.order) mx = Math.max(mx, getp(c,e));
  const cols = [[t('matrix.p1'),0,'37,99,235'],[t('matrix.in_money'),1,'22,163,74'],[t('matrix.p_last'),2,'220,38,38']];
  const smax = cols.map(([_l,i])=> Math.max(...d.order.map(e=> (d.winprob[e]||[0,0,0])[i]), 1e-9));
  const gold = t => `rgba(217,119,6,${(0.06+0.78*Math.pow(t,0.6)).toFixed(3)})`;
  const tint = (rgb,t) => `rgba(${rgb},${(0.08+0.72*Math.pow(t,0.6)).toFixed(3)})`;
  let h = '<table class="cmtbl"><thead><tr><th class="nm">'+t('matrix.entry')+'</th>';
  for(const c of C){
    h += `<th class="ch"><div>${T(c)}</div>`+
         `<div class="t">${Math.round((d.pTitle[c]||0)*100)}%</div></th>`;
  }
  for(const [lbl,_i,rgb] of cols) h += `<th class="sum" style="color:rgb(${rgb})">${lbl}</th>`;
  h += '</tr></thead><tbody>';
  for(const e of d.order){
    h += `<tr><td class="nm" title="${e}">${e}</td>`;
    for(const c of C){
      const p = getp(c,e);
      const bg = p>0 ? gold(p/mx) : 'transparent';
      h += `<td class="cell" style="background:${bg}">${p>=0.04? Math.round(p*100): ''}</td>`;
    }
    const w = d.winprob[e]||[0,0,0];
    cols.forEach(([_l,i,rgb])=>{
      h += `<td class="cell sum" style="background:${tint(rgb, w[i]/smax[i])}">${(w[i]*100).toFixed(1)}%</td>`;
    });
    h += '</tr>';
  }
  h += '</tbody></table>';
  host.innerHTML = h;
}
renderMatrix();
document.addEventListener('langchange', renderMatrix);
""".replace("__DATA__", data)


CMTBL_CSS = """
  /* lovable-style top hero (logo + title banner image) */
  .herotop{background:#0a1530; text-align:center; line-height:0;}
  .herotop .herologo{display:block; width:100%; max-width:1024px; margin:0 auto; height:auto;}
  header.hero.intro{border-radius:16px; margin:16px 0 4px; padding:30px 22px 24px;}
  /* live win-probability banner */
  h2.bigsec{font-size:1.9rem; margin:56px 0 8px; padding:16px 22px; color:#fff; line-height:1.2;
            background:linear-gradient(135deg,#0b1220,#1e3a8a); border-radius:14px;
            box-shadow:0 6px 20px -10px rgba(30,58,138,.6);}
  h2.bigsec.real{margin-top:14px; background:linear-gradient(135deg,#052e26,#16a34a);
            box-shadow:0 6px 20px -10px rgba(22,163,74,.6);}
  /* live standings podium */
  .podwrap{margin:6px 0 4px;}
  .podium{display:grid; grid-template-columns:repeat(4,1fr); gap:12px; align-items:end;}
  .pcard{border:1px solid var(--line); border-radius:14px; padding:16px 12px; text-align:center;
            background:#fff; position:relative;}
  .pcard .medal{font-size:1.9rem; line-height:1;}
  .pcard .pname{font-weight:800; color:var(--ink); margin:7px 0 2px; font-size:1rem;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .pcard .ppts{font-size:1.55rem; font-weight:800; color:var(--blue);}
  .pcard .ppts small{font-size:.66rem; color:var(--muted); font-weight:600;}
  .pcard .pprize{font-size:.86rem; color:var(--muted); margin-top:2px;}
  .pcard.gold{border-color:#f5c518; box-shadow:0 10px 24px -12px rgba(245,197,24,.85);
            transform:translateY(-10px);}
  .pcard.silver{border-color:#cbd5e1;}
  .pcard.bronze{border-color:#d8b384;}
  .pcard.last{border-color:#fca5a5;}
  /* live standings table */
  .standwrap{max-height:600px; overflow:auto; border:1px solid var(--line);
            border-radius:12px; margin-top:8px;}
  table.standtbl{border-collapse:separate; border-spacing:0; width:100%; font-size:.82rem;
            font-variant-numeric:tabular-nums;}
  table.standtbl thead th{position:sticky; top:0; z-index:2; background:#f8fafc;
            border-bottom:1px solid var(--line); font-weight:700; color:#334155;
            padding:7px 8px; white-space:nowrap;}
  table.standtbl td{padding:6px 8px; border-bottom:1px solid #f1f5f9; white-space:nowrap;
            text-align:center; color:#475569;}
  table.standtbl td.rk{font-weight:800; color:#334155;}
  table.standtbl td.nm{text-align:right; font-weight:700; color:var(--ink); position:sticky;
            right:0; z-index:1; background:#fff; box-shadow:-6px 0 6px -6px rgba(0,0,0,.10);
            max-width:160px; overflow:hidden; text-overflow:ellipsis;}
  table.standtbl thead th.nm{z-index:3; right:0; position:sticky;}
  table.standtbl td.pts{font-weight:800; color:var(--ink);}
  table.standtbl td.p1{font-weight:700; color:var(--blue);}
  table.standtbl td.pm{font-weight:700; color:var(--green);}
  table.standtbl td.pick small{color:var(--muted); font-weight:700; font-size:.78em;}
  table.standtbl tbody tr:nth-child(odd){background:#fcfcfd;}
  table.standtbl tbody tr:nth-child(odd) td.nm{background:#fcfcfd;}
  table.standtbl tbody tr:hover td{background:#f1f5f9;}
  .chg-up{color:var(--green); font-weight:800;}
  .chg-dn{color:#dc2626; font-weight:800;}
  .chg-eq{color:var(--muted);}
  @media (max-width:760px){ .podium{grid-template-columns:repeat(2,1fr);} }
  /* live-leader widgets (clickable dark cards + hovering category tables) */
  .leaders{display:grid; grid-template-columns:repeat(3,1fr); gap:14px; direction:rtl;
            margin:16px 0 6px;}
  .lcard{position:relative; border-radius:16px; padding:15px 18px 22px; color:#e5e7eb;
            cursor:pointer; border:1px solid rgba(255,255,255,.09); min-height:92px;
            user-select:none; transition:border-color .15s, box-shadow .15s;}
  /* NB: avoid filter/transform on hover/active - they create a stacking context
     that would trap .lpop's z-index beneath the standings table's sticky cells. */
  .lcard:hover{border-color:rgba(255,255,255,.28);
            box-shadow:0 10px 26px -14px rgba(0,0,0,.55);}
  .lcard.open{border-color:rgba(255,255,255,.35);}
  .lcard.scorer{background:linear-gradient(135deg,#0f172a,#1f2a44);}
  .lcard.conceding{background:linear-gradient(135deg,#241141,#3a1c5c);}
  .lcard.scoring{background:linear-gradient(135deg,#062a24,#0f3d34);}
  .lc-top{display:flex; align-items:center; justify-content:space-between; gap:8px;
            color:#9aa7b8; font-size:.92rem;}
  .lc-ic{display:inline-flex; color:#cbd5e1; opacity:.92;}
  .lc-ic svg{width:26px; height:26px;}
  .lc-title{font-weight:600;}
  .lc-val{font-size:1.7rem; font-weight:800; color:#fff; margin-top:10px; line-height:1.15;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .lc-sub{color:#9aa7b8; font-weight:700; margin-top:2px;}
  /* live indicator: shown only when the tallies include in-progress matches */
  .lc-top{justify-content:flex-start;}
  .lc-live{margin-inline-start:auto; display:inline-flex; align-items:center; gap:5px;
           color:#fecaca; font-weight:800; font-size:.72rem; letter-spacing:.02em;}
  .lc-pulse{width:8px; height:8px; border-radius:50%; background:#ef4444;
            animation:lcpulse 1.6s infinite;}
  @keyframes lcpulse{0%{box-shadow:0 0 0 0 rgba(239,68,68,.6);}
    70%{box-shadow:0 0 0 7px rgba(239,68,68,0);}100%{box-shadow:0 0 0 0 rgba(239,68,68,0);}}
  .lcard::after{content:"\\25be"; position:absolute; bottom:7px; left:14px; color:#64748b;
            font-size:.85rem; transition:transform .15s;}
  .lcard.open::after{transform:rotate(180deg);}
  .lpop{display:none; position:absolute; top:calc(100% + 8px); right:0; left:0; z-index:60;
            background:#fff; color:#0f172a; border:1px solid var(--line); border-radius:12px;
            box-shadow:0 18px 44px -16px rgba(0,0,0,.5); max-height:320px; overflow:auto;
            direction:rtl; text-align:right;}
  .lcard.open .lpop{display:block;}
  table.ltbl{width:100%; border-collapse:separate; border-spacing:0; font-size:.9rem;
            font-variant-numeric:tabular-nums;}
  table.ltbl td{padding:8px 12px; border-bottom:1px solid #f1f5f9; color:#475569;}
  table.ltbl tr:last-child td{border-bottom:0;}
  table.ltbl td.nm{text-align:right; color:var(--ink);}
  table.ltbl td.tm{text-align:right; color:#64748b;}
  /* red dot next to a team/player whose match is in progress right now */
  .lt-dot{display:inline-block; width:8px; height:8px; border-radius:50%;
            background:#ef4444; margin-inline-start:7px; vertical-align:middle;
            animation:lcpulse 1.6s infinite;}
  table.ltbl td.v{text-align:center; font-weight:800; color:var(--green); width:54px;}
  table.ltbl tr.hit td{font-weight:800; color:var(--ink); background:#f0fdf4;}
  table.ltbl tr.hit td.nm{box-shadow:inset 3px 0 0 var(--green);}
  table.ltbl tbody tr:hover td{background:#eef2f7;}
  table.ltbl tbody tr.hit:hover td{background:#e3f7e8;}
  @media (max-width:760px){ .leaders{grid-template-columns:1fr;} }
  /* champion-conditional matrix */
  table.cmtbl{border-collapse:separate; border-spacing:0; font-size:.8rem;
              font-variant-numeric:tabular-nums;}
  table.cmtbl th, table.cmtbl td{padding:5px 6px; text-align:center; white-space:nowrap;}
  table.cmtbl thead th{position:sticky; top:0; z-index:2; background:#f8fafc;
              border-bottom:1px solid var(--line); font-weight:700; color:#334155;}
  table.cmtbl th.ch .t{font-size:.72rem; color:var(--muted); font-weight:600;}
  table.cmtbl th.sum{color:#334155;}
  table.cmtbl th.nm, table.cmtbl td.nm{position:sticky; right:0; z-index:1; background:#fff;
              text-align:right; font-weight:600; max-width:150px; overflow:hidden;
              text-overflow:ellipsis; box-shadow:-6px 0 6px -6px rgba(0,0,0,.12);}
  table.cmtbl thead th.nm{z-index:3;}
  table.cmtbl td.cell{min-width:34px; color:#0f172a; font-weight:600;}
  table.cmtbl td.sum{font-weight:700;}
  table.cmtbl tbody tr:hover td.nm{background:#f1f5f9;}
  /* data-freshness / coverage strip */
  .freshness{display:flex; flex-wrap:wrap; align-items:center; gap:8px 16px;
             background:#0f172a; color:#e2e8f0; border-radius:0 0 12px 12px;
             margin:-8px 0 18px; padding:11px 18px; font-size:.92rem; line-height:1.5;}
  .freshness .fresh-when{font-weight:800; color:#7dd3fc; white-space:nowrap;
             font-variant-numeric:tabular-nums;}
  .freshness .fresh-body b{color:#fff;}
  /* group-stage standings cards */
  .ggrid{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:8px;}
  .gcard{border:1px solid var(--line); border-radius:12px; padding:12px 14px; background:#fff;}
  .gh{font-weight:800; color:var(--ink); margin-bottom:6px;}
  table.gtbl{width:100%; border-collapse:collapse; font-size:.84rem;}
  table.gtbl th{font-size:.66rem; color:var(--muted); text-transform:uppercase;
             letter-spacing:.02em; text-align:center; padding:2px 3px; font-weight:600;}
  table.gtbl th:first-child{text-align:right;}
  table.gtbl td{padding:4px 3px; text-align:center; border-top:1px solid #f1f5f9;
             font-variant-numeric:tabular-nums; color:#475569;}
  table.gtbl td.gt{text-align:right; font-weight:600; color:#334155; white-space:nowrap;
             overflow:hidden; text-overflow:ellipsis; max-width:104px;
             border-right:3px solid transparent; padding-right:7px;}
  table.gtbl td.gq{font-weight:700; color:var(--blue);}
  table.gtbl tr.qual td{background:rgba(22,163,74,.08);}
  table.gtbl tr.qual td.gt{border-right-color:var(--green); color:var(--ink);}
  @media (max-width:760px){ .ggrid{grid-template-columns:repeat(2,1fr);} }
"""


TABS_CSS = """
  /* sticky tab navigation */
  nav.tabs{position:sticky; top:0; z-index:50; display:flex; gap:6px; flex-wrap:wrap;
           background:rgba(241,245,249,.92); backdrop-filter:saturate(1.4) blur(6px);
           padding:10px 0 8px; margin:0 0 6px; border-bottom:1px solid var(--line);}
  nav.tabs button{appearance:none; border:1px solid var(--line); background:#fff; color:#475569;
           font-family:inherit; font-size:.96rem; font-weight:700; cursor:pointer;
           padding:9px 16px; border-radius:999px; transition:all .15s;}
  nav.tabs button:hover{border-color:#cbd5e1; color:var(--ink);}
  nav.tabs button.active{background:linear-gradient(135deg,#0b1220,#1e3a8a); color:#fff;
           border-color:transparent; box-shadow:0 6px 16px -8px rgba(30,58,138,.7);}
  .tabpanel[hidden]{display:none;}
"""

WHATIF_CSS = """
  /* What-If tab */
  .wibar{display:flex; align-items:center; gap:12px; margin:14px 0 4px; flex-wrap:wrap;}
  .wibtn{appearance:none; border:1px solid var(--line); background:#fff; color:#334155;
         font-family:inherit; font-weight:700; font-size:.9rem; cursor:pointer;
         padding:8px 14px; border-radius:10px;}
  .wibtn:hover{border-color:#cbd5e1; background:#f8fafc;}
  .wihint{color:var(--muted); font-size:.86rem;}
  .wigrid{display:grid; grid-template-columns:330px minmax(0,1fr); gap:18px; margin-top:10px; align-items:start;}
  .wicol{min-width:0;}
  .wicolhd{font-weight:800; color:var(--ink); margin-bottom:8px; font-size:1.02rem;}
  #wiMatches{max-height:560px; overflow:auto; border:1px solid var(--line); border-radius:12px; padding:6px 10px;}
  .wistage{font-weight:800; color:#1e3a8a; margin:12px 4px 6px; font-size:.98rem;
           border-bottom:2px solid #e2e8f0; padding-bottom:4px;}
  .wisub{font-weight:700; color:#64748b; margin:8px 4px 4px; font-size:.82rem;}
  .wimatch{padding:7px 6px; border-bottom:1px solid #f1f5f9;}
  .wimatch.decided{background:#f0fdf4;}
  .wiadv{margin-top:5px; font-size:.8rem; color:#15803d;}
  .wiadv b{color:#166534;}
  .wimrow{display:flex; align-items:center; gap:8px;}
  .witeam{flex:1; font-size:.9rem; color:#334155; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .witeam.h{text-align:left;} .witeam.a{text-align:right;}
  .wiscore{width:42px; text-align:center; font-variant-numeric:tabular-nums; font-weight:700;
           border:1px solid var(--line); border-radius:8px; padding:5px 2px; font-family:inherit;}
  .wiscore:focus{outline:none; border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.15);}
  .widash{color:var(--muted); font-weight:800;}
  .wiso{margin-top:5px; font-size:.82rem; color:#475569; display:flex; gap:12px; align-items:center; flex-wrap:wrap;}
  .wiso label{display:inline-flex; align-items:center; gap:4px; cursor:pointer;}
  .wiscorers{margin-top:7px; padding-top:6px; border-top:1px dashed var(--line);}
  .wisc-hd{font-size:.78rem; font-weight:700; color:#334155; margin-bottom:4px;}
  .wisc-hd small{font-weight:600; color:#64748b;}
  .wisc-row{display:flex; align-items:center; justify-content:space-between; gap:8px; padding:2px 0;}
  .wisc-nm{font-size:.82rem; color:#1e293b;}
  .wisc-nm small{color:#94a3b8; font-weight:400;}
  .wistep{display:inline-flex; align-items:center; gap:7px;}
  .wisc-v{min-width:14px; text-align:center; font-size:.85rem; font-weight:700;
          font-variant-numeric:tabular-nums; color:#0f172a;}
  .wistepbtn{appearance:none; border:1px solid var(--line); background:#fff; color:#1e3a8a;
             border-radius:7px; width:22px; height:22px; line-height:1; cursor:pointer;
             font-weight:800; font-size:.95rem; padding:0;}
  .wistepbtn:hover:not(:disabled){background:#eff6ff; border-color:#bfdbfe;}
  .wistepbtn:disabled{opacity:.4; cursor:default;}
  .wiboardwrap{max-height:560px; overflow:auto; border:1px solid var(--line); border-radius:12px;}
  table.witbl{border-collapse:separate; border-spacing:0; width:100%; font-size:.85rem;
              font-variant-numeric:tabular-nums;}
  table.witbl thead th{position:sticky; top:0; z-index:2; background:#f8fafc; font-weight:700;
              color:#334155; padding:8px; border-bottom:1px solid var(--line); white-space:nowrap;}
  table.witbl td{padding:7px 8px; border-bottom:1px solid #f1f5f9; text-align:center; color:#475569;}
  table.witbl td.rk{font-weight:800; color:#334155;}
  table.witbl td.nm{text-align:right; font-weight:700; color:var(--ink); max-width:200px;
              overflow:hidden; text-overflow:ellipsis;}
  table.witbl td.pts{font-weight:800; color:var(--ink);}
  table.witbl tbody tr:nth-child(odd){background:#fcfcfd;}

  /* What-If: section blocks + group-stage split */
  .wisec{margin-top:18px;}
  .wisub2{font-weight:700; color:#1e3a8a; margin:4px 4px 8px; font-size:.92rem;}
  .wigs{display:grid; grid-template-columns:320px minmax(0,1fr); gap:18px; align-items:start;}
  .wigs #wiMatches{max-height:620px;}

  /* What-If: live group-standings cards */
  .wggrid{display:grid; grid-template-columns:repeat(3,1fr); gap:12px;}
  .wgcard{border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:#fff;}
  .wgcard.live{border-color:#bfdbfe; box-shadow:0 0 0 2px rgba(37,99,235,.08);}
  .wgh{font-weight:800; color:var(--ink); margin-bottom:5px; font-size:.92rem; display:flex;
       justify-content:space-between; align-items:center;}
  .wgh .wgdone{font-size:.66rem; font-weight:700; color:#16a34a; background:#dcfce7;
       padding:1px 7px; border-radius:999px;}
  table.wgtbl{width:100%; border-collapse:collapse; font-size:.82rem;}
  table.wgtbl th{font-size:.62rem; color:var(--muted); text-transform:uppercase;
       letter-spacing:.02em; text-align:center; padding:2px 3px; font-weight:600;}
  table.wgtbl th.nm{text-align:right;}
  table.wgtbl td{padding:3px 3px; text-align:center; border-top:1px solid #f1f5f9;
       font-variant-numeric:tabular-nums; color:#475569;}
  table.wgtbl td.pos{font-weight:800; color:#94a3b8; width:14px;}
  table.wgtbl td.nm{text-align:right; font-weight:600; color:#334155; white-space:nowrap;
       overflow:hidden; text-overflow:ellipsis; max-width:118px;
       border-right:3px solid transparent; padding-right:6px;}
  table.wgtbl td.pts{font-weight:800; color:var(--ink);}
  table.wgtbl td.chg{width:18px; font-weight:800;}
  table.wgtbl tr.q1 td, table.wgtbl tr.q2 td{background:rgba(22,163,74,.09);}
  table.wgtbl tr.q1 td.nm, table.wgtbl tr.q2 td.nm{border-right-color:var(--green); color:var(--ink);}
  table.wgtbl tr.q3 td{background:rgba(37,99,235,.09);}
  table.wgtbl tr.q3 td.nm{border-right-color:var(--blue); color:var(--ink);}
  .wgfl{font-size:.92rem; margin-inline-end:3px;}
  .chg-up{color:#16a34a;} .chg-dn{color:#dc2626;} .chg-eq{color:#cbd5e1;}

  /* What-If: knockout bracket (NBA-style, two-sided, LTR) */
  .wibracket-wrap{overflow-x:auto; padding:6px 2px 12px; -webkit-overflow-scrolling:touch;}
  .wibracket{display:flex; gap:6px; align-items:stretch; min-width:max-content; direction:ltr;}
  .wibr-round{display:flex; flex-direction:column; min-width:140px;}
  .wibr-round.fin{min-width:170px;}
  .wibr-rndhd{font-size:.66rem; font-weight:800; text-transform:uppercase; letter-spacing:.03em;
       color:#64748b; text-align:center; padding:2px 0 6px;}
  .wibr-col{flex:1; display:flex; flex-direction:column; justify-content:space-around; gap:6px;}
  .wibr-col.cen{justify-content:center; gap:14px;}
  .wibr-node{position:relative; border:1px solid var(--line); border-radius:9px; background:#fff;
       padding:3px 4px; box-shadow:0 1px 3px rgba(2,6,23,.05);}
  .wibr-node.decided{background:#f0fdf4; border-color:#bbf7d0;}
  .wibr-node.fin{border-color:#fcd34d; box-shadow:0 0 0 2px rgba(245,158,11,.18);}
  .wibr-node.tp{border-style:dashed;}
  .wibr-mno{position:absolute; top:-8px; inset-inline-start:6px; font-size:.58rem; font-weight:700;
       color:#94a3b8; background:#fff; padding:0 4px;}
  .wibr-trow{display:flex; align-items:center; gap:5px; padding:3px 4px; border-radius:6px;}
  .wibr-trow.win{background:rgba(22,163,74,.12);}
  .wibr-trow.win .wibr-nm{font-weight:800; color:#166534;}
  .wibr-trow.lose{opacity:.5;}
  .wibr-fl{font-size:.92rem; width:18px; text-align:center; flex:none;}
  .wibr-nm{flex:1; min-width:0; font-size:.8rem; color:#334155; white-space:nowrap;
       overflow:hidden; text-overflow:ellipsis;}
  .wibr-nm.tbd{color:#94a3b8; font-style:italic; font-size:.74rem;}
  .wibr-sc{width:30px; flex:none; text-align:center; font-variant-numeric:tabular-nums; font-weight:700;
       border:1px solid var(--line); border-radius:6px; padding:3px 0; font-family:inherit; font-size:.82rem;}
  .wibr-sc:focus{outline:none; border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.15);}
  .wibr-sc:disabled{background:#f8fafc; color:#64748b; -webkit-text-fill-color:#64748b;}
  .wibr-pen{display:flex; gap:6px; justify-content:center; align-items:center; flex-wrap:wrap;
       margin-top:3px; padding-top:3px; border-top:1px dashed var(--line); font-size:.68rem; color:#64748b;}
  .wibr-pen button{appearance:none; border:1px solid var(--line); background:#fff; border-radius:6px;
       font-family:inherit; font-size:.68rem; font-weight:700; color:#475569; padding:2px 7px; cursor:pointer;}
  .wibr-pen button.on{background:#1e3a8a; color:#fff; border-color:transparent;}
  .wibr-scorers{margin-top:4px; padding-top:4px; border-top:1px dashed var(--line);}

  @media (max-width:760px){
    .wigs{grid-template-columns:1fr;}
    .wggrid{grid-template-columns:repeat(2,1fr);}
    .wibr-round{min-width:128px;}
  }
"""

ODDS_CSS = """
  /* Odds & ELO tab */
  .odcal{display:flex; gap:10px; flex-wrap:wrap; margin-top:12px;}
  .odchip{background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px 16px;
          display:flex; flex-direction:column; gap:2px; min-width:130px;}
  .odchip .odk{color:var(--muted); font-size:.78rem; font-weight:600;}
  .odchip .odv{color:var(--ink); font-size:1.3rem; font-weight:800; font-variant-numeric:tabular-nums;}
  table.odtbl{border-collapse:separate; border-spacing:0; width:100%; font-size:.85rem;
              font-variant-numeric:tabular-nums;}
  table.odtbl thead th{position:sticky; top:0; z-index:2; background:#f8fafc; font-weight:700;
              color:#334155; padding:8px; border-bottom:1px solid var(--line); white-space:nowrap;
              text-align:center;}
  table.odtbl thead th.nm{text-align:right;}
  table.odtbl td{padding:6px 8px; border-bottom:1px solid #f1f5f9; text-align:center; color:#475569;}
  table.odtbl td.nm{text-align:right; font-weight:700; color:var(--ink);}
  table.odtbl td.v{font-weight:800; color:var(--blue);}
  table.odtbl tbody tr:nth-child(odd){background:#fcfcfd;}
  .odchart{margin-top:14px;}
  a.odlink{color:#2563eb;font-weight:600;font-size:.86rem;text-decoration:none;}
  a.odlink:hover{text-decoration:underline;}
  .odsvg{width:100%; height:auto; background:#fff; border:1px solid var(--line); border-radius:12px;}
  .odleg{display:flex; flex-wrap:wrap; gap:12px; margin:6px 0;}
  .odlg{font-size:.82rem; color:#475569; display:inline-flex; align-items:center; gap:5px;}
  .odsw{width:12px; height:12px; border-radius:3px; display:inline-block;}
  .odhistctrls{display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:8px 0 4px;}
  .odhistctrls .stmode button{font-size:.84rem;}
"""

RACE_CSS = """
  /* Bar-chart-race trigger button + overlay */
  .racebtn{display:inline-flex; align-items:center; gap:7px; margin:6px 0 12px;
           background:linear-gradient(135deg,#1d4ed8,#7c3aed); color:#fff; border:0;
           border-radius:12px; padding:9px 16px; font-size:.9rem; font-weight:800;
           cursor:pointer; box-shadow:0 2px 8px rgba(29,78,216,.28);}
  .racebtn::before{content:"▶"; font-size:.72rem;}
  .racebtn:hover{filter:brightness(1.06);}
  .racebtn:active{transform:translateY(1px);}
  #raceModal{position:fixed; inset:0; z-index:9999; display:none;
             background:rgba(15,23,42,.62); backdrop-filter:blur(3px);
             align-items:center; justify-content:center; padding:16px;}
  #raceModal.open{display:flex;}
  .racecard{background:#fff; border-radius:18px; width:min(960px,100%);
            max-height:94vh; overflow:auto; box-shadow:0 24px 60px rgba(2,6,23,.45);
            padding:18px 18px 14px;}
  .racehd{display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:6px;}
  .racehd h3{margin:0; font-size:1.12rem; font-weight:900; color:var(--ink);}
  .raceclose{background:#f1f5f9; border:0; border-radius:10px; width:34px; height:34px;
             font-size:1.2rem; line-height:1; cursor:pointer; color:#334155;}
  .raceclose:hover{background:#e2e8f0;}
  .racecanvaswrap{width:100%;}
  #raceCanvas{width:100%; height:auto; display:block;}
  .racectrls{display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-top:10px;}
  .raceplay{background:#1d4ed8; color:#fff; border:0; border-radius:10px; padding:8px 16px;
            font-weight:800; cursor:pointer; min-width:92px;}
  .raceplay:hover{filter:brightness(1.07);}
  .racescrub{flex:1 1 200px; min-width:160px; accent-color:#1d4ed8;}
  .racedate{font-variant-numeric:tabular-nums; font-weight:800; color:#334155; min-width:118px;
            text-align:center; font-size:.92rem;}
  .racespeed{border:1px solid var(--line); border-radius:10px; padding:6px 8px; font-weight:700;
             color:#334155; background:#fff;}
  .racefoot{color:var(--muted); font-size:.8rem; margin:8px 2px 0;}
"""

CHEER_CSS = """
  /* "Who to root for?" tab */
  .rfnote{border-right-color:var(--amber); background:#fffbeb;}
  .rfsub-il{color:var(--muted); font-weight:600;}
  .rffilters{margin:14px 0 6px; background:#f8fafc; border:1px solid var(--line);
             border-radius:12px; padding:12px 14px;}
  .rffl-row{display:flex; align-items:center; gap:10px; flex-wrap:wrap;}
  /* today / tomorrow segmented toggle */
  .rfdaytoggle{display:inline-flex; gap:0; background:#eef2f7; border:1px solid var(--line);
               border-radius:10px; padding:3px; margin-bottom:10px;}
  .rfday{appearance:none; border:0; background:none; font-family:inherit; font-weight:800;
         font-size:.86rem; color:#64748b; cursor:pointer; padding:6px 16px; border-radius:8px;}
  .rfday.on{background:#fff; color:var(--ink); box-shadow:0 2px 8px -4px rgba(2,6,23,.4);}
  .rfday:disabled{color:#cbd5e1; cursor:not-allowed;}
  .rftoggle{display:inline-flex; align-items:center; gap:7px; font-size:.88rem; color:#475569; cursor:pointer;}
  /* searchable dropdowns (scale to 53+ participants) */
  .rfdd{position:relative;}
  .rfdd-btn{appearance:none; border:1px solid var(--line); background:#fff; color:#334155;
            font-family:inherit; font-weight:700; font-size:.86rem; cursor:pointer;
            padding:7px 14px; border-radius:10px; display:inline-flex; align-items:center; gap:6px;}
  .rfdd-btn:hover{border-color:#cbd5e1;}
  .rfdd-cnt{color:var(--blue); font-weight:800;}
  .rfcar{color:var(--muted);}
  .rfdd-pop{position:absolute; z-index:60; top:calc(100% + 6px); inset-inline-start:0; width:280px;
            max-width:84vw; background:#fff; border:1px solid var(--line); border-radius:12px;
            box-shadow:0 16px 40px -16px rgba(2,6,23,.45); padding:10px;}
  .rfdd-search{width:100%; box-sizing:border-box; border:1px solid var(--line); border-radius:9px;
               padding:7px 10px; font-family:inherit; font-size:.86rem; margin-bottom:6px;}
  .rfdd-search:focus{outline:none; border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.15);}
  .rfdd-actions{display:flex; justify-content:flex-end; margin-bottom:4px;}
  .rflink{appearance:none; border:0; background:none; color:var(--blue); font-family:inherit;
          font-weight:700; font-size:.82rem; cursor:pointer; padding:2px 4px;}
  .rfdd-list{max-height:240px; overflow:auto; display:flex; flex-direction:column; gap:1px;}
  .rfopt{display:flex; align-items:center; gap:8px; padding:5px 6px; border-radius:8px;
         font-size:.86rem; color:#334155; cursor:pointer;}
  .rfopt:hover{background:#f1f5f9;}
  .rfopt span{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
  .rfopt2{display:block; width:100%; text-align:right; appearance:none; border:0; background:none;
          font-family:inherit; font-size:.86rem; color:#334155; padding:6px 8px; border-radius:8px; cursor:pointer;}
  .rfopt2:hover{background:#f1f5f9;}
  .rfopt2.cur{background:#fef3c7; color:#92400e; font-weight:800;}
  .rfgame{border:1px solid var(--line); border-radius:14px; padding:14px 16px 16px; margin:14px 0;
          background:#fff; box-shadow:0 6px 18px -14px rgba(2,6,23,.4);}
  .rftime-row{display:flex; margin-bottom:6px;}
  .rftime{color:var(--muted); font-size:.85rem; font-weight:700;
          background:#f1f5f9; padding:3px 10px; border-radius:999px;}
  .rfbuckets{display:grid; grid-template-columns:repeat(3,1fr); gap:14px; align-items:start;}
  .rfcol{border:1px solid var(--line); border-radius:12px; padding:10px; background:#fcfcfd; min-width:0;}
  /* big flag (centered) + team name below; middle column shows the large X */
  .rfcolhd{display:flex; flex-direction:column; align-items:center; gap:5px; text-align:center;
           padding:8px 4px 12px; margin-bottom:10px; border-bottom:2px solid #eef2f7;}
  .rffl-big{font-size:3.1rem; line-height:1;}
  .rfx-big{font-size:2.7rem; line-height:1.05; font-weight:800; color:#cbd5e1;}
  .rfcname{font-weight:800; font-size:1.12rem; color:var(--ink);}
  .rfcname.rfcdraw{color:#a16207;}
  .rfprob{font-size:.78rem; font-weight:700; color:var(--muted);}
  .rf-win1 .rfcolhd{border-bottom-color:#86efac;}
  .rf-draw .rfcolhd{border-bottom-color:#fde047;}
  .rf-win2 .rfcolhd{border-bottom-color:#93c5fd;}
  .rfchips{display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px;}
  .rfchip{background:#fff; border:1px solid var(--line); border-radius:9px; padding:5px 8px 8px;
          font-size:.8rem; color:#334155; display:flex; align-items:center; justify-content:space-between;
          gap:5px; position:relative; overflow:hidden;}
  /* relative-emphasis bar: width ∝ |Δ| / max|Δ| within the game */
  .rfbar{position:absolute; inset-inline-start:0; bottom:0; height:3px; border-radius:0 2px 2px 0;
         opacity:.6; transition:width .2s ease;}
  .rfbar.pos{background:var(--green,#16a34a);}
  .rfbar.neg{background:var(--red,#dc2626);}
  .rfchip .rfnm{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
  .rfchip .rfdelta{font-style:normal; flex:none; font-weight:800; font-size:.78rem;}
  .rfchip .rfdelta.pos{color:var(--green,#16a34a);}
  .rfchip .rfdelta.neg{color:var(--red,#dc2626);}
  .rfchip.hl{border-color:#f59e0b; background:#fffbeb; box-shadow:0 0 0 2px rgba(245,158,11,.4);}
  .rfempty{color:var(--muted); font-size:.82rem; text-align:center; padding:8px 0; grid-column:1/-1;}
  .rfneutral{margin-top:12px; border-top:1px dashed var(--line); padding-top:10px;}
  .rfneutral>summary{cursor:pointer; color:var(--muted); font-size:.84rem; font-weight:700; list-style:none;}
  .rfneutral>summary::-webkit-details-marker{display:none;}
  .rfneutral>summary::before{content:'▸ '; color:#94a3b8;}
  .rfneutral[open]>summary::before{content:'▾ ';}
  .rfneutral .rfchips{margin-top:8px; grid-template-columns:repeat(3,minmax(0,1fr));}
  /* knockout layout: two team columns with a big centred ✕ (no draw bucket) */
  .rfbuckets.ko{grid-template-columns:1fr auto 1fr;}
  .rfvs{align-self:center; display:flex; justify-content:center; padding:0 6px;}
  .rfvs .rfx-big{font-size:3rem; color:#cbd5e1;}
  .rfko-badge{margin-inline-start:8px; background:#ede9fe; color:#6d28d9; font-size:.72rem;
              font-weight:800; padding:3px 9px; border-radius:999px;}
  .rfpending .rfvs-line{font-weight:800; color:var(--ink); margin:8px 0; font-size:1.02rem;}
  .rffl-mini{font-size:1.3rem; vertical-align:middle;}
  .rfx-mini{color:#94a3b8; font-weight:800; margin:0 5px;}
  @media (max-width:760px){ .rfbuckets{grid-template-columns:1fr;} .rfbuckets.ko{grid-template-columns:1fr;}
    .rfvs{display:none;} .rfneutral .rfchips{grid-template-columns:repeat(2,minmax(0,1fr));} }
"""

TABS_JS = """
(function(){
  const tabs = Array.from(document.querySelectorAll('nav.tabs button[data-tab]'));
  const panels = Array.from(document.querySelectorAll('.tabpanel[data-tab]'));
  if(!tabs.length) return;
  function show(name){
    tabs.forEach(b=> b.classList.toggle('active', b.dataset.tab===name));
    panels.forEach(p=> p.hidden = (p.dataset.tab!==name));
    window.scrollTo({top:0, behavior:'instant' in window? 'instant':'auto'});
  }
  tabs.forEach(b=> b.addEventListener('click', ()=> show(b.dataset.tab)));
  show('main');
})();
"""


# =========================================================================== #
# Shared data loaders for the new tabs
# =========================================================================== #
def _teams_meta() -> dict:
    """team -> {tier, group, elo, elo_eloratings, elo_market, market_prob}."""
    out = {}
    f = DATA_PROCESSED / "teams.csv"
    if not f.exists():
        return out
    with f.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            def _f(k):
                try:
                    return float(r[k])
                except (TypeError, ValueError):
                    return None
            out[r["team"]] = {
                "tier": r.get("tier", ""), "group": r.get("group", ""),
                "elo": _f("elo"), "elo_eloratings": _f("elo_eloratings"),
                "elo_market": _f("elo_market"), "market_prob": _f("market_prob"),
            }
    return out


def _load_state() -> dict:
    f = DATA_LIVE / "state_latest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# =========================================================================== #
# Tab "What If" - inject the data the in-browser scoring engine needs
# =========================================================================== #
def whatif_payload(data: dict, state: dict) -> dict:
    meta = _teams_meta()
    team_he, pl_he = _team_he_map(), _player_he_map()
    teams = sorted(meta)
    team_tier = {t: meta[t]["tier"] for t in teams}
    team_group = {t: meta[t]["group"] for t in teams}
    groups: dict[str, list[str]] = {}
    for t in teams:
        groups.setdefault(meta[t]["group"], []).append(t)
    # order each group by the official groups.csv position when available
    pos = {(r["group"], r["team"]): int(r["pos"]) for r in _read_csv(DATA_PROCESSED / "groups.csv")}
    for g in groups:
        groups[g].sort(key=lambda t: pos.get((g, t), 99))

    sched = _read_csv(DATA_PROCESSED / "schedule_groups.csv")
    group_matches = [{"no": int(r["match"]), "group": r["group"],
                      "home": r["home"], "away": r["away"]} for r in sched]

    bracket_raw = json.loads((DATA_PROCESSED / "bracket.json").read_text())
    bracket = [{"m": b["match"], "rc": b["round_code"], "stage": b["stage"],
                "hr": b["home_ref"], "ar": b["away_ref"]} for b in bracket_raw]
    third_slots = []
    for b in bracket_raw:
        if b["round_code"] != 1:
            continue
        for side in ("home_ref", "away_ref"):
            if b[side]["type"] == "third":
                third_slots.append({"m": b["match"], "side": side,
                                    "eligible": list(b[side]["eligible"])})

    rules = {
        "win": 3.0, "draw": 1.0, "loss": 0.0, "pen_win": 3.0, "pen_loss": 1.0,
        "b_r32_top2_D": 3.0, "b_r32_top2_C": 1.0, "b_r32_third_D": 1.0,
        "b_final": 2.0, "b_win": 1.0,
        "per_gf": 0.5, "per_ga": 0.5, "per_gk": 0.5, "gb_bonus": 1.0,
    }

    ents = data.get("entries") or []
    entries = [{"name": e["name"], "picks": e["picks"],
                "base": float(e.get("current_points", 0)),
                "bd": e.get("pts_breakdown") or {}} for e in ents]

    # Goal-scorer attribution is only offered for players that someone picked as
    # "top scorer" (others can't change any entry's score). Resolve each pick's
    # national team so we can later restrict suggestions to the relevant match.
    player_team: dict[str, str] = {}
    for pf in (DATA_PROCESSED / "players.csv", WC_ROOT / "data" / "live" / "extra_players.csv"):
        try:
            for r in _read_csv(pf):
                if r.get("scorer") and r.get("team"):
                    player_team.setdefault(r["scorer"], r["team"])
        except Exception:
            pass
    for s in (state.get("all_scorers") or data.get("scorers") or []):
        if s.get("scorer") and s.get("team"):
            player_team.setdefault(s["scorer"], s["team"])
    picked = sorted({e["picks"]["top_scorer"] for e in ents if e["picks"].get("top_scorer")})
    tracked_players = [{"name": n, "team": player_team.get(n, "")} for n in picked]

    # Hebrew labels limited to the teams/players actually referenced
    he_teams = {t: team_he.get(t, t) for t in teams}
    he_players = {p["name"]: pl_he.get(p["name"], p["name"]) for p in tracked_players}

    return {
        "rules": rules,
        "teamTier": team_tier, "teamGroup": team_group, "groups": groups,
        "groupMatches": group_matches, "bracket": bracket, "thirdSlots": third_slots,
        "realGroupScores": {k: list(v) for k, v in (state.get("group_scores") or {}).items()},
        "predGroupScores": {k: list(v) for k, v in (data.get("pred_group_scores") or {}).items()},
        "predGroupScorers": {k: dict(v) for k, v in (data.get("pred_group_scorers") or {}).items()},
        "realKo": state.get("ko_results") or [],
        "realTeamPlayed": state.get("team_played") or data.get("team_played") or {},
        "realPlayerGoals": state.get("player_goals") or {},
        "groupStageComplete": bool(state.get("group_stage_complete")),
        "entries": entries, "trackedPlayers": tracked_players,
        "teamHe": he_teams, "playerHe": he_players,
        "iso": {t: _TEAM_ISO.get(t, "") for t in teams},
    }


def whatif_html() -> str:
    return """
  <h2 class="bigsec" data-i18n="tab.whatif">What If..?</h2>
  <section>
    <p class="sub" style="margin-top:4px" data-i18n="wi.intro" data-i18n-html></p>
    <div class="callout" style="border-right-color:var(--amber); background:#fffbeb;"
         data-i18n="wi.callout" data-i18n-html></div>
    <div class="wibar">
      <button type="button" id="wiFillGroups" class="wibtn" data-i18n="wi.fill">מלא משחקי בתים בתוצאה הסבירה ביותר</button>
      <button type="button" id="wiReset" class="wibtn" data-i18n="wi.reset">איפוס כל התרחישים</button>
      <span id="wiCount" class="wihint"></span>
    </div>
  </section>

  <section class="wisec">
    <div class="wicolhd" data-i18n="wi.group_stage">שלב הבתים</div>
    <div class="wigs">
      <div class="wicol">
        <div class="wisub2" data-i18n="wi.matches">משחקים למילוי</div>
        <div id="wiMatches"></div>
      </div>
      <div class="wicol">
        <div class="wisub2" data-i18n="wi.groups_title">טבלאות הבתים — בתרחיש שלכם</div>
        <p class="panel-cap" data-i18n="wi.groups_cap"></p>
        <div id="wiGroups" class="wggrid"></div>
      </div>
    </div>
  </section>

  <section class="wisec">
    <div class="wicolhd" data-i18n="wi.bracket_title">עץ הנוק‑אאוט — בתרחיש שלכם</div>
    <p class="panel-cap" data-i18n="wi.bracket_cap"></p>
    <div id="wiBracket" class="wibracket-wrap"></div>
  </section>

  <section class="wisec">
    <div class="wicolhd" data-i18n="wi.board">טבלת הדירוג — בתרחיש שלכם</div>
    <div class="wiboardwrap"><table class="witbl"><thead><tr>
      <th data-i18n="th.rank">מקום</th><th data-i18n="th.change">שינוי</th>
      <th class="nm" data-i18n="th.name">שם</th><th data-i18n="th.pts">נק׳</th>
      <th data-i18n="th.tierA">דרג א׳</th><th data-i18n="th.tierB">דרג ב׳</th>
      <th data-i18n="th.tierC">דרג ג׳</th><th data-i18n="th.tierD">דרג ד׳</th>
      <th data-i18n="th.scoring">כובשת</th><th data-i18n="th.conceding">סופגת</th>
      <th data-i18n="th.top_scorer">מלך שערים</th></tr></thead>
      <tbody id="wiBoard"></tbody></table></div>
  </section>
"""


# =========================================================================== #
# Tab "Odds & ELO" - current run values + history-over-time
# =========================================================================== #
def odds_payload(data: dict) -> dict:
    meta = _teams_meta()
    team_he = _team_he_map()
    pl_he = _player_he_map()

    elo = [{"team": t, "he": team_he.get(t, t),
            "blended": m["elo"], "eloratings": m["elo_eloratings"],
            "market": m["elo_market"], "marketProb": m["market_prob"]}
           for t, m in meta.items() if m["elo"] is not None]
    elo.sort(key=lambda r: -(r["blended"] or 0))

    advance = [{"team": r["team"], "he": team_he.get(r["team"], r["team"]),
                "p": float(r["p_advance"])}
               for r in _read_csv(DATA_PROCESSED / "market_advance.csv") if r.get("p_advance")]
    advance.sort(key=lambda r: -r["p"])

    gb = [{"player": r["player"], "he": pl_he.get(r["player"], r["player"]),
           "p": float(r["p_gb"])}
          for r in _read_csv(DATA_PROCESSED / "market_golden_boot.csv") if r.get("p_gb")]
    gb.sort(key=lambda r: -r["p"])

    cm = data.get("champion_matrix") or {}
    sim_title = cm.get("p_title") or {}
    cal = data.get("calibration") or {}

    # history (committed jsonl, one record per pipeline run); full series sent to
    # the page — run-mode downsamples client-side; daily mode averages by date.
    hist = []
    hf = DATA_HISTORY / "metrics_history.jsonl"
    if hf.exists():
        for line in hf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    hist.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    kalshi = {}
    kf = DATA_HISTORY / "kalshi_title_history.json"
    if kf.exists():
        try:
            kalshi = json.loads(kf.read_text(encoding="utf-8"))
            for s in kalshi.get("series") or []:
                s["he"] = team_he.get(s.get("team", ""), s.get("team", ""))
        except json.JSONDecodeError:
            kalshi = {}

    elo_prior = {}
    ef = DATA_HISTORY / "eloratings_weighted.json"
    if ef.exists():
        try:
            ew = json.loads(ef.read_text(encoding="utf-8"))
            base = ew.get("baseline", {})
            wt = ew.get("weighted", {})
            live = ew.get("last_live", {})
            rows = []
            for t in sorted(wt, key=lambda x: -float(wt[x])):
                if t in base:
                    rows.append({"team": t, "he": team_he.get(t, t),
                                 "baseline": float(base[t]),
                                 "weighted": float(wt[t]),
                                 "live": float(live[t]) if t in live else None})
            elo_prior = {"round": ew.get("round"),
                         "updatedAt": ew.get("updated_at"),
                         "alpha": ew.get("alpha"),
                         "appliedRounds": ew.get("applied_rounds"),
                         "rows": rows[:14],
                         "history": ew.get("history", [])}
        except json.JSONDecodeError:
            elo_prior = {}

    return {
        "generatedAt": data.get("timestamp", ""),
        "elo": elo, "advance": advance[:24], "advanceTail": advance[-8:],
        "goldenBoot": gb[:15],
        "simTitle": {t: round(float(p), 4) for t, p in sim_title.items()},
        "titleHe": {t: team_he.get(t, t) for t in sim_title},
        "calibration": {"strength_spread": cal.get("strength_spread"),
                        "golden_boot_scale": cal.get("golden_boot_scale")},
        "history": hist,
        "kalshi": kalshi,
        "eloPrior": elo_prior,
    }


def race_payload(data: dict) -> dict:
    """Time-series feeding the three bar-chart-race overlays.

    * entryHist — per-run participant points + P(1st)         (entry_history.jsonl)
    * simTitle  — per-run model title probability per team     (metrics_history.jsonl)
    * titleHe / iso — Hebrew names + flag ISO codes for the team race.
    """
    team_he = _team_he_map()

    entry_hist = []
    ehf = DATA_HISTORY / "entry_history.jsonl"
    if ehf.exists():
        for line in ehf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entry_hist.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    sim_hist, teams = [], set()
    mhf = DATA_HISTORY / "metrics_history.jsonl"
    if mhf.exists():
        for line in mhf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sim = rec.get("sim_title") or {}
            if sim:
                sim_hist.append({"ts": rec.get("ts"), "sim": sim})
                teams.update(sim.keys())

    return {
        "entryHist": entry_hist,
        "simHist": sim_hist,
        "titleHe": {t: team_he.get(t, t) for t in teams},
        "iso": {t: _TEAM_ISO.get(t, "") for t in teams},
    }


def odds_html() -> str:
    return """
  <h2 class="bigsec" data-i18n="od.title">הימורי השוק ודירוגי הכוח (ELO)</h2>
  <section>
    <p class="sub" style="margin-top:4px" data-i18n="od.intro" data-i18n-html></p>
    <div class="callout" data-i18n="od.note" data-i18n-html></div>
    <div id="odCal" class="odcal"></div>
  </section>
  <div class="grid2">
    <section><div class="panel-title" data-i18n="od.elo_title">דירוג כוח (ELO) — ההרצה האחרונה</div>
      <p class="panel-cap" data-i18n="od.elo_cap">משוקלל = שילוב דירוג בסיס והימורי השוק</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm" data-i18n="od.th.team">נבחרת</th><th data-i18n="od.th.blended">משוקלל</th>
        <th data-i18n="od.th.base">בסיס</th><th data-i18n="od.th.market">שוק</th>
        <th data-i18n="od.th.p_win">P(זכייה)</th>
      </tr></thead><tbody id="odElo"></tbody></table></div>
    </section>
    <section><div class="panel-title" data-i18n="od.title_title">סיכויי תואר — שוק מול סימולציה</div>
      <p class="panel-cap" data-i18n="od.title_cap">P(זכייה בגביע): השוק (הסתברות גלומה) מול הסימולציה שלנו</p>
      <button type="button" class="racebtn" data-race="title" data-i18n="race.btn.title">מרוץ סיכויי התואר (סימולציה) — 10 המובילות</button>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm" data-i18n="od.th.team">נבחרת</th><th data-i18n="od.th.market">שוק</th>
        <th data-i18n="od.th.sim">סימולציה</th></tr></thead>
        <tbody id="odTitle"></tbody></table></div>
    </section>
  </div>
  <div class="grid2">
    <section><div class="panel-title" data-i18n="od.adv_title">סיכויי העפלה (שוק)</div>
      <p class="panel-cap" data-i18n="od.adv_cap">P(העפלה לשלב הנוק‑אאוט) לפי השוק — 24 המובילות</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm" data-i18n="od.th.team">נבחרת</th><th data-i18n="od.th.advance">העפלה</th></tr></thead>
        <tbody id="odAdv"></tbody></table></div>
    </section>
    <section><div class="panel-title" data-i18n="od.gb_title">נעל הזהב (שוק)</div>
      <p class="panel-cap" data-i18n="od.gb_cap">P(זכייה בנעל הזהב) לפי השוק — 15 המובילים</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm" data-i18n="od.th.player">שחקן</th><th data-i18n="od.th.odds">סיכוי</th></tr></thead>
        <tbody id="odGb"></tbody></table></div>
    </section>
  </div>
  <section>
    <div class="panel-title" data-i18n="od.kalshi_title">Kalshi — סיכויי זכייה לאורך זמן</div>
    <p class="panel-cap" data-i18n="od.kalshi_cap">מחיר YES יומי בשוק Kalshi (8 המובילות). מקור: Kalshi API.</p>
    <div id="odKalshi"></div>
  </section>
  <section>
    <div class="panel-title" data-i18n="od.elop_title">דירוג הכוח (ELO) — בסיס → משוקלל → חי</div>
    <p class="panel-cap" data-i18n="od.elop_cap" data-i18n-html></p>
    <div id="odEloPriorNote" class="callout"></div>
    <div class="scrollbox"><table class="odtbl"><thead><tr>
      <th class="nm" data-i18n="od.th.team">נבחרת</th>
      <th data-i18n="od.elop.base">בסיס (30.5)</th>
      <th data-i18n="od.elop.weighted">משוקלל</th>
      <th data-i18n="od.elop.live">חי</th>
      <th data-i18n="od.elop.delta">Δ מהבסיס</th>
    </tr></thead><tbody id="odEloPrior"></tbody></table></div>
    <div id="odEloPriorChart"></div>
  </section>
  <section>
    <h2 style="margin-top:6px" data-i18n="od.hist_title">לאורך זמן</h2>
    <p class="sub" data-i18n="od.hist_sub">מעקב אחר ההסתברויות מהסימולציה ופרמטרי הכיול לאורך ההרצות. ייאסף ויתעבה ככל שיצטברו עדכונים.</p>
    <div class="odhistctrls">
      <div class="stmode" id="odHistAxis">
        <button type="button" data-axis="run" class="on" data-i18n="od.hist.by_run">לפי הרצה</button>
        <button type="button" data-axis="day" data-i18n="od.hist.by_day">ממוצע יומי</button>
      </div>
    </div>
    <div id="odHist"></div>
  </section>
"""


def whatif_js(payload: dict) -> str:
    return _WHATIF_JS.replace("__WHATIF__", json.dumps(payload, ensure_ascii=False))


def odds_js(payload: dict) -> str:
    return _ODDS_JS.replace("__ODDS__", json.dumps(payload, ensure_ascii=False))


# --- "Who to root for?" tab -------------------------------------------------- #
# Fixtures + per-outcome expected-prize deltas are computed in the pipeline
# (run_live_update.py -> live_latest.json["cheer"]); here we only add flags +
# Hebrew names and render. _flag maps a canonical team name to its emoji flag.
_TEAM_ISO = {
    "United States": "US", "Canada": "CA", "Mexico": "MX", "Panama": "PA",
    "Curaçao": "CW", "Haiti": "HT", "Argentina": "AR", "Brazil": "BR", "Uruguay": "UY",
    "Colombia": "CO", "Paraguay": "PY", "Ecuador": "EC", "France": "FR", "Spain": "ES",
    "Germany": "DE", "Portugal": "PT", "Netherlands": "NL", "Belgium": "BE",
    "Croatia": "HR", "Switzerland": "CH", "Austria": "AT", "Norway": "NO",
    "Sweden": "SE", "Turkey": "TR", "Czech Republic": "CZ", "Bosnia and Herzegovina": "BA",
    "Morocco": "MA", "Senegal": "SN", "Egypt": "EG", "Algeria": "DZ", "Tunisia": "TN",
    "Ghana": "GH", "Ivory Coast": "CI", "Cape Verde": "CV", "South Africa": "ZA",
    "DR Congo": "CD", "Japan": "JP", "South Korea": "KR", "Iran": "IR", "Australia": "AU",
    "Saudi Arabia": "SA", "Qatar": "QA", "Jordan": "JO", "Uzbekistan": "UZ",
    "Iraq": "IQ", "New Zealand": "NZ",
}
_FLAG_OVERRIDE = {"England": "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
                  "Scotland": "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f"}


def _flag(team: str) -> str:
    if team in _FLAG_OVERRIDE:
        return _FLAG_OVERRIDE[team]
    iso = _TEAM_ISO.get(team)
    if not iso or len(iso) != 2:
        return "🏳️"
    return chr(0x1F1E6 + ord(iso[0]) - 65) + chr(0x1F1E6 + ord(iso[1]) - 65)


def cheer_html(data: dict) -> str:
    ents = data.get("entries") or []
    names = [e["name"] for e in ents]
    he = _team_he_map()
    cheer = data.get("cheer") or {}
    pmap = {e["name"]: {"t3": float(e.get("P_top3", 0) or 0),
                        "last": float(e.get("P_last", 0) or 0)} for e in ents}

    # enrich the per-day games with Hebrew names + flags for display
    days = []
    for day in cheer.get("days", []):
        gs = []
        for g in day.get("games", []):
            gs.append({"mno": g["mno"], "ko": g.get("ko", ""), "p": g.get("p", [0, 0, 0]),
                       "type": g.get("type", "group"), "pending": bool(g.get("pending")),
                       "homeEn": g["home"], "awayEn": g["away"],
                       "t1": he.get(g["home"], g["home"]), "f1": _flag(g["home"]),
                       "t2": he.get(g["away"], g["away"]), "f2": _flag(g["away"])})
        days.append({"key": day["key"], "date": day.get("date", ""), "games": gs})
    cdata = {"days": days, "deltas": cheer.get("deltas", {}),
             "thr": cheer.get("neutral_threshold", 1.0), "pmap": pmap}

    filt_opts = "".join(
        f'<label class="rfopt" data-name="{n}"><input type="checkbox" value="{n}">'
        f'<span>{n}</span></label>' for n in names)
    hi_opts = "".join(
        f'<button type="button" class="rfopt2" data-name="{n}">{n}</button>' for n in names)

    blob = json.dumps(cdata, ensure_ascii=False)
    return f"""
  <h2 class="bigsec" data-i18n="cheer.title">את מי לעודד?</h2>
  <section>
    <p class="sub" style="margin-top:4px"><span data-i18n="cheer.intro" data-i18n-html></span>
      <span class="rfsub-il" data-i18n="cheer.il_time">השעות בשעון ישראל.</span></p>
    <div class="callout rfnote" data-i18n="cheer.note" data-i18n-html></div>
    <div class="rffilters">
      <div class="rfdaytoggle" id="rfDayToggle">
        <button type="button" class="rfday" data-day="today" data-i18n="cheer.today">היום</button>
        <button type="button" class="rfday" data-day="tomorrow" data-i18n="cheer.tomorrow">מחר</button>
      </div>
      <div class="rffl-row">
        <div class="rfdd">
          <button type="button" class="rfdd-btn" id="rfFilterBtn"><span data-i18n="cheer.filter">סינון משתתפים</span>
            <span class="rfdd-cnt" id="rfFilterCnt"></span> <span class="rfcar">▾</span></button>
          <div class="rfdd-pop" id="rfFilterPop" hidden>
            <input type="search" class="rfdd-search" id="rfFilterSearch" data-i18n-placeholder="cheer.search">
            <div class="rfdd-actions"><button type="button" class="rflink" id="rfClear" data-i18n="cheer.clear">נקה הכל</button></div>
            <div class="rfdd-list" id="rfFilterList">{filt_opts}</div>
          </div>
        </div>
        <div class="rfdd">
          <button type="button" class="rfdd-btn" id="rfHiBtn"><span data-i18n="cheer.highlight">הדגשת משתתפים</span><span id="rfHiCur"></span>
            <span class="rfcar">▾</span></button>
          <div class="rfdd-pop" id="rfHiPop" hidden>
            <input type="search" class="rfdd-search" id="rfHiSearch" data-i18n-placeholder="cheer.search">
            <div class="rfdd-actions"><button type="button" class="rflink" id="rfHiClear" data-i18n="cheer.unhighlight">בטל הכל</button></div>
            <div class="rfdd-list" id="rfHiList">{hi_opts}</div>
          </div>
        </div>
        <label class="rftoggle"><input type="checkbox" id="rfTop3"> <span data-i18n="cheer.top3">רק עם סיכוי לפודיום</span></label>
        <label class="rftoggle"><input type="checkbox" id="rfLast"> <span data-i18n="cheer.last">רק עם סיכוי למקום אחרון</span></label>
      </div>
    </div>
    <div id="rfGames" class="rfgames"></div>
    <script id="rfData" type="application/json">{blob}</script>
  </section>
"""


CHEER_JS = r"""
(function(){
  const panel = document.getElementById('tab-cheer');
  if(!panel) return;
  const I = window.I18N;
  const t = k => I.t(k);
  const T = en => I.team(en);
  const dataEl = document.getElementById('rfData');
  let C; try { C = JSON.parse(dataEl.textContent); } catch(e){ return; }
  const gamesEl = document.getElementById('rfGames');
  const top3=document.getElementById('rfTop3'), last=document.getElementById('rfLast');
  const fBtn=document.getElementById('rfFilterBtn'), fPop=document.getElementById('rfFilterPop');
  const fSearch=document.getElementById('rfFilterSearch'), fList=document.getElementById('rfFilterList');
  const fClear=document.getElementById('rfClear'), fCnt=document.getElementById('rfFilterCnt');
  const hBtn=document.getElementById('rfHiBtn'), hPop=document.getElementById('rfHiPop');
  const hSearch=document.getElementById('rfHiSearch'), hList=document.getElementById('rfHiList');
  const hClear=document.getElementById('rfHiClear'), hCur=document.getElementById('rfHiCur');
  const dayToggle=document.getElementById('rfDayToggle');

  const THR = C.thr || 1.0;
  const pmap = C.pmap || {};
  const deltas = C.deltas || {};
  const names = Object.keys(deltas).length ? Object.keys(deltas) : Object.keys(pmap);
  const dayByKey = {}; (C.days||[]).forEach(d=> dayByKey[d.key]=d);
  const esc = s => (s+'').replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  // ---- state ----
  const filt = new Set();   // selected participants (empty = everyone)
  const hi   = new Set();   // highlighted participants
  let day = (dayByKey.today && dayByKey.today.games.length) ? 'today'
          : (dayByKey.tomorrow && dayByKey.tomorrow.games.length) ? 'tomorrow' : 'today';

  function fmtMoney(v){
    const a = Math.abs(v);
    const s = a < 10 ? (Math.round(a*10)/10).toString() : Math.round(a).toString();
    return (v>=0 ? '+' : '−') + '₪' + s;
  }
  function eligible(n){
    if(filt.size && !filt.has(n)) return false;
    const p = pmap[n] || {};
    if(top3 && top3.checked && !(p.t3 > 0)) return false;
    if(last && last.checked && !(p.last > 0)) return false;
    return true;
  }
  function chip(n, v, showDelta, imp){
    const cls = 'rfchip' + (hi.has(n)?' hl':'');
    let d = '';
    if(showDelta) d = ' <i class="rfdelta '+(v>=0?'pos':'neg')+'">'+fmtMoney(v)+'</i>';
    // within-game relative emphasis: bar width = |Δ| / max|Δ| in this game.
    let bar = '';
    if(showDelta && imp > 0){
      bar = '<span class="rfbar '+(v>=0?'pos':'neg')+'" style="width:'
          + Math.round(imp*100) + '%"></span>';
    }
    return '<span class="'+cls+'" data-name="'+esc(n)+'"><span class="rfnm">'+esc(n)+'</span>'+d+bar+'</span>';
  }
  function colHead(flag, name, pct){
    return '<div class="rfcolhd"><span class="rffl-big">'+flag+'</span>'
         + '<span class="rfcname">'+esc(name)+'</span>'
         + '<span class="rfprob">'+t('cheer.prob')+' '+pct+'%</span></div>';
  }
  function bucketCol(kind, headHtml, items, focus){
    items.sort((a,b)=> b.v - a.v);
    const chips = items.map(it=> chip(it.n, it.v, true, it.imp||0)).join('') ||
                  '<div class="rfempty">'+t('cheer.empty')+'</div>';
    return '<div class="rfcol rf-'+kind+'">'+headHtml+'<div class="rfchips">'+chips+'</div></div>';
  }

  function render(){
    // day toggle buttons (label + disabled state)
    if(dayToggle) dayToggle.querySelectorAll('.rfday').forEach(b=>{
      const d = dayByKey[b.dataset.day];
      const n = d ? d.games.length : 0;
      b.disabled = !n;
      b.classList.toggle('on', b.dataset.day===day);
      const dayLbl = b.dataset.day==='today' ? t('cheer.today') : t('cheer.tomorrow');
      b.textContent = dayLbl + (d ? ' · '+(d.date||'').slice(5).split('-').reverse().join('.') : '');
    });
    if(fCnt) fCnt.textContent = filt.size ? '('+filt.size+')' : '';
    if(hCur) hCur.textContent = hi.size ? ' ('+hi.size+')' : '';

    const D = dayByKey[day];
    if(!D || !D.games.length){
      const dayLbl = day==='today' ? t('cheer.today').toLowerCase() : t('cheer.tomorrow').toLowerCase();
      gamesEl.innerHTML = '<div class="callout">'+I.fmt('cheer.no_games', {day: dayLbl})+'</div>';
      return;
    }
    const focus = filt.size > 0;
    let html = '';
    D.games.forEach(g=>{
      const mno = String(g.mno);
      const isKo = g.type === 'ko';
      const nOut = isKo ? 2 : 3;

      // knockout game whose two teams aren't settled yet -> show placeholder
      if(isKo && g.pending){
        html += '<div class="rfgame rfpending"><div class="rftime-row">'
              + '<span class="rftime">'+esc(g.ko)+'</span><span class="rfko-badge">'+t('cheer.ko')+'</span></div>'
              + '<div class="rfvs-line"><span class="rffl-mini">'+g.f1+'</span> '+esc(T(g.homeEn))
              + ' <span class="rfx-mini">✕</span> '+g.f2+' '+esc(T(g.awayEn))+'</div>'
              + '<div class="rfempty">'+t('cheer.pending')+'</div></div>';
        return;
      }

      const pr = (g.p||new Array(nOut).fill(0)).map(x=> Math.round(x*100));
      const cols = []; for(let k=0;k<nOut;k++) cols.push([]);
      const neutral = [];

      // first pass: max |Δ| in this game (across eligible entries & outcomes)
      // = the within-game scale for the relative-emphasis bars.
      const elig = [];
      let gMax = 0;
      names.forEach(n=>{
        if(!eligible(n)) return;
        const dd = (deltas[n] && deltas[n][mno]) || new Array(nOut).fill(0);
        let mx = 0; for(let k=0;k<nOut;k++) mx = Math.max(mx, Math.abs(dd[k]));
        gMax = Math.max(gMax, mx);
        elig.push({n, dd, mx});
      });
      const impOf = v => gMax > 0 ? Math.abs(v)/gMax : 0;
      elig.forEach(({n, dd, mx})=>{
        if(focus){
          for(let k=0;k<nOut;k++) cols[k].push({n, v:dd[k], imp:impOf(dd[k])});
        } else if(mx < THR){
          neutral.push(n);
        } else {
          let best=0; for(let k=1;k<nOut;k++) if(dd[k]>dd[best]) best=k;
          cols[best].push({n, v:dd[best], imp:impOf(dd[best])});
        }
      });

      const badge = isKo ? '<span class="rfko-badge">'+t('cheer.ko')+'</span>' : '';
      let buckets;
      if(isKo){
        const h1 = colHead(g.f1, T(g.homeEn), pr[0]);
        const h2 = colHead(g.f2, T(g.awayEn), pr[1]);
        buckets = '<div class="rfbuckets ko">'
                + bucketCol('win1', h1, cols[0], focus)
                + '<div class="rfvs"><span class="rfx-big">✕</span></div>'
                + bucketCol('win2', h2, cols[1], focus)
                + '</div>';
      } else {
        const h1 = colHead(g.f1, T(g.homeEn), pr[0]);
        const hd = '<div class="rfcolhd"><span class="rfx-big">✕</span>'
                 + '<span class="rfcname rfcdraw">'+t('cheer.draw')+'</span>'
                 + '<span class="rfprob">'+t('cheer.prob')+' '+pr[1]+'%</span></div>';
        const h2 = colHead(g.f2, T(g.awayEn), pr[2]);
        buckets = '<div class="rfbuckets">'
                + bucketCol('win1', h1, cols[0], focus)
                + bucketCol('draw', hd, cols[1], focus)
                + bucketCol('win2', h2, cols[2], focus)
                + '</div>';
      }
      let card = '<div class="rfgame"><div class="rftime-row"><span class="rftime">'+esc(g.ko)+'</span>'+badge+'</div>'
               + buckets;
      if(!focus && neutral.length){
        const nb = neutral.map(n=> chip(n, 0, false, 0)).join('');
        card += '<details class="rfneutral"><summary>'+I.fmt('cheer.neutral_sum', {n: neutral.length})+'</summary>'
              + '<div class="rfchips">'+nb+'</div></details>';
      }
      card += '</div>';
      html += card;
    });
    gamesEl.innerHTML = html;
  }

  // ---- dropdowns (search + multi-select), shared with the old UX ----
  function toggle(pop){ const open = pop.hidden; [fPop,hPop].forEach(p=>{ if(p) p.hidden=true; }); pop.hidden=!open; }
  if(fBtn) fBtn.addEventListener('click', e=>{ e.stopPropagation(); toggle(fPop); });
  if(hBtn) hBtn.addEventListener('click', e=>{ e.stopPropagation(); toggle(hPop); });
  document.addEventListener('click', e=>{ if(!e.target.closest('.rfdd')){ if(fPop)fPop.hidden=true; if(hPop)hPop.hidden=true; } });
  function search(list,q){ q=(q||'').trim().toLowerCase();
    list.querySelectorAll('[data-name]').forEach(o=>{ o.style.display=(!q||o.dataset.name.toLowerCase().indexOf(q)>=0)?'':'none'; }); }
  if(fSearch) fSearch.addEventListener('input', ()=> search(fList,fSearch.value));
  if(hSearch) hSearch.addEventListener('input', ()=> search(hList,hSearch.value));

  if(fList) fList.addEventListener('change', e=>{ const b=e.target.closest('input[type=checkbox]'); if(!b) return;
    if(b.checked) filt.add(b.value); else filt.delete(b.value); render(); });
  if(fClear) fClear.addEventListener('click', ()=>{ filt.clear();
    fList.querySelectorAll('input[type=checkbox]').forEach(b=>b.checked=false); render(); });

  if(hList) hList.addEventListener('click', e=>{ const o=e.target.closest('.rfopt2'); if(!o) return;
    const n=o.dataset.name;
    if(hi.has(n)){ hi.delete(n); o.classList.remove('cur'); } else { hi.add(n); o.classList.add('cur'); }
    render(); });
  if(hClear) hClear.addEventListener('click', ()=>{ hi.clear();
    hList.querySelectorAll('.rfopt2').forEach(b=>b.classList.remove('cur')); render(); });

  if(dayToggle) dayToggle.addEventListener('click', e=>{ const b=e.target.closest('.rfday'); if(!b||b.disabled) return;
    day=b.dataset.day; render(); });
  if(top3) top3.addEventListener('change', render);
  if(last) last.addEventListener('change', render);
  render();
  document.addEventListener('langchange', render);
})();
"""


_WHATIF_JS = r"""
const WHATIF = __WHATIF__;
(function(){
  const W = WHATIF;
  const board = document.getElementById('wiBoard');
  const matchesEl = document.getElementById('wiMatches');
  if(!W || !W.entries || !board || !matchesEl) return;
  // common ancestor for delegated events (covers matches list + bracket + board)
  const root = board.closest('.tabpanel') || document;
  const R = W.rules;
  const I = window.I18N;
  const t = k => I.t(k);
  const heT = en => I.team(en);
  const heP = en => I.player(en);
  const g2 = x => (Math.round(x*10)/10).toString();

  const gmByNo = {};            // match no -> {no,group,home,away}
  const gmByGroup = {};         // group -> [match,...]
  W.groupMatches.forEach(m=>{ gmByNo[m.no]=m; (gmByGroup[m.group]=gmByGroup[m.group]||[]).push(m); });
  const pairKey = (a,b)=> [a,b].sort().join(' || ');

  // ---- hypothetical state (what the user invented) ---------------------- //
  let hypoGroup = {};    // match no -> [hg,ag]
  let hypoKo = {};       // match no -> {hg,ag,so}  (so = shootout winner team)
  let hypoScorers = {};  // matchKey -> { player: goals }
  let lastSig = null;
  let lastFull = null;   // most recent evaluate(true) (for per-team goal caps)
  const playerTeam = {}; W.trackedPlayers.forEach(p=> playerTeam[p.name]=p.team);

  function mergedGroupScores(){
    const o = {};
    for(const k in W.realGroupScores) o[k] = W.realGroupScores[k];
    for(const k in hypoGroup) o[k] = hypoGroup[k];
    return o;
  }
  function mergedPlayerGoals(){
    const o = {};
    for(const k in (W.realPlayerGoals||{})) o[k] = W.realPlayerGoals[k];
    for(const mk in hypoScorers) for(const p in hypoScorers[mk]) o[p] = (o[p]||0) + hypoScorers[mk][p];
    return o;
  }

  function groupStandings(gs){
    const out = {complete:{}, finish:{}, adv:{}, winner:{}, runner:{}, third:{}, tstats:{}, allComplete:true};
    for(const g of Object.keys(W.groups)){
      const ms = gmByGroup[g]||[];
      const done = ms.every(m=> gs[m.no]!==undefined);
      out.complete[g] = done;
      if(!done){ out.allComplete = false; continue; }
      const tab = {}; const hh = {}; W.groups[g].forEach(t=>{ tab[t]={pts:0,gd:0,gf:0}; hh[t]={}; });
      ms.forEach(m=>{ const [hg,ag]=gs[m.no];
        tab[m.home].gf+=hg; tab[m.away].gf+=ag; tab[m.home].gd+=hg-ag; tab[m.away].gd+=ag-hg;
        if(hg>ag) tab[m.home].pts+=3; else if(ag>hg) tab[m.away].pts+=3; else { tab[m.home].pts++; tab[m.away].pts++; }
        // head-to-head record (each pair meets once in the group stage)
        hh[m.home][m.away] = {gf:hg, ga:ag, pts: hg>ag?3:(hg===ag?1:0)};
        hh[m.away][m.home] = {gf:ag, ga:hg, pts: ag>hg?3:(ag===hg?1:0)};
      });
      // FIFA 2026 tie-break: among teams level on points, rank by the mini-league
      // played BETWEEN them (H2H pts -> H2H GD -> H2H GF) before overall GD/GF.
      const mk = {};
      W.groups[g].forEach(t=>{ let mp=0,mgd=0,mgf=0;
        W.groups[g].forEach(o=>{ if(o===t || tab[o].pts!==tab[t].pts) return;
          const r=hh[t][o]; if(!r) return; mp+=r.pts; mgd+=r.gf-r.ga; mgf+=r.gf; });
        mk[t]=[mp,mgd,mgf];
      });
      const ord = W.groups[g].slice().sort((a,b)=> tab[b].pts-tab[a].pts
        || mk[b][0]-mk[a][0] || mk[b][1]-mk[a][1] || mk[b][2]-mk[a][2]
        || tab[b].gd-tab[a].gd || tab[b].gf-tab[a].gf || a.localeCompare(b));
      ord.forEach((t,i)=> out.finish[t]=i+1);
      out.winner[g]=ord[0]; out.runner[g]=ord[1]; out.third[g]=ord[2];
      out.adv[ord[0]]=true; out.adv[ord[1]]=true;
      out.tstats[g]=tab[ord[2]];
    }
    if(out.allComplete){
      const thirds = Object.keys(W.groups).map(g=>({g, t:out.third[g], s:out.tstats[g]}));
      thirds.sort((a,b)=> b.s.pts-a.s.pts || b.s.gd-a.s.gd || b.s.gf-a.s.gf || a.g.localeCompare(b.g));
      out.top8 = thirds.slice(0,8).map(x=>x.g).sort();
      thirds.slice(0,8).forEach(x=> out.adv[x.t]=true);
    }
    return out;
  }

  // Provisional per-group table from whatever results exist (partial-aware), so
  // the standings can be shown live while a group is still in progress.
  function groupTable(gs){
    const out = {};
    for(const g of Object.keys(W.groups)){
      const teams = W.groups[g];
      const tab = {}; teams.forEach(t=> tab[t]={p:0,w:0,d:0,l:0,gf:0,ga:0,gd:0,pts:0});
      (gmByGroup[g]||[]).forEach(m=>{ const s=gs[m.no]; if(s===undefined) return;
        const [hg,ag]=s; const H=tab[m.home], A=tab[m.away]; if(!H||!A) return;
        H.p++; A.p++; H.gf+=hg; H.ga+=ag; A.gf+=ag; A.ga+=hg; H.gd=H.gf-H.ga; A.gd=A.gf-A.ga;
        if(hg>ag){ H.w++; A.l++; H.pts+=3; } else if(ag>hg){ A.w++; H.l++; A.pts+=3; }
        else { H.d++; A.d++; H.pts++; A.pts++; }
      });
      const order = teams.slice().sort((a,b)=>
        tab[b].pts-tab[a].pts || tab[b].gd-tab[a].gd || tab[b].gf-tab[a].gf || a.localeCompare(b));
      out[g] = {order, stats:tab};
    }
    return out;
  }

  function matchThirds(groups8, slots){
    const inEl = (s,g)=> s.eligible.indexOf(g)>=0;
    const order = slots.map((s,i)=>i).sort((a,b)=>
      groups8.filter(g=>inEl(slots[a],g)).length - groups8.filter(g=>inEl(slots[b],g)).length);
    const assign={}, used={};
    function bt(k){
      if(k===order.length) return true;
      const si=order[k];
      for(const g of groups8){ if(used[g]) continue; if(inEl(slots[si],g)){ assign[si]=g; used[g]=1;
        if(bt(k+1)) return true; used[g]=0; delete assign[si]; } }
      return false;
    }
    if(!bt(0)){ const rem=groups8.slice(); slots.forEach((s,si)=>{ for(let j=0;j<rem.length;j++){ if(inEl(s,rem[j])){ assign[si]=rem[j]; rem.splice(j,1); break; } } });
      slots.forEach((s,si)=>{ if(assign[si]===undefined && rem.length) assign[si]=rem.shift(); }); }
    return assign;
  }

  // evaluate one full world (real merged with hypotheticals when useHypo)
  function evaluate(useHypo){
    const gs = useHypo ? mergedGroupScores() : Object.assign({}, W.realGroupScores);
    const stand = groupStandings(gs);
    const gtab = groupTable(gs);
    const koByMatch = {};       // match no -> {hg,ag,winner,so,real}
    const koPlayed = [];        // {home,away,hg,ag,winner,so}
    const fillable = [];        // KO matches awaiting a result
    const teamsByMatch = {}, winByMatch = {};
    let wonCup = null; const madeFinal = {};

    // Resolve the bracket whenever feeders are known - a KO match opens for
    // input as soon as BOTH its teams are determined (its feeder groups are
    // complete, or its feeder matches decided). 'third' slots additionally need
    // all 12 groups complete (the best-thirds ranking is global).
    const slotTeam = {};
    if(stand.allComplete){
      const assign = matchThirds(stand.top8, W.thirdSlots);   // slotIndex -> group
      W.thirdSlots.forEach((s,i)=> slotTeam[s.m+'|'+s.side] = stand.third[assign[i]]);
    }
    const resolve = (ref,m,side)=>{
      if(ref.type==='group_winner') return stand.winner[ref.group]||null;
      if(ref.type==='group_runner') return stand.runner[ref.group]||null;
      if(ref.type==='third') return slotTeam[m+'|'+side]||null;
      if(ref.type==='match_winner') return winByMatch[ref.match]||null;
      if(ref.type==='match_loser'){ const w=winByMatch[ref.match]; const tt=teamsByMatch[ref.match];
        if(!w||!tt) return null; return tt[0]===w?tt[1]:tt[0]; }
      return null;
    };
    const realByPair = {};
    (W.realKo||[]).forEach(k=> realByPair[pairKey(k.home,k.away)] = k);
    const matchedReal = {};
    let nUnresolved = 0;        // displayed KO matches that still lack a decided winner
    for(const bm of W.bracket){
      const home = resolve(bm.hr, bm.m, 'home_ref');
      const away = resolve(bm.ar, bm.m, 'away_ref');
      teamsByMatch[bm.m] = [home, away];
      if(!home || !away) continue;
      const rk = realByPair[pairKey(home,away)];
      if(rk && rk.winner){                       // real result: fixed, not shown for editing
        matchedReal[pairKey(home,away)]=1;
        let hg=rk.home_goals, ag=rk.away_goals; const so=!!rk.shootout;
        if(home!==rk.home){ const t=hg; hg=ag; ag=t; }
        winByMatch[bm.m]=rk.winner; koPlayed.push({home,away,hg,ag,winner:rk.winner,so});
        koByMatch[bm.m]={hg,ag,winner:rk.winner,so,real:true};
        continue;
      }
      // hypothetical entry: resolve a winner ONLY once BOTH scores are filled, so a
      // half-typed score never auto-progresses a team. The match stays in the editable
      // list either way (just like the group matches), so it never "disappears".
      let winner=null, hg=null, ag=null, so=false;
      const h = (useHypo && hypoKo[bm.m]!==undefined) ? hypoKo[bm.m] : null;
      if(h){ hg=(h.hg!=null?h.hg:null); ag=(h.ag!=null?h.ag:null); }
      if(hg!=null && ag!=null){
        if(hg>ag) winner=home; else if(ag>hg) winner=away; else { so=true; winner=h.so||null; } }
      if(winner){ winByMatch[bm.m]=winner; koPlayed.push({home,away,hg,ag,winner,so}); }
      else nUnresolved++;
      koByMatch[bm.m]={hg,ag,winner,so,real:false};
      fillable.push({m:bm.m, stage:bm.stage, rc:bm.rc, home, away, winner});
    }
    // safety: count any real KO result not matched into a bracket slot
    (W.realKo||[]).forEach(k=>{ if(!matchedReal[pairKey(k.home,k.away)] && k.winner)
      koPlayed.push({home:k.home,away:k.away,hg:k.home_goals,ag:k.away_goals,winner:k.winner,so:!!k.shootout}); });
    const ft = teamsByMatch[104]||[null,null];
    ft.forEach(t=>{ if(t) madeFinal[t]=true; });
    wonCup = winByMatch[104]||null;

    // per-team stats + goals for/against
    const st={}, gf={}, ga={};
    for(const t in W.teamTier){ st[t]={rw:0,dr:0,rl:0,pw:0,pl:0,finish:0,adv:false,fin:false,won:false}; gf[t]=0; ga[t]=0; }
    for(const no in gs){ const m=gmByNo[no]; if(!m) continue; const [hg,ag]=gs[no];
      gf[m.home]+=hg; ga[m.home]+=ag; gf[m.away]+=ag; ga[m.away]+=hg;
      if(hg>ag){ st[m.home].rw++; st[m.away].rl++; } else if(ag>hg){ st[m.away].rw++; st[m.home].rl++; }
      else { st[m.home].dr++; st[m.away].dr++; } }
    koPlayed.forEach(k=>{ gf[k.home]+=k.hg; ga[k.home]+=k.ag; gf[k.away]+=k.ag; ga[k.away]+=k.hg;
      if(!k.winner) return; const l = k.winner===k.home?k.away:k.home;
      if(k.so){ st[k.winner].pw++; st[l].pl++; } else { st[k.winner].rw++; st[l].rl++; } });
    for(const t in stand.finish){ st[t].finish=stand.finish[t]; st[t].adv=!!stand.adv[t]; }
    for(const t in madeFinal) st[t].fin=true;
    if(wonCup) st[wonCup].won=true;

    const pg = useHypo ? mergedPlayerGoals() : Object.assign({}, W.realPlayerGoals||{});
    const tournComplete = Object.keys(gs).length>=72 && stand.allComplete && nUnresolved===0 && !!winByMatch[104];
    let gb = null;
    if(tournComplete){ let mx=-1, who=null, tie=false;
      for(const p in pg){ if(pg[p]>mx){ mx=pg[p]; who=p; tie=false; } else if(pg[p]===mx){ tie=true; } }
      gb = tie?null:who; }

    function teamPts(t){ const s=st[t]; const tier=W.teamTier[t];
      let p = R.win*s.rw + R.draw*s.dr + R.loss*s.rl + R.pen_win*s.pw + R.pen_loss*s.pl;
      if(tier==='D'){ if(s.adv && s.finish>0 && s.finish<=2) p+=R.b_r32_top2_D; else if(s.adv && s.finish===3) p+=R.b_r32_third_D; }
      else if(tier==='C'){ if(s.adv && s.finish>0 && s.finish<=2) p+=R.b_r32_top2_C; }
      p += R.b_final*(s.fin?1:0) + R.b_win*(s.won?1:0);
      return p; }

    const bd={};
    for(const e of W.entries){ const k=e.picks;
      const o = {tierA:teamPts(k.tierA), tierB:teamPts(k.tierB), tierC:teamPts(k.tierC),
                 tierD:teamPts(k.tierD), scoring:R.per_gf*(gf[k.scoring]||0),
                 conceding:R.per_ga*(ga[k.conceding]||0),
                 top_scorer:R.per_gk*(pg[k.top_scorer]||0) + R.gb_bonus*((gb && gb===k.top_scorer)?1:0)};
      o.total = o.tierA+o.tierB+o.tierC+o.tierD+o.scoring+o.conceding+o.top_scorer;
      bd[e.name] = o; }
    return {bd, fillable, allComplete:stand.allComplete,
            stand, gtab, teamsByMatch, winByMatch, koByMatch};
  }

  const realEval = evaluate(false);                 // cached baseline engine score
  const SLOTS = ['tierA','tierB','tierC','tierD','scoring','conceding','top_scorer'];
  const baseTotal = {}, baseBd = {};
  W.entries.forEach(e=>{ baseTotal[e.name]=e.base; baseBd[e.name]=e.bd||{}; });
  // baseline ranking (current standings) for the "change" column
  const baseRank = {};
  W.entries.map(e=>e.name).sort((a,b)=> baseTotal[b]-baseTotal[a] || a.localeCompare(b))
    .forEach((n,i)=> baseRank[n]=i+1);

  function fmtStage(s){ const m={'Round of 32':'1/16 גמר','Round of 16':'1/8 גמר',
    'Quarter-final':'רבע גמר','Semi-final':'חצי גמר','Third place':'מקום שלישי','Final':'גמר'}; return m[s]||s; }

  // ---- group standings + bracket helpers --------------------------------- //
  const bm = {}; W.bracket.forEach(b=> bm[b.m]=b);     // match no -> bracket def
  function flagChar(en){ const iso=(W.iso||{})[en];
    if(!iso || iso.length!==2) return '';
    return String.fromCodePoint(...[...iso.toUpperCase()].map(c=>0x1F1E6+c.charCodeAt(0)-65)); }
  function refLabel(ref){
    if(!ref) return t('wi.tbd');
    if(ref.type==='group_winner') return I.fmt('wi.ref.gw',{g:ref.group});
    if(ref.type==='group_runner') return I.fmt('wi.ref.gr',{g:ref.group});
    if(ref.type==='third') return t('wi.ref.third');
    if(ref.type==='match_winner') return I.fmt('wi.ref.wm',{m:ref.match});
    if(ref.type==='match_loser') return I.fmt('wi.ref.lm',{m:ref.match});
    return t('wi.tbd'); }

  // baseline (real-only) group positions -> the standings "change" arrows
  const basePos = {};
  (function(){ const gt=realEval.gtab; for(const g in gt) gt[g].order.forEach((tm,i)=> basePos[tm]=i+1); })();
  function chgSpan(dr){ return dr>0?`<span class="chg-up">▲${dr}</span>`
    : dr<0?`<span class="chg-dn">▼${-dr}</span>` : '<span class="chg-eq">·</span>'; }

  function renderGroups(full){
    const el=document.getElementById('wiGroups'); if(!el) return;
    const gt=full.gtab, stand=full.stand, allDone=stand.allComplete;
    el.innerHTML = Object.keys(W.groups).sort().map(g=>{
      const order=gt[g].order, stats=gt[g].stats, done=stand.complete[g];
      const rows=order.map((tm,i)=>{ const s=stats[tm]; const pos=i+1;
        let cls=''; if(pos<=2) cls='q'+pos;
        else if(pos===3 && allDone && stand.top8 && stand.top8.indexOf(g)>=0) cls='q3';
        const bp=basePos[tm]; const dr=bp?(bp-pos):0; const fl=flagChar(tm);
        return `<tr class="${cls}"><td class="pos">${pos}</td>`+
          `<td class="nm" title="${tm}">${fl?`<span class="wgfl">${fl}</span>`:''}${heT(tm)}</td>`+
          `<td>${s.p}</td><td class="pts">${s.pts}</td>`+
          `<td dir="ltr">${s.gd>0?'+':''}${s.gd}</td>`+
          `<td class="chg">${chgSpan(dr)}</td></tr>`;
      }).join('');
      return `<div class="wgcard${done?'':' live'}">`+
        `<div class="wgh"><span>${t('groups.group')} ${g}</span>${done?'<span class="wgdone">✓</span>':''}</div>`+
        `<table class="wgtbl"><thead><tr>`+
          `<th>${t('wi.gt.pos')}</th><th class="nm">${t('wi.gt.team')}</th>`+
          `<th>${t('wi.gt.p')}</th><th>${t('wi.gt.pts')}</th><th>${t('wi.gt.gd')}</th><th></th>`+
        `</tr></thead><tbody>${rows}</tbody></table></div>`;
    }).join('');
  }

  // ---- bracket (two-sided, NBA-style) ------------------------------------ //
  function childMatches(m){ const b=bm[m]; const r=[];
    if(b) [b.hr,b.ar].forEach(ref=>{ if(ref && ref.type==='match_winner') r.push(ref.match); });
    return r; }
  function sideRounds(root){ const byRc={};
    (function rec(m){ const b=bm[m]; if(!b) return; childMatches(m).forEach(rec);
      (byRc[b.rc]=byRc[b.rc]||[]).push(m); })(root);
    return byRc; }
  function teamRow(m, side, team, ref, win, score, disabled){
    const tbd=!team;
    const nm = tbd ? `<span class="wibr-nm tbd">${refLabel(ref)}</span>`
      : `<span class="wibr-fl">${flagChar(team)}</span><span class="wibr-nm" title="${team}">${heT(team)}</span>`;
    const cls = win ? (win===team?'win':'lose') : '';
    const val = (score!=null)?score:'';
    return `<div class="wibr-trow ${cls}">${nm}`+
      `<input class="wiscore wibr-sc" type="number" min="0" inputmode="numeric" data-kind="k" data-m="${m}" data-side="${side}" value="${val}"${(disabled||tbd)?' disabled':''}></div>`;
  }
  function nodeHtml(m, full, extraCls){
    const b=bm[m]; const tm=full.teamsByMatch[m]||[null,null];
    const ko=full.koByMatch[m]||null; const win=full.winByMatch[m]||null;
    const real=!!(ko&&ko.real); const hg=ko?ko.hg:null, ag=ko?ko.ag:null;
    const tied=(hg!=null && ag!=null && hg===ag);
    let pen='';
    if(!real && tied){ const so=(hypoKo[m]||{}).so||'';
      pen=`<div class="wibr-pen">${t('wi.so')}`+
        `<button type="button" class="wibr-penbtn${so===tm[0]?' on':''}" data-m="${m}" data-team="${tm[0]||''}"${tm[0]?'':' disabled'}>${heT(tm[0]||'')}</button>`+
        `<button type="button" class="wibr-penbtn${so===tm[1]?' on':''}" data-m="${m}" data-team="${tm[1]||''}"${tm[1]?'':' disabled'}>${heT(tm[1]||'')}</button></div>`; }
    let scr='';
    const goals=(hg||0)+(ag||0);
    if(!real && hg!=null && ag!=null && goals>0){ const s=scorerEditor('k'+m, hg, ag, tm[0], tm[1]);
      if(s) scr=`<div class="wibr-scorers">${s}</div>`; }
    return `<div class="wibr-node${win?' decided':''} ${extraCls||''}" data-mbox data-mk="k${m}">`+
      `<span class="wibr-mno">M${m}</span>`+
      teamRow(m,'h',tm[0],b.hr,win,hg,real)+
      teamRow(m,'a',tm[1],b.ar,win,ag,real)+pen+scr+`</div>`;
  }
  function colHtml(matches, full, rc){
    return `<div class="wibr-round"><div class="wibr-rndhd">${t('wi.rc.'+rc)}</div>`+
      `<div class="wibr-col">${matches.map(m=> nodeHtml(m, full)).join('')}</div></div>`;
  }
  function renderBracket(full){
    const wrap=document.getElementById('wiBracket'); if(!wrap) return;
    const prevLeft=wrap.scrollLeft;
    const L=sideRounds(101), Rt=sideRounds(102);
    let h='';
    [1,2,3,4].forEach(rc=> h+=colHtml((L[rc]||[]), full, rc));
    h+=`<div class="wibr-round fin"><div class="wibr-rndhd">${t('wi.rc.6')}</div>`+
       `<div class="wibr-col cen">${nodeHtml(104, full, 'fin')}`+
       `<div class="wibr-rndhd" style="margin-top:8px">${t('wi.rc.5')}</div>${nodeHtml(103, full, 'tp')}</div></div>`;
    [4,3,2,1].forEach(rc=> h+=colHtml((Rt[rc]||[]), full, rc));
    wrap.innerHTML=`<div class="wibracket">${h}</div>`;
    wrap.scrollLeft=prevLeft;
  }

  // scenario points = site baseline + (engine(real+hypo) - engine(real)), per slot,
  // so with no hypotheticals it reproduces the displayed standings exactly.
  function dispBd(name, full){
    const o = {};
    SLOTS.forEach(s=>{ o[s] = Math.round(((baseBd[name][s]||0)
      + ((full.bd[name][s]||0) - (realEval.bd[name][s]||0)))*10)/10; });
    o.total = Math.round((baseTotal[name] + (full.bd[name].total - realEval.bd[name].total))*10)/10;
    return o;
  }

  function renderBoard(full){
    const rows = W.entries.map(e=>({name:e.name, picks:e.picks, d:dispBd(e.name, full)}));
    rows.sort((a,b)=> b.d.total-a.d.total || baseTotal[b.name]-baseTotal[a.name] || a.name.localeCompare(b.name));
    board.innerHTML = rows.map((r,i)=>{
      const rk=i+1, dr = baseRank[r.name]-rk;
      const chg = dr>0?`<span class="chg-up">▲${dr}</span>` : dr<0?`<span class="chg-dn">▼${-dr}</span>` : '<span class="chg-eq">–</span>';
      const cell = (nm,player,slot)=>`<td class="pick">${player?heP(nm):heT(nm)} <small>(${g2(r.d[slot])})</small></td>`;
      return `<tr><td class="rk">${rk}</td><td>${chg}</td>`+
             `<td class="nm" title="${r.name}">${r.name}</td><td class="pts">${g2(r.d.total)}</td>`+
             cell(r.picks.tierA,false,'tierA')+cell(r.picks.tierB,false,'tierB')+
             cell(r.picks.tierC,false,'tierC')+cell(r.picks.tierD,false,'tierD')+
             cell(r.picks.scoring,false,'scoring')+cell(r.picks.conceding,false,'conceding')+
             cell(r.picks.top_scorer,true,'top_scorer')+`</tr>`;
    }).join('');
  }

  function scorerEditor(mk, hg, ag, home, away){
    // only picked "top scorer" candidates who actually play in this match
    const elig = W.trackedPlayers.filter(p=> p.team===home || p.team===away);
    if(!elig.length) return '';
    const cur = hypoScorers[mk]||{};
    // each candidate is capped by the goals scored by THEIR OWN team, not the
    // match total (a 1:1 can give at most 1 goal to each side's scorers).
    const cap = {}; cap[home]=hg||0; cap[away]=ag||0;
    const usedBy = {}; usedBy[home]=0; usedBy[away]=0;
    for(const q in cur){ const tm=playerTeam[q]; if(tm in usedBy) usedBy[tm]+=cur[q]; }
    const over = usedBy[home]>cap[home] || usedBy[away]>cap[away];
    const rows = elig.map(p=>{
      const v = cur[p.name]||0;
      const teamCap = cap[p.team]||0, teamUsed = usedBy[p.team]||0;
      return `<div class="wisc-row">
        <span class="wisc-nm">${heP(p.name)} <small>· ${heT(p.team)} (${teamUsed}/${teamCap})</small></span>
        <span class="wistep">
          <button type="button" class="wistepbtn wisc-dec" data-mk="${mk}" data-p="${p.name}" ${v<=0?'disabled':''}>−</button>
          <span class="wisc-v">${v}</span>
          <button type="button" class="wistepbtn wisc-inc" data-mk="${mk}" data-p="${p.name}" ${teamUsed>=teamCap?'disabled':''}>+</button>
        </span></div>`;
    }).join('');
    return `<div class="wiscorers">
      <div class="wisc-hd">${t('wi.scorers')}</div>
      ${rows}
      ${over?`<div class="wihint" style="color:var(--red)">${t('wi.sc.over')}</div>`:''}
    </div>`;
  }

  function matchRow(kind, m, home, away, score, stage, winner){
    const mk = kind+m;
    const h0 = score? score[0] : null, a0 = score? score[1] : null;
    const hv = (h0!=null) ? h0 : '';
    const av = (a0!=null) ? a0 : '';
    const both = (h0!=null && a0!=null);     // a KO match is "played" only when both filled
    const tie = both && h0===a0;
    const goals = both ? (h0+a0) : 0;
    let so = '';
    if(kind==='k' && tie){
      const w = (hypoKo[m]||{}).so || '';
      so = `<div class="wiso">${t('wi.so')}
        <label><input type="radio" name="so${m}" class="wisoR" data-m="${m}" value="${home}" ${w===home?'checked':''}> ${heT(home)}</label>
        <label><input type="radio" name="so${m}" class="wisoR" data-m="${m}" value="${away}" ${w===away?'checked':''}> ${heT(away)}</label></div>`;
    }
    const scr = (both && goals>0) ? scorerEditor(mk, h0, a0, home, away) : '';
    const adv = (kind==='k' && winner) ? `<div class="wiadv">${t('wi.advance')} <b>${heT(winner)}</b></div>` : '';
    return `<div class="wimatch${winner?' decided':''}" data-mbox data-mk="${mk}">
      <div class="wimrow">
        <span class="witeam h">${heT(home)}</span>
        <input class="wiscore" type="number" min="0" inputmode="numeric" data-kind="${kind}" data-m="${m}" data-side="h" value="${hv}">
        <span class="widash">:</span>
        <input class="wiscore" type="number" min="0" inputmode="numeric" data-kind="${kind}" data-m="${m}" data-side="a" value="${av}">
        <span class="witeam a">${heT(away)}</span>
      </div>${so}${scr}${adv}</div>`;
  }

  function renderMatches(full){
    // only group matches still open (no real result yet); KO lives in the bracket
    const openGroup = W.groupMatches.filter(m=> W.realGroupScores[m.no]===undefined)
      .sort((a,b)=> a.no-b.no);
    let html = '';
    if(!openGroup.length) html = '<div class="wihint">'+t('wi.no_group')+'</div>';
    else openGroup.forEach(m=> html += matchRow('g', m.no, m.home, m.away, hypoGroup[m.no]||null, 'group'));
    const top = matchesEl.scrollTop;     // keep the scroll position across re-renders
    matchesEl.innerHTML = html;
    matchesEl.scrollTop = top;
  }

  function sigOf(full){
    return (full.allComplete?'C':'-') + '|' + full.fillable.map(f=>f.m+(f.winner?'>'+f.winner:'')).join(',') +
           '|' + W.groupMatches.filter(m=>W.realGroupScores[m.no]===undefined && hypoGroup[m.no]).length;
  }

  function recompute(forceMatches){
    const full = evaluate(true);
    lastFull = full;
    renderBoard(full);
    renderGroups(full);
    // remember which score input is focused so we can restore it after rebuilding
    // (group list + bracket both rebuild on edits, otherwise typing loses focus)
    const a = document.activeElement;
    const desc = (a && a.classList && a.classList.contains('wiscore'))
      ? {m:a.dataset.m, kind:a.dataset.kind, side:a.dataset.side} : null;
    const sig = sigOf(full);
    if(forceMatches || sig!==lastSig){ renderMatches(full); lastSig = sig; }
    renderBracket(full);
    if(desc){
      const el = root.querySelector('.wiscore[data-m="'+desc.m+'"][data-kind="'+desc.kind+'"][data-side="'+desc.side+'"]');
      if(el && el!==document.activeElement){ el.focus(); const v=el.value; try{ el.value=''; el.value=v; }catch(e){} }
    }
    const nHypo = Object.keys(hypoGroup).length + Object.keys(hypoKo).length;
    document.getElementById('wiCount').textContent = nHypo? I.fmt('wi.count.n', {n: nHypo}) : t('wi.count.none');
  }

  // ---- events (delegated) ------------------------------------------------ //
  root.addEventListener('input', function(ev){
    const t = ev.target;
    if(t.classList.contains('wiscore')){
      const m = +t.dataset.m, kind = t.dataset.kind;
      const box = t.closest('[data-mbox]');
      if(!box) return;
      const ins = box.querySelectorAll('.wiscore');
      const hv = ins[0].value==='' ? null : Math.max(0, parseInt(ins[0].value,10)||0);
      const av = ins[1].value==='' ? null : Math.max(0, parseInt(ins[1].value,10)||0);
      if(hv===null && av===null){
        if(kind==='g'){ delete hypoGroup[m]; }
        else { delete hypoKo[m]; delete hypoScorers['k'+m]; }
      }
      else if(kind==='g'){ hypoGroup[m]=[hv||0, av||0]; }    // group rows stay visible, so 0-fill is fine
      else {
        // KO: keep a half-typed score as a *partial* (null side) entry. The bracket
        // resolves a winner only when both sides are filled, so a single goal no
        // longer auto-advances a team / makes the match vanish.
        const prev=hypoKo[m]||{};
        hypoKo[m]={hg:hv, ag:av, so:((hv!=null && av!=null && hv===av)?prev.so:undefined)};
        if(hv==null || av==null) delete hypoScorers['k'+m];   // partial -> drop scorers
      }
      recompute(true);   // refresh the scorer editor (eligibility + goal caps)
    }
  });
  function matchGoals(mk){ const kind=mk[0], m=mk.slice(1);
    if(kind==='g'){ const s=hypoGroup[m]; return s? s[0]+s[1] : 0; }
    const s=hypoKo[m]; return s? s.hg+s.ag : 0; }
  // goals scored by ONE team in a match — caps each scorer to their own side.
  function teamGoalsForMatch(mk, team){ const kind=mk[0], id=mk.slice(1);
    if(kind==='g'){ const m=gmByNo[id]; const s=hypoGroup[id]; if(!m||!s) return 0;
      return team===m.home? (s[0]||0) : (team===m.away? (s[1]||0) : 0); }
    const k=hypoKo[id]; if(!k) return 0;
    const tm=(lastFull && lastFull.teamsByMatch[id]) || [null,null];
    return team===tm[0]? (k.hg||0) : (team===tm[1]? (k.ag||0) : 0); }
  root.addEventListener('change', function(ev){
    const t = ev.target;
    if(t.classList.contains('wisoR')){ const m=+t.dataset.m; if(hypoKo[m]) hypoKo[m].so=t.value; recompute(false); }
  });
  root.addEventListener('click', function(ev){
    const t = ev.target;
    if(t.classList.contains('wibr-penbtn')){ const m=+t.dataset.m, team=t.dataset.team;
      if(team && hypoKo[m]){ hypoKo[m].so=team; recompute(false); } return;
    }
    if(t.classList.contains('wisc-inc')){ const mk=t.dataset.mk, p=t.dataset.p;
      const team=playerTeam[p]; const cur=hypoScorers[mk]||{};
      let teamUsed=0; for(const q in cur){ if(playerTeam[q]===team) teamUsed+=cur[q]; }
      if(teamUsed < teamGoalsForMatch(mk, team)){ hypoScorers[mk]=cur; cur[p]=(cur[p]||0)+1; recompute(true); }
    } else if(t.classList.contains('wisc-dec')){ const mk=t.dataset.mk, p=t.dataset.p;
      const cur=hypoScorers[mk]; if(cur && cur[p]){ cur[p]--; if(cur[p]<=0) delete cur[p];
        if(!Object.keys(cur).length) delete hypoScorers[mk]; recompute(true); }
    }
  });
  document.getElementById('wiReset').addEventListener('click', function(){
    hypoGroup={}; hypoKo={}; hypoScorers={}; recompute(true);
  });
  // one-click: fill every still-open group match with the model's most-probable
  // scoreline (KO matches are left alone - they then open as their feeders resolve).
  const fillBtn = document.getElementById('wiFillGroups');
  if(fillBtn){
    const pred = W.predGroupScores||{};
    if(!Object.keys(pred).length){ fillBtn.disabled = true; }
    fillBtn.addEventListener('click', function(){
      const predSc = W.predGroupScorers||{};
      W.groupMatches.forEach(m=>{
        if(W.realGroupScores[m.no]!==undefined) return;   // already played for real
        const mk = 'g'+m.no;
        const p = pred[m.no];
        if(p) hypoGroup[m.no] = [p[0], p[1]];
        const sc = predSc[m.no];
        if(sc && Object.keys(sc).length) hypoScorers[mk] = Object.assign({}, sc);
        else delete hypoScorers[mk];
      });
      recompute(true);
    });
  }

  recompute(true);
  document.addEventListener('langchange', ()=> recompute(true));
})();
"""


_ODDS_JS = r"""
const ODDS = __ODDS__;
(function(){
  const O = ODDS;
  if(!O || !document.getElementById('odElo')) return;
  const I = window.I18N;
  const t = k => I.t(k);
  const T = en => I.team(en);
  const P = en => I.player(en);
  const pct = x => (x==null? '—' : (x*100).toFixed(1)+'%');
  const num = x => (x==null? '—' : Math.round(x));
  const HIST_LS = 'wc2026-odhist-axis';
  let histAxis = localStorage.getItem(HIST_LS) || 'run';
  if (histAxis !== 'run' && histAxis !== 'day') histAxis = 'run';

  function dayKey(ts){
    const m = (ts||'').match(/^(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : null;
  }
  function fmtDayLabel(day){
    const p = day.split('-');
    return p.length===3 ? (p[2]+'/'+p[1]) : day;
  }
  function aggregateByDay(hist){
    const buckets = new Map();
    hist.forEach(h=>{
      const d = dayKey(h.ts);
      if(!d) return;
      let b = buckets.get(d);
      if(!b) b = {n:0, spread:0, gb:0, titles:{}};
      b.n++;
      if(h.strength_spread!=null) b.spread += h.strength_spread;
      if(h.golden_boot_scale!=null) b.gb += h.golden_boot_scale;
      Object.entries(h.sim_title||{}).forEach(([team,v])=>{
        b.titles[team] = (b.titles[team]||0) + v;
      });
      buckets.set(d, b);
    });
    return [...buckets.entries()].sort((a,b)=> a[0].localeCompare(b[0])).map(([day,b])=>({
      ts: day,
      strength_spread: b.n ? b.spread/b.n : null,
      golden_boot_scale: b.n ? b.gb/b.n : null,
      sim_title: Object.fromEntries(Object.entries(b.titles).map(([team,s])=>[team, s/b.n]))
    }));
  }
  function downsampleRuns(hist, max){
    if(hist.length <= max) return hist;
    const step = Math.floor(hist.length / max) + 1;
    const out = hist.filter((_,i)=> i % step === 0);
    const last = hist[hist.length-1];
    if(out[out.length-1] !== last) out.push(last);
    return out;
  }
  function chartPoints(raw){
    if(histAxis === 'day') return aggregateByDay(raw);
    return downsampleRuns(raw, 60);
  }

  function renderKalshiChart(){
    const host = document.getElementById('odKalshi');
    if(!host) return;
    const k = O.kalshi||{};
    const series = k.series||[];
    if(series.length < 1 || !(series[0].points||[]).length){
      host.innerHTML = '<div class="wihint">'+t('od.kalshi_empty')+'</div>';
      return;
    }
    const COLORS = ['#2563eb','#16a34a','#d97706','#7c3aed','#dc2626','#0891b2','#db2777','#65a30d'];
    const allTs = new Set();
    series.forEach(s=> (s.points||[]).forEach(pt=> allTs.add(pt.ts)));
    const tsList = Array.from(allTs).sort((a,b)=> a-b);
    const idx = {}; tsList.forEach((t,i)=> idx[t]=i);
    const W=560, H=240, padL=44, padR=12, padT=14, padB=36;
    const n = tsList.length;
    const xs = tsList.map((_,i)=> padL + (W-padL-padR)*(n>1? i/(n-1):0));
    let vmax=0;
    series.forEach(s=> (s.points||[]).forEach(pt=>{ if(pt.p>vmax) vmax=pt.p; }));
    vmax = vmax>0? vmax*1.12 : 0.25;
    const y = v => padT + (H-padT-padB)*(1 - (v/vmax));
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="odsvg">`;
    [0,0.25,0.5,0.75,1].forEach(f=>{ const yy=padT+(H-padT-padB)*f; const val=vmax*(1-f);
      svg+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="#e2e8f0"/>`+
           `<text x="${padL-6}" y="${yy+3}" text-anchor="end" font-size="9" fill="#94a3b8">${(val*100).toFixed(0)}%</text>`; });
    const step = n > 14 ? Math.ceil(n/14) : 1;
    for(let i=0; i<n; i+=step){
      const d = new Date(tsList[i]*1000);
      const lbl = d.toLocaleDateString(undefined,{month:'short',day:'numeric'});
      svg+=`<text x="${xs[i].toFixed(1)}" y="${H-8}" text-anchor="middle" font-size="9" fill="#94a3b8">${lbl}</text>`;
    }
    series.forEach((s,si)=>{
      const c=COLORS[si%COLORS.length];
      let d='';
      (s.points||[]).forEach(pt=>{
        const i=idx[pt.ts]; if(i==null) return;
        d+=(d?'L':'M')+xs[i].toFixed(1)+' '+y(pt.p).toFixed(1)+' ';
      });
      svg+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="2"/>`;
    });
    svg += '</svg>';
    const leg = series.map((s,si)=>`<span class="odlg"><span class="odsw" style="background:${COLORS[si%COLORS.length]}"></span>${T(s.team)}</span>`).join('');
    const link = k.source_url ? `<a class="odlink" href="${k.source_url}" target="_blank" rel="noopener">${t('od.kalshi_link')}</a>` : '';
    host.innerHTML = `<div class="odchart"><div class="odleg">${leg}</div>${svg}${link?`<div style="margin-top:6px">${link}</div>`:''}</div>`;
  }

  function renderEloPrior(){
    const tb = document.getElementById('odEloPrior');
    const note = document.getElementById('odEloPriorNote');
    const chartHost = document.getElementById('odEloPriorChart');
    if(!tb) return;
    const ep = O.eloPrior||{};
    const rows = ep.rows||[];
    if(!rows.length){
      tb.innerHTML = '<tr><td class="nm" colspan="4">—</td></tr>';
      if(note) note.textContent = t('od.elop.empty');
      if(chartHost) chartHost.innerHTML = '';
      return;
    }
    if(note){
      const rd = ep.round||'—';
      note.innerHTML = `${t('od.elop.round')}: <b>${rd}</b> · α=${ep.alpha!=null?ep.alpha:'—'}`;
    }
    const num1 = v => v==null? '—' : v.toFixed(1);
    tb.innerHTML = rows.map(r=>{
      const d = (r.weighted!=null && r.baseline!=null)? (r.weighted-r.baseline):null;
      const ds = d==null? '—' : (d>=0? '+':'')+d.toFixed(1);
      const dc = d==null? '' : (d>0? 'style="color:#16a34a"' : (d<0? 'style="color:#dc2626"':''));
      return `<tr><td class="nm">${T(r.team)}</td><td>${num1(r.baseline)}</td>`+
             `<td class="v">${num1(r.weighted)}</td><td>${num1(r.live)}</td>`+
             `<td ${dc}>${ds}</td></tr>`;
    }).join('');

    // Convergence chart: weighted ELO per round for the top teams. Round 0 =
    // baseline; each subsequent point is a scheduled per-round update.
    const hist = ep.history||[];
    if(chartHost){
      if(hist.length < 1){ chartHost.innerHTML=''; return; }
      const teams = rows.slice(0,5).map(r=> r.team);
      const labels = ['base'].concat(hist.map(h=> h.round||''));
      const baseByTeam = {}; rows.forEach(r=> baseByTeam[r.team]=r.baseline);
      const series = teams.map(tm=>{
        const vals = [baseByTeam[tm]];
        hist.forEach(h=> vals.push((h.weighted_top||{})[tm] ?? null));
        return {label:T(tm), vals};
      });
      const W=560,H=220,padL=46,padR=12,padT=14,padB=30;
      const n=labels.length;
      const xs=labels.map((_,i)=> padL+(W-padL-padR)*(n>1? i/(n-1):0));
      let vmin=Infinity,vmax=-Infinity;
      series.forEach(s=> s.vals.forEach(v=>{ if(v!=null){ if(v<vmin)vmin=v; if(v>vmax)vmax=v; }}));
      if(!isFinite(vmin)){ chartHost.innerHTML=''; return; }
      const pad=(vmax-vmin)*0.15||20; vmin-=pad; vmax+=pad;
      const y=v=> padT+(H-padT-padB)*(1-(v-vmin)/(vmax-vmin));
      const COLORS=['#2563eb','#16a34a','#d97706','#7c3aed','#dc2626'];
      let svg=`<svg viewBox="0 0 ${W} ${H}" class="odsvg">`;
      [0,0.25,0.5,0.75,1].forEach(f=>{ const yy=padT+(H-padT-padB)*f; const val=vmax-(vmax-vmin)*f;
        svg+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="#e2e8f0"/>`+
             `<text x="${padL-6}" y="${yy+3}" text-anchor="end" font-size="9" fill="#94a3b8">${val.toFixed(0)}</text>`;});
      labels.forEach((lb,i)=>{ svg+=`<text x="${xs[i].toFixed(1)}" y="${H-8}" text-anchor="middle" font-size="9" fill="#94a3b8">${lb}</text>`; });
      series.forEach((s,si)=>{ const c=COLORS[si%COLORS.length]; let d='';
        s.vals.forEach((v,i)=>{ if(v==null) return; d+=(d?'L':'M')+xs[i].toFixed(1)+' '+y(v).toFixed(1)+' '; });
        svg+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="2"/>`;
        s.vals.forEach((v,i)=>{ if(v!=null) svg+=`<circle cx="${xs[i].toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.2" fill="${c}"/>`; });
      });
      svg+='</svg>';
      const leg=series.map((s,si)=>`<span class="odlg"><span class="odsw" style="background:${COLORS[si%COLORS.length]}"></span>${s.label}</span>`).join('');
      chartHost.innerHTML = `<div class="odchart"><div class="odleg">${leg}</div>${svg}</div>`;
    }
  }

  function renderOdds(){
    const cal = O.calibration||{};
    document.getElementById('odCal').innerHTML =
      `<div class="odchip"><span class="odk">${t('od.spread')}</span><span class="odv">${cal.strength_spread!=null?cal.strength_spread.toFixed(3):'—'}</span></div>`+
      `<div class="odchip"><span class="odk">${t('od.gb_scale')}</span><span class="odv">${cal.golden_boot_scale!=null?cal.golden_boot_scale.toFixed(3):'—'}</span></div>`+
      `<div class="odchip"><span class="odk">${t('od.updated')}</span><span class="odv">${O.generatedAt||'—'}</span></div>`;

    document.getElementById('odElo').innerHTML = (O.elo||[]).map(r=>
      `<tr><td class="nm">${T(r.team)}</td><td class="v">${num(r.blended)}</td><td>${num(r.eloratings)}</td>`+
      `<td>${num(r.market)}</td><td>${pct(r.marketProb)}</td></tr>`).join('');

    const titleRows = Object.keys(O.simTitle||{}).map(team=>({t:team, sim:O.simTitle[team]}));
    const eloByTeam = {}; (O.elo||[]).forEach(r=> eloByTeam[r.team]=r.marketProb);
    titleRows.sort((a,b)=> b.sim-a.sim);
    document.getElementById('odTitle').innerHTML = titleRows.map(r=>
      `<tr><td class="nm">${T(r.t)}</td><td>${pct(eloByTeam[r.t])}</td><td class="v">${pct(r.sim)}</td></tr>`).join('')
      || '<tr><td class="nm" colspan="3">—</td></tr>';

    document.getElementById('odAdv').innerHTML = (O.advance||[]).map(r=>
      `<tr><td class="nm">${T(r.team)}</td><td class="v">${pct(r.p)}</td></tr>`).join('');
    document.getElementById('odGb').innerHTML = (O.goldenBoot||[]).map(r=>
      `<tr><td class="nm">${P(r.player)}</td><td class="v">${pct(r.p)}</td></tr>`).join('');

    renderKalshiChart();
    renderEloPrior();

    const raw = O.history||[];
    const host = document.getElementById('odHist');
    const axisWrap = document.getElementById('odHistAxis');
    if(axisWrap){
      axisWrap.querySelectorAll('button[data-axis]').forEach(b=>{
        b.classList.toggle('on', b.dataset.axis===histAxis);
      });
    }
    if(raw.length < 2){
      host.innerHTML = '<div class="wihint">'+t('od.hist.empty')+'</div>';
      return;
    }
    const hist = chartPoints(raw);
    if(hist.length < 2){
      host.innerHTML = '<div class="wihint">'+t('od.hist.empty')+'</div>';
      return;
    }
    const xLabels = histAxis==='day'
      ? hist.map(h=> fmtDayLabel(dayKey(h.ts)||''))
      : null;
    const COLORS = ['#2563eb','#16a34a','#d97706','#7c3aed','#dc2626','#0891b2'];
    function lineChart(title, series, fmtY){
      const W=560, H=xLabels?230:210, padL=44, padR=12, padT=14, padB=xLabels?36:26;
      const n = hist.length;
      const xs = hist.map((_,i)=> padL + (W-padL-padR)*(n>1? i/(n-1):0));
      let vmax=0; series.forEach(s=> s.vals.forEach(v=>{ if(v!=null && v>vmax) vmax=v; }));
      vmax = vmax>0? vmax*1.1 : 1;
      const y = v => padT + (H-padT-padB)*(1 - (v/vmax));
      let svg = `<svg viewBox="0 0 ${W} ${H}" class="odsvg">`;
      [0,0.25,0.5,0.75,1].forEach(f=>{ const yy=padT+(H-padT-padB)*f; const val=vmax*(1-f);
        svg+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="#e2e8f0"/>`+
             `<text x="${padL-6}" y="${yy+3}" text-anchor="end" font-size="9" fill="#94a3b8">${fmtY(val)}</text>`; });
      if(xLabels){
        const step = n > 14 ? Math.ceil(n/14) : 1;
        for(let i=0; i<n; i+=step){
          svg+=`<text x="${xs[i].toFixed(1)}" y="${H-8}" text-anchor="middle" font-size="9" fill="#94a3b8">${xLabels[i]}</text>`;
        }
      }
      series.forEach((s,si)=>{ const c=COLORS[si%COLORS.length];
        let d=''; s.vals.forEach((v,i)=>{ if(v==null) return; d+=(d?'L':'M')+xs[i].toFixed(1)+' '+y(v).toFixed(1)+' '; });
        svg+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="2"/>`; });
      svg += '</svg>';
      const leg = series.map((s,si)=>`<span class="odlg"><span class="odsw" style="background:${COLORS[si%COLORS.length]}"></span>${s.label}</span>`).join('');
      return `<div class="odchart"><div class="panel-title">${title}</div><div class="odleg">${leg}</div>${svg}</div>`;
    }
    const last = hist[hist.length-1];
    const titleKeys = Object.keys(last.sim_title||{}).sort((a,b)=> (last.sim_title[b]||0)-(last.sim_title[a]||0)).slice(0,6);
    const s1 = titleKeys.map(team=>({label:T(team), vals:hist.map(h=> (h.sim_title||{})[team]!=null? h.sim_title[team]:null)}));
    const s2 = [{label:t('od.chart.spread_short'), vals:hist.map(h=> h.strength_spread!=null? h.strength_spread:null)},
                {label:t('od.chart.gb_short'), vals:hist.map(h=> h.golden_boot_scale!=null? h.golden_boot_scale:null)}];
    host.innerHTML =
      (s1.length? lineChart(t('od.chart.title_sim'), s1, v=> (v*100).toFixed(0)+'%') : '') +
      lineChart(t('od.chart.title_cal'), s2, v=> v.toFixed(2));
  }

  const axisWrap = document.getElementById('odHistAxis');
  if(axisWrap){
    axisWrap.addEventListener('click', e=>{
      const b = e.target.closest('button[data-axis]');
      if(!b) return;
      histAxis = b.dataset.axis;
      localStorage.setItem(HIST_LS, histAxis);
      renderOdds();
    });
  }
  renderOdds();
  document.addEventListener('langchange', renderOdds);
})();
"""


STAGES_CSS = """
  /* ---- "עד לאן יגיעו?" — stage-reaching heatmap + distribution chart ---- */
  .stwrap{margin-top:6px;}
  .stctrls{display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:10px 0 4px;}
  .stmode{display:inline-flex; border:1px solid var(--line); border-radius:10px; overflow:hidden;}
  .stmode button{appearance:none; border:0; background:#fff; color:#475569; font-weight:700;
            padding:7px 12px; cursor:pointer; font-size:.86rem;}
  .stmode button.on{background:linear-gradient(135deg,#0b1220,#1e3a8a); color:#fff;}
  .stmode button+button{border-inline-start:1px solid var(--line);}
  .sthint{color:var(--muted); font-size:.82rem; margin:2px 0 0;}
  /* heatmap */
  .stheatwrap{overflow:auto; border:1px solid var(--line); border-radius:12px; margin-top:8px;}
  table.sttbl{border-collapse:separate; border-spacing:0; width:100%; font-size:.82rem;
            font-variant-numeric:tabular-nums;}
  table.sttbl thead th{position:sticky; top:0; z-index:2; background:#f8fafc; color:#475569;
            font-weight:700; padding:8px 9px; border-bottom:1px solid var(--line); white-space:nowrap;}
  table.sttbl thead th.nm{z-index:3; inset-inline-start:0; text-align:right;}
  table.sttbl td{padding:0; border-bottom:1px solid #f1f5f9; text-align:center;}
  table.sttbl td.nm{text-align:right; font-weight:700; color:var(--ink); padding:6px 9px;
            position:sticky; inset-inline-start:0; background:#fff; white-space:nowrap;}
  table.sttbl td.nm small{color:var(--muted); font-weight:700;}
  table.sttbl tbody tr:hover td.nm{background:#f1f5f9;}
  .stcell{display:block; padding:7px 6px; font-weight:700;}
  .stflag{margin-inline-end:5px;}
  /* distribution chart */
  .stchart{margin-top:10px; border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:#fff;}
  .stsvg{width:100%; height:auto; display:block;}
  .stleg{display:flex; flex-wrap:wrap; gap:10px 14px; margin-bottom:6px;}
  .stlg{display:inline-flex; align-items:center; gap:6px; font-size:.82rem; color:#334155; font-weight:700;}
  .stsw{width:12px; height:12px; border-radius:3px; display:inline-block;}
  /* knockout-path panel */
  .stpath{margin-top:8px; display:flex; flex-direction:column; gap:12px;}
  .stpteam{border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:#fff;}
  .stpname{font-weight:800; color:var(--ink); font-size:1.02rem; margin-bottom:8px;}
  .stprounds{display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:8px;}
  .stpcard{border:1px solid var(--line); border-radius:10px; padding:8px 10px; background:#f8fafc;}
  .stpr{display:flex; justify-content:space-between; align-items:center; font-weight:800;
            color:#334155; border-bottom:1px solid var(--line); padding-bottom:5px; margin-bottom:6px;}
  .stppass{font-weight:800; color:var(--blue); font-size:.82rem;}
  .stpopps{display:flex; flex-direction:column; gap:7px;}
  .stpopp{display:flex; flex-direction:column; gap:2px; font-size:.8rem;}
  .stpopp.other{opacity:.75;}
  .stpo-nm{font-weight:700; color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .stpo-stats{display:flex; gap:8px; align-items:center; flex-wrap:wrap;}
  .stpo-meet{color:var(--muted); font-weight:700; font-variant-numeric:tabular-nums;}
  .stpo-beat{font-weight:800; font-variant-numeric:tabular-nums; border-radius:6px; padding:1px 6px;}
  .stpo-beat.good{color:#166534; background:#dcfce7;}
  .stpo-beat.even{color:#92400e; background:#fef3c7;}
  .stpo-beat.bad{color:#991b1b; background:#fee2e2;}
"""


def stages_payload(data: dict) -> dict:
    """Per-team stage profile (Hebrew names + flags baked in) for the client.

    teams[] carry exact[7] (a true distribution over where the run ends) and
    reach[6] (cumulative P(reach at least stage)); ordered strongest-first."""
    he = _team_he_map()
    ko_he = {"R32": "שלב 32", "R16": "שמינית", "QF": "רבע", "SF": "חצי", "Final": "גמר"}
    ko_en = {"R32": "Round of 32", "R16": "Round of 16", "QF": "Quarter-finals",
             "SF": "Semi-finals", "Final": "Final"}

    def conv_ko(ko):
        out = []
        for rd in ko or []:
            opp = [{"t": he.get(o["t"], o["t"]), "te": o["t"], "flag": _flag(o["t"]),
                    "meet": o.get("meet", 0), "beat": o.get("beat", 0)}
                   for o in rd.get("opp", [])]
            out.append({"r": rd["r"], "rhe": ko_he.get(rd["r"], rd["r"]),
                        "ren": ko_en.get(rd["r"], rd["r"]),
                        "pass": rd.get("pass", 0), "opp": opp})
        return out

    teams = []
    for r in (data.get("stages") or []):
        en = r["team"]
        teams.append({"t": he.get(en, en), "en": en, "flag": _flag(en),
                      "exact": r.get("exact", []), "reach": r.get("reach", []),
                      "exp": r.get("exp", 0), "ko": conv_ko(r.get("ko"))})
    return {
        "teams": teams,
        "reachLabels": ["שלב 32", "שמינית", "רבע", "חצי", "גמר", "אלופה"],
        "exactLabels": ["בתים", "שלב 32", "שמינית", "רבע", "חצי", "סגנית", "אלופה"],
    }


def stages_html(data: dict) -> str:
    payload = stages_payload(data)
    opts = "".join(
        f'<label class="rfopt" data-name="{t["t"]}"><input type="checkbox" value="{t["en"]}">'
        f'<span>{t["flag"]} {_te(t["en"])}</span></label>' for t in payload["teams"])
    blob = json.dumps(payload, ensure_ascii=False)
    return f"""
  <h2 class="bigsec" data-i18n="st.title">עד לאן יגיעו?</h2>
  <section class="stwrap">
    <p class="sub" style="margin-top:4px" data-i18n="st.intro" data-i18n-html></p>
    <div class="stctrls">
      <div class="rfdd">
        <button type="button" class="rfdd-btn" id="stTeamBtn"><span data-i18n="st.pick_teams">בחירת נבחרות</span>
          <span class="rfdd-cnt" id="stTeamCnt"></span> <span class="rfcar">▾</span></button>
        <div class="rfdd-pop" id="stTeamPop" hidden>
          <input type="search" class="rfdd-search" id="stTeamSearch" data-i18n-placeholder="st.search_team">
          <div class="rfdd-actions"><button type="button" class="rflink" id="stTeamClear" data-i18n="cheer.clear">נקה הכל</button></div>
          <div class="rfdd-list" id="stTeamList">{opts}</div>
        </div>
      </div>
    </div>
    <div class="stheatwrap"><div id="stHeat"></div></div>

    <h3 style="margin:18px 0 0" data-i18n="st.dist_chart">גרף התפלגות</h3>
    <div class="stctrls">
      <div class="stmode" id="stMode">
        <button type="button" data-mode="exact" class="on" data-i18n="st.mode.exact">התפלגות (איפה ייעצרו)</button>
        <button type="button" data-mode="cum" data-i18n="st.mode.cum">מצטבר (להגיע לפחות ל…)</button>
      </div>
    </div>
    <p class="sthint" id="stChartHint"></p>
    <div class="stchart"><div class="stleg" id="stLeg"></div><div id="stChart"></div></div>

    <h3 style="margin:18px 0 0" data-i18n="st.ko_path">מסלול הנוקאאוט הצפוי</h3>
    <p class="sub" style="margin-top:4px" data-i18n="st.path.intro" data-i18n-html></p>
    <div id="stPath" class="stpath"></div>
    <script id="stData" type="application/json">{blob}</script>
  </section>
"""


STAGES_JS = r"""
(function(){
  const panel = document.getElementById('tab-stages');
  if(!panel) return;
  const I = window.I18N;
  const t = k => I.t(k);
  const T = en => I.team(en);
  const el = document.getElementById('stData');
  let S; try { S = JSON.parse(el.textContent); } catch(e){ return; }
  const teams = S.teams || [];
  if(!teams.length) return;
  const byEn = {}; teams.forEach(t=> byEn[t.en]=t);
  const heatEl = document.getElementById('stHeat');
  const chartEl = document.getElementById('stChart');
  const legEl = document.getElementById('stLeg');
  const hintEl = document.getElementById('stChartHint');
  const COLORS = ['#2563eb','#16a34a','#d97706','#7c3aed','#dc2626','#0891b2','#db2777','#65a30d'];
  const CHART_CAP = 8;
  const esc = s => (s+'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const REACH_KEYS = ['st.reach.r32','st.reach.r16','st.reach.qf','st.reach.sf','st.reach.final','st.reach.champ'];
  const EXACT_KEYS = ['st.exact.groups','st.reach.r32','st.reach.r16','st.reach.qf','st.reach.sf','st.exact.runner','st.reach.champ'];
  function reachLabels(){ return REACH_KEYS.map(k=> t(k)); }
  function exactLabels(){ return EXACT_KEYS.map(k=> t(k)); }
  function teamLabel(tm){ return T(tm.en); }
  function koRound(rd){ return I.lang==='en' ? (rd.ren||rd.r) : (rd.rhe||rd.r); }

  const sel = new Set();       // selected team english keys (empty = all in heatmap)
  let mode = 'exact';

  function pct(p){ if(p<=0) return '·'; if(p<0.10) return (p*100).toFixed(1)+'%'; return Math.round(p*100)+'%'; }
  function heat(p){
    const a = p<=0 ? 0 : (0.10 + 0.90*p);
    return {bg:'rgba(37,99,235,'+a.toFixed(3)+')', fg:(p>=0.55?'#fff':'#0f172a')};
  }

  function renderHeat(){
    const rows = sel.size ? teams.filter(t=> sel.has(t.en)) : teams;
    const L = reachLabels();
    let h = '<table class="sttbl"><thead><tr><th class="nm">'+t('st.team')+'</th>';
    L.forEach(lb=> h += '<th>'+lb+'</th>');
    h += '</tr></thead><tbody>';
    rows.forEach(tm=>{
      h += '<tr><td class="nm"><span class="stflag">'+tm.flag+'</span>'+esc(teamLabel(tm))+'</td>';
      (tm.reach||[]).forEach(p=>{ const c=heat(p);
        h += '<td><span class="stcell" style="background:'+c.bg+';color:'+c.fg+'">'+pct(p)+'</span></td>'; });
      h += '</tr>';
    });
    h += '</tbody></table>';
    heatEl.innerHTML = h;
  }

  function chartTeams(){
    if(sel.size) return teams.filter(tm=> sel.has(tm.en)).slice(0, CHART_CAP);
    return teams.slice(0, 6);   // default: 6 strongest
  }
  function barChart(labels, series){
    const W=760,H=340,padL=38,padR=12,padT=14,padB=44;
    const n=labels.length, m=series.length;
    const plotW=W-padL-padR, plotH=H-padT-padB;
    let vmax=0; series.forEach(s=> s.vals.forEach(v=>{ if(v>vmax) vmax=v; }));
    vmax = Math.min(1, vmax*1.15); if(vmax<=0) vmax=1;
    const y = v => padT + plotH*(1 - v/vmax);
    const groupW = plotW/n;
    const barW = Math.min(30, (groupW*0.78)/Math.max(1,m));
    let svg = '<svg viewBox="0 0 '+W+' '+H+'" class="stsvg" preserveAspectRatio="xMidYMid meet">';
    [0,.25,.5,.75,1].forEach(f=>{ const val=vmax*f, yy=y(val);
      svg += '<line x1="'+padL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-padR)+'" y2="'+yy.toFixed(1)+'" stroke="#e2e8f0"/>'
           + '<text x="'+(padL-5)+'" y="'+(yy+3).toFixed(1)+'" text-anchor="end" font-size="9" fill="#94a3b8">'+Math.round(val*100)+'%</text>'; });
    for(let i=0;i<n;i++){
      const gx = padL + groupW*i;
      const span = m*barW, start = gx + (groupW-span)/2;
      for(let j=0;j<m;j++){
        const v = series[j].vals[i]||0, bx=start+j*barW, by=y(v), bh=padT+plotH-by;
        svg += '<rect x="'+bx.toFixed(1)+'" y="'+by.toFixed(1)+'" width="'+Math.max(1,barW-2).toFixed(1)
             + '" height="'+Math.max(0,bh).toFixed(1)+'" fill="'+series[j].color+'" rx="2">'
             + '<title>'+esc(series[j].label)+' · '+esc(labels[i])+': '+(v*100).toFixed(1)+'%</title></rect>';
      }
      svg += '<text x="'+(gx+groupW/2).toFixed(1)+'" y="'+(H-padB+15)+'" text-anchor="middle" font-size="10" fill="#475569">'+esc(labels[i])+'</text>';
    }
    svg += '</svg>';
    return svg;
  }
  function renderChart(){
    const ts = chartTeams();
    const labels = mode==='exact' ? exactLabels() : reachLabels();
    const series = ts.map((tm,i)=>({
      label: teamLabel(tm), color: COLORS[i%COLORS.length],
      vals: (mode==='exact' ? tm.exact : tm.reach) || []
    }));
    legEl.innerHTML = series.map(s=> '<span class="stlg"><span class="stsw" style="background:'+s.color+'"></span>'+esc(s.label)+'</span>').join('');
    chartEl.innerHTML = barChart(labels, series);
    let hint = mode==='exact' ? t('st.hint.exact') : t('st.hint.cum');
    if(!sel.size) hint += t('st.hint.default6');
    else if(sel.size>CHART_CAP) hint += I.fmt('st.hint.cap', {n: CHART_CAP, total: sel.size});
    hintEl.innerHTML = hint;
  }
  const pathEl = document.getElementById('stPath');
  const PATH_CAP = 4;
  function beatClass(p){ return p>=0.55 ? 'good' : (p<=0.45 ? 'bad' : 'even'); }
  function renderPath(){
    const ts = sel.size ? teams.filter(tm=> sel.has(tm.en)).slice(0, PATH_CAP) : [];
    if(!ts.length){
      pathEl.innerHTML = '<div class="callout">'+t('st.path.pick')+'</div>';
      return;
    }
    pathEl.innerHTML = ts.map(tm=>{
      const rounds = (tm.ko||[]).map(rd=>{
        const shown = rd.opp||[];
      const meetSum = shown.reduce((a,o)=> a + (o.meet||0), 0);
      let opps = shown.map(o=>
          '<div class="stpopp"><div class="stpo-nm">'+o.flag+' '+esc(T(o.te||o.t))+'</div>'
          + '<div class="stpo-stats"><span class="stpo-meet">'+t('st.meet')+' '+Math.round(o.meet*100)+'%</span>'
          + '<span class="stpo-beat '+beatClass(o.beat)+'">'+t('st.beat')+' '+Math.round(o.beat*100)+'%</span></div></div>'
        ).join('');
      const other = 1 - meetSum;
      if(other > 0.005){
        opps += '<div class="stpopp other"><div class="stpo-nm">'+t('st.other_opp')+'</div>'
          + '<div class="stpo-stats"><span class="stpo-meet">'+t('st.meet')+' '+Math.round(other*100)+'%</span></div></div>';
      }
      if(!opps) opps = '<div class="rfempty">'+t('cheer.empty')+'</div>';
        return '<div class="stpcard"><div class="stpr">'+esc(koRound(rd))
          + '<span class="stppass">'+t('st.pass')+' '+Math.round(rd.pass*100)+'%</span></div>'
          + '<div class="stpopps">'+opps+'</div></div>';
      }).join('') || '<div class="rfempty">'+t('st.no_ko')+'</div>';
      return '<div class="stpteam"><div class="stpname">'+tm.flag+' '+esc(teamLabel(tm))+'</div>'
        + '<div class="stprounds">'+rounds+'</div></div>';
    }).join('');
    if(sel.size>PATH_CAP){
      pathEl.innerHTML += '<p class="sthint">'+I.fmt('st.hint.cap', {n: PATH_CAP, total: sel.size})+'</p>';
    }
  }
  function renderAll(){ renderHeat(); renderChart(); renderPath(); }

  // ---- team dropdown (search + multi-select) ----
  const tBtn=document.getElementById('stTeamBtn'), tPop=document.getElementById('stTeamPop');
  const tSearch=document.getElementById('stTeamSearch'), tList=document.getElementById('stTeamList');
  const tClear=document.getElementById('stTeamClear'), tCnt=document.getElementById('stTeamCnt');
  if(tBtn) tBtn.addEventListener('click', e=>{ e.stopPropagation(); tPop.hidden=!tPop.hidden; });
  document.addEventListener('click', e=>{ if(tPop && !tPop.hidden && !tPop.contains(e.target) && e.target!==tBtn) tPop.hidden=true; });
  if(tSearch) tSearch.addEventListener('input', ()=>{ const q=tSearch.value.trim().toLowerCase();
    tList.querySelectorAll('.rfopt').forEach(o=>{ o.style.display = (o.dataset.name||'').toLowerCase().includes(q)?'':'none'; }); });
  if(tList) tList.addEventListener('change', e=>{ const cb=e.target.closest('input[type=checkbox]'); if(!cb) return;
    if(cb.checked) sel.add(cb.value); else sel.delete(cb.value);
    if(tCnt) tCnt.textContent = sel.size? '('+sel.size+')':''; renderAll(); });
  if(tClear) tClear.addEventListener('click', ()=>{ sel.clear();
    tList.querySelectorAll('input[type=checkbox]').forEach(c=> c.checked=false);
    if(tCnt) tCnt.textContent=''; renderAll(); });

  // ---- distribution mode toggle ----
  const modeWrap = document.getElementById('stMode');
  if(modeWrap) modeWrap.addEventListener('click', e=>{ const b=e.target.closest('button[data-mode]'); if(!b) return;
    mode = b.dataset.mode;
    modeWrap.querySelectorAll('button').forEach(x=> x.classList.toggle('on', x===b));
    renderChart(); });

  renderAll();
  document.addEventListener('langchange', renderAll);
})();
"""


def race_modal_html() -> str:
    """Single reusable overlay shared by all three race buttons."""
    return """
  <div id="raceModal" aria-hidden="true">
    <div class="racecard" role="dialog" aria-modal="true">
      <div class="racehd">
        <h3 id="raceTitle"></h3>
        <button type="button" class="raceclose" id="raceClose" aria-label="Close">×</button>
      </div>
      <div class="racecanvaswrap"><canvas id="raceCanvas"></canvas></div>
      <div class="racectrls">
        <button type="button" class="raceplay" id="racePlay"></button>
        <input type="range" class="racescrub" id="raceScrub" min="0" max="1000" value="0">
        <span class="racedate" id="raceDate"></span>
        <select class="racespeed" id="raceSpeed" aria-label="speed">
          <option value="0.5">0.5×</option>
          <option value="1" selected>1×</option>
          <option value="2">2×</option>
          <option value="4">4×</option>
        </select>
      </div>
      <p class="racefoot" id="raceFoot"></p>
    </div>
  </div>
"""


def race_js(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return r"""
(function(){
  const RD = __RACEDATA__;
  const I = window.I18N;
  const TOPN = 10;
  const MODAL = document.getElementById('raceModal');
  if(!MODAL || !I) return;
  const canvas = document.getElementById('raceCanvas');
  const ctx = canvas.getContext('2d');
  const titleEl = document.getElementById('raceTitle');
  const playBtn = document.getElementById('racePlay');
  const scrub   = document.getElementById('raceScrub');
  const dateEl  = document.getElementById('raceDate');
  const speedSel= document.getElementById('raceSpeed');
  const footEl  = document.getElementById('raceFoot');

  function hue(s){ let h=0; for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0; return h%360; }
  function colorFor(k){ return 'hsl('+hue(k)+' 62% 50%)'; }
  // Golden-angle palette: spacing hues by ~137.5° (plus small S/L variation) keeps
  // even value-adjacent bars far apart in colour, avoiding clusters of similar greens.
  function paletteColor(i){ const h=(i*137.508)%360, s=60+(i%3)*6, l=45+(i%2)*9;
    return 'hsl('+h.toFixed(1)+' '+s+'% '+l+'%)'; }
  function assignColors(frames){
    const peak={};
    for(const f of frames) for(const k in f.map){ const v=f.map[k].value;
      if(!(k in peak) || v>peak[k]) peak[k]=v; }
    const ordered=Object.keys(peak).sort((a,b)=> peak[b]-peak[a] || (a<b?-1:1));
    const cmap={}; ordered.forEach((k,i)=> cmap[k]=paletteColor(i));
    for(const f of frames) for(const k in f.map) f.map[k].color=cmap[k];
  }
  function flagOf(en){ const iso=(RD.iso||{})[en]; if(!iso||iso.length!==2) return '';
    return String.fromCodePoint(...[...iso.toUpperCase()].map(c=>0x1F1E6+c.charCodeAt(0)-65)); }
  function fmtTs(ts){ if(!ts) return ''; const m=String(ts).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})/);
    if(!m) return ts; const mo=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m[2]-1];
    return (+m[3])+' '+mo+' '+m[4]+':'+m[5]; }
  function roundRect(c,x,y,w,h,r){ r=Math.min(r,h/2,w/2); c.beginPath();
    c.moveTo(x+r,y); c.arcTo(x+w,y,x+w,y+h,r); c.arcTo(x+w,y+h,x,y+h,r);
    c.arcTo(x,y+h,x,y,r); c.arcTo(x,y,x+w,y,r); c.closePath(); }

  function buildFrames(kind){
    let frames=[], fmtVal, title;
    // valuePaced: percentage races also stretch transition time by how much the
    // value moves (not just rank), so odds visibly climb (e.g. 5%->6%) instead
    // of snapping. The points race stays rank-paced to keep dead time compressed.
    let valuePaced=false;
    if(kind==='title'){
      title = I.t('race.title.title'); valuePaced=true;
      fmtVal = v => v.toFixed(1)+'%';
      for(const rec of (RD.simHist||[])){
        const map={};
        for(const tm in rec.sim) map[tm]={label:I.team(tm), value:(rec.sim[tm]||0)*100, flag:flagOf(tm), color:colorFor(tm)};
        frames.push({ts:rec.ts, map});
      }
    } else {
      const usePts = (kind==='leaderboard'); valuePaced=!usePts;
      title  = I.t(usePts?'race.title.leaderboard':'race.title.p1');
      fmtVal = usePts ? (v=> (Math.round(v*10)/10).toFixed(1)) : (v=> v.toFixed(1)+'%');
      for(const rec of (RD.entryHist||[])){
        const map={};
        for(const nm in rec.entries){ const e=rec.entries[nm];
          map[nm]={label:nm, value: usePts?(e.pts||0):((e.p1||0)*100), flag:'', color:colorFor(nm)}; }
        frames.push({ts:rec.ts, map});
      }
    }
    assignColors(frames);
    return {frames, fmtVal, title, valuePaced};
  }

  // Per-race state. `clock` is the master timeline in ms; `pos` is the derived
  // fractional frame index. Timing is variable: transitions with no standings
  // movement are compressed to a short slide, while transitions with overtakes
  // are stretched and eased so each pass is clearly readable (Flourish-style).
  let cur=null, playing=false, raf=0, lastT=0, pos=0, clock=0, totalMs=0;
  let frameRanks=[], phases=[], dispY={};   // dispY: smoothed vertical slot per key
  const MIN_SEG=420, MAX_SEG=2900, HOLD=700, CAP_MS=70000;  // ms: slide bounds / rest / total cap
  const RANK_TAU=190;   // ms time-constant for a bar to glide one slot when overtaking
  function speed(){ return parseFloat(speedSel.value)||1; }
  // gentle sine ease: steadier mid-transition so values visibly climb (5%->6%)
  // rather than snapping through the middle the way a cubic ease does.
  function easeInOut(t){ return -(Math.cos(Math.PI*t)-1)/2; }
  function allKeys(){ const s=new Set(); for(const f of cur.frames) for(const k in f.map) s.add(k); return [...s]; }

  function ranksOf(frame){ const arr=Object.keys(frame.map)
      .map(k=>({k,v:frame.map[k].value})).sort((a,b)=> b.v-a.v || (a.k<b.k?-1:1));
    const r={}; arr.forEach((o,i)=> r[o.k]=i); return r; }
  // Per-transition movement, split into rank change (overtakes) and summed
  // value change across the visible bars, so each can drive pacing separately.
  function movement(i){ const a=frameRanks[i], b=frameRanks[i+1];
    const fa=cur.frames[i].map, fb=cur.frames[i+1].map; let rankM=0, valM=0;
    const ks=new Set([...Object.keys(a),...Object.keys(b)]);
    for(const k of ks){ const ra=(k in a)?a[k]:TOPN, rb=(k in b)?b[k]:TOPN;
      if(ra<TOPN || rb<TOPN){
        rankM+=Math.abs(Math.min(ra,TOPN)-Math.min(rb,TOPN));
        valM +=Math.abs((fb[k]?fb[k].value:0)-(fa[k]?fa[k].value:0));
      } }
    return {rankM, valM}; }

  function buildTimeline(){
    frameRanks = cur.frames.map(ranksOf);
    phases=[]; totalMs=0;
    const F=cur.frames; if(F.length<2) return;
    const mv=[]; let rMax=0, vMax=0;
    for(let i=0;i<F.length-1;i++){ const m=movement(i); mv.push(m);
      if(m.rankM>rMax) rMax=m.rankM; if(m.valM>vMax) vMax=m.valM; }
    for(let i=0;i<F.length-1;i++){
      const rR = rMax>0 ? mv[i].rankM/rMax : 0;
      const vR = vMax>0 ? mv[i].valM/vMax : 0;
      // value races: a big % swing earns as much time as a big rank swing.
      const score = cur.valuePaced ? Math.max(rR, vR) : rR;
      const dur = MIN_SEG + (MAX_SEG-MIN_SEG)*Math.pow(score, 0.6);   // perceptual
      phases.push({seg:i, dur}); totalMs+=dur;
      if(mv[i].rankM > 0){ phases.push({hold:i+1, dur:HOLD}); totalMs+=HOLD; } // rest to read overtakes
    }
    // Keep autoplay reasonable for long histories without losing the relative
    // slow/fast contrast — scale the whole timeline down if it exceeds the cap.
    if(totalMs > CAP_MS){ const s=CAP_MS/totalMs; phases.forEach(p=> p.dur*=s); totalMs=CAP_MS; }
  }
  function posFromClock(c){
    if(!phases.length) return 0;
    if(c>=totalMs) return cur.frames.length-1;
    let acc=0;
    for(const ph of phases){
      if(c < acc+ph.dur){ const lt=(c-acc)/ph.dur;
        return ('seg' in ph) ? ph.seg + easeInOut(lt) : ph.hold; }
      acc+=ph.dur;
    }
    return cur.frames.length-1;
  }

  function valAt(k,p){ const i=Math.floor(p), t=p-i, j=Math.min(i+1,cur.frames.length-1);
    const a=cur.frames[i]&&cur.frames[i].map[k], b=cur.frames[j]&&cur.frames[j].map[k];
    const va=a?a.value:0, vb=b?b.value:0; return va+(vb-va)*t; }
  // Instantaneous slot by interpolated value (with stable name tiebreak). As a
  // climbing bar's value passes each rival's at a different moment, its target
  // slot drops one step at a time -> sequential overtakes rather than one leap.
  function instRanks(p){ const arr=allKeys().map(k=>({k, v:valAt(k,p)}))
      .sort((a,b)=> b.v-a.v || (a.k<b.k?-1:1));
    const r={}; arr.forEach((o,i)=> r[o.k]=i); return r; }
  function snapDisp(p){ dispY=instRanks(p); }
  function easeDisp(p, dtMs){ const target=instRanks(p);
    const a=Math.min(1, 1-Math.exp(-dtMs/RANK_TAU));
    for(const k in target){ if(!(k in dispY)) dispY[k]=target[k];
      dispY[k] += (target[k]-dispY[k])*a; } }
  function metaOf(k,p){ const i=Math.min(Math.round(p),cur.frames.length-1);
    return (cur.frames[i]&&cur.frames[i].map[k]) || (cur.frames[Math.max(0,i-1)]&&cur.frames[Math.max(0,i-1)].map[k])
        || {label:k,flag:'',color:colorFor(k)}; }

  function draw(p){
    if(!cur || !cur.frames.length) return;
    // Position each bar at its smoothed slot (dispY) so it physically slides past
    // rivals one at a time on an overtake; width/label use the interpolated value.
    const items=allKeys().map(k=>({key:k, value:valAt(k,p), yr:(k in dispY?dispY[k]:TOPN+2)}))
                         .filter(o=> o.yr < TOPN + 0.6)
                         .sort((a,b)=> a.yr-b.yr);
    const maxV=Math.max(...items.filter(o=> o.yr<TOPN).map(o=>o.value), 1e-6);
    const cssW=canvas.clientWidth||900, rowH=38, gap=10, padT=14, padB=8;
    const cssH=padT+padB + TOPN*rowH + (TOPN-1)*gap;
    const dpr=window.devicePixelRatio||1;
    if(canvas.width!==Math.round(cssW*dpr) || canvas.height!==Math.round(cssH*dpr)){
      canvas.width=Math.round(cssW*dpr); canvas.height=Math.round(cssH*dpr); canvas.style.height=cssH+'px'; }
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,cssW,cssH);
    const x0=8, padR=14, maxBarW=cssW-x0-padR-64;
    ctx.textBaseline='middle';
    for(const it of items){
      const meta=metaOf(it.key,p), y=padT+it.yr*(rowH+gap), cy=y+rowH/2;
      const w=Math.max(3, maxBarW*(it.value/maxV));
      ctx.globalAlpha = it.yr<TOPN ? 1 : Math.max(0, 1-(it.yr-TOPN)/0.6);  // slide-in/out fade
      ctx.fillStyle=meta.color; roundRect(ctx,x0,y,w,rowH,8); ctx.fill();
      const lbl=(meta.flag?meta.flag+' ':'')+meta.label;
      ctx.font='700 15px system-ui,Arial'; ctx.textAlign='left';
      const tw=ctx.measureText(lbl).width; let tipX=x0+w+8;
      if(tw+18<w){ ctx.fillStyle='#fff'; ctx.fillText(lbl, x0+10, cy); }
      else { ctx.fillStyle='#334155'; ctx.fillText(lbl, tipX, cy); tipX+=tw+8; }
      ctx.fillStyle='#0f172a'; ctx.font='800 14px system-ui,Arial';
      ctx.fillText(cur.fmtVal(it.value), tipX, cy);
      ctx.globalAlpha=1;
    }
    const ts=cur.frames[Math.min(Math.round(p),cur.frames.length-1)].ts;
    dateEl.textContent=fmtTs(ts);
    if(document.activeElement!==scrub)
      scrub.value=String(Math.round((totalMs>0? clock/totalMs : 0)*1000));
  }

  function tick(now){
    if(!playing) return;
    if(!lastT) lastT=now;
    const stepDt=(now-lastT)*speed(); clock += stepDt; lastT=now;
    if(clock>=totalMs){ clock=totalMs; pos=cur.frames.length-1; easeDisp(pos,stepDt); draw(pos); stop(); return; }
    pos=posFromClock(clock); easeDisp(pos, stepDt); draw(pos); raf=requestAnimationFrame(tick);
  }
  function play(){ if(!cur||cur.frames.length<2||totalMs<=0) return;
    if(clock>=totalMs) clock=0;
    playing=true; lastT=0; playBtn.textContent=I.t('race.pause');
    cancelAnimationFrame(raf); raf=requestAnimationFrame(tick); }
  function stop(){ playing=false; cancelAnimationFrame(raf); playBtn.textContent=I.t('race.play'); }

  function open(kind){
    cur=buildFrames(kind); MODAL.dataset.kind=kind; buildTimeline();
    titleEl.textContent=cur.title;
    footEl.textContent=I.fmt('race.foot', {n: cur.frames.length});
    clock=0; pos=0; stop(); scrub.value='0'; snapDisp(0);
    MODAL.classList.add('open'); MODAL.setAttribute('aria-hidden','false');
    requestAnimationFrame(()=>{ draw(0); play(); });
  }
  function close(){ stop(); MODAL.classList.remove('open'); MODAL.setAttribute('aria-hidden','true'); }

  // The modal must live directly under <body>; otherwise it is nested inside a
  // .tabpanel that gets display:none on other tabs (e.g. the title-race button
  // sits in the Odds tab), which would hide the overlay entirely.
  if(MODAL.parentNode!==document.body) document.body.appendChild(MODAL);

  document.querySelectorAll('.racebtn').forEach(b=> b.addEventListener('click', ()=> open(b.dataset.race)));
  document.getElementById('raceClose').addEventListener('click', close);
  MODAL.addEventListener('click', e=>{ if(e.target===MODAL) close(); });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape' && MODAL.classList.contains('open')) close(); });
  playBtn.addEventListener('click', ()=> playing?stop():play());
  scrub.addEventListener('input', ()=>{ stop(); clock=(scrub.value/1000)*totalMs; pos=posFromClock(clock); snapDisp(pos); draw(pos); });
  speedSel.addEventListener('change', ()=>{ if(playing) lastT=0; });
  window.addEventListener('resize', ()=>{ if(MODAL.classList.contains('open')) draw(pos); });
  document.addEventListener('langchange', ()=>{ if(!MODAL.classList.contains('open')) return;
    const c=clock, kind=MODAL.dataset.kind; cur=buildFrames(kind); buildTimeline();
    titleEl.textContent=cur.title; footEl.textContent=I.fmt('race.foot',{n:cur.frames.length});
    playBtn.textContent=I.t(playing?'race.pause':'race.play'); clock=c; pos=posFromClock(clock); snapDisp(pos); draw(pos); });
})();
""".replace("__RACEDATA__", data)


def main() -> None:
    data = json.loads((WC_ROOT / "results" / "live_latest.json").read_text())
    state = _load_state()
    ents = sorted(data["entries"], key=lambda e: -e["exp_winnings"])
    cm = data["champion_matrix"]
    champs = cm["champions"]
    order = [e["name"] for e in ents]
    winprob = {e["name"]: [round(e["P_first"], 4), round(e["P_top2"], 4),
                           round(e["P_last"], 4)] for e in ents}
    matrix = {c: {k: round(v, 4) for k, v in cm["matrix"].get(c, {}).items() if v > 0}
              for c in champs}
    n_sims = data.get("n_sims", 50000)
    n_ent = data.get("n_entries", len(ents))

    html = OUT.read_text(encoding="utf-8")

    # All regions are bounded by persistent markers in the base page and replaced
    # in place, so the build is idempotent and the static tab scaffold is kept.
    # 1) CSS: matrix/leaders/standings + the three new tabs, in one managed block.
    all_css = "\n".join([i18n_css(), CMTBL_CSS, TABS_CSS, WHATIF_CSS, ODDS_CSS, RACE_CSS, CHEER_CSS, STAGES_CSS])
    html = replace_region(html, CSS_START, CSS_END, all_css)

    # 2) Main-tab live body (podium / leaders / standings / simulation / groups).
    #    The race overlay is a global fixed element shared by all three buttons.
    main_body = (podium_html(data) + leaders_html(data) + standings_table_html(data)
                 + explanation_html(n_ent, n_sims, coverage_html(data)) + groups_html(data)
                 + race_modal_html())
    html = replace_region(html, HTML_START, HTML_END, main_body)

    # 3) What-If + Odds tab bodies.
    html = replace_region(html, WHATIF_START, WHATIF_END, whatif_html())
    html = replace_region(html, ODDS_START, ODDS_END, odds_html())
    html = replace_region(html, CHEER_START, CHEER_END, cheer_html(data))
    html = replace_region(html, STAGES_START, STAGES_END, stages_html(data))

    # 4) All injected JS in one managed block before </script>.
    wi_payload = whatif_payload(data, state)
    od_payload = odds_payload(data)
    rc_payload = race_payload(data)
    team_he, pl_he = _team_he_map(), _player_he_map()
    all_js = "\n".join([
        i18n_js(team_he, pl_he),
        js_block(champs, CHAMP_HE, cm["p_title"], matrix, order, winprob),
        LEADERS_JS, TABS_JS, whatif_js(wi_payload), odds_js(od_payload),
        race_js(rc_payload), CHEER_JS, STAGES_JS,
    ])
    html = replace_region(html, JS_START, JS_END, all_js)

    OUT.write_text(html, encoding="utf-8")
    print(f"Updated {OUT}  ({len(html)//1024} KB) — {n_ent} entries, {n_sims:,} sims, "
          f"{len(wi_payload['entries'])} what-if rows")


if __name__ == "__main__":
    main()
