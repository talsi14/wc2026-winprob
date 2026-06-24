"""Bilingual UI strings (Hebrew default + English) for the friends report page."""
from __future__ import annotations

import json

# key -> (hebrew, english)
STRINGS: dict[str, tuple[str, str]] = {
    "page.title": ("התערבות חברים מונדיאל 2026 — ניתוח הטפסים",
                   "Friends World Cup 2026 Pool — Entry Analysis"),
    "hero.alt": ("התערבות חברים — מונדיאל 2026", "Friends pool — World Cup 2026"),
    "lang.toggle": ("English", "עברית"),
    "tab.main": ("דירוג וניתוח", "Standings & analysis"),
    "tab.whatif": ("What If..?", "What If..?"),
    "tab.odds": ("הימורים ו‑ELO", "Odds & ELO"),
    "tab.cheer": ("את מי לעודד?", "Who to root for?"),
    "tab.stages": ("עד לאן יגיעו?", "How far will they go?"),
    "pts.abbr": ("נק׳", "pts"),
    "live.badge": ("חי", "LIVE"),
    "live.tooltip": ("כולל משחקים שמתנהלים כעת", "Includes matches currently in progress"),
    "live.match": ("משחק מתנהל כעת", "Match in progress"),
    "na": ("טרם זמין", "Not yet available"),
    "podium.title": ("טבלת הדירוג", "Standings"),
    "leader.top_scorer": ("מלך השערים כרגע", "Top scorer now"),
    "leader.conceding": ("הסופגת המובילה", "Most goals conceded"),
    "leader.scoring": ("הכובשת המובילה", "Top scoring team"),
    "standings.sub": (
        "כל הטפסים מדורגים לפי הניקוד בפועל. העמודות <b>זכייה</b> ו<b>תוך הכסף</b> "
        "הן הסתברויות מהסימולציה (מקום 1, ומקום 1–2). בכל בחירה מוצג בסוגריים מספר "
        "הנקודות שצברה עד כה.",
        "All entries ranked by actual points. <b>Win</b> and <b>In the money</b> are "
        "simulation probabilities (1st place, and top 2). Points earned so far appear "
        "in parentheses next to each pick.",
    ),
    "th.rank": ("מקום", "Rank"),
    "th.change": ("שינוי", "Chg"),
    "th.name": ("שם", "Name"),
    "th.pts": ("נק׳", "Pts"),
    "th.tierA": ("דרג א׳", "Tier A"),
    "th.tierB": ("דרג ב׳", "Tier B"),
    "th.tierC": ("דרג ג׳", "Tier C"),
    "th.tierD": ("דרג ד׳", "Tier D"),
    "th.scoring": ("כובשת", "Scoring"),
    "th.conceding": ("סופגת", "Conceding"),
    "th.top_scorer": ("מלך שערים", "Top scorer"),
    "th.win": ("זכייה", "Win"),
    "th.in_money": ("תוך הכסף", "In money"),
    "sim.title": ("סימולציית סיכויי זכיה מתעדכנת", "Live win-probability simulation"),
    "sim.how": ("איך נבנה הניתוח", "How the analysis is built"),
    "sim.how.sub": ("נתונים + סימולציה — בשפה פשוטה.", "Data + simulation — in plain language."),
    "sim.data": (
        "<b>הנתונים.</b> לכל אחת מ‑48 הנבחרות חושב דירוג כוח (Elo) ששוקלל עם "
        "<b>הימורי השוק</b>: יחסי זכייה בגביע, יחסי \"העפלה מהבית\" ויחסי מלך השערים "
        "מאתרי ההימורים המובילים. כך הדירוג \"מיושר\" לחוכמת ההמונים ולא מסתמך רק על "
        "נוסחה. במקביל נמשכו <b>כל {{n_ent}} הטפסים</b> ישירות מהאתר, כדי לדעת מי בחר במה.",
        "<b>Data.</b> Each of the 48 teams gets a strength rating (Elo) blended with "
        "<b>market odds</b>: outright winner, group advance, and golden boot from major "
        "sportsbooks — aligning the model with the crowd rather than a formula alone. "
        "All <b>{{n_ent}} entries</b> were pulled from the pool site so we know every pick.",
    ),
    "sim.mc": (
        "<b>הסימולציה.</b> הטורניר כולו הורץ <b>{{n_sims}} פעמים</b> (מונטה‑קרלו). "
        "בכל הרצה מוגרלת תוצאה לכל משחק לפי הסתברות שנגזרת מהפרשי הכוח בין הנבחרות "
        "(מודל Dixon‑Coles להבקעת שערים), מתקדמים שלב‑שלב מהבתים ועד הגמר, ומגרילים גם "
        "מבקיעי שערים. בכל הרצה מחושבות נקודות לכל טופס לפי חוקי ההגרלה, {{n_ent}} הטפסים "
        "מדורגים, והקופה מתחלקת לפי המיקום (כולל חלוקת פרס בין שווים). מתוך {{n_sims}} "
        "ההרצות מתקבלים המספרים: הסתברות לזכייה, הסתברות ל\"תוך הכסף\" (מקום 1–2), "
        "הסתברות למקום אחרון, ותוחלת הנקודות והדירוג.",
        "<b>Simulation.</b> The full tournament is run <b>{{n_sims}} times</b> (Monte Carlo). "
        "Each run draws every match from team-strength gaps (Dixon–Coles goal model), "
        "advances group-by-group through the knockout bracket, and draws goal scorers. "
        "Entries are scored and ranked each run; prizes split on ties. From {{n_sims}} "
        "runs we get P(win), P(top 2 / in the money), P(last), and expected points/rank.",
    ),
    "sim.update": (
        "<b>איך זה יתעדכן במהלך הטורניר.</b> ברגע שמשחקים מתחילים, ההרצה הבאה "
        "\"מקבעת\" את מה שכבר קרה — תוצאות, מבקיעים ודירוג הבתים ננעלים כעובדה, "
        "ומוגרל רק מה שעדיין לא ידוע. במקביל נמשכים יחסי הימורים מעודכנים לרענון "
        "דירוגי הכוח. כל עדכון יוצר חותמת זמן חדשה, וכך אפשר לעקוב מי עולה ומי יורד "
        "ככל שהמציאות מתבהרת. התהליך אוטומטי — מספיק להריץ אותו מחדש.",
        "<b>Updates during the tournament.</b> Once matches start, each run locks in "
        "known results, scorers, and group tables — only unknown fixtures are simulated. "
        "Market odds refresh team strengths. Every update gets a new timestamp so you "
        "can track who rises and falls as reality unfolds. Fully automatic on each run.",
    ),
    "sim.spain": (
        "<b>למה לבוחרי ספרד סיכוי זכייה נמוך.</b> ספרד היא המועמדת מספר 1 בשוק, "
        "ולכן חלק ניכר מהמשתתפים עיגנו עליה את הטופס (ורבים בחרו במבאפה כמלך שערים) — "
        "כך שגם אם ספרד תזכה, הפרס יתחלק בין המון מתחרים כמעט זהים, ואיש מהם לא ייבדל. "
        "כדי לנצח את הקופה לא מספיק לצדוק — צריך <b>לצדוק במקום שבו אחרים טעו</b>. "
        "הטפסים שמובילים בתוחלת הם דווקא ה\"קונטראריאניים\" שזנחו את ספרד לטובת בחירות "
        "פחות פופולריות (אנגליה, נורווגיה, ארגנטינה), כי הם זוכים בקופה כמעט לבדם "
        "כשהבחירות האלה מצליחות. כלומר: ספרד מקטינה את הסיכוי להפסד גדול, אבל גם "
        "<b>כמעט מבטלת את הסיכוי לזכייה בולטת</b> — בדיוק מפני שכל כך הרבה עשו אותו דבר.",
        "<b>Why Spain picks rarely win the pool.</b> Spain is the market favourite, so "
        "many entries anchor on Spain (and Mbappé as top scorer). If Spain wins, the prize "
        "splits among near-identical tickets — no one stands out. To win you must be "
        "<b>right where others were wrong</b>. High expected-value entries often skip "
        "Spain for contrarian picks (England, Norway, Argentina) and capture the pot "
        "almost alone when those land. Spain lowers downside risk but also "
        "<b>wipes out upside</b> because so many copied the same sheet.",
    ),
    "matrix.title": ("סיכויי ניצחון בהתערבות - מותנה בזהות האלופה",
                     "Pool win odds — conditional on the champion"),
    "matrix.sub": (
        "לכל שילוב של טופס (שורה) ואלופה אפשרית (עמודה): ההסתברות שאותו טופס יזכה "
        "בקופה בהינתן שאותה נבחרת זוכה במונדיאל. האחוז מתחת לשם הנבחרת = ההסתברות "
        "שלה לתואר. שלוש העמודות השמאליות הן הנתונים הכלליים של כל טופס: סיכוי לזכייה, "
        "סיכוי לכסף (מקום 1–2), וסיכוי למקום אחרון. מוצגים מדורגים לפי תוחלת הרווח — "
        "גללו בתוך החלון לשאר.",
        "For each entry (row) and possible champion (column): P(that entry wins the pool "
        "| that team wins the World Cup). The % under each team is its title probability. "
        "The three summary columns are overall P(1st), P(in the money / top 2), and "
        "P(last). Sorted by expected winnings — scroll for the rest.",
    ),
    "matrix.gold": ("תאים זהובים = סיכוי גבוה יותר לזכות בקופה בהינתן האלוף.",
                    "Gold cells = higher pool-win chance given that champion."),
    "matrix.entry": ("טופס", "Entry"),
    "matrix.p1": ("P(1st)", "P(1st)"),
    "matrix.in_money": ("In money", "In money"),
    "matrix.p_last": ("P(last)", "P(last)"),
    "groups.title": ("טבלאות הבתים — סיכויי העפלה", "Group tables — advance odds"),
    "groups.sub": (
        "לכל בית: מספר משחקים ששוחקו (מ׳), נקודות (נק׳), הפרש שערים, וההסתברות "
        "להעפיל לשלב הנוק‑אאוט לפי הסימולציה (העפלה). שתי הנבחרות המודגשות הן "
        "המועמדות המובילות להעפלה מכל בית.",
        "Per group: matches played (P), points (Pts), goal difference, and simulated "
        "P(advance to knockout). The two highlighted rows are the leading qualifiers.",
    ),
    "groups.group": ("בית", "Group"),
    "groups.team": ("נבחרת", "Team"),
    "groups.played": ("מ׳", "P"),
    "groups.pts": ("נק׳", "Pts"),
    "groups.gd": ("הפרש", "GD"),
    "groups.advance": ("העפלה", "Advance"),
    "coverage.when": ("עודכן:", "Updated:"),
    "coverage.pre": (
        "<b>מצב הנתונים:</b> טרם שוחקו משחקים — זוהי תחזית הבסיס לפני פתיחת הטורניר. "
        "כל המשחקים מדומים.",
        "<b>Data status:</b> No matches played yet — baseline forecast before kickoff. "
        "Every match is simulated.",
    ),
    "coverage.live": (
        "<b>מצב הנתונים:</b> נכללו <b>{{gp}}/{{total_gp}}</b> משחקי בתים "
        "ו‑<b>{{kp}}/{{total_ko}}</b> משחקי נוק‑אאוט שכבר שוחקו "
        "(ו‑{{goals}} שערים שנרשמו למועמדי נעל הזהב). {{stage}}; "
        "רק מה שטרם נקבע מדומה.",
        "<b>Data status:</b> <b>{{gp}}/{{total_gp}}</b> group matches and "
        "<b>{{kp}}/{{total_ko}}</b> knockout matches recorded "
        "({{goals}} golden-boot candidate goals). {{stage}}; "
        "only undecided fixtures are simulated.",
    ),
    "coverage.stage_done": ("שלב הבתים הושלם", "Group stage complete"),
    "coverage.stage_live": ("שלב הבתים בעיצומו", "Group stage in progress"),
    # What If
    "wi.fill": ("מלא משחקי בתים בתוצאה הסבירה ביותר", "Fill groups with most likely scores"),
    "wi.reset": ("איפוס כל התרחישים", "Reset all scenarios"),
    "wi.matches": ("משחקים למילוי", "Matches to fill"),
    "wi.board": ("טבלת הדירוג — בתרחיש שלכם", "Standings — your scenario"),
    "wi.group_stage": ("שלב הבתים", "Group stage"),
    "wi.ko": ("נוק‑אאוט", "Knockout"),
    "wi.no_group": ("כל משחקי הבתים כבר שוחקו.", "All group matches already played."),
    "wi.ko_hint": (
        "משחקי נוק‑אאוט נפתחים אוטומטית ברגע ששתי הקבוצות בהם נקבעות — מלאו תוצאות "
        "בתים (או משחקי נוק‑אאוט מוקדמים יותר) כדי לפתוח אותם. שיבוץ מקומות השלישי "
        "דורש סיום כל הבתים.",
        "Knockout matches open once both teams are known — fill group (or earlier KO) "
        "results to unlock them. Third-place pairing needs all groups complete.",
    ),
    "wi.advance": ("עולה לשלב הבא:", "Advances:"),
    "wi.so": ("עלתה בפנדלים:", "Won on penalties:"),
    "wi.scorers": ("מבקיעים מההתערבות", "Scenario goal scorers"),
    "wi.sc.over": (
        "שויכו לקבוצה יותר שערים מאלה שהבקיעה — צמצמו",
        "More goals assigned to a team than it scored — reduce",
    ),
    "wi.count.none": ("לא הוזנו תוצאות עדיין", "No results entered yet"),
    "wi.count.n": ("{{n}} תוצאות בתרחיש", "{{n}} scenario results"),
    # What-If: live group standings
    "wi.groups_title": ("טבלאות הבתים — בתרחיש שלכם", "Group tables — your scenario"),
    "wi.groups_cap": (
        "הטבלאות מתעדכנות תוך כדי הזנת התוצאות. ירוק = מקום העפלה; חץ = שינוי מול המצב האמיתי.",
        "Tables update as you enter results. Green = qualifying spot; arrow = change vs the real standings.",
    ),
    "wi.gt.pos": ("#", "#"),
    "wi.gt.team": ("נבחרת", "Team"),
    "wi.gt.p": ("מ׳", "P"),
    "wi.gt.pts": ("נק׳", "Pts"),
    "wi.gt.gd": ("הפרש", "GD"),
    "wi.gt.third": ("שלישי מעפיל", "Best third (advances)"),
    # What-If: knockout bracket
    "wi.bracket_title": ("עץ הנוק‑אאוט — בתרחיש שלכם", "Knockout bracket — your scenario"),
    "wi.bracket_cap": (
        "מלאו תוצאות והעץ יתקדם אוטומטית. נבחרת שטרם נקבעה מוצגת כמציין (מנצחת/מקום בבית).",
        "Fill scores and the bracket advances automatically. Undetermined teams show as a placeholder (winner/seed).",
    ),
    "wi.tbd": ("טרם נקבע", "TBD"),
    "wi.ref.gw": ("מנצחת בית {{g}}", "Winner {{g}}"),
    "wi.ref.gr": ("סגנית בית {{g}}", "Runner-up {{g}}"),
    "wi.ref.third": ("מקום 3", "3rd place"),
    "wi.ref.wm": ("מנצחת מ׳ {{m}}", "Winner of M{{m}}"),
    "wi.ref.lm": ("מפסידה מ׳ {{m}}", "Loser of M{{m}}"),
    "wi.rc.1": ("1/16 גמר", "Round of 32"),
    "wi.rc.2": ("1/8 גמר", "Round of 16"),
    "wi.rc.3": ("רבע גמר", "Quarter-finals"),
    "wi.rc.4": ("חצי גמר", "Semi-finals"),
    "wi.rc.5": ("מקום 3", "Third place"),
    "wi.rc.6": ("גמר", "Final"),
    # Cheer
    "cheer.today": ("היום", "Today"),
    "cheer.tomorrow": ("מחר", "Tomorrow"),
    "cheer.filter": ("סינון משתתפים", "Filter entries"),
    "cheer.highlight": ("הדגשת משתתפים", "Highlight entries"),
    "cheer.clear": ("נקה הכל", "Clear all"),
    "cheer.unhighlight": ("בטל הכל", "Clear all"),
    "cheer.search": ("חיפוש שם…", "Search name…"),
    "cheer.top3": ("רק עם סיכוי לפודיום", "Only with podium chance"),
    "cheer.last": ("רק עם סיכוי למקום אחרון", "Only with last-place chance"),
    "cheer.prob": ("סיכוי", "Odds"),
    "cheer.neutral": ("לא מהותי", "Neutral"),
    "cheer.ko": ("נוקאאוט", "Knockout"),
    "cheer.pending": ("המשחק ייפתח כשייקבעו המעפילים מהשלב הקודם.",
                      "Match opens once qualifiers from the previous round are known."),
    "cheer.no_games": ("אין משחקים {{day}}.", "No games {{day}}."),
    "cheer.empty": ("— אין —", "— none —"),
    "cheer.il_time": ("השעות בשעון ישראל.", "Times in Israel time."),
    "cheer.title": ("את מי לעודד?", "Who to root for?"),
    "cheer.intro": (
        "לכל משחק — באיזו תוצאה כדאי <b>לכם</b> לתמוך? תחת כל תוצאה מופיעים המשתתפים "
        "שאותה תוצאה <b>משפרת להם את תוחלת הפרס</b>, והסכום שלצד השם הוא "
        "<b>השינוי הצפוי בתוחלת הזכייה</b> (₪) אם זו התוצאה. הדגישו את עצמכם ועודדו בהתאם.",
        "For each match — which outcome should <b>you</b> root for? Under each outcome, "
        "entries whose <b>expected prize improves</b> are listed; the amount is the "
        "<b>expected winnings change</b> (₪) if that result happens. Highlight yourself "
        "and cheer accordingly.",
    ),
    "cheer.note": (
        "ברירת המחדל: כל משתתף מופיע <b>בתוצאה הטובה לו ביותר</b>. סננו לטופס שלכם כדי לראות "
        "אותו בכל התוצאות עם השינוי הצפוי בכל אחת. מי שהמשחק כמעט לא משפיע עליו מופיע תחת "
        "<b>״לא מהותי״</b>. עוצמת הפס שלצד כל שם משקפת כמה המשחק <b>מהותי</b> עבורו ביחס לאחרים. "
        "במשחקי נוקאאוט יש שתי תוצאות (אין תיקו). ההשפעה מחושבת בכל משחק בנפרד (מתוך אותה סימולציה), "
        "ומתעדכנת לאחר כל משחק שמסתיים.",
        "By default each entry appears under its <b>best outcome</b>. Filter to your sheet to "
        "see yourself in every outcome with the expected change. Entries barely affected appear "
        "under <b>Neutral</b>. Bar width shows how much the match matters relative to others. "
        "Knockout matches have two outcomes (no draw). Impact is computed per match from the "
        "same simulation and updates after each finished match.",
    ),
    "cheer.draw": ("תיקו", "Draw"),
    "cheer.neutral_sum": (
        "לא מהותי ({{n}}) — המשחק כמעט לא משפיע",
        "Neutral ({{n}}) — match barely matters",
    ),
    # What If static copy
    "wi.intro": (
        "בחרו תוצאות למשחקים שטרם נגמרו וראו איך <b>טבלת הניקוד בפועל</b> של ההתערבות משתנה. "
        "אפשר למלא משחקי בתים, וגם <b>משחקי נוק‑אאוט</b> — כל משחק נפתח למילוי ברגע ששתי "
        "הקבוצות בו ידועות, והתוצאות שמזינים מתגלגלות הלאה בעץ המשחקים עד הגמר. מי שירצה — "
        "יכול גם לשייך מבקיעי שערים כדי להשפיע על בחירת \"מלך השערים\".",
        "Pick results for unfinished matches and see how the pool's <b>actual standings</b> "
        "change. Fill group matches and <b>knockout</b> games — each opens once both teams are "
        "known, and your inputs propagate through the bracket to the final. Optionally assign "
        "goal scorers to affect the top-scorer pick.",
    ),
    "wi.callout": (
        "<b>זו לא תחזית.</b> הטבלה כאן מציגה <b>רק את הניקוד</b> שהיה מתקבל לפי התוצאות "
        "שאתם ממציאים — בלי סיכויי זכייה ובלי סימולציה. הניקוד מחושב בדפדפן לפי חוקי ההגרלה. "
        "עמודת <b>שינוי</b> = תזוזת המיקום לעומת הדירוג הנוכחי, ובכל בחירה מוצג בסוגריים "
        "הניקוד שלה בתרחיש.",
        "<b>This is not a forecast.</b> The table shows <b>only the points</b> from the "
        "results you invent — no win odds, no simulation. Scoring follows pool rules in the "
        "browser. <b>Chg</b> = rank move vs current standings; picks show scenario points "
        "in parentheses.",
    ),
    # Stages
    "st.pick_teams": ("בחירת נבחרות", "Pick teams"),
    "st.search_team": ("חיפוש נבחרת…", "Search team…"),
    "st.dist_chart": ("גרף התפלגות", "Distribution chart"),
    "st.mode.exact": ("התפלגות (איפה ייעצרו)", "Distribution (where they exit)"),
    "st.mode.cum": ("מצטבר (להגיע לפחות ל…)", "Cumulative (reach at least…)"),
    "st.ko_path": ("מסלול הנוקאאוט הצפוי", "Expected knockout path"),
    "st.team": ("נבחרת", "Team"),
    "st.meet": ("נפגשים", "Meet"),
    "st.beat": ("מנצחים", "Beat"),
    "st.pass": ("מעבר", "Pass"),
    "st.other_opp": ("יריבות נוספות", "Other opponents"),
    "st.no_ko": ("לא צפויה להגיע לשלב הנוקאאוט.", "Not expected to reach knockout."),
    "st.title": ("עד לאן יגיעו?", "How far will they go?"),
    "st.intro": (
        "לכל נבחרת — ההסתברות (מתוך הסימולציה) <b>להגיע לכל שלב</b> בטורניר. "
        "המפה צבועה לפי ההסתברות <b>להגיע לפחות</b> לשלב. סננו לנבחרות מסוימות, "
        "ובחרו אותן גם לגרף ההשוואה למטה.",
        "Per team — simulated probability of <b>reaching each stage</b>. The heatmap is "
        "coloured by P(reach <b>at least</b> that stage). Filter teams and compare them "
        "in the chart below.",
    ),
    "st.hint.exact": (
        "כל נבחרת: באיזה שלב צפויה להיעצר (סכום הטורים = 100%).",
        "Each team: where they are expected to exit (columns sum to 100%).",
    ),
    "st.hint.cum": (
        "כל נבחרת: הסיכוי להגיע <b>לפחות</b> לשלב.",
        "Each team: P(reach <b>at least</b> that stage).",
    ),
    "st.hint.default6": (
        " מוצגות 6 הנבחרות החזקות — בחרו נבחרות להשוואה.",
        " Showing the 6 strongest teams — pick teams to compare.",
    ),
    "st.hint.cap": (
        " מוצגות {{n}} הראשונות מבין {{total}} שנבחרו.",
        " Showing first {{n}} of {{total}} selected.",
    ),
    "st.path.intro": (
        "לנבחרת שתבחרו — בכל שלב נוקאאוט: סיכוי <b>המעבר</b> הכולל, ומי היריבות הסבירות. "
        "לצד כל יריבה: <b>נפגשים</b> (כמה פעמים זו היריבה בשלב הזה) ו<b>מנצחים</b> "
        "(הסיכוי לנצח אותה אם נפגשים).",
        "For a selected team — at each knockout round: overall <b>advance</b> odds and likely "
        "opponents. Per opponent: <b>meet</b> (how often they face them) and <b>beat</b> "
        "(win probability if they meet).",
    ),
    "st.path.pick": (
        "בחרו נבחרת (למעלה) כדי לראות את מסלול הנוקאאוט הצפוי שלה ואת היריבות הסבירות בכל שלב.",
        "Pick a team (above) to see its expected knockout path and likely opponents per round.",
    ),
    "st.reach.r32": ("שלב 32", "Round of 32"),
    "st.reach.r16": ("שמינית", "Round of 16"),
    "st.reach.qf": ("רבע", "Quarter-finals"),
    "st.reach.sf": ("חצי", "Semi-finals"),
    "st.reach.final": ("גמר", "Final"),
    "st.reach.champ": ("אלופה", "Champion"),
    "st.exact.groups": ("בתים", "Groups"),
    "st.exact.runner": ("סגנית", "Runner-up"),
    "st.ko.r32": ("שלב 32", "Round of 32"),
    "st.ko.r16": ("שמינית", "Round of 16"),
    "st.ko.qf": ("רבע", "Quarter-finals"),
    "st.ko.sf": ("חצי", "Semi-finals"),
    "st.ko.final": ("גמר", "Final"),
    # Odds tab
    "od.title": ("הימורי השוק ודירוגי הכוח (ELO)", "Market odds & strength ratings (ELO)"),
    "od.intro": (
        "בכל הרצה הצינור מרענן את נתוני השוק ומחשב דירוג כוח (ELO) משוקלל. "
        "כאן רואים את הערכים <b>של ההרצה האחרונה</b>, ולמטה מעקב <b>לאורך זמן</b>.",
        "Each pipeline run refreshes market data and computes blended strength (ELO). "
        "Values from the <b>latest run</b> appear here, with <b>history</b> below.",
    ),
    "od.note": (
        "<b>שימו לב.</b> סיכויי זכייה בגביע (וערכי ה‑ELO המשוקללים) מתעדכנים "
        "מ<b>Kalshi</b> לפני כל הרצה מלאה. יחסי העפלה ונעל הזהב עדיין מהצילום "
        "שלפני הטורניר. מה שבאמת זז עם תוצאות אמת הוא ה<b>הסתברויות "
        "מהסימולציה</b> ופרמטרי ה<b>כיול</b> — ואותם מציגים גם לאורך זמן.",
        "<b>Note.</b> Title winner odds (and blended ELO) refresh from <b>Kalshi</b> "
        "before each full run. Advance and golden-boot odds are still the pre-tournament "
        "snapshot. What shifts with real results are <b>simulation probabilities</b> "
        "and <b>calibration</b> — tracked over time below.",
    ),
    "od.elo_title": ("דירוג כוח (ELO) — ההרצה האחרונה", "Strength (ELO) — latest run"),
    "od.elo_cap": ("משוקלל = שילוב דירוג בסיס והימורי השוק", "Blended = base rating + market odds"),
    "od.title_title": ("סיכויי תואר — שוק מול סימולציה", "Title odds — market vs simulation"),
    "od.title_cap": (
        "P(זכייה בגביע): השוק (הסתברות גלומה) מול הסימולציה שלנו",
        "P(World Cup winner): implied market vs our simulation",
    ),
    "od.adv_title": ("סיכויי העפלה (שוק)", "Advance odds (market)"),
    "od.adv_cap": ("P(העפלה לשלב הנוק‑אאוט) לפי השוק — 24 המובילות", "P(advance to knockout) — top 24"),
    "od.gb_title": ("נעל הזהב (שוק)", "Golden boot (market)"),
    "od.gb_cap": ("P(זכייה בנעל הזהב) לפי השוק — 15 המובילים", "P(golden boot) — top 15"),
    "od.hist_title": ("לאורך זמן", "Over time"),
    "od.hist_sub": (
        "מעקב אחר ההסתברויות מהסימולציה ופרמטרי הכיול לאורך ההרצות. "
        "ייאסף ויתעבה ככל שיצטברו עדכונים.",
        "Simulation probabilities and calibration parameters across runs — "
        "grows denser as updates accumulate.",
    ),
    "od.updated": ("עודכן", "Updated"),
    "od.spread": ("מקדם פיזור הכוח", "Strength spread"),
    "od.gb_scale": ("מקדם נעל הזהב", "Golden boot scale"),
    "od.th.team": ("נבחרת", "Team"),
    "od.th.player": ("שחקן", "Player"),
    "od.th.blended": ("משוקלל", "Blended"),
    "od.th.base": ("בסיס", "Base"),
    "od.th.market": ("שוק", "Market"),
    "od.th.p_win": ("P(זכייה)", "P(win)"),
    "od.th.sim": ("סימולציה", "Simulation"),
    "od.th.advance": ("העפלה", "Advance"),
    "od.th.odds": ("סיכוי", "Odds"),
    "od.hist.empty": (
        "עדיין אין מספיק נקודות מדידה לאורך זמן — ייאסף עם ההרצות הבאות.",
        "Not enough history yet — will accumulate with future runs.",
    ),
    "od.hist.by_run": ("לפי הרצה", "By run"),
    "od.hist.by_day": ("ממוצע יומי", "Daily average"),
    # Bar-chart-race overlays
    "race.btn.leaderboard": ("מרוץ הנקודות — 10 המובילים", "Points race — top 10"),
    "race.btn.p1": ("מרוץ סיכויי הזכייה — 10 המובילים", "Win-odds race — top 10"),
    "race.btn.title": ("מרוץ סיכויי התואר (סימולציה) — 10 המובילות",
                       "Title-odds race (simulation) — top 10"),
    "race.title.leaderboard": ("מרוץ הנקודות לאורך זמן — 10 המובילים",
                               "Points over time — top 10"),
    "race.title.p1": ("מרוץ סיכויי הזכייה במקום הראשון לאורך זמן — 10 המובילים",
                      "P(win the pool) over time — top 10"),
    "race.title.title": ("מרוץ סיכויי התואר (סימולציה) לאורך זמן — 10 המובילות",
                         "Title odds (simulation) over time — top 10"),
    "race.play": ("▶ הפעל", "▶ Play"),
    "race.pause": ("⏸ עצור", "⏸ Pause"),
    "race.foot": ("{{n}} צילומי מצב לאורך זמן. גרור את הסרגל כדי לדלג.",
                  "{{n}} snapshots over time. Drag the slider to scrub."),
    "od.chart.title_sim": ("סיכויי תואר מהסימולציה (6 המובילות)", "Title odds from simulation (top 6)"),
    "od.chart.title_cal": ("פרמטרי כיול", "Calibration parameters"),
    "od.chart.spread_short": ("מקדם פיזור", "Strength spread"),
    "od.chart.gb_short": ("מקדם נעל זהב", "Golden boot scale"),
    "od.kalshi_title": ("Kalshi — סיכויי זכייה לאורך זמן", "Kalshi — title odds over time"),
    "od.kalshi_cap": (
        "מחיר YES יומי בשוק Kalshi (8 המובילות). מקור: Kalshi API.",
        "Daily YES price on Kalshi for the top 8 teams. Source: Kalshi API.",
    ),
    "od.kalshi_link": ("פתח ב‑Kalshi", "Open on Kalshi"),
    "od.kalshi_empty": ("אין עדיין היסטוריית Kalshi — תופיע אחרי הרצה מלאה.", "No Kalshi history yet — appears after a full pipeline run."),
    "od.elop_title": ("דירוג הכוח (ELO) — בסיס → משוקלל → חי", "Strength prior (ELO) — baseline → weighted → live"),
    "od.elop_cap": (
        "ה‑ELO של המודל מתעדכן <b>פעם בכל סבב</b> (קבוצות: אחרי כל מחזור; נוק‑אאוט: אחרי כל שלב), "
        "בשקלול 65% לערך הקודם ו‑35% ל‑ELO החי מ‑eloratings.net. כך הכוח \"זוחל\" בהדרגה לעבר המציאות.",
        "The model's ELO updates <b>once per round</b> (group: after each matchday; knockout: after each round), "
        "weighting 65% prior and 35% live eloratings.net. The prior thus glides gradually toward reality.",
    ),
    "od.elop.base": ("בסיס (30.5)", "Baseline (May 30)"),
    "od.elop.weighted": ("משוקלל", "Weighted"),
    "od.elop.live": ("חי", "Live"),
    "od.elop.delta": ("Δ מהבסיס", "Δ vs baseline"),
    "od.elop.round": ("עודכן לאחרונה בסבב", "Last updated at round"),
    "od.elop.empty": ("טרם בוצע עדכון ELO מתוזמן.", "No scheduled ELO update yet."),
}


