"""Small-case reference: maximum seatable participants under hard constraints only.

Expected counts are hand-derived. "Seated count" is NOT a quality optimum (U05/U06).
"""

import pytest

from oracle.hard_constraints import Participant, max_seatable, validate_assignment

SLOT_A = ("2026-11-07", "seongsu")
SLOT_B = ("2026-11-08", "hapjeong")


def person(pid: str, birth_year: int = 1995, paid: bool = True, slots=(SLOT_A,)) -> Participant:
    return Participant(id=pid, paid=paid, consented_slots=frozenset(slots), birth_year=birth_year)


def people(prefix: str, count: int, **kwargs) -> list[Participant]:
    return [person(f"{prefix}{i}", **kwargs) for i in range(count)]


def assert_witness(participants, result, excluded_pairs=()):
    """The returned tables must themselves pass the validator and match the count."""
    assert validate_assignment(participants, result.tables, excluded_pairs=excluded_pairs) == []
    assert sum(len(t.members) for t in result.tables) == result.seated_count


def test_three_people_cannot_form_a_table():
    participants = people("p", 3)

    result = max_seatable(participants)

    assert result.seated_count == 0
    assert result.tables == ()


def test_eight_compatible_people_are_all_seated():
    participants = people("p", 8)

    result = max_seatable(participants)

    assert result.seated_count == 8
    assert_witness(participants, result)


def test_eight_people_with_seven_eligible_seat_only_six():
    # 7 cannot be written as a sum of table sizes 4..6, so one eligible person is left out.
    participants = people("p", 7) + [person("unpaid", paid=False)]

    result = max_seatable(participants)

    assert result.seated_count == 6
    assert_witness(participants, result)


def test_age_chain_requires_the_four_plus_four_split():
    # Birth years 1990,1990,1994,1994,1998,1998,2002,2002. A greedy 6-table
    # {1990..1998} (gap 8) strands the two 2002s; only {1990,1994}x2 + {1998,2002}x2 seats 8.
    participants = [
        person(f"{year}-{n}", year) for year in (1990, 1994, 1998, 2002) for n in (1, 2)
    ]

    result = max_seatable(participants)

    assert result.seated_count == 8
    assert sorted(len(t.members) for t in result.tables) == [4, 4]
    assert_witness(participants, result)


def test_nine_year_gap_splits_nine_people_into_five_and_four():
    participants = people("old", 5, birth_year=1990) + people("young", 4, birth_year=1999)

    result = max_seatable(participants)

    assert result.seated_count == 9
    assert_witness(participants, result)


def test_nine_year_gap_with_three_young_seats_only_the_five_old():
    participants = people("old", 5, birth_year=1990) + people("young", 3, birth_year=1999)

    assert max_seatable(participants).seated_count == 5


def test_person_excluded_from_everyone_else_is_left_out():
    participants = people("p", 8)
    excluded = [("p0", f"p{i}") for i in range(1, 8)]

    result = max_seatable(participants, excluded_pairs=excluded)

    # p0 cannot sit with anyone; the other 7 can only fill one table of at most 6.
    assert result.seated_count == 6
    assert_witness(participants, result, excluded_pairs=excluded)


def test_excluded_pair_is_separated_across_a_four_plus_four_split():
    participants = people("p", 8)
    excluded = [("p0", "p1")]

    result = max_seatable(participants, excluded_pairs=excluded)

    assert result.seated_count == 8
    assert_witness(participants, result, excluded_pairs=excluded)


def test_people_are_seated_only_in_slots_they_consented_to():
    participants = people("a", 5, slots=(SLOT_A,)) + people("b", 4, slots=(SLOT_B,))

    result = max_seatable(participants)

    assert result.seated_count == 9
    assert {t.slot for t in result.tables} == {SLOT_A, SLOT_B}
    assert_witness(participants, result)


def test_three_in_a_slot_are_not_moved_to_an_unconsented_slot():
    participants = people("a", 5, slots=(SLOT_A,)) + people("b", 3, slots=(SLOT_B,))

    assert max_seatable(participants).seated_count == 5


def test_flexible_people_complete_a_second_slot():
    # 3 only-B people need one flexible (A or B) person; 5 flexible + 3 B -> 4 at A, 4 at B.
    participants = people("flex", 5, slots=(SLOT_A, SLOT_B)) + people("b", 3, slots=(SLOT_B,))

    result = max_seatable(participants)

    assert result.seated_count == 8
    assert_witness(participants, result)


def test_twelve_people_mixed_case_finishes():
    # Ages 1990x6 and 2000x6 (gap 10), one excluded pair inside each age group.
    participants = people("old", 6, birth_year=1990) + people("young", 6, birth_year=2000)
    excluded = [("old0", "old1"), ("young0", "young1")]

    result = max_seatable(participants, excluded_pairs=excluded)

    # Age groups cannot mix (gap 10). A group of 6 fits only one table (3+3 is too small),
    # and that table cannot hold the excluded pair, so each group seats 5: 5 + 5.
    assert result.seated_count == 10
    assert_witness(participants, result, excluded_pairs=excluded)


def test_more_than_twelve_participants_is_refused():
    with pytest.raises(ValueError):
        max_seatable(people("p", 13))
