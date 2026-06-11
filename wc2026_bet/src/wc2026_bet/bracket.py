"""Knockout-bracket helpers.

Parses the real 2026 bracket (data/processed/bracket.json) and precomputes the
assignment of the eight qualifying third-placed teams to the eight "3rd ..."
slots in the Round of 32. Each third-slot lists five eligible groups; for any
set of 8 advancing groups we find a perfect matching (group -> slot) respecting
eligibility. This mirrors FIFA's predetermined best-thirds table (any valid
eligibility-respecting matching is a faithful representation).
"""
from __future__ import annotations

from itertools import combinations

from .config import GROUPS


def third_slots(bracket: list[dict]) -> list[dict]:
    """The 8 R32 third-place slots: {match, side, eligible:set}, in match order."""
    slots = []
    for m in bracket:
        if m["round_code"] != 1:
            continue
        for side in ("home_ref", "away_ref"):
            ref = m[side]
            if ref["type"] == "third":
                slots.append({"match": m["match"], "side": side,
                              "eligible": set(ref["eligible"])})
    assert len(slots) == 8, f"expected 8 third slots, got {len(slots)}"
    return slots


def _match_groups_to_slots(groups8: tuple[str, ...], slots: list[dict]) -> list[str] | None:
    """Perfect matching: return group letter assigned to each slot, or None.

    Backtracking with most-constrained-slot-first ordering.
    """
    order = sorted(range(len(slots)),
                   key=lambda s: len(slots[s]["eligible"] & set(groups8)))
    assign: dict[int, str] = {}
    used: set[str] = set()

    def bt(k: int) -> bool:
        if k == len(order):
            return True
        si = order[k]
        for g in groups8:
            if g in used:
                continue
            if g in slots[si]["eligible"]:
                assign[si] = g
                used.add(g)
                if bt(k + 1):
                    return True
                used.discard(g)
                del assign[si]
        return False

    if not bt(0):
        return None
    return [assign[s] for s in range(len(slots))]


def precompute_thirds_table(bracket: list[dict]) -> dict[tuple[str, ...], list[str]]:
    """Map each sorted 8-group combo -> list of group letters (one per slot).

    Falls back to a partial assignment if no perfect matching exists (rare).
    """
    slots = third_slots(bracket)
    table: dict[tuple[str, ...], list[str]] = {}
    for combo in combinations(GROUPS, 8):
        m = _match_groups_to_slots(combo, slots)
        if m is None:
            # Greedy partial fallback: fill what we can, then dump leftovers.
            remaining = list(combo)
            res = [None] * len(slots)
            for si, s in enumerate(slots):
                for g in list(remaining):
                    if g in s["eligible"]:
                        res[si] = g
                        remaining.remove(g)
                        break
            for si in range(len(slots)):
                if res[si] is None and remaining:
                    res[si] = remaining.pop(0)
            m = res
        table[combo] = m
    return table
