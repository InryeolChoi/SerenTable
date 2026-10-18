"""100-person matching planner measurement on deterministic synthetic pools, aggregates only.

Work #10 "100명 측정": for each synthetic pool the real planner (``plan_allocation`` with
the worker's default policy, minimum score 60) is run and measured for wall time, peak
traced memory, seated count against a known optimum or an independent upper bound, hard
constraint violations (``tests/oracle/hard_constraints.validate_assignment``), minimum
score compliance (``tests/oracle/scoring.validate_allocation``), duplicate seats, missing
participants, and determinism (two runs give the same tables).

No ``data/`` file is read and no personal data exists: every pool is generated from a seed.
Only aggregates are printed. The ADR-0011 5 second target is flagged, not turned into a
new acceptance number; the policy for inputs above 100 (U19) is not decided here.

What this does not measure: HTTP, the separate worker process, PostgreSQL work and the
deployed environment (see ``tests/test_matching_scale.py`` for the end-to-end path).

Usage: PYTHONPATH=backend uv run python scripts/measure_matching_scale.py [--seeds N] [--json]
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "backend", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from oracle import hard_constraints as hard  # noqa: E402
from oracle import scoring as oracle_scoring  # noqa: E402
from serentable.matching import Participant, plan_allocation  # noqa: E402
from serentable.matching_score import DEFAULT_POLICY  # noqa: E402

SLOT = "synthetic-slot"
POOL_SIZE = 100
ADR_TARGET_SECONDS = 5.0  # ADR-0011 / U06 target, reported only.

MBTIS = ("INTJ", "ENFP", "ISTJ", "ESFP", "INFP", "ENTJ", "ISFJ", "ESTP")
INTERESTS = (
    "movies_drama",
    "music",
    "reading",
    "writing",
    "exercise",
    "food_cafes",
    "travel",
    "photo_video",
    "exhibitions_performances_art",
    "fashion_beauty",
    "self_development_study",
)
SELF_TRAITS = (
    "calm",
    "energetic",
    "deep_conversation",
    "light_humor",
    "listener",
    "conversation_leader",
)
DESIRED = (
    "similar",
    "different",
    "deep_conversation",
    "comfortable_humor",
    "passionate",
    "calm_stable",
)
GENDERS = ("남성", "여성")


@dataclass
class Scenario:
    shape: str
    seed: int
    participants: list[Participant]
    capacity: int = POOL_SIZE
    exclusions: frozenset = frozenset()
    met_pairs: frozenset = frozenset()
    known_optimum: int | None = None  # constructed: witness exists and bound is tight
    notes: dict = field(default_factory=dict)


def _id(seed, index):
    return f"s{seed}-a{index:03d}"


def _homogeneous(app_id, birth_year, index):
    """Identical preferences: every age-valid table of these people scores >= 70.

    age 100 (same year) and mbti/interest/trait/new 100 give at least 70 even when the
    gender component is 0, so any 4..6 group of equal birth years passes minimum 60.
    """
    return Participant(
        application_id=app_id,
        user_id=app_id,
        birth_year=birth_year,
        gender=GENDERS[index % 2],
        mbtis=("INTJ",),
        interests=("music", "reading"),
        self_traits=("calm",),
        desired_traits=("calm_stable",),
    )


def _random_person(rng, app_id, birth_year, gender):
    return Participant(
        application_id=app_id,
        user_id=app_id,
        birth_year=birth_year,
        gender=gender,
        mbtis=tuple(rng.sample(MBTIS, rng.choice((0, 1, 1, 1)))),
        interests=tuple(rng.sample(INTERESTS, rng.randint(1, 3))),
        self_traits=tuple(rng.sample(SELF_TRAITS, rng.randint(1, 2))),
        desired_traits=tuple(rng.sample(DESIRED, rng.randint(0, 2))),
    )


def uniform_random(seed):
    """Random attributes, birth years 1985..2004, a few met pairs. Optimum unknown."""
    rng = random.Random(f"uniform-{seed}")
    people = [
        _random_person(rng, _id(seed, i), rng.randint(1985, 2004), rng.choice(GENDERS + ("",)))
        for i in range(POOL_SIZE)
    ]
    ids = [p.application_id for p in people]
    met = frozenset(frozenset(rng.sample(ids, 2)) for _ in range(30))
    return Scenario("uniform_random", seed, people, met_pairs=met)


def skewed(seed):
    """85% one gender, ages bunched in 1996..1999 with a long tail, two popular interests."""
    rng = random.Random(f"skewed-{seed}")
    people = []
    for i in range(POOL_SIZE):
        year = rng.randint(1996, 1999) if rng.random() < 0.7 else rng.randint(1980, 2005)
        gender = "여성" if rng.random() < 0.85 else "남성"
        person = _random_person(rng, _id(seed, i), year, gender)
        if rng.random() < 0.6:
            person = replace(person, interests=("food_cafes", "travel")[: rng.randint(1, 2)])
        people.append(person)
    return Scenario("skewed_gender_age", seed, people)


def two_age_groups(seed):
    """50 born 1990 + 50 born 2005 (gap 15, never mixed). Witness: 10 tables of 5 each."""
    rng = random.Random(f"two-groups-{seed}")
    years = [1990] * 50 + [2005] * 50
    rng.shuffle(years)  # submission order does not follow the groups
    people = [_homogeneous(_id(seed, i), year, i) for i, year in enumerate(years)]
    return Scenario("two_age_groups", seed, people, known_optimum=POOL_SIZE)


def dense_exclusions(seed):
    """100 equal-age people; witness partition 20x5; ~30% of cross-group pairs excluded.

    Exclusions never fall inside a witness table, so 100 stays seatable (= trivial bound).
    """
    rng = random.Random(f"exclusions-{seed}")
    order = list(range(POOL_SIZE))
    rng.shuffle(order)
    group = {person: position // 5 for position, person in enumerate(order)}
    people = [_homogeneous(_id(seed, i), 1995, i) for i in range(POOL_SIZE)]
    exclusions = frozenset(
        frozenset({_id(seed, a), _id(seed, b)})
        for a in range(POOL_SIZE)
        for b in range(a + 1, POOL_SIZE)
        if group[a] != group[b] and rng.random() < 0.3
    )
    return Scenario(
        "dense_exclusions",
        seed,
        people,
        exclusions=exclusions,
        known_optimum=POOL_SIZE,
        notes={"excluded_pairs": len(exclusions)},
    )


def isolated_and_unknown_age(seed):
    """92 equal-age, 3 isolated (gap > 8, too few for a table), 5 without a birth year.

    Upper bound 92: the isolated three cannot sit with anyone or alone, unknown ages are
    never seated; witness: 92 = 6x12 + 4x5 tables of equal ages.
    """
    rng = random.Random(f"isolated-{seed}")
    kinds = ["main"] * 92 + ["isolated"] * 3 + ["unknown"] * 5
    rng.shuffle(kinds)
    year = {"main": 1997, "isolated": 1970, "unknown": None}
    people = [_homogeneous(_id(seed, i), year[kind], i) for i, kind in enumerate(kinds)]
    return Scenario("isolated_and_unknown_age", seed, people, known_optimum=92)


def capacity_limited(seed):
    """100 equal-age people, slot capacity 62 (= 6x9 + 4x2). Optimum 62."""
    rng = random.Random(f"capacity-{seed}")
    years = [rng.choice((1993, 1994)) for _ in range(POOL_SIZE)]
    people = [_homogeneous(_id(seed, i), y, i) for i, y in enumerate(years)]
    # Two adjacent birth years: age component 87.5, still >= 60 for every table.
    return Scenario("capacity_limited", seed, people, capacity=62, known_optimum=62)


SHAPES = {
    "uniform_random": uniform_random,
    "skewed_gender_age": skewed,
    "two_age_groups": two_age_groups,
    "dense_exclusions": dense_exclusions,
    "isolated_and_unknown_age": isolated_and_unknown_age,
    "capacity_limited": capacity_limited,
}


def independent_upper_bound(scenario):
    """min(capacity, people with a known age inside some 9-year window holding >= 4).

    A seated person needs three others within the age gap, so anyone failing this cannot
    be seated. Independent of the planner; loose for score/exclusion-limited pools.
    """
    years = [p.birth_year for p in scenario.participants if p.birth_year is not None]
    counts = Counter(years)
    possible = 0
    for year in years:
        if any(
            sum(counts[y] for y in range(start, start + hard.MAX_AGE_GAP + 1)) >= 4
            for start in range(year - hard.MAX_AGE_GAP, year + 1)
        ):
            possible += 1
    return min(scenario.capacity, possible)


def _run(scenario):
    return plan_allocation(
        scenario.participants,
        scenario.capacity,
        policy=DEFAULT_POLICY,
        exclusions=scenario.exclusions,
        met_pairs=scenario.met_pairs,
    )


def measure(scenario, trace_memory=True):
    """One scenario: two timed runs (determinism), one traced run (memory), oracle checks.

    tracemalloc roughly doubles the planner's run time, so the traced run is used for the
    memory peak only; its seated count and completeness are kept as a slowdown signal,
    because the planner's 5 second wall-clock guard can cut the search on a slower run.
    """
    started = time.perf_counter()
    plan = _run(scenario)
    seconds = time.perf_counter() - started
    started = time.perf_counter()
    repeat = _run(scenario)
    repeat_seconds = time.perf_counter() - started

    traced, peak = repeat, None
    if trace_memory:
        tracemalloc.start()
        traced = _run(scenario)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    ids = [p.application_id for p in scenario.participants]
    seated_ids = [app_id for table in plan.tables for app_id in table]
    unseated_ids = [app_id for app_id, _ in plan.unseated]
    accounted = Counter(seated_ids + unseated_ids)
    duplicate_seats = sum(n - 1 for n in Counter(seated_ids).values() if n > 1)
    missing = sum(1 for app_id in ids if app_id not in accounted)
    double_accounted = sum(1 for n in accounted.values() if n > 1)
    unknown_output = sum(1 for app_id in accounted if app_id not in set(ids))

    known_age = [p for p in scenario.participants if p.birth_year is not None]
    oracle_roster = [
        hard.Participant(
            id=p.application_id,
            paid=True,
            consented_slots=frozenset({SLOT}),
            birth_year=p.birth_year,
        )
        for p in known_age
    ]
    oracle_tables = [
        hard.Table(table_id=f"t{n}", slot=SLOT, members=table)
        for n, table in enumerate(plan.tables)
    ]
    hard_violations = hard.validate_assignment(
        oracle_roster, oracle_tables, excluded_pairs=scenario.exclusions
    )
    order = {p.application_id: n for n, p in enumerate(scenario.participants)}
    oracle_members = [
        oracle_scoring.Member(
            user_id=p.application_id,
            birth_year=p.birth_year,
            gender=p.gender,
            mbtis=p.mbtis,
            interests=p.interests,
            self_traits=p.self_traits,
            desired_traits=p.desired_traits,
            order=order[p.application_id],
        )
        for p in known_age
    ]
    oracle_policy = oracle_scoring.Policy(
        weights=oracle_scoring.DEFAULT_POLICY.weights, min_score=DEFAULT_POLICY.min_score
    )
    score_violations = oracle_scoring.validate_allocation(
        plan.tables,
        oracle_members,
        scenario.capacity,
        oracle_policy,
        scenario.exclusions,
        scenario.met_pairs,
    )
    bound = independent_upper_bound(scenario)
    reference = scenario.known_optimum if scenario.known_optimum is not None else bound
    sizes = Counter(len(table) for table in plan.tables)
    return {
        "shape": scenario.shape,
        "seed": scenario.seed,
        "participants": len(ids),
        "capacity": scenario.capacity,
        "seconds": seconds,
        "peak_traced_bytes": peak,
        "seated": plan.seated_count,
        "tables": len(plan.tables),
        "table_sizes": {str(k): v for k, v in sorted(sizes.items())},
        "min_table_score": float(min(plan.table_scores)) if plan.table_scores else None,
        "known_optimum": scenario.known_optimum,
        "upper_bound": bound,
        "gap_to_reference": reference - plan.seated_count,
        "hard_violations": len(hard_violations),
        "score_violations": len(score_violations),
        "duplicate_seats": duplicate_seats,
        "missing": missing,
        "double_accounted": double_accounted,
        "unknown_output": unknown_output,
        "seated_count_consistent": plan.seated_count == len(seated_ids),
        "deterministic": repeat.tables == plan.tables and repeat.unseated == plan.unseated,
        "repeat_seconds": repeat_seconds,
        "search_complete": plan.search_complete and repeat.search_complete,
        "over_adr_target": max(seconds, repeat_seconds) > ADR_TARGET_SECONDS,
        "traced_seated": traced.seated_count,
        "traced_search_complete": traced.search_complete,
        "unseated_reasons": dict(sorted(Counter(r for _, r in plan.unseated).items())),
        **scenario.notes,
    }


def is_clean(result):
    """The checks that must hold for every run regardless of unapproved thresholds."""
    return (
        result["hard_violations"] == 0
        and result["score_violations"] == 0
        and result["duplicate_seats"] == 0
        and result["missing"] == 0
        and result["double_accounted"] == 0
        and result["unknown_output"] == 0
        and result["seated_count_consistent"]
        and result["deterministic"]
        and result["seated"] <= result["upper_bound"]
    )


def run_all(seeds, shapes=None):
    return [measure(SHAPES[name](seed)) for name in (shapes or SHAPES) for seed in seeds]


def summarize(results):
    rows = []
    for shape in dict.fromkeys(r["shape"] for r in results):
        group = [r for r in results if r["shape"] == shape]
        seconds = [r["seconds"] for r in group] + [r["repeat_seconds"] for r in group]
        rows.append(
            {
                "shape": shape,
                "runs": len(group),
                "clean_runs": sum(is_clean(r) for r in group),
                "seconds_median": statistics.median(seconds),
                "seconds_max": max(seconds),
                "peak_mib_max": max(r["peak_traced_bytes"] for r in group) / 2**20,
                "seated_min": min(r["seated"] for r in group),
                "seated_max": max(r["seated"] for r in group),
                "reference": sorted({r["known_optimum"] or r["upper_bound"] for r in group}),
                "reference_kind": "known optimum"
                if group[0]["known_optimum"] is not None
                else "upper bound",
                "gap_max": max(r["gap_to_reference"] for r in group),
                "violations": sum(r["hard_violations"] + r["score_violations"] for r in group),
                "duplicates": sum(r["duplicate_seats"] for r in group),
                "missing": sum(r["missing"] for r in group),
                "incomplete_search": sum(not r["search_complete"] for r in group),
                "over_5s": sum(r["over_adr_target"] for r in group),
                "traced_cut": sum(not r["traced_search_complete"] for r in group),
                "traced_seated_min": min(r["traced_seated"] for r in group),
            }
        )
    return rows


def environment():
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    return {
        "machine": platform.machine(),
        "system": platform.system(),
        "python": platform.python_version(),
        "commit": sha,
        "min_score": str(DEFAULT_POLICY.min_score),
        "policy_version": DEFAULT_POLICY.version,
    }


def markdown(results, env):
    lines = [
        "| shape | runs | clean | median s | max s | peak MiB | seated | reference | "
        "max gap | violations | dup | missing | incomplete | >5s | traced cut (min seated) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in summarize(results):
        seated = (
            str(row["seated_min"])
            if row["seated_min"] == row["seated_max"]
            else f"{row['seated_min']}~{row['seated_max']}"
        )
        reference = "/".join(str(v) for v in row["reference"])
        lines.append(
            f"| {row['shape']} | {row['runs']} | {row['clean_runs']} | "
            f"{row['seconds_median']:.3f} | {row['seconds_max']:.3f} | "
            f"{row['peak_mib_max']:.2f} | {seated} | {reference} ({row['reference_kind']}) | "
            f"{row['gap_max']} | {row['violations']} | {row['duplicates']} | "
            f"{row['missing']} | {row['incomplete_search']} | {row['over_5s']} | "
            f"{row['traced_cut']} ({row['traced_seated_min']}) |"
        )
    total = len(results)
    clean = sum(is_clean(r) for r in results)
    slowest = max(max(r["seconds"], r["repeat_seconds"]) for r in results)
    lines.append("")
    lines.append(
        f"runs={total} clean={clean} max_seconds={slowest:.3f} "
        f"process_max_rss={_max_rss_mib():.1f}MiB machine={env['machine']} "
        f"python={env['python']} commit={env['commit'][:12]} min_score={env['min_score']}"
    )
    return "\n".join(lines)


def _max_rss_mib():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 2**20 if sys.platform == "darwin" else rss / 2**10


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5, help="seeds per shape")
    parser.add_argument("--json", action="store_true", help="also print per-run JSON")
    args = parser.parse_args(argv)
    env = environment()
    results = run_all(range(args.seeds))
    print(markdown(results, env))
    if args.json:
        print(json.dumps({"environment": env, "runs": results}, ensure_ascii=False, indent=1))
    return 0 if all(is_clean(r) for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
