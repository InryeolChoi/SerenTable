"""The CI partition must cover every test once and keep module state together."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("ci_pytest", Path("scripts/ci_pytest.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_partition_covers_every_file_once_and_is_independent_of_collection_order():
    nodeids = [
        f"tests/test_{file}.py::test_{case}" for file in range(11) for case in range(file + 1)
    ]
    assignment = module.assign_files(nodeids, 4)
    assert assignment == module.assign_files(list(reversed(nodeids)), 4)
    groups = [{node for node in nodeids if assignment[node.split("::")[0]] == i} for i in range(4)]
    assert set.union(*groups) == set(nodeids)
    assert sum(map(len, groups)) == len(nodeids)
    assert max(map(len, groups)) - min(map(len, groups)) <= 11
    assert set(assignment) == {node.split("::")[0] for node in nodeids}


def test_parameterized_tests_in_one_file_always_share_a_shard():
    nodes = [f"tests/test_shared.py::test_case[{i}]" for i in range(20)]
    assignment = module.assign_files(nodes + ["tests/test_other.py::test_a"], 4)
    assert len({assignment[node.split("::")[0]] for node in nodes}) == 1


def test_invalid_partition_count_is_rejected():
    with pytest.raises(ValueError):
        module.assign_files([], 0)
