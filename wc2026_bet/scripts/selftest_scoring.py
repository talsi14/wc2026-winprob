"""Self-test for the scoring engine: vectorized == scalar, plus a hand example."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc2026_bet.config import DEFAULT_RULES
from wc2026_bet.scoring import (
    TIER_CODE, Entry, score_entry, team_points_scalar,
    tier_total_points,
)


def test_vectorized_matches_scalar() -> None:
    rng = np.random.default_rng(0)
    S, T = 200, 6
    tiers = ["A", "B", "C", "D", "C", "D"]
    tier_code = np.array([TIER_CODE[t] for t in tiers])

    reg_wins = rng.integers(0, 7, (S, T))
    group_draws = rng.integers(0, 4, (S, T))
    reg_losses = rng.integers(0, 4, (S, T))
    pen_wins = rng.integers(0, 3, (S, T))
    pen_losses = rng.integers(0, 3, (S, T))
    group_finish = rng.integers(1, 5, (S, T))
    advanced = rng.random((S, T)) < 0.6
    made_final = rng.random((S, T)) < 0.1
    won_cup = made_final & (rng.random((S, T)) < 0.5)

    O = dict(
        reg_wins=reg_wins, group_draws=group_draws, reg_losses=reg_losses,
        pen_wins=pen_wins, pen_losses=pen_losses, group_finish=group_finish,
        advanced=advanced, made_final=made_final, won_cup=won_cup,
    )
    vec = tier_total_points(O, tier_code, DEFAULT_RULES)

    for s in range(S):
        for t in range(T):
            stats = dict(
                reg_wins=int(reg_wins[s, t]), group_draws=int(group_draws[s, t]),
                reg_losses=int(reg_losses[s, t]), pen_wins=int(pen_wins[s, t]),
                pen_losses=int(pen_losses[s, t]), group_finish=int(group_finish[s, t]),
                advanced=bool(advanced[s, t]), made_final=bool(made_final[s, t]),
                won_cup=bool(won_cup[s, t]),
            )
            exp = team_points_scalar(stats, tiers[t], DEFAULT_RULES)
            assert abs(exp - vec[s, t]) < 1e-9, (s, t, exp, vec[s, t])
    print("OK  vectorized tier points == scalar reference  (%d cells)" % (S * T))


def test_hand_example() -> None:
    """A champion Tier-A team: 6 reg wins, 1 group draw, reached & won final."""
    stats = dict(reg_wins=6, group_draws=1, reg_losses=0, pen_wins=0,
                 pen_losses=0, group_finish=1, advanced=True,
                 made_final=True, won_cup=True)
    pts = team_points_scalar(stats, "A", DEFAULT_RULES)
    assert pts == 3 * 6 + 1 + 2 + 1, pts          # 22
    print("OK  champion tier-A team scores", pts)

    # Tier D team sneaking through as 3rd place, loses R32 on penalties.
    statsd = dict(reg_wins=0, group_draws=1, reg_losses=2, pen_wins=0,
                  pen_losses=1, group_finish=3, advanced=True,
                  made_final=False, won_cup=False)
    ptsd = team_points_scalar(statsd, "D", DEFAULT_RULES)
    # 1 (draw) + 1 (pen loss) + 1 (tier-D third bonus) = 3
    assert ptsd == 3, ptsd
    print("OK  tier-D 3rd-place team scores", ptsd)


def test_full_entry() -> None:
    entry = Entry("Germany", "Ecuador", "Egypt", "Haiti",
                  "Spain", "Uzbekistan", "Vinícius Júnior")
    team_tier = {"Germany": "A", "Ecuador": "B", "Egypt": "C", "Haiti": "D",
                 "Spain": "A", "Uzbekistan": "D"}
    team_stats = {
        "Germany": dict(reg_wins=6, group_draws=1, reg_losses=0, pen_wins=0,
                        pen_losses=0, group_finish=1, advanced=True,
                        made_final=True, won_cup=True),
        "Ecuador": dict(reg_wins=1, group_draws=0, reg_losses=3, pen_wins=0,
                        pen_losses=0, group_finish=3, advanced=True,
                        made_final=False, won_cup=False),
        "Egypt": dict(reg_wins=2, group_draws=1, reg_losses=1, pen_wins=0,
                      pen_losses=0, group_finish=1, advanced=True,
                      made_final=False, won_cup=False),
        "Haiti": dict(reg_wins=0, group_draws=1, reg_losses=3, pen_wins=0,
                      pen_losses=0, group_finish=3, advanced=True,
                      made_final=False, won_cup=False),
    }
    bd = score_entry(
        entry, team_stats,
        team_gf={"Spain": 12}, team_ga={"Uzbekistan": 8},
        player_goals={"Vinícius Júnior": 5}, golden_boot="Harry Kane",
        team_tier=team_tier, rules=DEFAULT_RULES,
    )
    # 22 + 3 + 8 + 2 + 6 + 4 + 2.5 = 47.5
    assert abs(bd["total"] - 47.5) < 1e-9, bd
    print("OK  full example entry total =", bd["total"], bd)


if __name__ == "__main__":
    test_vectorized_matches_scalar()
    test_hand_example()
    test_full_entry()
    print("\nAll scoring self-tests passed.")
