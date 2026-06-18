"""Live eloratings.net refresh with a round-scheduled EMA smoother.

eloratings.net publishes World Football Elo for every national team and updates
it after every match (World Cup games carry the highest K-factor, so ratings
move fast mid-tournament). To let tournament form bleed into the model's
strength prior *gradually* - rather than letting a single K=60 result jerk the
prior around - we keep a running ``weighted`` Elo and step it toward the live
value **once per tournament round** (not once per pipeline run):

    weighted_new[t] = (1 - alpha) * weighted_prev[t] + alpha * live[t]   (alpha=0.35)

Update schedule (8 points): after each of the three group rounds (24 / 48 / 72
games played) and after each knockout round (R32, R16, QF, SF, Final). The step
fires only when a new round boundary is crossed; repeated runs within the same
round reuse the stored value (idempotent). If rounds were missed between runs we
apply the corresponding number of catch-up steps in closed form.

Because updates are rarer than runs, each one carries more weight (35% live /
65% prior). The running value persists in data/history/eloratings_weighted.json
(committed), seeded from the pre-tournament May-30 baseline.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from wc2026_bet.config import DATA_LIVE
from wc2026_bet.names import CANONICAL_TEAMS

import collect_data as cd  # noqa: E402  (same scripts dir)

ELO_TSV_URL = "https://www.eloratings.net/World.tsv"
WEIGHTED_FILE = (Path(__file__).resolve().parents[1]
                 / "data" / "history" / "eloratings_weighted.json")
# Weight on the live Elo at each scheduled (per-round) update; the running
# weighted value keeps (1 - alpha). 0.35 => last weighted Elo retains 65%.
DEFAULT_ALPHA = 0.35
UA = "Mozilla/5.0 (wc2026-bet eloratings refresh)"

# Ordered update points. Group rounds complete at 24 / 48 / 72 games; knockout
# rounds at cumulative KO-game counts R32=16, R16=24, QF=28, SF=30, Final=32.
GROUP_ROUND_THRESHOLDS = (24, 48, 72)
KO_ROUND_THRESHOLDS = (16, 24, 28, 30, 32)
ROUND_LABELS = ["group-r1", "group-r2", "group-r3",
                "ko-r32", "ko-r16", "ko-qf", "ko-sf", "ko-final"]


def completed_rounds(n_group: int, n_ko: int) -> int:
    """How many scheduled update points have been passed (0..8)."""
    c = sum(1 for t in GROUP_ROUND_THRESHOLDS if n_group >= t)
    c += sum(1 for t in KO_ROUND_THRESHOLDS if n_ko >= t)
    return c


def _read_state_counts() -> tuple[int, int]:
    """(n_group_played, n_ko_played) from the latest collected state, or (0,0)."""
    f = DATA_LIVE / "state_latest.json"
    if not f.exists():
        return 0, 0
    try:
        d = json.loads(f.read_text())
        return int(d.get("n_group_played", 0)), int(d.get("n_ko_played", 0))
    except (json.JSONDecodeError, ValueError):
        return 0, 0

# Canonical finalist name -> eloratings.net team code (ISO2, with EN/SC for the
# home nations). Verified against the live World.tsv at integration time; any
# code that fails to resolve falls back to the static May-30 baseline.
FINALIST_CODE: dict[str, str] = {
    "United States": "US", "Canada": "CA", "Mexico": "MX", "Panama": "PA",
    "Curaçao": "CW", "Haiti": "HT", "Argentina": "AR", "Brazil": "BR",
    "Uruguay": "UY", "Colombia": "CO", "Paraguay": "PY", "Ecuador": "EC",
    "France": "FR", "England": "EN", "Spain": "ES", "Germany": "DE",
    "Portugal": "PT", "Netherlands": "NL", "Belgium": "BE", "Croatia": "HR",
    "Switzerland": "CH", "Austria": "AT", "Norway": "NO", "Scotland": "SC",
    "Sweden": "SE", "Turkey": "TR", "Czech Republic": "CZ",
    "Bosnia and Herzegovina": "BA", "Morocco": "MA", "Senegal": "SN",
    "Egypt": "EG", "Algeria": "DZ", "Tunisia": "TN", "Ghana": "GH",
    "Ivory Coast": "CI", "Cape Verde": "CV", "South Africa": "ZA",
    "DR Congo": "CD", "Japan": "JP", "South Korea": "KR", "Iran": "IR",
    "Australia": "AU", "Saudi Arabia": "SA", "Qatar": "QA", "Jordan": "JO",
    "Uzbekistan": "UZ", "Iraq": "IQ", "New Zealand": "NZ",
}
assert set(FINALIST_CODE) == set(CANONICAL_TEAMS), (
    set(CANONICAL_TEAMS) ^ set(FINALIST_CODE))


def fetch_live_eloratings() -> dict[str, float]:
    """Fetch eloratings.net World.tsv -> {canonical finalist name: live Elo}.

    Missing codes are simply omitted (caller falls back to the baseline).
    """
    req = urllib.request.Request(ELO_TSV_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    by_code: dict[str, float] = {}
    for line in body.splitlines():
        f = line.split("\t")
        if len(f) > 4:
            try:
                by_code[f[2]] = float(f[3])
            except ValueError:
                continue
    out: dict[str, float] = {}
    for team, code in FINALIST_CODE.items():
        if code in by_code:
            out[team] = by_code[code]
    return out


def _load_weighted() -> dict | None:
    if WEIGHTED_FILE.exists():
        try:
            return json.loads(WEIGHTED_FILE.read_text())
        except json.JSONDecodeError:
            return None
    return None


def update_weighted_eloratings(alpha: float = DEFAULT_ALPHA) -> dict[str, float]:
    """Step the running weighted Elo toward live, once per completed round.

    Reads the current (n_group_played, n_ko_played) from state_latest.json,
    compares the number of completed rounds to how many we've already applied,
    and - only if a new round boundary was crossed - blends toward the freshly
    fetched live Elo (one EMA step per newly completed round, in closed form).
    Within the same round the stored value is reused unchanged.

    Returns {canonical name: weighted Elo} for all 48 finalists; persists the
    running value (+ a per-update history tail) to WEIGHTED_FILE.
    """
    baseline = dict(cd.ELORATINGS_2026)
    store = _load_weighted()
    prev = {t: float((store or {}).get("weighted", {}).get(t, baseline[t]))
            for t in CANONICAL_TEAMS}
    applied = int((store or {}).get("applied_rounds", 0))

    n_group, n_ko = _read_state_counts()
    target_rounds = completed_rounds(n_group, n_ko)
    steps = target_rounds - applied
    label = ROUND_LABELS[target_rounds - 1] if target_rounds >= 1 else "pre"

    if steps <= 0:
        # No new round since the last update - hold the prior weighted value.
        print(f"  eloratings: held (no new round; at {label}, "
              f"group {n_group}/72, ko {n_ko}). {applied} update(s) applied.")
        return prev

    try:
        live = fetch_live_eloratings()
    except Exception as e:  # noqa: BLE001
        print(f"  eloratings: live fetch failed ({str(e)[:120]}); holding prior.")
        return prev

    # k EMA steps toward the same live value == single blend with factor (1-a)^k.
    factor = (1.0 - alpha) ** steps
    weighted: dict[str, float] = {}
    n_live = 0
    for t in CANONICAL_TEAMS:
        if t in live:
            weighted[t] = round(factor * prev[t] + (1 - factor) * live[t], 1)
            n_live += 1
        else:
            weighted[t] = round(prev[t], 1)

    top_now = sorted(weighted, key=lambda t: -weighted[t])[:10]
    history = (store or {}).get("history", [])
    history.append({"at": datetime.now(timezone.utc).isoformat(),
                    "round": label, "steps": steps, "alpha": alpha,
                    "n_group": n_group, "n_ko": n_ko,
                    "weighted_top": {t: weighted[t] for t in top_now},
                    "live_top": {t: live[t] for t in top_now if t in live}})
    rec = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "alpha": alpha,
        "applied_rounds": target_rounds,
        "round": label,
        "n_live_matched": n_live,
        "baseline": {t: baseline[t] for t in CANONICAL_TEAMS},
        "weighted": weighted,
        "last_live": {t: live[t] for t in sorted(live, key=lambda x: -live[x])},
        "history": history[-32:],
    }
    WEIGHTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTED_FILE.write_text(json.dumps(rec, indent=2, ensure_ascii=False))

    top = sorted(weighted, key=lambda t: -weighted[t])[:3]
    summary = ", ".join(f"{t} {weighted[t]:.0f}" for t in top)
    print(f"  eloratings: UPDATED at {label} (+{steps} step(s), alpha={alpha}, "
          f"{n_live}/48 live); weighted top: {summary}")
    return weighted
