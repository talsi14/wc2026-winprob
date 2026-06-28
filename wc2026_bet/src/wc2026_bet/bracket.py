"""Knockout-bracket helpers.

Parses the real 2026 bracket (data/processed/bracket.json) and assigns the eight
qualifying third-placed teams to the eight "3rd ..." slots in the Round of 32.

The assignment is FIFA's *official* predetermined mapping, transcribed from
"Annex C: Combinations for eight best third-placed teams" of the FIFA World Cup
26 Regulations (495 rows = C(12,8)). Earlier this module computed *any* valid
eligibility-respecting matching, which can differ from FIFA's published table
(e.g. for advancing groups {B,D,E,F,I,J,K,L} it mis-seeded 4 of 8 third slots),
so we now key directly off Annex C. ``_match_groups_to_slots`` is retained only
as a defensive fallback if the bracket structure ever stops matching Annex C.
"""
from __future__ import annotations

from itertools import combinations

from .config import GROUPS

# --------------------------------------------------------------------------- #
# Official FIFA "Annex C" lookup. ANNEX_C_WINNERS is the column order: the group
# whose *winner* each column's R32 third-place opponent is fixed against. Each
# ANNEX_C_ROWS entry is the 8 third-place group letters in that same column
# order; sorting a row's letters yields the combination of advancing groups.
# --------------------------------------------------------------------------- #
ANNEX_C_WINNERS = ['A', 'B', 'D', 'E', 'G', 'I', 'K', 'L']