def i18n_js(team_he: dict, player_he: dict) -> str:
    """Bootstrap I18N on window — must run before other page scripts."""
    he = {k: v[0] for k, v in STRINGS.items()}
    en = {k: v[1] for k, v in STRINGS.items()}
    payload = json.dumps({"he": he, "en": en, "teamHe": team_he, "playerHe": player_he},
                         ensure_ascii=False)
    return f"""
window.I18N = (function(){{
  const D = {payload};
  const LS = 'wc2026-lang';
  let lang = localStorage.getItem(LS) || 'he';
  if (lang !== 'he' && lang !== 'en') lang = 'he';

  function t(k) {{ return (D[lang] && D[lang][k]) || (D.he[k]) || k; }}
  function fmt(k, vars) {{
    let s = t(k);
    if (vars) for (const p in vars) s = s.split('{{{{'+p+'}}}}').join(String(vars[p]));
    return s;
  }}
  function team(en) {{ return lang==='he' ? (D.teamHe[en]||en) : en; }}
  function player(en) {{ return lang==='he' ? (D.playerHe[en]||en) : en; }}

  function applyStatic() {{
    document.querySelectorAll('[data-i18n]').forEach(el => {{
      const k = el.getAttribute('data-i18n');
      const v = t(k);
      if (el.hasAttribute('data-i18n-html')) el.innerHTML = v;
      else el.textContent = v;
    }});
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {{
      el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    }});
    document.querySelectorAll('[data-i18n-title]').forEach(el => {{
      el.title = t(el.getAttribute('data-i18n-title'));
    }});
    document.querySelectorAll('[data-i18n-fmt]').forEach(el => {{
      let vars = {{}};
      try {{ vars = JSON.parse(el.getAttribute('data-i18n-vars')||'{{}}'); }} catch(e) {{}}
      const sk = el.getAttribute('data-stage-key');
      if (sk) vars.stage = t(sk);
      const html = fmt(el.getAttribute('data-i18n-fmt'), vars);
      if (el.hasAttribute('data-i18n-html')) el.innerHTML = html;
      else el.textContent = html;
    }});
    document.querySelectorAll('.i18nte').forEach(el => {{
      const en = el.getAttribute('data-en');
      if (!en) return;
      el.textContent = team(en);
    }});
    document.querySelectorAll('.i18npl').forEach(el => {{
      const en = el.getAttribute('data-en');
      if (!en) return;
      el.textContent = player(en);
    }});
    const btn = document.getElementById('langToggle');
    if (btn) btn.textContent = t('lang.toggle');
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === 'he' ? 'rtl' : 'ltr';
    document.title = t('page.title');
    const hero = document.querySelector('.herologo');
    if (hero) hero.alt = t('hero.alt');
  }}

  function setLang(l) {{
    if (l !== 'he' && l !== 'en') return;
    lang = l;
    localStorage.setItem(LS, l);
    applyStatic();
    document.dispatchEvent(new CustomEvent('langchange', {{detail:{{lang:l}}}}));
  }}

  document.addEventListener('DOMContentLoaded', () => {{
    applyStatic();
    const btn = document.getElementById('langToggle');
    if (btn) btn.addEventListener('click', () => setLang(lang === 'he' ? 'en' : 'he'));
  }});

  return {{ t, fmt, team, player, setLang, get lang(){{ return lang; }} }};
}})();
"""


