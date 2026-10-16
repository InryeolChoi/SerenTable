"""Boundary tests for the independent hard-constraint oracle.

Every expected value below is hand-computed from the PRD hard constraints, never from the
oracle itself.
"""

from oracle.hard_constraints import Participant, Rule, Table, Violation, validate_assignment

SLOT_A = ("2026-11-07", "seongsu")
SLOT_B = ("2026-11-07", "hapjeong")


def person(pid: str, birth_year: int = 1995, paid: bool = True, slots=(SLOT_A,)) -> Participant:
    return Participant(id=pid, paid=paid, consented_slots=frozenset(slots), birth_year=birth_year)


def people(*ids: str, **kwargs) -> list[Participant]:
    return [person(pid, **kwargs) for pid in ids]


def test_valid_four_person_table_has_no_violations():
    participants = people("a", "b", "c", "d")
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables) == []


def test_six_person_table_is_the_largest_accepted_size():
    ids = ("a", "b", "c", "d", "e", "f")
    assert validate_assignment(people(*ids), [Table("t1", SLOT_A, ids)]) == []


def test_three_person_table_violates_size():
    ids = ("a", "b", "c")
    violations = validate_assignment(people(*ids), [Table("t1", SLOT_A, ids)])

    assert violations == [Violation(Rule.TABLE_SIZE, "t1", ids)]


def test_seven_person_table_violates_size():
    ids = ("a", "b", "c", "d", "e", "f", "g")
    violations = validate_assignment(people(*ids), [Table("t1", SLOT_A, ids)])

    assert violations == [Violation(Rule.TABLE_SIZE, "t1", ids)]


def test_birth_year_gap_of_eight_is_accepted():
    participants = [person("a", 1990), person("b", 1994), person("c", 1996), person("d", 1998)]
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables) == []


def test_birth_year_gap_of_nine_is_rejected_naming_the_extremes():
    participants = [person("a", 1990), person("b", 1994), person("c", 1996), person("d", 1999)]
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables) == [Violation(Rule.AGE_GAP, "t1", ("a", "d"))]


def test_age_key_is_pluggable_for_a_future_age_definition():
    # Birth years are identical, but a hypothetical alternative age key (U02/U17) spreads them.
    participants = people("a", "b", "c", "d")
    ages = {"a": 30, "b": 31, "c": 35, "d": 40}
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables, age_key=lambda p: ages[p.id]) == [
        Violation(Rule.AGE_GAP, "t1", ("a", "d"))
    ]


def test_unpaid_member_is_reported():
    participants = people("a", "b", "c") + [person("d", paid=False)]
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables) == [Violation(Rule.UNPAID, "t1", ("d",))]


def test_member_who_did_not_consent_to_the_table_slot_is_reported():
    participants = people("a", "b", "c") + [person("d", slots=(SLOT_B,))]
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables) == [
        Violation(Rule.NOT_CONSENTED, "t1", ("d",))
    ]


def test_excluded_pair_at_one_table_is_reported_in_either_order():
    participants = people("a", "b", "c", "d")
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "d"))]

    assert validate_assignment(participants, tables, excluded_pairs=[("c", "a")]) == [
        Violation(Rule.EXCLUDED_PAIR, "t1", ("a", "c"))
    ]


def test_excluded_pair_split_across_tables_is_fine():
    participants = people("a", "b", "c", "d", "e", "f", "g", "h")
    tables = [
        Table("t1", SLOT_A, ("a", "b", "c", "d")),
        Table("t2", SLOT_A, ("e", "f", "g", "h")),
    ]

    assert validate_assignment(participants, tables, excluded_pairs=[("a", "e")]) == []


def test_participant_at_two_tables_in_the_same_slot_is_double_booked():
    participants = people("a", "b", "c", "d", "e", "f", "g")
    tables = [
        Table("t1", SLOT_A, ("a", "b", "c", "d")),
        Table("t2", SLOT_A, ("d", "e", "f", "g")),
    ]

    assert validate_assignment(participants, tables) == [
        Violation(Rule.DOUBLE_BOOKED, None, ("d",), ("t1", "t2"))
    ]


def test_participant_at_tables_in_two_different_slots_is_double_booked():
    # One application holds at most one live assignment, even across consented slots.
    participants = people("a", "b", "c", "d", "e", "f", "g", slots=(SLOT_A, SLOT_B))
    tables = [
        Table("t1", SLOT_A, ("a", "b", "c", "d")),
        Table("t2", SLOT_B, ("d", "e", "f", "g")),
    ]

    assert validate_assignment(participants, tables) == [
        Violation(Rule.DOUBLE_BOOKED, None, ("d",), ("t1", "t2"))
    ]


def test_participant_listed_twice_in_one_table_is_double_booked_and_not_counted_twice():
    participants = people("a", "b", "c")
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "c"))]

    assert validate_assignment(participants, tables) == [
        Violation(Rule.TABLE_SIZE, "t1", ("a", "b", "c")),
        Violation(Rule.DOUBLE_BOOKED, None, ("c",), ("t1", "t1")),
    ]


def test_member_missing_from_participant_input_is_reported():
    participants = people("a", "b", "c")
    tables = [Table("t1", SLOT_A, ("a", "b", "c", "zz"))]

    assert validate_assignment(participants, tables) == [
        Violation(Rule.UNKNOWN_PARTICIPANT, "t1", ("zz",))
    ]


def test_valid_four_plus_four_split_of_eight_people():
    participants = people("a", "b", "c", "d", "e", "f", "g", "h")
    tables = [
        Table("t1", SLOT_A, ("a", "b", "c", "d")),
        Table("t2", SLOT_A, ("e", "f", "g", "h")),
    ]

    assert validate_assignment(participants, tables) == []


def test_every_broken_rule_on_one_table_is_reported():
    participants = [
        person("a", 1990),
        person("b", 2000, paid=False),
        person("c", slots=(SLOT_B,)),
    ]
    tables = [Table("t1", SLOT_A, ("a", "b", "c"))]

    assert validate_assignment(participants, tables, excluded_pairs=[("a", "c")]) == [
        Violation(Rule.TABLE_SIZE, "t1", ("a", "b", "c")),
        Violation(Rule.UNPAID, "t1", ("b",)),
        Violation(Rule.NOT_CONSENTED, "t1", ("c",)),
        Violation(Rule.AGE_GAP, "t1", ("a", "b")),
        Violation(Rule.EXCLUDED_PAIR, "t1", ("a", "c")),
    ]