ANNEX_C_ROWS = [
    "EJIFHGLK", "HGIDJFLK", "EJIDHGLK", "EJIDHFLK", "EGIDJFLK", "EGJDHFLK", "EGIDHFLK", "EGJDHFLI",
    "EGJDHFIK", "HGICJFLK", "EJICHGLK", "EJICHFLK", "EGICJFLK", "EGJCHFLK", "EGICHFLK", "EGJCHFLI",
    "EGJCHFIK", "HGICJDLK", "CJIDHFLK", "CGIDJFLK", "CGJDHFLK", "CGIDHFLK", "CGJDHFLI", "CGJDHFIK",
    "EJICHDLK", "EGICJDLK", "EGJCHDLK", "EGICHDLK", "EGJCHDLI", "EGJCHDIK", "CJEDIFLK", "CJEDHFLK",
    "CEIDHFLK", "CJEDHFLI", "CJEDHFIK", "CGEDJFLK", "CGEDIFLK", "CGEDJFLI", "CGEDJFIK", "CGEDHFLK",
    "CGJDHFLE", "CGJDHFEK", "CGEDHFLI", "CGEDHFIK", "CGJDHFEI", "HJBFIGLK", "EJIBHGLK", "EJBFIHLK",
    "EJBFIGLK", "EJBFHGLK", "EGBFIHLK", "EJBFHGLI", "EJBFHGIK", "HJBDIGLK", "HJBDIFLK", "IGBDJFLK",
    "HGBDJFLK", "HGBDIFLK", "HGBDJFLI", "HGBDJFIK", "EJBDIHLK", "EJBDIGLK", "EJBDHGLK", "EGBDIHLK",
    "EJBDHGLI", "EJBDHGIK", "EJBDIFLK", "EJBDHFLK", "EIBDHFLK", "EJBDHFLI", "EJBDHFIK", "EGBDJFLK",
    "EGBDIFLK", "EGBDJFLI", "EGBDJFIK", "EGBDHFLK", "HGBDJFLE", "HGBDJFEK", "EGBDHFLI", "EGBDHFIK",
    "HGBDJFEI", "HJBCIGLK", "HJBCIFLK", "IGBCJFLK", "HGBCJFLK", "HGBCIFLK", "HGBCJFLI", "HGBCJFIK",
    "EJBCIHLK", "EJBCIGLK", "EJBCHGLK", "EGBCIHLK", "EJBCHGLI", "EJBCHGIK", "EJBCIFLK", "EJBCHFLK",
    "EIBCHFLK", "EJBCHFLI", "EJBCHFIK", "EGBCJFLK", "EGBCIFLK", "EGBCJFLI", "EGBCJFIK", "EGBCHFLK",
    "HGBCJFLE", "HGBCJFEK", "EGBCHFLI", "EGBCHFIK", "HGBCJFEI", "HJBCIDLK", "IGBCJDLK", "HGBCJDLK",
    "HGBCIDLK", "HGBCJDLI", "HGBCJDIK", "CJBDIFLK", "CJBDHFLK", "CIBDHFLK", "CJBDHFLI", "CJBDHFIK",
    "CGBDJFLK", "CGBDIFLK", "CGBDJFLI", "CGBDJFIK", "CGBDHFLK", "CGBDHFLJ", "HGBCJFDK", "CGBDHFLI",
    "CGBDHFIK", "HGBCJFDI", "EJBCIDLK", "EJBCHDLK", "EIBCHDLK", "EJBCHDLI", "EJBCHDIK", "EGBCJDLK",
    "EGBCIDLK", "EGBCJDLI", "EGBCJDIK", "EGBCHDLK", "HGBCJDLE", "HGBCJDEK", "EGBCHDLI", "EGBCHDIK",
    "HGBCJDEI", "CJBDEFLK", "CEBDIFLK", "CJBDEFLI", "CJBDEFIK", "CEBDHFLK", "CJBDHFLE", "CJBDHFEK",
    "CEBDHFLI", "CEBDHFIK", "CJBDHFEI", "CGBDEFLK", "CGBDJFLE", "CGBDJFEK", "CGBDEFLI", "CGBDEFIK",
    "CGBDJFEI", "CGBDHFLE", "CGBDHFEK", "HGBCJFDE", "CGBDHFEI", "HJIFAGLK", "EJIAHGLK", "EJIFAHLK",
    "EJIFAGLK", "EGJFAHLK", "EGIFAHLK", "EGJFAHLI", "EGJFAHIK", "HJIDAGLK", "HJIDAFLK", "IGJDAFLK",
    "HGJDAFLK", "HGIDAFLK", "HGJDAFLI", "HGJDAFIK", "EJIDAHLK", "EJIDAGLK", "EGJDAHLK", "EGIDAHLK",
    "EGJDAHLI", "EGJDAHIK", "EJIDAFLK", "HJEDAFLK", "HEIDAFLK", "HJEDAFLI", "HJEDAFIK", "EGJDAFLK",
    "EGIDAFLK", "EGJDAFLI", "EGJDAFIK", "HGEDAFLK", "HGJDAFLE", "HGJDAFEK", "HGEDAFLI", "HGEDAFIK",
    "HGJDAFEI", "HJICAGLK", "HJICAFLK", "IGJCAFLK", "HGJCAFLK", "HGICAFLK", "HGJCAFLI", "HGJCAFIK",
    "EJICAHLK", "EJICAGLK", "EGJCAHLK", "EGICAHLK", "EGJCAHLI", "EGJCAHIK", "EJICAFLK", "HJECAFLK",
    "HEICAFLK", "HJECAFLI", "HJECAFIK", "EGJCAFLK", "EGICAFLK", "EGJCAFLI", "EGJCAFIK", "HGECAFLK",
    "HGJCAFLE", "HGJCAFEK", "HGECAFLI", "HGECAFIK", "HGJCAFEI", "HJICADLK", "IGJCADLK", "HGJCADLK",
    "HGICADLK", "HGJCADLI", "HGJCADIK", "CJIDAFLK", "HJFCADLK", "HFICADLK", "HJFCADLI", "HJFCADIK",
    "CGJDAFLK", "CGIDAFLK", "CGJDAFLI", "CGJDAFIK", "HGFCADLK", "CGJDAFLH", "HGJCAFDK", "HGFCADLI",
    "HGFCADIK", "HGJCAFDI", "EJICADLK", "HJECADLK", "HEICADLK", "HJECADLI", "HJECADIK", "EGJCADLK",
    "EGICADLK", "EGJCADLI", "EGJCADIK", "HGECADLK", "HGJCADLE", "HGJCADEK", "HGECADLI", "HGECADIK",
    "HGJCADEI", "CJEDAFLK", "CEIDAFLK", "CJEDAFLI", "CJEDAFIK", "HEFCADLK", "HJFCADLE", "HJECAFDK",
    "HEFCADLI", "HEFCADIK", "HJECAFDI", "CGEDAFLK", "CGJDAFLE", "CGJDAFEK", "CGEDAFLI", "CGEDAFIK",
    "CGJDAFEI", "HGFCADLE", "HGECAFDK", "HGJCAFDE", "HGECAFDI", "HJBAIGLK", "HJBAIFLK", "IJBFAGLK",
    "HJBFAGLK", "HGBAIFLK", "HJBFAGLI", "HJBFAGIK", "EJBAIHLK", "EJBAIGLK", "EJBAHGLK", "EGBAIHLK",
    "EJBAHGLI", "EJBAHGIK", "EJBAIFLK", "EJBFAHLK", "EIBFAHLK", "EJBFAHLI", "EJBFAHIK", "EJBFAGLK",
    "EGBAIFLK", "EJBFAGLI", "EJBFAGIK", "EGBFAHLK", "HJBFAGLE", "HJBFAGEK", "EGBFAHLI", "EGBFAHIK",
    "HJBFAGEI", "IJBDAHLK", "IJBDAGLK", "HJBDAGLK", "IGBDAHLK", "HJBDAGLI", "HJBDAGIK", "IJBDAFLK",
    "HJBDAFLK", "HIBDAFLK", "HJBDAFLI", "HJBDAFIK", "FJBDAGLK", "IGBDAFLK", "FJBDAGLI", "FJBDAGIK",
    "HGBDAFLK", "HGBDAFLJ", "HGBDAFJK", "HGBDAFLI", "HGBDAFIK", "HGBDAFIJ", "EJBAIDLK", "EJBDAHLK",
    "EIBDAHLK", "EJBDAHLI", "EJBDAHIK", "EJBDAGLK", "EGBAIDLK", "EJBDAGLI", "EJBDAGIK", "EGBDAHLK",
    "HJBDAGLE", "HJBDAGEK", "EGBDAHLI", "EGBDAHIK", "HJBDAGEI", "EJBDAFLK", "EIBDAFLK", "EJBDAFLI",
    "EJBDAFIK", "HEBDAFLK", "HJBDAFLE", "HJBDAFEK", "HEBDAFLI", "HEBDAFIK", "HJBDAFEI", "EGBDAFLK",
    "EGBDAFLJ", "EGBDAFJK", "EGBDAFLI", "EGBDAFIK", "EGBDAFIJ", "HGBDAFLE", "HGBDAFEK", "HGBDAFEJ",
    "HGBDAFEI", "IJBCAHLK", "IJBCAGLK", "HJBCAGLK", "IGBCAHLK", "HJBCAGLI", "HJBCAGIK", "IJBCAFLK",
    "HJBCAFLK", "HIBCAFLK", "HJBCAFLI", "HJBCAFIK", "CJBFAGLK", "IGBCAFLK", "CJBFAGLI", "CJBFAGIK",
    "HGBCAFLK", "HGBCAFLJ", "HGBCAFJK", "HGBCAFLI", "HGBCAFIK", "HGBCAFIJ", "EJBAICLK", "EJBCAHLK",
    "EIBCAHLK", "EJBCAHLI", "EJBCAHIK", "EJBCAGLK", "EGBAICLK", "EJBCAGLI", "EJBCAGIK", "EGBCAHLK",
    "HJBCAGLE", "HJBCAGEK", "EGBCAHLI", "EGBCAHIK", "HJBCAGEI", "EJBCAFLK", "EIBCAFLK", "EJBCAFLI",
    "EJBCAFIK", "HEBCAFLK", "HJBCAFLE", "HJBCAFEK", "HEBCAFLI", "HEBCAFIK", "HJBCAFEI", "EGBCAFLK",
    "EGBCAFLJ", "EGBCAFJK", "EGBCAFLI", "EGBCAFIK", "EGBCAFIJ", "HGBCAFLE", "HGBCAFEK", "HGBCAFEJ",
    "HGBCAFEI", "IJBCADLK", "HJBCADLK", "HIBCADLK", "HJBCADLI", "HJBCADIK", "CJBDAGLK", "IGBCADLK",
    "CJBDAGLI", "CJBDAGIK", "HGBCADLK", "HGBCADLJ", "HGBCADJK", "HGBCADLI", "HGBCADIK", "HGBCADIJ",
    "CJBDAFLK", "CIBDAFLK", "CJBDAFLI", "CJBDAFIK", "HFBCADLK", "CJBDAFLH", "HJBCAFDK", "HFBCADLI",
    "HFBCADIK", "HJBCAFDI", "CGBDAFLK", "CGBDAFLJ", "CGBDAFJK", "CGBDAFLI", "CGBDAFIK", "CGBDAFIJ",
    "CGBDAFLH", "HGBCAFDK", "HGBCAFDJ", "HGBCAFDI", "EJBCADLK", "EIBCADLK", "EJBCADLI", "EJBCADIK",
    "HEBCADLK", "HJBCADLE", "HJBCADEK", "HEBCADLI", "HEBCADIK", "HJBCADEI", "EGBCADLK", "EGBCADLJ",
    "EGBCADJK", "EGBCADLI", "EGBCADIK", "EGBCADIJ", "HGBCADLE", "HGBCADEK", "HGBCADEJ", "HGBCADEI",
    "CEBDAFLK", "CJBDAFLE", "CJBDAFEK", "CEBDAFLI", "CEBDAFIK", "CJBDAFEI", "HFBCADLE", "HEBCAFDK",
    "HJBCAFDE", "HEBCAFDI", "CGBDAFLE", "CGBDAFEK", "CGBDAFEJ", "CGBDAFEI", "HGBCAFDE",
]

