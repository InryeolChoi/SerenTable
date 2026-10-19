"""Run one deterministic, file-preserving shard of the complete pytest collection."""

import argparse
from collections import Counter

import pytest


def assign_files(nodeids: list[str], count: int) -> dict[str, int]:
    """Balance collected test counts; never split a module's shared fixtures."""
    if count < 1:
        raise ValueError("shard count must be positive")
    sizes = Counter(nodeid.split("::", 1)[0] for nodeid in nodeids)
    loads = [0] * count
    assignment = {}
    for path in sorted(sizes, key=lambda path: (-sizes[path], path)):
        shard = min(range(count), key=lambda index: (loads[index], index))
        assignment[path] = shard
        loads[shard] += sizes[path]
    return assignment


class Shard:
    def __init__(self, index: int, count: int):
        self.index = index
        self.count = count

    def pytest_collection_modifyitems(self, config, items):
        assignment = assign_files([item.nodeid for item in items], self.count)
        selected, deselected = [], []
        for item in items:
            target = (
                selected if assignment[item.nodeid.split("::", 1)[0]] == self.index else deselected
            )
            target.append(item)
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True, help="one-based shard index")
    parser.add_argument("--shards", type=int, default=4)
    options, arguments = parser.parse_known_args()
    if not 1 <= options.shard <= options.shards:
        parser.error("require 1 <= shard <= shards")
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    return pytest.main(arguments, plugins=[Shard(options.shard - 1, options.shards)])


if __name__ == "__main__":
    raise SystemExit(main())
