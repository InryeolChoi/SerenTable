"""The ADR-0011 planner against the independent oracle (``tests/oracle/scoring.py``).

The oracle was written from the ADR alone, without reading the engine. Here the engine's
allocations are re-checked by the oracle's validator and scored by the oracle's
objective, and on inputs of up to ten people compared with the exhaustive optimum. The
engine is a local search, so the gap is measured and reported, not assumed to be zero;
only validity and "never above the optimum" are hard requirements.
"""

import random
from fractions import Fraction

from serentable.matching import Participant, plan_allocation
from serentable.matching_score import DEFAULT_WEIGHTS, Policy

from oracle.scoring import DEFAULT_POLICY as ORACLE_POLICY
from oracle.scoring import Member as OracleMember
from oracle.scoring import Policy as OraclePolicy
from oracle.scoring import best_allocation, objective, validate_allocation

INTERESTS = ["music", "reading", "travel", "exercise", "food_cafes"]
TYPES = ["INTJ", "ENFP", "ISTJ", "ESFP", "INFP"]
TRAITS = ["calm", "energetic", "deep_conversation", "light_humor", "listener"]
WANTS = ["similar", "different", "deep_conversation", "calm_stable", "passionate"]


def scenario(seed):
    rng = random.Random(seed)
    size = rng.randint(4, 10)
    people = []
    for n in range(size):
        people.append(
            dict(
                user_id=f"u{n}",
                birth_year=rng.randint(1992, 2003),
                gender=rng.choice(["남성", "여성", "남성", "여성", ""]),
                mbtis=tuple(rng.sample(TYPES, rng.randint(0, 1))),
                interests=tuple(rng.sample(INTERESTS, rng.randint(1, 2))),
                self_traits=tuple(rng.sample(TRAITS, rng.randint(1, 2))),
                desired_traits=tuple(rng.sample(WANTS, rng.randint(0, 2))),
            )
        )
    users = [p["user_id"] for p in people]
    exclusions = frozenset(frozenset(rng.sample(users, 2)) for _ in range(rng.randint(0, 2)))
    met = frozenset(frozenset(rng.sample(users, 2)) for _ in range(rng.randint(0, 2)))
    capacity = rng.choice([6, 8, 10, 24])
    minimum = rng.choice([0, 40, 50, 60, 70])
    return people, exclusions, met, capacity, minimum


def engine(people, exclusions, met, capacity, minimum):
    roster = [Participant(application_id=p["user_id"], **p) for p in people]
    policy = Policy(weights=DEFAULT_WEIGHTS, min_score=Fraction(minimum))
    return plan_allocation(roster, capacity, policy=policy, exclusions=exclusions, met_pairs=met)


def oracle_inputs(people, minimum):
    members = [OracleMember(order=n, **p) for n, p in enumerate(people)]
    policy = OraclePolicy(weights=ORACLE_POLICY.weights, min_score=Fraction(minimum))
    return members, policy


SEEDS = range(150)


def test_every_engine_allocation_passes_the_independent_validator():
    for seed in SEEDS:
        people, exclusions, met, capacity, minimum = scenario(seed)
        plan = engine(people, exclusions, met, capacity, minimum)
        members, policy = oracle_inputs(people, minimum)
        violations = validate_allocation(plan.tables, members, capacity, policy, exclusions, met)
        assert violations == [], (seed, violations)


def test_engine_against_the_exhaustive_optimum_on_up_to_ten_people():
    exact = seat_gaps = 0
    worst = Fraction(0)
    for seed in SEEDS:
        people, exclusions, met, capacity, minimum = scenario(seed)
        plan = engine(people, exclusions, met, capacity, minimum)
        members, policy = oracle_inputs(people, minimum)
        by_id = {m.user_id: m for m in members}
        got = objective([[by_id[u] for u in t] for t in plan.tables], policy, met)
        _, best = best_allocation(members, capacity, policy, exclusions, met)
        assert got <= best, seed  # the oracle's optimum can never be beaten
        if got[:3] == best[:3]:
            exact += 1
        if got[0] < best[0]:
            seat_gaps += 1
        elif best[1]:
            worst = max(worst, (best[1] - got[1]) / best[1])
    print(
        f"\nengine vs exhaustive optimum on {len(SEEDS)} inputs (4-10 people): "
        f"same seats+quality+min {exact}, fewer seats {seat_gaps}, "
        f"worst quality gap at equal seats {float(worst):.2%}"
    )