# combo (sorted 8-group tuple) -> {winner_group_letter: third_group_letter}
_OFFICIAL_THIRDS: dict[tuple[str, ...], dict[str, str]] = {
    tuple(sorted(row)): {ANNEX_C_WINNERS[i]: row[i] for i in range(8)}
    for row in ANNEX_C_ROWS
}


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


def _winner_group_for_match(bracket: list[dict], match: int) -> str | None:
    """The group whose winner occupies the non-third side of an R32 match."""
    for m in bracket:
        if m["match"] != match:
            continue
        for side in ("home_ref", "away_ref"):
            ref = m[side]
            if ref.get("type") == "group_winner":
                return ref.get("group")
    return None


def _match_groups_to_slots(groups8: tuple[str, ...], slots: list[dict]) -> list[str] | None:
    """Perfect matching: return group letter assigned to each slot, or None.

    Backtracking with most-constrained-slot-first ordering. Defensive fallback
    only; the official Annex C table is authoritative.
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

    Uses FIFA's official Annex C assignment, projected onto our slot (match)
    order. Falls back to any valid eligibility-respecting matching only if the
    official third for a slot is somehow ineligible under the parsed bracket
    (should never happen; indicates a bracket.json / Annex C mismatch).
    """
    slots = third_slots(bracket)
    win_by_slot = [_winner_group_for_match(bracket, s["match"]) for s in slots]
    table: dict[tuple[str, ...], list[str]] = {}
    for combo in combinations(GROUPS, 8):
        official = _OFFICIAL_THIRDS.get(combo)
        assign: list[str] | None = None
        if official is not None:
            cand = []
            ok = True
            for i, slot in enumerate(slots):
                tg = official.get(win_by_slot[i])
                if tg is None or tg not in slot["eligible"]:
                    ok = False
                    break
                cand.append(tg)
            if ok:
                assign = cand
        if assign is None:
            assign = _match_groups_to_slots(combo, slots)
        if assign is None:
            # last-ditch greedy partial fill
            remaining = list(combo)
            assign = [None] * len(slots)
            for si, s in enumerate(slots):
                for g in list(remaining):
                    if g in s["eligible"]:
                        assign[si] = g
                        remaining.remove(g)
                        break
            for si in range(len(slots)):
                if assign[si] is None and remaining:
                    assign[si] = remaining.pop(0)
        table[combo] = assign
    return table
