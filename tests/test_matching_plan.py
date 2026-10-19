"""ADR-0011 allocation through the planner's public function, without the database."""

from fractions import Fraction

from serentable.matching import Participant, plan_allocation
from serentable.matching_score import DEFAULT_POLICY, Policy


def person(
    n,
    year,
    gender="남성",
    mbtis=("INTJ",),
    interests=("music",),
    self_traits=("calm",),
    desired=("calm_stable",),
):
    return Participant(
        application_id=f"app-{n:02d}",
        birth_year=year,
        user_id=f"user-{n:02d}",
        gender=gender,
        mbtis=tuple(mbtis),
        interests=tuple(interests),
        self_traits=tuple(self_traits),
        desired_traits=tuple(desired),
    )


def policy(min_score):
    return Policy(weights=DEFAULT_POLICY.weights, min_score=Fraction(min_score))


# Four men, ages 8 apart at the extremes, nothing in common and wanting what nobody is.
POOR = [
    person(1, 1990, mbtis=("ISTJ",), interests=("music",), desired=("passionate",)),
    person(2, 1998, mbtis=("ENFP",), interests=("travel",), desired=("passionate",)),
    person(3, 1994, mbtis=("ISTJ",), interests=("reading",), desired=("passionate",)),
    person(4, 1996, mbtis=("ENFP",), interests=("exercise",), desired=("passionate",)),
]


def test_a_table_below_the_minimum_score_is_not_built():
    # age 100*(1-8/8)=0; gender 4 men -> 0; MBTI pairs 12:80 13:100 14:80 23:80 24:100
    # 34:80 -> 520/6; interest 0; trait 0 (nobody energetic/leading); new 100.
    # .15*520/6 + .15*100 = 13 + 15 = 28 < 50.
    plan = plan_allocation(POOR, 24, policy=policy(50))
    assert plan.tables == ()
    # A local search cannot prove no table exists, so the reason says what it found.
    assert {reason for _, reason in plan.unseated} == {"no_qualifying_table"}


def test_with_a_zero_minimum_the_same_table_is_built_and_scored():
    plan = plan_allocation(POOR, 24, policy=policy(0))
    assert plan.seated_count == 4
    assert plan.table_scores == (Fraction(28),)


def alike(n, year=1995, gender=None, interests=("music",)):
    return person(n, year, gender=gender or ("남성" if n % 2 else "여성"), interests=interests)


def test_an_excluded_pair_never_shares_a_table_and_everyone_is_still_seated():
    people = [alike(n) for n in range(1, 9)]
    excluded = frozenset({frozenset({"user-01", "user-02"})})
    # The DP alone puts the first four applicants (01..04) together.
    baseline = plan_allocation(people, 24)
    assert any({"app-01", "app-02"} <= set(table) for table in baseline.tables)
    plan = plan_allocation(people, 24, policy=policy(50), exclusions=excluded)
    assert plan.seated_count == 8
    assert not any({"app-01", "app-02"} <= set(table) for table in plan.tables)


def test_a_lone_excluded_pair_that_cannot_be_split_leaves_people_out_with_the_reason():
    people = [alike(n) for n in range(1, 5)]
    excluded = frozenset({frozenset({"user-01", "user-02"})})
    plan = plan_allocation(people, 24, policy=policy(0), exclusions=excluded)
    assert plan.seated_count == 0
    assert dict(plan.unseated)["app-01"] == "no_qualifying_table"


def test_people_left_out_only_by_a_full_slot_are_told_it_is_the_capacity():
    # Ten compatible applicants, capacity 6: one table of six, the last four would have
    # formed a second table if the slot had room. A wrong age/table reason misleads them.
    people = [alike(n) for n in range(1, 11)]
    for plan in (plan_allocation(people, 6), plan_allocation(people, 6, policy=policy(0))):
        assert plan.seated_count == 6
        assert {reason for _, reason in plan.unseated} == {"capacity"}


