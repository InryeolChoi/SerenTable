"""Independent oracle for SerenTable matching hard constraints (필수조건).

Deliberately independent of ``backend/serentable``: pure Python, no DB, no shared code
with any matching engine. See ``docs/design/matching-oracle.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from enum import Enum
from functools import cache
from itertools import combinations

SlotKey = Hashable

MIN_TABLE_SIZE = 4
MAX_TABLE_SIZE = 6
MAX_AGE_GAP = 8


class Rule(Enum):
    UNKNOWN_PARTICIPANT = "unknown_participant"
    TABLE_SIZE = "table_size"
    UNPAID = "unpaid"
    NOT_CONSENTED = "not_consented"
    AGE_GAP = "age_gap"
    EXCLUDED_PAIR = "excluded_pair"
    DOUBLE_BOOKED = "double_booked"


@dataclass(frozen=True)
class Violation:
    rule: Rule
    table_id: str | None
    participant_ids: tuple[str, ...]
    related_table_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Participant:
    id: str
    paid: bool
    consented_slots: frozenset[SlotKey]
    birth_year: int


@dataclass(frozen=True)
class Table:
    table_id: str
    slot: SlotKey
    members: tuple[str, ...]


AgeKey = Callable[[Participant], int]


def birth_year_age_key(participant: Participant) -> int:
    """Provisional "나이 차이" basis: birth-year difference (pending U02/U17)."""
    return participant.birth_year


def validate_assignment(
    participants: Iterable[Participant],
    tables: Iterable[Table],
    *,
    excluded_pairs: Iterable[Iterable[str]] = (),
    age_key: AgeKey = birth_year_age_key,
) -> list[Violation]:
    by_id = {p.id: p for p in participants}
    excluded = {frozenset(pair) for pair in excluded_pairs}
    violations: list[Violation] = []
    appearances: dict[str, list[str]] = {}
    for table in tables:
        for pid in table.members:
            appearances.setdefault(pid, []).append(table.table_id)
        distinct = tuple(dict.fromkeys(table.members))
        unknown = tuple(pid for pid in distinct if pid not in by_id)
        if unknown:
            violations.append(Violation(Rule.UNKNOWN_PARTICIPANT, table.table_id, unknown))
        if not MIN_TABLE_SIZE <= len(distinct) <= MAX_TABLE_SIZE:
            violations.append(Violation(Rule.TABLE_SIZE, table.table_id, distinct))
        members = [by_id[pid] for pid in distinct if pid in by_id]
        unpaid = tuple(p.id for p in members if not p.paid)
        if unpaid:
            violations.append(Violation(Rule.UNPAID, table.table_id, unpaid))
        unconsented = tuple(p.id for p in members if table.slot not in p.consented_slots)
        if unconsented:
            violations.append(Violation(Rule.NOT_CONSENTED, table.table_id, unconsented))
        if members:
            low = min(members, key=age_key)
            high = max(members, key=age_key)
            if age_key(high) - age_key(low) > MAX_AGE_GAP:
                violations.append(Violation(Rule.AGE_GAP, table.table_id, (low.id, high.id)))
        for i, first in enumerate(distinct):
            for second in distinct[i + 1 :]:
                if frozenset((first, second)) in excluded:
                    violations.append(
                        Violation(Rule.EXCLUDED_PAIR, table.table_id, (first, second))
                    )
    for pid, table_ids in appearances.items():
        if len(table_ids) > 1:
            violations.append(Violation(Rule.DOUBLE_BOOKED, None, (pid,), tuple(table_ids)))
    return violations


MAX_BRUTE_FORCE_PARTICIPANTS = 12


@dataclass(frozen=True)
class SeatingResult:
    """Maximum seated count under hard constraints only, plus one witness assignment.

    This is NOT a quality/score optimum: scoring and the seated-count vs. quality priority
    are undecided (U05/U06). Only ``seated_count`` is meant for comparison; the witness is
    one arbitrary maximal assignment.
    """

    seated_count: int
    tables: tuple[Table, ...]


def max_seatable(
    participants: Iterable[Participant],
    *,
    excluded_pairs: Iterable[Iterable[str]] = (),
    age_key: AgeKey = birth_year_age_key,
    max_participants: int = MAX_BRUTE_FORCE_PARTICIPANTS,
) -> SeatingResult:
    """Exhaustively find how many participants can be seated at valid tables at once.

    Each participant sits at most one table across all slots. Every candidate table is
    accepted only if ``validate_assignment`` reports no violation for it, so the reference
    and the validator share one definition of the hard constraints.
    """
    roster = list(participants)
    if len(roster) > max_participants:
        raise ValueError(
            f"brute force is limited to {max_participants} participants, got {len(roster)}"
        )
    by_id = {p.id: p for p in roster}
    if len(by_id) != len(roster):
        raise ValueError("participant ids must be unique")
    excluded = [frozenset(pair) for pair in excluded_pairs]

    def table_is_valid(slot: SlotKey, members: tuple[str, ...]) -> bool:
        candidate = Table("candidate", slot, members)
        return not validate_assignment(
            [by_id[pid] for pid in members],
            [candidate],
            excluded_pairs=excluded,
            age_key=age_key,
        )

    @cache
    def best(remaining: tuple[str, ...]) -> tuple[int, tuple[tuple[SlotKey, tuple[str, ...]], ...]]:
        if len(remaining) < MIN_TABLE_SIZE:
            return 0, ()
        first, rest = remaining[0], remaining[1:]
        best_count, best_tables = best(rest)  # option: `first` stays unseated
        for slot in sorted(by_id[first].consented_slots, key=repr):
            pool = [pid for pid in rest if slot in by_id[pid].consented_slots]
            for size in range(MIN_TABLE_SIZE - 1, MAX_TABLE_SIZE):
                for others in combinations(pool, size):
                    members = (first, *others)
                    if not table_is_valid(slot, members):
                        continue
                    left = tuple(pid for pid in rest if pid not in others)
                    sub_count, sub_tables = best(left)
                    if len(members) + sub_count > best_count:
                        best_count = len(members) + sub_count
                        best_tables = ((slot, members), *sub_tables)
                        if best_count == len(remaining):
                            return best_count, best_tables
        return best_count, best_tables

    count, chosen = best(tuple(sorted(by_id)))
    tables = tuple(
        Table(f"t{index}", slot, members) for index, (slot, members) in enumerate(chosen, 1)
    )
    return SeatingResult(count, tables)
