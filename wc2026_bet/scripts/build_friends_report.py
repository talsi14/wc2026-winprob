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

import json
import os
import re
from pathlib import Path

WC_ROOT = Path(__file__).resolve().parents[1]          # .../wc2026_bet
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
            nm = he.get(t["team"], t["team"])
            cls = " class=\"qual\"" if i < 2 else ""
            rows.append(
                f'<tr{cls}><td class="gt">{nm}</td>'
                f'<td>{t["played"]}</td><td>{t["points"]}</td>'
                f'<td dir="ltr">{t["gd"]:+d}</td>'
                f'<td class="gq">{t["p_advance"]*100:.0f}%</td></tr>')
        cards.append(
            f'<div class="gcard"><div class="gh">בית {g}</div>'
            f'<table class="gtbl"><thead><tr><th>נבחרת</th><th>מ׳</th>'
            f'<th>נק׳</th><th>הפרש</th><th>העפלה</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')
    return (
        '\n  <section>\n'
        '    <h2 style="margin-top:6px">טבלאות הבתים — סיכויי העפלה</h2>\n'
        '    <p class="sub">לכל בית: מספר משחקים ששוחקו (מ׳), נקודות (נק׳), הפרש שערים, '
        'וההסתברות להעפיל לשלב הנוק‑אאוט לפי הסימולציה (העפלה). שתי הנבחרות המודגשות הן '
        'המועמדות המובילות להעפלה מכל בית.</p>\n'
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
            f'<div class="ppts">{_g(e["current_points"])} <small>נק׳</small></div>'
            f'<div class="pprize">₪{prize.get(rk, 0):,}</div></div>')
    return (
        '\n  <section class="podwrap">\n'
        '    <h2 class="bigsec real">טבלת הדירוג</h2>\n'
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
        he = (pl_he if player else team_he).get(name_en, name_en)
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
    head = ('<tr><th>מקום</th><th>שינוי</th><th class="nm">שם</th><th>נק׳</th>'
            '<th>דרג א׳</th><th>דרג ב׳</th><th>דרג ג׳</th><th>דרג ד׳</th>'
            '<th>כובשת</th><th>סופגת</th><th>מלך שערים</th>'
            '<th>זכייה</th><th>תוך הכסף</th></tr>')
    return (
        '\n  <section>\n'
        '    <p class="sub" style="margin-top:4px">כל הטפסים מדורגים לפי הניקוד בפועל. '
        'העמודות <b>זכייה</b> ו<b>תוך הכסף</b> הן הסתברויות מהסימולציה (מקום 1, ומקום 1–2). '
        'בכל בחירה מוצג בסוגריים מספר הנקודות שצברה עד כה.</p>\n'
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

    played = [(t, int(v.get("gf", 0)), int(v.get("ga", 0)))
              for t, v in tp.items() if int(v.get("games", 0)) > 0]
    gf_rank = sorted(played, key=lambda x: (-x[1], x[0]))
    ga_rank = sorted(played, key=lambda x: (-x[2], x[0]))

    def team_rows(rank, val_i, sel):
        body = ""
        for row in rank:
            t = row[0]
            hit = ' class="hit"' if t in sel else ''
            body += (f'<tr{hit}><td class="nm">{team_he.get(t, t)}</td>'
                     f'<td class="v">{row[val_i]}</td></tr>')
        return body or '<tr><td class="nm" colspan="2">טרם זמין</td></tr>'

    def scorer_rows():
        body = ""
        for s in scorers:
            nm = pl_he.get(s["scorer"], s["scorer"])
            tm = team_he.get(s.get("team", ""), s.get("team", "") or "")
            hit = ' class="hit"' if s["scorer"] in sel_scorer else ''
            body += (f'<tr{hit}><td class="nm">{nm}</td><td class="tm">{tm}</td>'
                     f'<td class="v">{s["goals"]}</td></tr>')
        return body or '<tr><td class="nm" colspan="3">טרם זמין</td></tr>'

    def lead_team(rank, val_i):
        if not rank:
            return ("טרם זמין", "—")
        row = rank[0]
        return (team_he.get(row[0], row[0]), f"({row[val_i]})")

    sc_name, sc_val = lead_team(gf_rank, 1)   # most goals scored
    cc_name, cc_val = lead_team(ga_rank, 2)   # most goals conceded
    if scorers:
        ks_name = pl_he.get(scorers[0]["scorer"], scorers[0]["scorer"])
        ks_val = f'({scorers[0]["goals"]})'
    else:
        ks_name, ks_val = "טרם זמין", "—"

    # RTL grid: first child renders on the right -> matches the screenshot order
    cards = [
        ("scorer", _IC_CROWN, "מלך השערים כרגע", ks_name, ks_val,
         f'<table class="ltbl"><tbody>{scorer_rows()}</tbody></table>'),
        ("conceding", _IC_SHIELD, "הסופגת המובילה", cc_name, cc_val,
         f'<table class="ltbl"><tbody>{team_rows(ga_rank, 2, sel_conceding)}</tbody></table>'),
        ("scoring", _IC_GAUGE, "הכובשת המובילה", sc_name, sc_val,
         f'<table class="ltbl"><tbody>{team_rows(gf_rank, 1, sel_scoring)}</tbody></table>'),
    ]
    out = ""
    for cls, ic, title, name, val, tbl in cards:
        out += (f'<div class="lcard {cls}" tabindex="0">'
                f'<div class="lc-top"><span class="lc-ic">{ic}</span>'
                f'<span class="lc-title">{title}</span></div>'
                f'<div class="lc-val" title="{name}">{name}</div>'
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
        body = ('<b>מצב הנתונים:</b> טרם שוחקו משחקים — זוהי תחזית הבסיס לפני פתיחת '
                'הטורניר. כל המשחקים מדומים.')
    else:
        stage = "שלב הבתים הושלם" if complete else "שלב הבתים בעיצומו"
        body = (f'<b>מצב הנתונים:</b> נכללו <b>{gp}/{N_GROUP_MATCHES}</b> משחקי בתים'
                f' ו‑<b>{kp}/{N_KO_MATCHES}</b> משחקי נוק‑אאוט שכבר שוחקו'
                f' (ו‑{goals} שערים שנרשמו למועמדי נעל הזהב). {stage};'
                f' רק מה שטרם נקבע מדומה.')
    return (f'<div class="freshness"><span class="fresh-when">עודכן: {when}</span>'
            f'<span class="fresh-body">{body}</span></div>')


def explanation_html(n_ent: int, n_sims: int, coverage: str = "") -> str:
    return f"""
  <h2 class="bigsec">סימולציית סיכויי זכיה מתעדכנת</h2>
  {coverage}

  <section>
    <h2 style="margin-top:6px">איך נבנה הניתוח</h2>
    <p class="sub">נתונים + סימולציה — בשפה פשוטה.</p>
    <p><b>הנתונים.</b> לכל אחת מ‑48 הנבחרות חושב דירוג כוח (Elo) ששוקלל עם <b>הימורי השוק</b>:
      יחסי זכייה בגביע, יחסי "העפלה מהבית" ויחסי מלך השערים מאתרי ההימורים המובילים. כך הדירוג
      "מיושר" לחוכמת ההמונים ולא מסתמך רק על נוסחה. במקביל נמשכו <b>כל {n_ent} הטפסים</b> ישירות
      מהאתר, כדי לדעת מי בחר במה.</p>
    <p><b>הסימולציה.</b> הטורניר כולו הורץ <b>{n_sims:,} פעמים</b> (מונטה‑קרלו). בכל הרצה מוגרלת
      תוצאה לכל משחק לפי הסתברות שנגזרת מהפרשי הכוח בין הנבחרות (מודל Dixon‑Coles להבקעת שערים),
      מתקדמים שלב‑שלב מהבתים ועד הגמר, ומגרילים גם מבקיעי שערים. בכל הרצה מחושבות נקודות לכל טופס
      לפי חוקי ההגרלה, {n_ent} הטפסים מדורגים, והקופה מתחלקת לפי המיקום (כולל חלוקת פרס בין שווים).
      מתוך {n_sims:,} ההרצות מתקבלים המספרים: הסתברות לזכייה, הסתברות ל"תוך הכסף" (מקום 1–2),
      הסתברות למקום אחרון, ותוחלת הנקודות והדירוג.</p>
    <div class="callout">
      <b>איך זה יתעדכן במהלך הטורניר.</b> ברגע שמשחקים מתחילים, ההרצה הבאה "מקבעת" את מה שכבר קרה —
      תוצאות, מבקיעים ודירוג הבתים ננעלים כעובדה, ומוגרל רק מה שעדיין לא ידוע. במקביל נמשכים יחסי
      הימורים מעודכנים לרענון דירוגי הכוח. כל עדכון יוצר חותמת זמן חדשה, וכך אפשר לעקוב מי עולה ומי
      יורד ככל שהמציאות מתבהרת. התהליך אוטומטי — מספיק להריץ אותו מחדש.
    </div>
    <div class="callout" style="border-right-color:var(--amber); background:#fffbeb;">
      <b>למה לבוחרי ספרד סיכוי זכייה נמוך.</b> ספרד היא המועמדת מספר 1 בשוק, ולכן חלק ניכר מהמשתתפים
      עיגנו עליה את הטופס (ורבים בחרו במבאפה כמלך שערים) — כך שגם אם ספרד תזכה, הפרס יתחלק בין המון
      מתחרים כמעט זהים, ואיש מהם לא ייבדל. כדי לנצח את הקופה לא מספיק לצדוק — צריך <b>לצדוק במקום
      שבו אחרים טעו</b>. הטפסים שמובילים בתוחלת הם דווקא ה"קונטראריאניים" שזנחו את ספרד לטובת בחירות
      פחות פופולריות (אנגליה, נורווגיה, ארגנטינה), כי הם זוכים בקופה כמעט לבדם כשהבחירות האלה מצליחות.
      כלומר: ספרד מקטינה את הסיכון להפסד גדול, אבל גם <b>כמעט מבטלת את הסיכוי לזכייה בולטת</b> —
      בדיוק מפני שכל כך הרבה עשו אותו דבר.
    </div>
  </section>

  <section>
    <h2 style="margin-top:6px">סיכויי ניצחון בהתערבות - מותנה בזהות האלופה</h2>
    <p class="sub">לכל שילוב של טופס (שורה) ואלופה אפשרית (עמודה): ההסתברות שאותו טופס יזכה
      בקופה בהינתן שאותה נבחרת זוכה במונדיאל. האחוז מתחת לשם הנבחרת = ההסתברות שלה לתואר. שלוש
      העמודות השמאליות הן הנתונים הכלליים של כל טופס: סיכוי לזכייה, סיכוי לכסף (מקום 1–2), וסיכוי
      למקום אחרון. מוצגים מדורגים לפי תוחלת הרווח — גללו בתוך החלון לשאר.</p>
    <div class="scrollbox"><div id="cmMatrix"></div></div>
    <p class="sub" style="margin-top:8px">תאים זהובים = סיכוי גבוה יותר לזכות בקופה בהינתן האלוף.</p>
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
(function renderMatrix(){
  const d = CMDATA, host = document.getElementById('cmMatrix');
  if(!host) return;
  const C = d.champs, getp = (c,e)=> (d.matrix[c]&&d.matrix[c][e])||0;
  let mx = 0; for(const c of C) for(const e of d.order) mx = Math.max(mx, getp(c,e));
  const cols = [['P(1st)',0,'37,99,235'],['In money',1,'22,163,74'],['P(last)',2,'220,38,38']];
  const smax = cols.map(([_l,i])=> Math.max(...d.order.map(e=> (d.winprob[e]||[0,0,0])[i]), 1e-9));
  const gold = t => `rgba(217,119,6,${(0.06+0.78*Math.pow(t,0.6)).toFixed(3)})`;
  const tint = (rgb,t) => `rgba(${rgb},${(0.08+0.72*Math.pow(t,0.6)).toFixed(3)})`;
  let h = '<table class="cmtbl"><thead><tr><th class="nm">טופס</th>';
  for(const c of C){
    h += `<th class="ch"><div>${d.champsHe[c]||c}</div>`+
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
})();
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


def main() -> None:
    data = json.loads((WC_ROOT / "results" / "live_latest.json").read_text())
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

    # strip any previously-injected blocks (idempotent)
    html = re.sub(re.escape(HTML_START) + r".*?" + re.escape(HTML_END), "",
                  html, flags=re.S)
    html = re.sub(re.escape(JS_START) + r".*?" + re.escape(JS_END), "",
                  html, flags=re.S)
    html = re.sub(re.escape(CSS_START) + r".*?" + re.escape(CSS_END), "",
                  html, flags=re.S)

    # 1) CSS (banner + matrix table), before </style>
    css = f"{CSS_START}\n{CMTBL_CSS}\n{CSS_END}\n"
    html = html.replace("</style>", css + "</style>", 1)

    # 2) HTML sections, placed at the very TOP of the content (right after the
    #    <div class="wrap"> open) so the live standings + simulation + group
    #    tables lead the page; the choices-analysis intro follows below them.
    body = (podium_html(data) + leaders_html(data) + standings_table_html(data)
            + explanation_html(n_ent, n_sims, coverage_html(data)) + groups_html(data))
    block = f"{HTML_START}\n{body}\n  {HTML_END}\n"
    wrap_marker = '<div class="wrap">'
    wi = html.find(wrap_marker)
    if wi >= 0:
        cut = wi + len(wrap_marker)
        html = html[:cut] + "\n" + block + html[cut:]
    else:                                   # fallback: before the footer
        html = re.sub(r"(\n\s*<footer)", "\n" + block + r"\1", html, count=1)

    # 3) JS render code, just before the closing </script>
    js = (f"\n{JS_START}\n{js_block(champs, CHAMP_HE, cm['p_title'], matrix, order, winprob)}"
          f"\n{LEADERS_JS}\n{JS_END}\n")
    html = re.sub(r"(\n</script>)", js + r"\1", html, count=1)

    OUT.write_text(html, encoding="utf-8")
    print(f"Updated {OUT}  ({len(html)//1024} KB) — {n_ent} entries, {n_sims:,} sims")


if __name__ == "__main__":
    main()
