"""Canonical team names + robust normalization / alias resolution.

The 48 finalists use one canonical spelling throughout the pipeline (matching
the official FIFA draw). Historical-results and Elo sources use many variants,
so we normalize aggressively and keep an explicit alias table for the tricky
cases (e.g. "Congo DR" -> DR Congo, while plain "Congo" is a *different*
country and must NOT match).
"""
from __future__ import annotations

import re
import unicodedata

# The 48 canonical names (must match the official draw spelling).
CANONICAL_TEAMS: list[str] = [
    "United States", "Canada", "Mexico", "Panama", "Curaçao", "Haiti",
    "Argentina", "Brazil", "Uruguay", "Colombia", "Paraguay", "Ecuador",
    "France", "England", "Spain", "Germany", "Portugal", "Netherlands",
    "Belgium", "Croatia", "Switzerland", "Austria", "Norway", "Scotland",
    "Sweden", "Turkey", "Czech Republic", "Bosnia and Herzegovina",
    "Morocco", "Senegal", "Egypt", "Algeria", "Tunisia", "Ghana",
    "Ivory Coast", "Cape Verde", "South Africa", "DR Congo",
    "Japan", "South Korea", "Iran", "Australia", "Saudi Arabia", "Qatar",
    "Jordan", "Uzbekistan", "Iraq", "New Zealand",
]
assert len(CANONICAL_TEAMS) == 48


def _norm(s: str) -> str:
    """Lowercase, strip accents, '&'->'and', collapse non-letters to spaces."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def slug(name: str) -> str:
    """Canonical-name -> hyphen slug (e.g. 'DR Congo' -> 'dr-congo')."""
    return _norm(name).replace(" ", "-")


# Normalized-variant -> canonical name. Only list forms that differ from a
# straightforward normalization of the canonical name.
_ALIASES_RAW = {
    "usa": "United States",
    "united states of america": "United States",
    "us": "United States",
    "turkiye": "Turkey",
    "czechia": "Czech Republic",
    "bosnia herzegovina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "cape verde islands": "Cape Verde",
    "cabo verde": "Cape Verde",
    "congo dr": "DR Congo",
    "dr congo": "DR Congo",
    "democratic republic of the congo": "DR Congo",
    "korea republic": "South Korea",
    "republic of korea": "South Korea",
    "korea dpr": "North Korea",        # explicitly NOT South Korea
    "ir iran": "Iran",
    "cote d ivoire": "Ivory Coast",
    "ivory coast": "Ivory Coast",
    "the netherlands": "Netherlands",
}

# Build the lookup: canonical self-maps + aliases.
_CANON_BY_NORM: dict[str, str] = {_norm(t): t for t in CANONICAL_TEAMS}
_ALIASES: dict[str, str] = {_norm(k): v for k, v in _ALIASES_RAW.items()}


def resolve(name: str) -> str | None:
    """Map any source spelling to a canonical finalist name, or None.

    Returns None for teams that are not among the 48 finalists (e.g. opponents
    in historical friendlies like 'Suriname' or 'Congo'). Callers fitting on
    historical data still *use* those rows (they inform the model), but only
    finalist ratings are exported.
    """
    n = _norm(name)
    if n in _ALIASES:
        return _ALIASES[n]
    if n in _CANON_BY_NORM:
        return _CANON_BY_NORM[n]
    return None


def resolve_any(name: str) -> str:
    """Like resolve() but returns a stable label for non-finalists too.

    Non-finalists keep their normalized name so the fit can still use the row.
    """
    r = resolve(name)
    return r if r is not None else _norm(name)


# --------------------------------------------------------------------------- #
# Hebrew alias resolution (friends-pool leaderboard tokens -> canonical)
# --------------------------------------------------------------------------- #
import json as _json
from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1)
def _he_aliases() -> dict:
    from .config import DATA_PROCESSED
    f = DATA_PROCESSED / "he_aliases.json"
    if not f.exists():
        return {"teams": {}, "players": {}}
    d = _json.loads(f.read_text())
    return {"teams": d.get("teams", {}), "players": d.get("players", {})}


def _he_norm(s: str) -> str:
    """Normalize a Hebrew token: trim, collapse whitespace, unify geresh/quote
    marks so '\u05e6\u05f3\u05db\u05d9\u05d4' and '\u05e6\'\u05db\u05d9\u05d4' match."""
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\u05f3", "'").replace("\u2019", "'").replace("\u05f4", '"').replace("\u201d", '"')
    return s


def resolve_he_team(token: str) -> str | None:
    """Hebrew team token -> canonical finalist name (or None if unmapped)."""
    aliases = _he_aliases()["teams"]
    norm = {_he_norm(k): v for k, v in aliases.items()}
    return norm.get(_he_norm(token))


def resolve_he_player(token: str) -> str | None:
    """Hebrew player token -> canonical scorer name (or None if unmapped)."""
    aliases = _he_aliases()["players"]
    norm = {_he_norm(k): v for k, v in aliases.items()}
    return norm.get(_he_norm(token))
