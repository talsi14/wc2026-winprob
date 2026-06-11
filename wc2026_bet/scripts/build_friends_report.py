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
    <p class="sub">לכל שילוב של טופס (שורה) ואלוף עולמי אפשרי (עמודה): ההסתברות שאותו טופס יזכה
      בקופה בהינתן שאותה נבחרת זוכה במונדיאל. האחוז מתחת לשם הנבחרת = ההסתברות שלה לתואר. שלוש
      העמודות הימניות הן הנתונים הכלליים של כל טופס: סיכוי לזכייה, סיכוי לכסף (מקום 1–2), וסיכוי
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
  /* live win-probability banner */
  h2.bigsec{font-size:1.9rem; margin:56px 0 8px; padding:16px 22px; color:#fff; line-height:1.2;
            background:linear-gradient(135deg,#0b1220,#1e3a8a); border-radius:14px;
            box-shadow:0 6px 20px -10px rgba(30,58,138,.6);}
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

    # 2) HTML sections, placed near the TOP of the page - right after the stat
    #    boxes + headline callout, before the "כמה בחרו" tier-breakdown section.
    body = explanation_html(n_ent, n_sims, coverage_html(data)) + groups_html(data)
    block = f"{HTML_START}\n{body}\n  {HTML_END}\n"
    anchor = re.compile(r"(\n\s*<section>\s*\n\s*<h2[^>]*>כמה בחרו)")
    if anchor.search(html):
        html = anchor.sub("\n" + block + r"\1", html, count=1)
    else:                                   # fallback: before the footer
        html = re.sub(r"(\n\s*<footer)", "\n" + block + r"\1", html, count=1)

    # 3) JS render code, just before the closing </script>
    js = f"\n{JS_START}\n{js_block(champs, CHAMP_HE, cm['p_title'], matrix, order, winprob)}\n{JS_END}\n"
    html = re.sub(r"(\n</script>)", js + r"\1", html, count=1)

    OUT.write_text(html, encoding="utf-8")
    print(f"Updated {OUT}  ({len(html)//1024} KB) — {n_ent} entries, {n_sims:,} sims")


if __name__ == "__main__":
    main()
