"""Stage-2 data loaders. Reads ONLY from data/processed (no network)."""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import DATA_PROCESSED
from .names import CANONICAL_TEAMS


@dataclass
class Dataset:
    teams: pd.DataFrame            # 48 finalists: team, slug, confederation, host, tier, group, elo
    groups: dict[str, list[str]]  # group letter -> [team, ...]
    group_matches: pd.DataFrame   # 72 group-stage fixtures
    bracket: list[dict]           # 32 knockout matches with slot refs
    results: pd.DataFrame         # historical internationals (weighted)
    players: pd.DataFrame         # candidate golden-boot scorers
    market: pd.DataFrame          # Opta title-prob anchors
    market_advance: pd.DataFrame  # de-vigged market P(advance to R32), 48 teams
    team_index: dict[str, int]    # finalist team -> 0..47
    team_list: list[str]          # finalists in index order


def load_dataset() -> Dataset:
    p = DATA_PROCESSED
    teams = pd.read_csv(p / "teams.csv")
    groups_df = pd.read_csv(p / "groups.csv")
    group_matches = pd.read_csv(p / "schedule_groups.csv")
    bracket = json.loads((p / "bracket.json").read_text())
    results = pd.read_csv(p / "results.csv")
    players = pd.read_csv(p / "players.csv")
    market = pd.read_csv(p / "market_title_odds.csv")
    market_advance = pd.read_csv(p / "market_advance.csv")

    groups = {g: list(sub.sort_values("pos")["team"])
              for g, sub in groups_df.groupby("group")}

    team_list = list(teams["team"])
    assert set(team_list) == set(CANONICAL_TEAMS)
    team_index = {t: i for i, t in enumerate(team_list)}

    return Dataset(
        teams=teams, groups=groups, group_matches=group_matches,
        bracket=bracket, results=results, players=players, market=market,
        market_advance=market_advance,
        team_index=team_index, team_list=team_list,
    )


def load_calibration() -> dict:
    """Return the saved calibration (strength spread, gb scale, ...) or defaults."""
    f = DATA_PROCESSED / "calibration.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"strength_spread": 1.0, "golden_boot_scale": 1.0,
            "strength_offsets": {}, "player_share_factor": {}}


def apply_share_factors(ds: Dataset, factors: dict) -> None:
    """In-place: multiply each candidate scorer's blended_share by its calibrated
    Golden-Boot factor (so the simulator's player goals follow the market board).
    """
    if not factors:
        return
    ds.players["blended_share"] = [
        float(min(0.92, sh * factors.get(name, 1.0)))
        for name, sh in zip(ds.players["scorer"], ds.players["blended_share"])
    ]