def i18n_css() -> str:
    return """
  /* language toggle */
  nav.tabs .langtog{margin-inline-start:auto; font-size:.88rem; min-width:72px;}
  /* LTR overrides when English is active */
  html[dir=ltr] thead th{text-align:left;}
  html[dir=ltr] table.standtbl td.nm,
  html[dir=ltr] table.witbl td.nm,
  html[dir=ltr] table.gtbl td.gt,
  html[dir=ltr] table.gtbl th:first-child{text-align:left;}
  html[dir=ltr] table.cmtbl th.nm,
  html[dir=ltr] table.cmtbl td.nm{right:auto;left:0;box-shadow:6px 0 6px -6px rgba(0,0,0,.12);}
  html[dir=ltr] .witeam.h{text-align:right;}
  html[dir=ltr] .witeam.a{text-align:left;}
  html[dir=ltr] .bar-label{text-align:right;}
  html[dir=ltr] .bar-val{text-align:left;}
  html[dir=ltr] .callout{border-right:0;border-left:4px solid var(--blue);border-radius:0 8px 8px 0;}
  html[dir=ltr] table.gtbl tr.qual td.gt{border-right:0;border-left-color:var(--green);padding-right:3px;padding-left:7px;}
  html[dir=ltr] table.ltbl tr.hit td.nm{box-shadow:inset -3px 0 0 var(--green);}
  html[dir=ltr] table.standtbl tr.hit td.nm{box-shadow:inset -3px 0 0 var(--green);}
"""
