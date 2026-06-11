"""Stage 1b - turn the historical friend-pool entries into a behavior model.

Reads the transcribed past entries (old_bets_data/entries.csv: Euro 2024 +
Qatar 2022, 3-tier / 6-pick) and distills *transferable* pool behavior that we
can re-apply to the 2026 (4-tier / 7-pick) field:

  * favorite-chase concentration per slot type, expressed as the average
    ownership share of the single most-owned candidate (the "top share").
    This is format-agnostic: it measures how hard the pool piles onto the
    chalk, independent of which teams are in which tier.
  * doubling/stacking rate: how often the scoring-team pick is one of the
    entry's own tier teams.
  * Golden-Boot chalk: top share of the most-owned top-scorer pick.

The 2026 field model (field.py) then reproduces these concentrations over the
2026 candidates (ranked by market strength / expected goals / Golden-Boot odds),
instead of the old synthetic raw-EV "savvy" archetype that over-piled on Spain.

Output: data/processed/pool_behavior.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wc2026_bet.config import DATA_PROCESSED

ENTRIES = Path(__file__).resolve().parents[1] / "old_bets_data" / "entries.csv"


def top_share(series: pd.Series) -> float:
    c = Counter(series)
    n = len(series)
    return c.most_common(1)[0][1] / n


def main() -> None:
    df = pd.read_csv(ENTRIES)
    tours = sorted(df["tournament"].unique())

    tier_shares, scoring_shares, conceding_shares, gb_shares, doubling = [], [], [], [], []
    per_tour = {}
    for t in tours:
        sub = df[df["tournament"] == t]
        tA, tB, tC = top_share(sub["tierA"]), top_share(sub["tierB"]), top_share(sub["tierC"])
        sc, co = top_share(sub["scoring"]), top_share(sub["conceding"])
        gb = top_share(sub["top_scorer"])
        dbl = sum(r.scoring in (r.tierA, r.tierB, r.tierC) for r in sub.itertuples()) / len(sub)
        tier_shares += [tA, tB, tC]
        scoring_shares.append(sc); conceding_shares.append(co); gb_shares.append(gb)
        doubling.append(dbl)
        per_tour[t] = {
            "n_entries": int(len(sub)),
            "tierA_top_share": round(tA, 3), "tierB_top_share": round(tB, 3),
            "tierC_top_share": round(tC, 3),
            "scoring_top_share": round(sc, 3), "conceding_top_share": round(co, 3),
            "golden_boot_top_share": round(gb, 3), "doubling_rate": round(dbl, 3),
            "tierA_counts": dict(Counter(sub["tierA"]).most_common()),
            "top_scorer_counts": dict(Counter(sub["top_scorer"]).most_common()),
        }

    mean = lambda xs: float(sum(xs) / len(xs))
    behavior = {
        "source": "old_bets_data/entries.csv (Euro 2024 + Qatar 2022)",
        "n_source_entries": int(len(df)),
        # concentration targets (avg ownership of the single most-owned candidate)
        "tier_top_share": round(mean(tier_shares), 3),
        "scoring_top_share": round(mean(scoring_shares), 3),
        "conceding_top_share": round(mean(conceding_shares), 3),
        "top_scorer_top_share": round(mean(gb_shares), 3),
        "doubling_rate": round(mean(doubling), 3),
        "per_tournament": per_tour,
        "note": ("Pool is favorite-chasing, not EV-optimizing: ownership concentrates "
                 "on the strongest/most-famous candidate in each slot. The 2026 field "
                 "reproduces these top-shares over market-ranked candidates."),
    }
    out = DATA_PROCESSED / "pool_behavior.json"
    out.write_text(json.dumps(behavior, indent=2, ensure_ascii=False))
    print("Wrote", out)
    for k in ["tier_top_share", "scoring_top_share", "conceding_top_share",
              "top_scorer_top_share", "doubling_rate"]:
        print(f"  {k:<22} {behavior[k]:.3f}")


if __name__ == "__main__":
    main()
