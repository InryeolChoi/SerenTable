"""Work #10 100-person measurement core on a few seeds (no DB, no data/ files).

Runs ``scripts/measure_matching_scale.py``'s measurement on synthetic 100-person pools and
checks only what must hold regardless of unapproved thresholds: no hard-constraint or
minimum-score violation by the independent oracles, no duplicate seat, no missing or
invented participant, seated count within capacity and the independent upper bound, and
identical results on a repeated run. Time and memory are measured by the script, not
asserted here (no acceptance number is approved; ADR-0011's 5 s is a target).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_matching_scale.py"
spec = importlib.util.spec_from_file_location("measure_matching_scale", SCRIPT)
measure_matching_scale = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = measure_matching_scale  # dataclasses resolve their module
spec.loader.exec_module(measure_matching_scale)

CASES = [
    (shape, seed)
    for shape in (
        "uniform_random",
        "two_age_groups",
        "dense_exclusions",
        "isolated_and_unknown_age",
    )
    for seed in (0, 1)
]


@pytest.mark.parametrize(("shape", "seed"), CASES)
def test_100_person_pool_has_no_violation_duplicate_or_missing_participant(shape, seed):
    scenario = measure_matching_scale.SHAPES[shape](seed)
    assert len(scenario.participants) == 100
    result = measure_matching_scale.measure(scenario, trace_memory=False)

    assert result["hard_violations"] == 0
    assert result["score_violations"] == 0
    assert result["duplicate_seats"] == 0
    assert result["missing"] == 0
    assert result["double_accounted"] == 0
    assert result["unknown_output"] == 0
    assert result["seated_count_consistent"]
    assert result["seated"] <= min(result["upper_bound"], result["capacity"])
    if result["known_optimum"] is not None:
        assert result["seated"] <= result["known_optimum"]
    assert set(result["table_sizes"]) <= {"4", "5", "6"}
    assert result["deterministic"]
    assert measure_matching_scale.is_clean(result)


def test_generated_pools_are_deterministic_per_seed():
    for name, build in measure_matching_scale.SHAPES.items():
        first, second = build(3), build(3)
        assert first.participants == second.participants, name
        assert first.exclusions == second.exclusions, name
        assert first.met_pairs == second.met_pairs, name


def test_constructed_known_optimum_matches_the_independent_upper_bound():
    # A constructed shape's optimum is "a witness exists and the bound is tight": the
    # stated number must equal the planner-independent upper bound, never exceed it.
    for name in ("two_age_groups", "dense_exclusions", "isolated_and_unknown_age"):
        scenario = measure_matching_scale.SHAPES[name](0)
        bound = measure_matching_scale.independent_upper_bound(scenario)
        assert scenario.known_optimum == bound, name
