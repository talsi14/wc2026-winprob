"""The four selection tiers (\u05d3\u05e8\u05d2\u05d9\u05dd), transcribed verbatim from the bet PDF.

Each participant picks one team from each tier. Tier membership also drives the
advancement bonuses (Tier C/D get R32 bonuses; see config.ScoringRules).
"""
from __future__ import annotations

# Tier A (\u05d3\u05e8\u05d2 \u05d0') - the elite contenders.
TIER_A = [
    "England", "Argentina", "Belgium", "Brazil", "Germany",
    "Netherlands", "Spain", "Portugal", "France",
]

# Tier B (\u05d3\u05e8\u05d2 \u05d1').
TIER_B = [
    "Austria", "Uruguay", "Ecuador", "United States", "Turkey", "Japan",
    "Morocco", "Mexico", "Norway", "Czech Republic", "Colombia", "Canada",
    "Croatia", "Switzerland",
]

# Tier C (\u05d3\u05e8\u05d2 \u05d2').
TIER_C = [
    "Australia", "Iran", "Algeria", "Bosnia and Herzegovina", "Ghana",
    "South Korea", "Ivory Coast", "Egypt", "Senegal", "Scotland",
    "Saudi Arabia", "Paraguay", "Sweden",
]

# Tier D (\u05d3\u05e8\u05d2 \u05d3').
TIER_D = [
    "Uzbekistan", "South Africa", "Haiti", "Jordan", "Cape Verde",
    "New Zealand", "Iraq", "Panama", "Qatar", "DR Congo", "Curaçao", "Tunisia",
]

TIERS: dict[str, list[str]] = {"A": TIER_A, "B": TIER_B, "C": TIER_C, "D": TIER_D}

# team -> tier letter
TEAM_TIER: dict[str, str] = {t: k for k, teams in TIERS.items() for t in teams}

# Sanity: exactly the 48 finalists, partitioned.
assert sum(len(v) for v in TIERS.values()) == 48
assert len(TEAM_TIER) == 48
