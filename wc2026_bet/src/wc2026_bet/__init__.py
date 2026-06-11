"""World Cup 2026 friends-bet optimizer.

A self-contained pipeline that:
  1. (Stage 1) collects + persists all source data into ``data/processed``.
  2. (Stage 2) fits a Dixon-Coles match model, runs a Monte Carlo simulation of
     the tournament, scores every possible bet selection against the bet rules,
     and optimizes two entries (a "safe" and a "risky" one) against a modelled
     field of opponents.

Stage 2 never touches the network; it reads only ``data/processed``.
"""

__version__ = "1.0.0"
