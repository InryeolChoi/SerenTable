"""ADR-0011 sensitivity experiments on the organisers' synthetic sheet, aggregates only.

Reads the local ``data/우연한식탁_가상데이터.xlsx`` (never committed) through the existing
reader and prints only counts, distributions and timings; no row, name or answer is
printed. The sheet has no satisfaction labels, so nothing here says which policy makes
people happier (Predictive Validity is out of reach). Experiment-only assumptions:

- birth year = 2026 - stated age (only differences matter for the age rules);
- submission order = sheet row order (the sheet has no timestamps);
- one pool per chosen region; a person who chose several regions appears in each pool,
  so pools overlap and are reported separately, not summed into one population;
- gender is read from the raw column and kept only when it clearly says 남/여.

Usage: PYTHONPATH=backend uv run python scripts/matching_experiments.py
"""

import random
import statistics
import sys
import time
from collections import Counter
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import serentable.matching_score as score_module
import serentable.source_import as source_import
from serentable.matching import Participant, plan_allocation
from serentable.matching_score import DEFAULT_POLICY, DEFAULT_WEIGHTS, Policy, component_scores

SOURCE = Path("data/우연한식탁_가상데이터.xlsx")
YEAR = 2026


def load():
    original = source_import.normalize

    def with_gender(cells):
        normalized, review = original(cells)
        raw = cells.get("F", "").strip()
        normalized["gender"] = "여성" if "여" in raw else "남성" if "남" in raw else ""
        return normalized, review

    source_import.normalize = with_gender
    try:
        _, _, responses = source_import.read_source(SOURCE)
    finally:
        source_import.normalize = original
    return responses


def participants(responses, region, order=None):
    rows = [r for r in responses if region in r["data"]["source_regions"]]
    if order is not None:
        rows = [rows[i] for i in order(len(rows))]
    people = []
    for n, row in enumerate(rows):
        data = row["data"]
        age = data["source_age"]
        people.append(
            Participant(
                application_id=f"{region}-{n}",
                birth_year=None if age is None else YEAR - age,
                user_id=f"row-{row['row']}",
                gender=data["gender"],
                mbtis=tuple(data["mbtis"]),
                interests=tuple(data["source_interests"]),
                self_traits=tuple(data["source_self_traits"]),
                desired_traits=tuple(data["source_desired_traits"]),
            )
        )
    return people


def policy(min_score=50, weights=DEFAULT_WEIGHTS):
    return Policy(weights=weights, min_score=Fraction(min_score))


def evaluate(people, plan):
    """Common metrics, every table scored with the ADR default weights."""
    by_app = {p.application_id: p.member() for p in people}
    tables = [[by_app[a] for a in t] for t in plan.tables]
    scores = [score_module.table_score(t, DEFAULT_POLICY) for t in tables]
    return {
        "seated": plan.seated_count,
        "rate": plan.seated_count / len(people) if people else 0,
        "tables": len(tables),
        "unseated": len(people) - plan.seated_count,
        "mean": float(statistics.mean(scores)) if scores else 0.0,
        "min": float(min(scores)) if scores else 0.0,
        "complete": plan.search_complete,
        "pairs": {
            frozenset(pair) for t in tables for pair in combinations([m.user_id for m in t], 2)
        },
        "components": [component_scores(t) for t in tables],
    }


def run(people, capacity, chosen=None):
    started = time.monotonic()
    plan = (
        plan_allocation(people, capacity, policy=chosen)
        if chosen
        else plan_allocation(people, capacity)
    )
    result = evaluate(people, plan)
    result["seconds"] = time.monotonic() - started
    return result


def row(label, r, base_pairs=None):
    changed = ""
    if base_pairs is not None:
        union = base_pairs | r["pairs"]
        same = len(base_pairs & r["pairs"]) / len(union) if union else 1
        changed = f" | {1 - same:.0%}"
    return (
        f"| {label} | {r['seated']} | {r['rate']:.0%} | {r['tables']} | {r['unseated']} | "
        f"{r['mean']:.1f} | {r['min']:.1f} | {r['seconds']:.2f}s"
        f"{'' if r['complete'] else ' (상한)'}{changed} |"
    )


def mbti_model(step):
    def pair(left, right):
        a = [v for v in left if v in score_module.MBTI_TYPES]
        b = [v for v in right if v in score_module.MBTI_TYPES]
        if not a or not b:
            return None
        return 100 - step * min(sum(x != y for x, y in zip(p, q)) for p in a for q in b)

    return pair


def main():
    if not SOURCE.exists():
        sys.exit("source sheet not found; nothing was inferred")
    responses = load()
    regions = Counter(code for r in responses for code in r["data"]["source_regions"])
    genders = Counter(r["data"]["gender"] or "unknown" for r in responses)
    print(f"responses={len(responses)} region_pools={dict(regions)} gender={dict(genders)}")
    header = "| 조건 | 확정 | 성공률 | 테이블 | 미매칭 | 평균 점수 | 최저 점수 | 시간 |"
    for region in sorted(regions):
        people = participants(responses, region)
        cap = len(people)
        print(f"\n## {region} (pool {len(people)})\n")
        base = run(people, cap, policy())
        print(header + " 구성 변화 |\n|" + "---|" * 9)
        print(row("A: DP 기준선(점수 무시)", run(people, cap), base["pairs"]))
        print(row("A: ADR-0011 최소 50", base, base["pairs"]))
        for minimum in (40, 60, 70, 80):
            print(row(f"C: 최소 {minimum}", run(people, cap, policy(minimum)), base["pairs"]))
        for name in DEFAULT_WEIGHTS:
            for factor in (Fraction(1, 2), Fraction(3, 2)):
                raw = {k: v * (factor if k == name else 1) for k, v in DEFAULT_WEIGHTS.items()}
                total = sum(raw.values())
                weights = {k: v / total for k, v in raw.items()}
                print(
                    row(
                        f"D: {name} ×{float(factor)}",
                        run(people, cap, policy(50, weights)),
                        base["pairs"],
                    )
                )
        original = score_module._mbti_pair
        for label, model in (
            ("M0 동일", lambda a, b: 100 if a and b else None),
            ("M2 100-10d", mbti_model(10)),
        ):
            score_module._mbti_pair = model
            try:
                print(row(f"B: MBTI {label}", run(people, cap, policy()), base["pairs"]))
            finally:
                score_module._mbti_pair = original
        for seed in range(3):
            rng = random.Random(seed)
            shuffled = participants(responses, region, order=lambda n: rng.sample(range(n), n))
            print(row(f"E: 순서 섞기 seed {seed}", run(shuffled, cap, policy()), base["pairs"]))
        print(
            "\n항목 분포(최소 50 결과의 테이블, 0~100 원점수): "
            "최소 / 평균 / 최대 / 표준편차 / 가중치×표준편차"
        )
        for key, weight in DEFAULT_WEIGHTS.items():
            values = [float(c[key]) for c in base["components"] if c[key] is not None]
            if values:
                sd = statistics.pstdev(values)
                print(
                    f"- {key}: {min(values):.1f} / {statistics.mean(values):.1f} / "
                    f"{max(values):.1f} / {sd:.1f} / {float(weight) * sd:.2f} "
                    f"(계산 가능 {len(values)}/{len(base['components'])})"
                )


if __name__ == "__main__":
    main()