def test_an_unseatable_age_outlier_keeps_its_own_reason_when_the_slot_is_also_full():
    people = [alike(n) for n in range(1, 9)] + [person(9, 1970)]
    plan = plan_allocation(people, 6, policy=policy(0))
    reasons = dict(plan.unseated)
    assert reasons["app-09"] == "age_gap"
    assert {reasons[f"app-0{n}"] for n in (7, 8)} == {"capacity"}


def test_swaps_group_shared_interests_when_the_seat_count_is_equal():
    # Same age; odd applicants like music, even ones travel; 01..04 are men. The DP seats
    # 01..04 and 05..08: one gender per table and mixed interests. Grouping by interest
    # gives both tables two men and two women and one shared interest.
    people = [
        alike(
            n, gender="남성" if n <= 4 else "여성", interests=("music",) if n % 2 else ("travel",)
        )
        for n in range(1, 9)
    ]
    plan = plan_allocation(people, 24, policy=policy(0))
    assert plan.seated_count == 8
    assert {frozenset(t) for t in plan.tables} == {
        frozenset({"app-01", "app-03", "app-05", "app-07"}),
        frozenset({"app-02", "app-04", "app-06", "app-08"}),
    }


def test_the_same_input_gives_the_same_allocation():
    people = [
        alike(n, year=1990 + n % 9, interests=(("music", "travel", "reading")[n % 3],))
        for n in range(1, 31)
    ]
    first = plan_allocation(people, 24, policy=policy(50))
    again = plan_allocation(list(people), 24, policy=policy(50))
    assert (first.tables, first.unseated, first.table_scores) == (
        again.tables,
        again.unseated,
        again.table_scores,
    )


def random_roster(seed, size):
    import random

    rng = random.Random(seed)
    interests = ["music", "reading", "travel", "exercise", "food_cafes", "movies_drama"]
    types = ["INTJ", "ENFP", "ISTJ", "ESFP", "INFP", "ENTJ"]
    traits = ["calm", "energetic", "deep_conversation", "light_humor", "listener"]
    wants = ["similar", "different", "deep_conversation", "calm_stable", "passionate"]
    return [
        person(
            n,
            rng.randint(1988, 2004),
            gender=rng.choice(["남성", "여성"]),
            mbtis=rng.sample(types, rng.randint(0, 1)),
            interests=rng.sample(interests, rng.randint(1, 3)),
            self_traits=rng.sample(traits, rng.randint(1, 2)),
            desired=rng.sample(wants, rng.randint(1, 2)),
        )
        for n in range(1, size + 1)
    ]


def test_without_a_minimum_or_exclusions_the_seat_count_equals_the_dp_baseline():
    # A regression floor only: equal counts here say nothing about global optimality.
    for seed in range(12):
        people = random_roster(seed, 4 + seed * 3)
        baseline = plan_allocation(people, 24)
        plan = plan_allocation(people, 24, policy=policy(0))
        assert plan.seated_count == baseline.seated_count, seed


def test_constraints_never_seat_more_than_the_dp_baseline():
    for seed in range(12):
        people = random_roster(100 + seed, 6 + seed * 2)
        excluded = frozenset({frozenset({"user-01", "user-02"}), frozenset({"user-03", "user-05"})})
        for minimum in (40, 60, 80):
            plan = plan_allocation(people, 24, policy=policy(minimum), exclusions=excluded)
            assert plan.seated_count <= plan_allocation(people, 24).seated_count
            assert all(score >= minimum for score in plan.table_scores)


def test_a_hundred_applicants_finish_within_the_time_bound():
    import time

    people = random_roster(7, 100)
    started = time.monotonic()
    plan = plan_allocation(people, 100, policy=policy(50))
    elapsed = time.monotonic() - started
    print(
        f"100 applicants: seated={plan.seated_count} elapsed={elapsed:.2f}s "
        f"complete={plan.search_complete}"
    )
    assert elapsed < 6
