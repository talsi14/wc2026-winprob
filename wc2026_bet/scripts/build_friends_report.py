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
import json
import os
import re
import sys
from pathlib import Path

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
    # when the tallies include goals from matches still in progress, flag it so
    # users know these three numbers are live (the win-probs/standings are not).
    live = bool(data.get("live_widgets"))
    live_dot = ('<span class="lc-live" title="כולל משחקים שמתנהלים כעת">'
                '<span class="lc-pulse"></span>חי</span>') if live else ''
    out = ""
    for cls, ic, title, name, val, tbl in cards:
        out += (f'<div class="lcard {cls}" tabindex="0">'
                f'<div class="lc-top"><span class="lc-ic">{ic}</span>'
                f'<span class="lc-title">{title}</span>{live_dot}</div>'
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
  @media (max-width:760px){ .wigrid{grid-template-columns:1fr;} }
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
  .odsvg{width:100%; height:auto; background:#fff; border:1px solid var(--line); border-radius:12px;}
  .odleg{display:flex; flex-wrap:wrap; gap:12px; margin:6px 0;}
  .odlg{font-size:.82rem; color:#475569; display:inline-flex; align-items:center; gap:5px;}
  .odsw{width:12px; height:12px; border-radius:3px; display:inline-block;}
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
        "realKo": state.get("ko_results") or [],
        "realTeamPlayed": state.get("team_played") or data.get("team_played") or {},
        "realPlayerGoals": state.get("player_goals") or {},
        "groupStageComplete": bool(state.get("group_stage_complete")),
        "entries": entries, "trackedPlayers": tracked_players,
        "teamHe": he_teams, "playerHe": he_players,
    }


def whatif_html() -> str:
    return """
  <h2 class="bigsec">What If..?</h2>
  <section>
    <p class="sub" style="margin-top:4px">בחרו תוצאות למשחקים שטרם נגמרו וראו איך <b>טבלת הניקוד בפועל</b>
      של ההתערבות משתנה. אפשר למלא משחקי בתים, וגם <b>משחקי נוק‑אאוט</b> — כל משחק נפתח למילוי ברגע ששתי
      הקבוצות בו ידועות, והתוצאות שמזינים מתגלגלות הלאה בעץ המשחקים עד הגמר. מי שירצה — יכול גם לשייך מבקיעי
      שערים כדי להשפיע על בחירת "מלך השערים".</p>
    <div class="callout" style="border-right-color:var(--amber); background:#fffbeb;">
      <b>זו לא תחזית.</b> הטבלה כאן מציגה <b>רק את הניקוד</b> שהיה מתקבל לפי התוצאות שאתם ממציאים —
      בלי סיכויי זכייה ובלי סימולציה. הניקוד מחושב בדפדפן לפי חוקי ההגרלה. עמודת <b>שינוי</b> = תזוזת המיקום
      לעומת הדירוג הנוכחי, ובכל בחירה מוצג בסוגריים הניקוד שלה בתרחיש.
    </div>
    <div class="wibar">
      <button type="button" id="wiReset" class="wibtn">איפוס כל התרחישים</button>
      <span id="wiCount" class="wihint"></span>
    </div>
    <div class="wigrid">
      <div class="wicol">
        <div class="wicolhd">משחקים למילוי</div>
        <div id="wiMatches"></div>
      </div>
      <div class="wicol">
        <div class="wicolhd">טבלת הדירוג — בתרחיש שלכם</div>
        <div class="standwrap"><table class="standtbl"><thead><tr>
          <th>מקום</th><th>שינוי</th><th class="nm">שם</th><th>נק׳</th>
          <th>דרג א׳</th><th>דרג ב׳</th><th>דרג ג׳</th><th>דרג ד׳</th>
          <th>כובשת</th><th>סופגת</th><th>מלך שערים</th></tr></thead>
          <tbody id="wiBoard"></tbody></table></div>
      </div>
    </div>
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

    # history (committed jsonl, one record per pipeline run); downsample to <=60 pts
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
    if len(hist) > 60:
        step = len(hist) // 60 + 1
        hist = hist[::step] + [hist[-1]]

    return {
        "generatedAt": data.get("timestamp", ""),
        "elo": elo, "advance": advance[:24], "advanceTail": advance[-8:],
        "goldenBoot": gb[:15],
        "simTitle": {t: round(float(p), 4) for t, p in sim_title.items()},
        "titleHe": {t: team_he.get(t, t) for t in sim_title},
        "calibration": {"strength_spread": cal.get("strength_spread"),
                        "golden_boot_scale": cal.get("golden_boot_scale")},
        "history": hist,
    }


def odds_html() -> str:
    return """
  <h2 class="bigsec">הימורי השוק ודירוגי הכוח (ELO)</h2>
  <section>
    <p class="sub" style="margin-top:4px">בכל הרצה הצינור מרענן את נתוני השוק ומחשב דירוג כוח (ELO) משוקלל.
      כאן רואים את הערכים <b>של ההרצה האחרונה</b>, ולמטה מעקב <b>לאורך זמן</b>.</p>
    <div class="callout">
      <b>שימו לב.</b> יחסי ההימורים ודירוגי ה‑ELO הם כיום קלט יציב (נקבעו לפני הטורניר), ולכן הם כמעט קבועים בין הרצות.
      מה שבאמת זז עם תוצאות אמת הוא ה<b>הסתברויות מהסימולציה</b> ופרמטרי ה<b>כיול</b> — ואותם מציגים גם לאורך זמן.
    </div>
    <div id="odCal" class="odcal"></div>
  </section>
  <div class="grid2">
    <section><div class="panel-title">דירוג כוח (ELO) — ההרצה האחרונה</div>
      <p class="panel-cap">משוקלל = שילוב דירוג בסיס והימורי השוק</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm">נבחרת</th><th>משוקלל</th><th>בסיס</th><th>שוק</th><th>P(זכייה)</th>
      </tr></thead><tbody id="odElo"></tbody></table></div>
    </section>
    <section><div class="panel-title">סיכויי תואר — שוק מול סימולציה</div>
      <p class="panel-cap">P(זכייה בגביע): השוק (הסתברות גלומה) מול הסימולציה שלנו</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm">נבחרת</th><th>שוק</th><th>סימולציה</th></tr></thead>
        <tbody id="odTitle"></tbody></table></div>
    </section>
  </div>
  <div class="grid2">
    <section><div class="panel-title">סיכויי העפלה (שוק)</div>
      <p class="panel-cap">P(העפלה לשלב הנוק‑אאוט) לפי השוק — 24 המובילות</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm">נבחרת</th><th>העפלה</th></tr></thead><tbody id="odAdv"></tbody></table></div>
    </section>
    <section><div class="panel-title">נעל הזהב (שוק)</div>
      <p class="panel-cap">P(זכייה בנעל הזהב) לפי השוק — 15 המובילים</p>
      <div class="scrollbox"><table class="odtbl"><thead><tr>
        <th class="nm">שחקן</th><th>סיכוי</th></tr></thead><tbody id="odGb"></tbody></table></div>
    </section>
  </div>
  <section>
    <h2 style="margin-top:6px">לאורך זמן</h2>
    <p class="sub">מעקב אחר ההסתברויות מהסימולציה ופרמטרי הכיול לאורך ההרצות. ייאסף ויתעבה ככל שיצטברו עדכונים.</p>
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
  <h2 class="bigsec">את מי לעודד?</h2>
  <section>
    <p class="sub" style="margin-top:4px">לכל משחק — באיזו תוצאה כדאי <b>לכם</b> לתמוך?
      תחת כל תוצאה מופיעים המשתתפים שאותה תוצאה <b>משפרת להם את תוחלת הפרס</b>, והסכום שלצד השם הוא
      <b>השינוי הצפוי בתוחלת הזכייה</b> (₪) אם זו התוצאה. הדגישו את עצמכם ועודדו בהתאם.
      <span class="rfsub-il">השעות בשעון ישראל.</span></p>
    <div class="callout rfnote">
      ברירת המחדל: כל משתתף מופיע <b>בתוצאה הטובה לו ביותר</b>. סננו לטופס שלכם כדי לראות אותו
      בכל התוצאות עם השינוי הצפוי בכל אחת. מי שהמשחק כמעט לא משפיע עליו מופיע תחת
      <b>״לא מהותי״</b>. עוצמת הפס שלצד כל שם משקפת כמה המשחק <b>מהותי</b> עבורו ביחס לאחרים.
      במשחקי נוקאאוט יש שתי תוצאות (אין תיקו). ההשפעה מחושבת בכל משחק בנפרד (מתוך אותה סימולציה),
      ומתעדכנת לאחר כל משחק שמסתיים.
    </div>
    <div class="rffilters">
      <div class="rfdaytoggle" id="rfDayToggle">
        <button type="button" class="rfday" data-day="today">היום</button>
        <button type="button" class="rfday" data-day="tomorrow">מחר</button>
      </div>
      <div class="rffl-row">
        <div class="rfdd">
          <button type="button" class="rfdd-btn" id="rfFilterBtn">סינון משתתפים
            <span class="rfdd-cnt" id="rfFilterCnt"></span> <span class="rfcar">▾</span></button>
          <div class="rfdd-pop" id="rfFilterPop" hidden>
            <input type="search" class="rfdd-search" id="rfFilterSearch" placeholder="חיפוש שם…">
            <div class="rfdd-actions"><button type="button" class="rflink" id="rfClear">נקה הכל</button></div>
            <div class="rfdd-list" id="rfFilterList">{filt_opts}</div>
          </div>
        </div>
        <div class="rfdd">
          <button type="button" class="rfdd-btn" id="rfHiBtn">הדגשת משתתפים<span id="rfHiCur"></span>
            <span class="rfcar">▾</span></button>
          <div class="rfdd-pop" id="rfHiPop" hidden>
            <input type="search" class="rfdd-search" id="rfHiSearch" placeholder="חיפוש שם…">
            <div class="rfdd-actions"><button type="button" class="rflink" id="rfHiClear">בטל הכל</button></div>
            <div class="rfdd-list" id="rfHiList">{hi_opts}</div>
          </div>
        </div>
        <label class="rftoggle"><input type="checkbox" id="rfTop3"> רק עם סיכוי לפודיום</label>
        <label class="rftoggle"><input type="checkbox" id="rfLast"> רק עם סיכוי למקום אחרון</label>
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
         + '<span class="rfprob">סיכוי '+pct+'%</span></div>';
  }
  function bucketCol(kind, headHtml, items, focus){
    items.sort((a,b)=> b.v - a.v);
    const chips = items.map(it=> chip(it.n, it.v, true, it.imp||0)).join('') ||
                  '<div class="rfempty">— אין —</div>';
    return '<div class="rfcol rf-'+kind+'">'+headHtml+'<div class="rfchips">'+chips+'</div></div>';
  }

  function render(){
    // day toggle buttons (label + disabled state)
    if(dayToggle) dayToggle.querySelectorAll('.rfday').forEach(b=>{
      const d = dayByKey[b.dataset.day];
      const n = d ? d.games.length : 0;
      b.disabled = !n;
      b.classList.toggle('on', b.dataset.day===day);
      b.textContent = (b.dataset.day==='today'?'היום':'מחר') + (d ? ' · '+(d.date||'').slice(5).split('-').reverse().join('.') : '');
    });
    if(fCnt) fCnt.textContent = filt.size ? '('+filt.size+')' : '';
    if(hCur) hCur.textContent = hi.size ? ' ('+hi.size+')' : '';

    const D = dayByKey[day];
    if(!D || !D.games.length){
      gamesEl.innerHTML = '<div class="callout">אין משחקים '+(day==='today'?'היום':'מחר')+'.</div>';
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
              + '<span class="rftime">'+esc(g.ko)+'</span><span class="rfko-badge">נוקאאוט</span></div>'
              + '<div class="rfvs-line"><span class="rffl-mini">'+g.f1+'</span> '+esc(g.t1)
              + ' <span class="rfx-mini">✕</span> '+g.f2+' '+esc(g.t2)+'</div>'
              + '<div class="rfempty">המשחק ייפתח כשייקבעו המעפילים מהשלב הקודם.</div></div>';
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

      const badge = isKo ? '<span class="rfko-badge">נוקאאוט</span>' : '';
      let buckets;
      if(isKo){
        const h1 = colHead(g.f1, g.t1, pr[0]);
        const h2 = colHead(g.f2, g.t2, pr[1]);
        buckets = '<div class="rfbuckets ko">'
                + bucketCol('win1', h1, cols[0], focus)
                + '<div class="rfvs"><span class="rfx-big">✕</span></div>'
                + bucketCol('win2', h2, cols[1], focus)
                + '</div>';
      } else {
        const h1 = colHead(g.f1, g.t1, pr[0]);
        const hd = '<div class="rfcolhd"><span class="rfx-big">✕</span>'
                 + '<span class="rfcname rfcdraw">תיקו</span>'
                 + '<span class="rfprob">סיכוי '+pr[1]+'%</span></div>';
        const h2 = colHead(g.f2, g.t2, pr[2]);
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
        card += '<details class="rfneutral"><summary>לא מהותי ('+neutral.length+') — המשחק כמעט לא משפיע</summary>'
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
})();
"""


_WHATIF_JS = r"""
const WHATIF = __WHATIF__;
(function(){
  const W = WHATIF;
  const board = document.getElementById('wiBoard');
  const matchesEl = document.getElementById('wiMatches');
  if(!W || !W.entries || !board || !matchesEl) return;
  const R = W.rules;
  const heT = t => (W.teamHe[t]||t);
  const heP = p => (W.playerHe[p]||p);
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
      const tab = {}; W.groups[g].forEach(t=> tab[t]={pts:0,gd:0,gf:0});
      ms.forEach(m=>{ const [hg,ag]=gs[m.no];
        tab[m.home].gf+=hg; tab[m.away].gf+=ag; tab[m.home].gd+=hg-ag; tab[m.away].gd+=ag-hg;
        if(hg>ag) tab[m.home].pts+=3; else if(ag>hg) tab[m.away].pts+=3; else { tab[m.home].pts++; tab[m.away].pts++; }
      });
      const ord = W.groups[g].slice().sort((a,b)=> tab[b].pts-tab[a].pts || tab[b].gd-tab[a].gd || tab[b].gf-tab[a].gf || a.localeCompare(b));
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
    for(const bm of W.bracket){
      const home = resolve(bm.hr, bm.m, 'home_ref');
      const away = resolve(bm.ar, bm.m, 'away_ref');
      teamsByMatch[bm.m] = [home, away];
      if(!home || !away) continue;
      let winner=null, hg=null, ag=null, so=false;
      const rk = realByPair[pairKey(home,away)];
      if(rk && rk.winner){ matchedReal[pairKey(home,away)]=1; winner=rk.winner; hg=rk.home_goals; ag=rk.away_goals; so=!!rk.shootout;
        if(home!==rk.home){ const t=hg; hg=ag; ag=t; } }
      else if(useHypo && hypoKo[bm.m]!==undefined){ const h=hypoKo[bm.m]; hg=h.hg; ag=h.ag;
        if(hg>ag) winner=home; else if(ag>hg) winner=away; else { so=true; winner=h.so||null; } }
      if(winner){ winByMatch[bm.m]=winner; koPlayed.push({home,away,hg,ag,winner,so}); }
      else fillable.push({m:bm.m, stage:bm.stage, rc:bm.rc, home, away});
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
    const tournComplete = Object.keys(gs).length>=72 && stand.allComplete && fillable.length===0 && !!winByMatch[104];
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
    return {bd, fillable, allComplete:stand.allComplete};
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

  function scorerEditor(mk, goals, home, away){
    // only picked "top scorer" candidates who actually play in this match
    const elig = W.trackedPlayers.filter(p=> p.team===home || p.team===away);
    if(!elig.length) return '';
    const cur = hypoScorers[mk]||{};
    const used = Object.values(cur).reduce((s,n)=>s+n,0);
    const over = used>goals;
    const rows = elig.map(p=>{
      const v = cur[p.name]||0;
      return `<div class="wisc-row">
        <span class="wisc-nm">${heP(p.name)} <small>· ${heT(p.team)}</small></span>
        <span class="wistep">
          <button type="button" class="wistepbtn wisc-dec" data-mk="${mk}" data-p="${p.name}" ${v<=0?'disabled':''}>−</button>
          <span class="wisc-v">${v}</span>
          <button type="button" class="wistepbtn wisc-inc" data-mk="${mk}" data-p="${p.name}" ${used>=goals?'disabled':''}>+</button>
        </span></div>`;
    }).join('');
    return `<div class="wiscorers">
      <div class="wisc-hd">מבקיעים מההתערבות <small>(${used}/${goals})</small></div>
      ${rows}
      ${over?'<div class="wihint" style="color:var(--red)">שויכו יותר שערים מהתוצאה — צמצמו</div>':''}
    </div>`;
  }

  function matchRow(kind, m, home, away, score, stage){
    const mk = kind+m;
    const hv = score? score[0] : '';
    const av = score? score[1] : '';
    const tie = score && score[0]===score[1];
    const goals = score? (score[0]+score[1]) : 0;
    let so = '';
    if(kind==='k' && tie){
      const w = (hypoKo[m]||{}).so || '';
      so = `<div class="wiso">עלתה בפנדלים:
        <label><input type="radio" name="so${m}" class="wisoR" data-m="${m}" value="${home}" ${w===home?'checked':''}> ${heT(home)}</label>
        <label><input type="radio" name="so${m}" class="wisoR" data-m="${m}" value="${away}" ${w===away?'checked':''}> ${heT(away)}</label></div>`;
    }
    const scr = (score && goals>0) ? scorerEditor(mk, goals, home, away) : '';
    return `<div class="wimatch" data-mk="${mk}">
      <div class="wimrow">
        <span class="witeam h">${heT(home)}</span>
        <input class="wiscore" type="number" min="0" inputmode="numeric" data-kind="${kind}" data-m="${m}" data-side="h" value="${hv}">
        <span class="widash">:</span>
        <input class="wiscore" type="number" min="0" inputmode="numeric" data-kind="${kind}" data-m="${m}" data-side="a" value="${av}">
        <span class="witeam a">${heT(away)}</span>
      </div>${so}${scr}</div>`;
  }

  function renderMatches(full){
    // group matches still open (no real result yet)
    const openGroup = W.groupMatches.filter(m=> W.realGroupScores[m.no]===undefined)
      .sort((a,b)=> a.no-b.no);
    let html = '';
    html += '<div class="wistage">שלב הבתים</div>';
    if(!openGroup.length) html += '<div class="wihint">כל משחקי הבתים כבר שוחקו.</div>';
    openGroup.forEach(m=> html += matchRow('g', m.no, m.home, m.away, hypoGroup[m.no]||null, 'group'));
    // knockout matches that are now resolvable (both teams determined)
    html += '<div class="wistage">נוק‑אאוט</div>';
    if(!full.fillable.length){
      html += '<div class="wihint">משחקי נוק‑אאוט נפתחים אוטומטית ברגע ששתי הקבוצות בהם נקבעות — מלאו תוצאות בתים (או משחקי נוק‑אאוט מוקדמים יותר) כדי לפתוח אותם. שיבוץ מקומות השלישי דורש סיום כל הבתים.</div>';
    } else {
      let curStage = '';
      full.fillable.sort((a,b)=> a.m-b.m).forEach(km=>{
        if(km.stage!==curStage){ curStage=km.stage; html += `<div class="wisub">${fmtStage(km.stage)}</div>`; }
        html += matchRow('k', km.m, km.home, km.away, hypoKo[km.m]? [hypoKo[km.m].hg,hypoKo[km.m].ag]:null, km.stage);
      });
    }
    const top = matchesEl.scrollTop;     // keep the scroll position across re-renders
    matchesEl.innerHTML = html;
    matchesEl.scrollTop = top;
  }

  function sigOf(full){
    return (full.allComplete?'C':'-') + '|' + full.fillable.map(f=>f.m).join(',') +
           '|' + W.groupMatches.filter(m=>W.realGroupScores[m.no]===undefined && hypoGroup[m.no]).length;
  }

  function recompute(forceMatches){
    const full = evaluate(true);
    renderBoard(full);
    const sig = sigOf(full);
    if(forceMatches || sig!==lastSig){
      // remember which score input is being edited so we can restore it after
      // the matches list is rebuilt (otherwise typing loses focus / scroll jumps)
      const a = document.activeElement;
      const desc = (a && a.classList && a.classList.contains('wiscore'))
        ? {m:a.dataset.m, kind:a.dataset.kind, side:a.dataset.side} : null;
      renderMatches(full); lastSig = sig;
      if(desc){
        const el = matchesEl.querySelector('.wiscore[data-m="'+desc.m+'"][data-kind="'+desc.kind+'"][data-side="'+desc.side+'"]');
        if(el){ el.focus(); const v=el.value; try{ el.value=''; el.value=v; }catch(e){} }
      }
    }
    const nHypo = Object.keys(hypoGroup).length + Object.keys(hypoKo).length;
    document.getElementById('wiCount').textContent = nHypo? `${nHypo} תוצאות בתרחיש` : 'לא הוזנו תוצאות עדיין';
  }

  // ---- events (delegated) ------------------------------------------------ //
  matchesEl.addEventListener('input', function(ev){
    const t = ev.target;
    if(t.classList.contains('wiscore')){
      const m = +t.dataset.m, kind = t.dataset.kind;
      const box = t.closest('.wimatch');
      const ins = box.querySelectorAll('.wiscore');
      const hv = ins[0].value==='' ? null : Math.max(0, parseInt(ins[0].value,10)||0);
      const av = ins[1].value==='' ? null : Math.max(0, parseInt(ins[1].value,10)||0);
      if(hv===null && av===null){ if(kind==='g') delete hypoGroup[m]; else delete hypoKo[m]; }
      else {
        const h=hv||0, a=av||0;
        if(kind==='g') hypoGroup[m]=[h,a];
        else { const prev=hypoKo[m]||{}; hypoKo[m]={hg:h,ag:a,so:(h===a?prev.so:undefined)}; }
      }
      recompute(true);   // refresh the scorer editor (eligibility + goal caps)
    }
  });
  function matchGoals(mk){ const kind=mk[0], m=mk.slice(1);
    if(kind==='g'){ const s=hypoGroup[m]; return s? s[0]+s[1] : 0; }
    const s=hypoKo[m]; return s? s.hg+s.ag : 0; }
  matchesEl.addEventListener('change', function(ev){
    const t = ev.target;
    if(t.classList.contains('wisoR')){ const m=+t.dataset.m; if(hypoKo[m]) hypoKo[m].so=t.value; recompute(false); }
  });
  matchesEl.addEventListener('click', function(ev){
    const t = ev.target;
    if(t.classList.contains('wisc-inc')){ const mk=t.dataset.mk, p=t.dataset.p;
      const cur=hypoScorers[mk]||{}; const used=Object.values(cur).reduce((s,n)=>s+n,0);
      if(used < matchGoals(mk)){ hypoScorers[mk]=cur; cur[p]=(cur[p]||0)+1; recompute(true); }
    } else if(t.classList.contains('wisc-dec')){ const mk=t.dataset.mk, p=t.dataset.p;
      const cur=hypoScorers[mk]; if(cur && cur[p]){ cur[p]--; if(cur[p]<=0) delete cur[p];
        if(!Object.keys(cur).length) delete hypoScorers[mk]; recompute(true); }
    }
  });
  document.getElementById('wiReset').addEventListener('click', function(){
    hypoGroup={}; hypoKo={}; hypoScorers={}; recompute(true);
  });

  recompute(true);
})();
"""


_ODDS_JS = r"""
const ODDS = __ODDS__;
(function(){
  const O = ODDS;
  if(!O || !document.getElementById('odElo')) return;
  const pct = x => (x==null? '—' : (x*100).toFixed(1)+'%');
  const num = x => (x==null? '—' : Math.round(x));

  const cal = O.calibration||{};
  document.getElementById('odCal').innerHTML =
    `<div class="odchip"><span class="odk">מקדם פיזור הכוח</span><span class="odv">${cal.strength_spread!=null?cal.strength_spread.toFixed(3):'—'}</span></div>`+
    `<div class="odchip"><span class="odk">מקדם נעל הזהב</span><span class="odv">${cal.golden_boot_scale!=null?cal.golden_boot_scale.toFixed(3):'—'}</span></div>`+
    `<div class="odchip"><span class="odk">עודכן</span><span class="odv">${O.generatedAt||'—'}</span></div>`;

  document.getElementById('odElo').innerHTML = (O.elo||[]).map(r=>
    `<tr><td class="nm">${r.he}</td><td class="v">${num(r.blended)}</td><td>${num(r.eloratings)}</td>`+
    `<td>${num(r.market)}</td><td>${pct(r.marketProb)}</td></tr>`).join('');

  const titleRows = Object.keys(O.simTitle||{}).map(t=>({t, he:(O.titleHe||{})[t]||t, sim:O.simTitle[t]}));
  const eloByTeam = {}; (O.elo||[]).forEach(r=> eloByTeam[r.team]=r.marketProb);
  titleRows.sort((a,b)=> b.sim-a.sim);
  document.getElementById('odTitle').innerHTML = titleRows.map(r=>
    `<tr><td class="nm">${r.he}</td><td>${pct(eloByTeam[r.t])}</td><td class="v">${pct(r.sim)}</td></tr>`).join('')
    || '<tr><td class="nm" colspan="3">—</td></tr>';

  document.getElementById('odAdv').innerHTML = (O.advance||[]).map(r=>
    `<tr><td class="nm">${r.he}</td><td class="v">${pct(r.p)}</td></tr>`).join('');
  document.getElementById('odGb').innerHTML = (O.goldenBoot||[]).map(r=>
    `<tr><td class="nm">${r.he}</td><td class="v">${pct(r.p)}</td></tr>`).join('');

  // ---- over-time mini charts -------------------------------------------- //
  const hist = O.history||[];
  const host = document.getElementById('odHist');
  if(hist.length < 2){
    host.innerHTML = '<div class="wihint">עדיין אין מספיק נקודות מדידה לאורך זמן — ייאסף עם ההרצות הבאות.</div>';
    return;
  }
  const COLORS = ['#2563eb','#16a34a','#d97706','#7c3aed','#dc2626','#0891b2'];
  function lineChart(title, series, fmtY){
    const W=560, H=210, padL=44, padR=12, padT=14, padB=26;
    const xs = hist.map((_,i)=> padL + (W-padL-padR)*(hist.length>1? i/(hist.length-1):0));
    let vmax=0; series.forEach(s=> s.vals.forEach(v=>{ if(v!=null && v>vmax) vmax=v; }));
    vmax = vmax>0? vmax*1.1 : 1;
    const y = v => padT + (H-padT-padB)*(1 - (v/vmax));
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="odsvg">`;
    [0,0.25,0.5,0.75,1].forEach(f=>{ const yy=padT+(H-padT-padB)*f; const val=vmax*(1-f);
      svg+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="#e2e8f0"/>`+
           `<text x="${padL-6}" y="${yy+3}" text-anchor="end" font-size="9" fill="#94a3b8">${fmtY(val)}</text>`; });
    series.forEach((s,si)=>{ const c=COLORS[si%COLORS.length];
      let d=''; s.vals.forEach((v,i)=>{ if(v==null) return; d+=(d?'L':'M')+xs[i].toFixed(1)+' '+y(v).toFixed(1)+' '; });
      svg+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="2"/>`; });
    svg += '</svg>';
    const leg = series.map((s,si)=>`<span class="odlg"><span class="odsw" style="background:${COLORS[si%COLORS.length]}"></span>${s.label}</span>`).join('');
    return `<div class="odchart"><div class="panel-title">${title}</div><div class="odleg">${leg}</div>${svg}</div>`;
  }
  // sim-title for the top 6 teams (by latest snapshot)
  const last = hist[hist.length-1];
  const titleKeys = Object.keys(last.sim_title||{}).sort((a,b)=> (last.sim_title[b]||0)-(last.sim_title[a]||0)).slice(0,6);
  const titleHe = O.titleHe||{};
  const s1 = titleKeys.map(t=>({label:(titleHe[t]||t), vals:hist.map(h=> (h.sim_title||{})[t]!=null? h.sim_title[t]:null)}));
  const s2 = [{label:'מקדם פיזור', vals:hist.map(h=> h.strength_spread!=null? h.strength_spread:null)},
              {label:'מקדם נעל זהב', vals:hist.map(h=> h.golden_boot_scale!=null? h.golden_boot_scale:null)}];
  host.innerHTML =
    (s1.length? lineChart('סיכויי תואר מהסימולציה (6 המובילות)', s1, v=> (v*100).toFixed(0)+'%') : '') +
    lineChart('פרמטרי כיול', s2, v=> v.toFixed(2));
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

    def conv_ko(ko):
        out = []
        for rd in ko or []:
            opp = [{"t": he.get(o["t"], o["t"]), "flag": _flag(o["t"]),
                    "meet": o.get("meet", 0), "beat": o.get("beat", 0)}
                   for o in rd.get("opp", [])]
            out.append({"r": rd["r"], "rhe": ko_he.get(rd["r"], rd["r"]),
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
        f'<span>{t["flag"]} {t["t"]}</span></label>' for t in payload["teams"])
    blob = json.dumps(payload, ensure_ascii=False)
    return f"""
  <h2 class="bigsec">עד לאן יגיעו?</h2>
  <section class="stwrap">
    <p class="sub" style="margin-top:4px">לכל נבחרת — ההסתברות (מתוך הסימולציה) <b>להגיע לכל שלב</b> בטורניר.
      המפה צבועה לפי ההסתברות <b>להגיע לפחות</b> לשלב. סננו לנבחרות מסוימות, ובחרו אותן גם לגרף ההשוואה למטה.</p>
    <div class="stctrls">
      <div class="rfdd">
        <button type="button" class="rfdd-btn" id="stTeamBtn">בחירת נבחרות
          <span class="rfdd-cnt" id="stTeamCnt"></span> <span class="rfcar">▾</span></button>
        <div class="rfdd-pop" id="stTeamPop" hidden>
          <input type="search" class="rfdd-search" id="stTeamSearch" placeholder="חיפוש נבחרת…">
          <div class="rfdd-actions"><button type="button" class="rflink" id="stTeamClear">נקה הכל</button></div>
          <div class="rfdd-list" id="stTeamList">{opts}</div>
        </div>
      </div>
    </div>
    <div class="stheatwrap"><div id="stHeat"></div></div>

    <h3 style="margin:18px 0 0">גרף התפלגות</h3>
    <div class="stctrls">
      <div class="stmode" id="stMode">
        <button type="button" data-mode="exact" class="on">התפלגות (איפה ייעצרו)</button>
        <button type="button" data-mode="cum">מצטבר (להגיע לפחות ל…)</button>
      </div>
    </div>
    <p class="sthint" id="stChartHint"></p>
    <div class="stchart"><div class="stleg" id="stLeg"></div><div id="stChart"></div></div>

    <h3 style="margin:18px 0 0">מסלול הנוקאאוט הצפוי</h3>
    <p class="sub" style="margin-top:4px">לנבחרת שתבחרו — בכל שלב נוקאאוט: סיכוי <b>המעבר</b> הכולל,
      ומי היריבות הסבירות. לצד כל יריבה: <b>נפגשים</b> (כמה פעמים זו היריבה בשלב הזה) ו<b>מנצחים</b>
      (הסיכוי לנצח אותה אם נפגשים). כך רואים אם המעבר הוא משחק־מטבע מול יריבה שקולה,
      או תערובת של יריבות חלשות וחזקות.</p>
    <div id="stPath" class="stpath"></div>
    <script id="stData" type="application/json">{blob}</script>
  </section>
"""


STAGES_JS = r"""
(function(){
  const panel = document.getElementById('tab-stages');
  if(!panel) return;
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

  const sel = new Set();       // selected team english keys (empty = all in heatmap)
  let mode = 'exact';

  function pct(p){ if(p<=0) return '·'; if(p<0.10) return (p*100).toFixed(1)+'%'; return Math.round(p*100)+'%'; }
  function heat(p){
    const a = p<=0 ? 0 : (0.10 + 0.90*p);
    return {bg:'rgba(37,99,235,'+a.toFixed(3)+')', fg:(p>=0.55?'#fff':'#0f172a')};
  }

  function renderHeat(){
    const rows = sel.size ? teams.filter(t=> sel.has(t.en)) : teams;
    const L = S.reachLabels;
    let h = '<table class="sttbl"><thead><tr><th class="nm">נבחרת</th>';
    L.forEach(lb=> h += '<th>'+lb+'</th>');
    h += '</tr></thead><tbody>';
    rows.forEach(t=>{
      h += '<tr><td class="nm"><span class="stflag">'+t.flag+'</span>'+esc(t.t)+'</td>';
      (t.reach||[]).forEach(p=>{ const c=heat(p);
        h += '<td><span class="stcell" style="background:'+c.bg+';color:'+c.fg+'">'+pct(p)+'</span></td>'; });
      h += '</tr>';
    });
    h += '</tbody></table>';
    heatEl.innerHTML = h;
  }

  function chartTeams(){
    if(sel.size) return teams.filter(t=> sel.has(t.en)).slice(0, CHART_CAP);
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
    const labels = mode==='exact' ? S.exactLabels : S.reachLabels;
    const series = ts.map((t,i)=>({
      label: t.t, color: COLORS[i%COLORS.length],
      vals: (mode==='exact' ? t.exact : t.reach) || []
    }));
    legEl.innerHTML = series.map(s=> '<span class="stlg"><span class="stsw" style="background:'+s.color+'"></span>'+esc(s.label)+'</span>').join('');
    chartEl.innerHTML = barChart(labels, series);
    let hint = mode==='exact'
      ? 'כל נבחרת: באיזה שלב צפויה להיעצר (סכום הטורים = 100%).'
      : 'כל נבחרת: הסיכוי להגיע <b>לפחות</b> לשלב.';
    if(!sel.size) hint += ' מוצגות 6 הנבחרות החזקות — בחרו נבחרות להשוואה.';
    else if(sel.size>CHART_CAP) hint += ' מוצגות '+CHART_CAP+' הראשונות מבין '+sel.size+' שנבחרו.';
    hintEl.innerHTML = hint;
  }
  const pathEl = document.getElementById('stPath');
  const PATH_CAP = 4;
  function beatClass(p){ return p>=0.55 ? 'good' : (p<=0.45 ? 'bad' : 'even'); }
  function renderPath(){
    const ts = sel.size ? teams.filter(t=> sel.has(t.en)).slice(0, PATH_CAP) : [];
    if(!ts.length){
      pathEl.innerHTML = '<div class="callout">בחרו נבחרת (למעלה) כדי לראות את מסלול הנוקאאוט הצפוי שלה ואת היריבות הסבירות בכל שלב.</div>';
      return;
    }
    pathEl.innerHTML = ts.map(t=>{
      const rounds = (t.ko||[]).map(rd=>{
        const shown = rd.opp||[];
      const meetSum = shown.reduce((a,o)=> a + (o.meet||0), 0);
      let opps = shown.map(o=>
          '<div class="stpopp"><div class="stpo-nm">'+o.flag+' '+esc(o.t)+'</div>'
          + '<div class="stpo-stats"><span class="stpo-meet">נפגשים '+Math.round(o.meet*100)+'%</span>'
          + '<span class="stpo-beat '+beatClass(o.beat)+'">מנצחים '+Math.round(o.beat*100)+'%</span></div></div>'
        ).join('');
      const other = 1 - meetSum;
      if(other > 0.005){
        opps += '<div class="stpopp other"><div class="stpo-nm">יריבות נוספות</div>'
          + '<div class="stpo-stats"><span class="stpo-meet">נפגשים '+Math.round(other*100)+'%</span></div></div>';
      }
      if(!opps) opps = '<div class="rfempty">—</div>';
        return '<div class="stpcard"><div class="stpr">'+esc(rd.rhe)
          + '<span class="stppass">מעבר '+Math.round(rd.pass*100)+'%</span></div>'
          + '<div class="stpopps">'+opps+'</div></div>';
      }).join('') || '<div class="rfempty">לא צפויה להגיע לשלב הנוקאאוט.</div>';
      return '<div class="stpteam"><div class="stpname">'+t.flag+' '+esc(t.t)+'</div>'
        + '<div class="stprounds">'+rounds+'</div></div>';
    }).join('');
    if(sel.size>PATH_CAP){
      pathEl.innerHTML += '<p class="sthint">מוצגות '+PATH_CAP+' הנבחרות הראשונות מבין '+sel.size+' שנבחרו.</p>';
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
})();
"""


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
    all_css = "\n".join([CMTBL_CSS, TABS_CSS, WHATIF_CSS, ODDS_CSS, CHEER_CSS, STAGES_CSS])
    html = replace_region(html, CSS_START, CSS_END, all_css)

    # 2) Main-tab live body (podium / leaders / standings / simulation / groups).
    main_body = (podium_html(data) + leaders_html(data) + standings_table_html(data)
                 + explanation_html(n_ent, n_sims, coverage_html(data)) + groups_html(data))
    html = replace_region(html, HTML_START, HTML_END, main_body)

    # 3) What-If + Odds tab bodies.
    html = replace_region(html, WHATIF_START, WHATIF_END, whatif_html())
    html = replace_region(html, ODDS_START, ODDS_END, odds_html())
    html = replace_region(html, CHEER_START, CHEER_END, cheer_html(data))
    html = replace_region(html, STAGES_START, STAGES_END, stages_html(data))

    # 4) All injected JS in one managed block before </script>.
    wi_payload = whatif_payload(data, state)
    od_payload = odds_payload(data)
    all_js = "\n".join([
        js_block(champs, CHAMP_HE, cm["p_title"], matrix, order, winprob),
        LEADERS_JS, TABS_JS, whatif_js(wi_payload), odds_js(od_payload), CHEER_JS, STAGES_JS,
    ])
    html = replace_region(html, JS_START, JS_END, all_js)

    OUT.write_text(html, encoding="utf-8")
    print(f"Updated {OUT}  ({len(html)//1024} KB) — {n_ent} entries, {n_sims:,} sims, "
          f"{len(wi_payload['entries'])} what-if rows")


if __name__ == "__main__":
    main()
