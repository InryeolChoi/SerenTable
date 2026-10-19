"""Independent oracle for the ADR-0011 table score, minimum score and allocation objective.

The only specification is ``docs/adr/0011-prd-matching-score-and-objective.md``. This module
deliberately shares no code with ``backend/serentable``: pure Python, standard library only,
exact rational arithmetic (``Fraction``), no DB.

Where the ADR is ambiguous the most literal reading is implemented and marked ``ADR 모호점``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations

MIN_TABLE_SIZE = 4
MAX_TABLE_SIZE = 6
MAX_AGE_GAP = 8
MAX_BRUTE_FORCE_CANDIDATES = 10

COMPONENTS = ("age", "gender", "mbti", "interest", "trait", "new")
MALE = "남성"
FEMALE = "여성"
MBTI_TYPES = frozenset(a + b + c + d for a in "EI" for b in "SN" for c in "TF" for d in "JP")

# 희망 성향 → 상대(j)의 본인 성향 중 하나라도 있으면 충족. similar/different는 별도 계산.
DESIRED_TRAIT_MATCHES: dict[str, frozenset[str]] = {
    "deep_conversation": frozenset({"deep_conversation"}),
    "comfortable_humor": frozenset({"light_humor"}),
    "calm_stable": frozenset({"calm", "listener"}),
    "passionate": frozenset({"energetic", "conversation_leader"}),
}

PairSet = frozenset[frozenset[str]]


@dataclass(frozen=True)
class Member:
    user_id: str
    birth_year: int | None
    gender: str
    mbtis: tuple[str, ...]
    interests: tuple[str, ...]
    self_traits: tuple[str, ...]
    desired_traits: tuple[str, ...]
    order: int  # 신청 순서, 작을수록 먼저


@dataclass(frozen=True)
class Policy:
    weights: dict[str, Fraction]
    min_score: Fraction


DEFAULT_POLICY = Policy(
    weights={
        "age": Fraction(25, 100),
        "gender": Fraction(20, 100),
        "mbti": Fraction(15, 100),
        "interest": Fraction(15, 100),
        "trait": Fraction(10, 100),
        "new": Fraction(15, 100),
    },
    min_score=Fraction(50),
)


def _mean(values: list[Fraction]) -> Fraction | None:
    return sum(values, Fraction(0)) / len(values) if values else None


def _jaccard(first: frozenset[str], second: frozenset[str]) -> Fraction:
    union = first | second
    return Fraction(len(first & second), len(union)) if union else Fraction(0)


def _mbti_distance(first: str, second: str) -> int:
    return sum(1 for x, y in zip(first, second, strict=True) if x != y)


def _age_score(members: Sequence[Member]) -> Fraction:
    years = [m.birth_year for m in members]
    if any(year is None for year in years):
        raise ValueError("age score needs every birth year (H4 precondition)")
    return 100 * (1 - Fraction(max(years) - min(years), MAX_AGE_GAP))


def _gender_score(members: Sequence[Member]) -> Fraction | None:
    genders = [m.gender.strip() for m in members]
    male, female = genders.count(MALE), genders.count(FEMALE)
    counted = male + female
    if counted < 2:
        return None
    return 100 * Fraction(min(male, female), counted // 2)


def _mbti_score(members: Sequence[Member]) -> Fraction | None:
    # ADR 모호점: "대문자"를 입력 조건으로 읽어 소문자·공백 포함 값은 정규화하지 않고 무효로 둔다.
    valid = [frozenset(t for t in m.mbtis if t in MBTI_TYPES) for m in members]
    scores = [
        Fraction(100 - 5 * min(_mbti_distance(x, y) for x in a for y in b))
        for a, b in combinations(valid, 2)
        if a and b
    ]
    return _mean(scores)


def _interest_score(members: Sequence[Member]) -> Fraction | None:
    sets = [frozenset(m.interests) for m in members]
    scores = [100 * _jaccard(a, b) for a, b in combinations(sets, 2) if a or b]
    return _mean(scores)


def _desire_satisfaction(desired: str, own: frozenset[str], other: frozenset[str]) -> Fraction:
    if desired == "similar":
        return _jaccard(own, other)
    if desired == "different":
        # ADR 모호점: "(둘 다 비면 0)"을 Jaccard에 붙여 읽으므로 둘 다 비면 1 − 0 = 1.
        return 1 - _jaccard(own, other)
    # ADR 모호점: 대응표에 없는 희망 성향은 집합 D에 남기되 충족 0으로 본다.
    return Fraction(1) if DESIRED_TRAIT_MATCHES.get(desired, frozenset()) & other else Fraction(0)


def _trait_score(members: Sequence[Member]) -> Fraction | None:
    scores: list[Fraction] = []
    for i in members:
        desired = frozenset(i.desired_traits)
        if not desired:
            continue
        own = frozenset(i.self_traits)
        for j in members:
            if j is i:
                continue
            other = frozenset(j.self_traits)
            hits = [_desire_satisfaction(d, own, other) for d in sorted(desired)]
            scores.append(sum(hits, Fraction(0)) / len(hits))
    mean = _mean(scores)
    return None if mean is None else 100 * mean


def _new_score(members: Sequence[Member], met_pairs: PairSet) -> Fraction:
    pairs = [frozenset((a.user_id, b.user_id)) for a, b in combinations(members, 2)]
    if not pairs:
        raise ValueError("new score needs at least two members")
    met = sum(1 for pair in pairs if pair in met_pairs)
    return 100 * (1 - Fraction(met, len(pairs)))


def component_scores(
    members: Sequence[Member], met_pairs: PairSet = frozenset()
) -> dict[str, Fraction | None]:
    """ADR-0011 3절 항목 점수 S_k(T). ``None``은 계산 불가."""
    return {
        "age": _age_score(members),
        "gender": _gender_score(members),
        "mbti": _mbti_score(members),
        "interest": _interest_score(members),
        "trait": _trait_score(members),
        "new": _new_score(members, met_pairs),
    }


def table_score(
    members: Sequence[Member], policy: Policy = DEFAULT_POLICY, met_pairs: PairSet = frozenset()
) -> Fraction:
    """S(T) = Σ w_k·S_k / Σ_{계산 가능한 k} w_k (정확한 유리수, 반올림 없음).

    ADR 모호점: 반올림은 "기록 시"에만 하므로 최소 점수 비교·목적함수는 반올림 전 값을 쓴다.
    """
    scores = component_scores(members, met_pairs)
    computable = {k: s for k, s in scores.items() if s is not None}
    total_weight = sum((policy.weights.get(k, Fraction(0)) for k in computable), Fraction(0))
    if total_weight == 0:
        raise ValueError("no computable component carries weight")
    weighted = sum((policy.weights.get(k, Fraction(0)) * s for k, s in computable.items()), 0)
    return Fraction(weighted) / total_weight


def table_is_valid(members: Sequence[Member], exclusions: PairSet = frozenset()) -> bool:
    """H3(4~6명)·H4(출생연도 모두 있고 차 ≤ 8)·H5(제외 쌍 없음)·테이블 안 user_id 중복 없음."""
    ids = [m.user_id for m in members]
    if len(set(ids)) != len(ids):
        return False
    if not MIN_TABLE_SIZE <= len(members) <= MAX_TABLE_SIZE:
        return False
    years = [m.birth_year for m in members]
    if any(year is None for year in years) or max(years) - min(years) > MAX_AGE_GAP:
        return False
    return not any(frozenset(pair) in exclusions for pair in combinations(ids, 2))


def validate_allocation(
    tables: Sequence[Sequence[str]],
    candidates: Iterable[Member],
    capacity: int,
    policy: Policy = DEFAULT_POLICY,
    exclusions: PairSet = frozenset(),
    met_pairs: PairSet = frozenset(),
) -> list[str]:
    """배정(user_id 테이블 목록)의 위반 메시지 목록. 빈 리스트면 통과."""
    by_id = {m.user_id: m for m in candidates}
    violations: list[str] = []
    seen: dict[str, int] = {}
    for index, table in enumerate(tables):
        unknown = [uid for uid in table if uid not in by_id]
        if unknown:
            violations.append(f"table {index}: not a candidate {sorted(set(unknown))}")
        for uid in dict.fromkeys(table):
            if uid in seen:
                violations.append(f"table {index}: {uid} already seated at table {seen[uid]}")
            else:
                seen[uid] = index
        if unknown:
            continue
        members = [by_id[uid] for uid in table]
        if not table_is_valid(members, exclusions):
            violations.append(f"table {index}: hard constraint violated")
            continue
        score = table_score(members, policy, met_pairs)
        if score < policy.min_score:
            violations.append(f"table {index}: score {score} below minimum {policy.min_score}")
    seated = sum(len(table) for table in tables)
    if seated > capacity:
        violations.append(f"seated {seated} exceeds capacity {capacity}")
    return violations


def objective(
    tables: Sequence[Sequence[Member]],
    policy: Policy = DEFAULT_POLICY,
    met_pairs: PairSet = frozenset(),
) -> tuple[int, Fraction, Fraction, Fraction]:
    """ADR-0011 4절 3~6번의 사전식 키. 클수록 좋다. 1~2번(유효성)은 호출자가 먼저 거른다.

    ``(앉은 인원, Σ_T n_T·S(T), 최저 테이블 점수(테이블 없으면 0), 제출 우선 키)``.

    제출 우선 키 = Σ_{앉은 구성원} 2^(−order). ``order``가 서로 다른 0 이상 정수이면 이는
    "order 0을 최상위 비트로 두고 앉은 사람을 1로 둔 이진수"와 같은 값이다. 따라서 두 배정의
    키는 "어느 한쪽에만 앉은 사람 중 가장 먼저 신청한 사람"을 앉힌 쪽이 크다(후보 집합과
    무관하게 비교 가능). ADR 모호점: 기존 비트마스크의 정확한 정의와 동순위 order 처리는
    ADR에 없다.
    """
    scores = [table_score(table, policy, met_pairs) for table in tables]
    seated = sum(len(table) for table in tables)
    quality = sum((len(t) * s for t, s in zip(tables, scores, strict=True)), Fraction(0))
    lowest = min(scores) if scores else Fraction(0)
    priority = sum((Fraction(1, 2**m.order) for t in tables for m in t), Fraction(0))
    return seated, quality, lowest, priority


def best_allocation(
    candidates: Iterable[Member],
    capacity: int,
    policy: Policy = DEFAULT_POLICY,
    exclusions: PairSet = frozenset(),
    met_pairs: PairSet = frozenset(),
) -> tuple[tuple[tuple[str, ...], ...], tuple[int, Fraction, Fraction, Fraction]]:
    """완전탐색으로 4절 목적함수가 최대인 유효 배정(필수조건+최소 점수)을 찾는다.

    빈 배정도 후보다. 목적함수가 같은 배정이 여럿이면 (정렬된 테이블 튜플의) 사전식 최소를
    고른다. 이 동점 규칙은 결정성을 위한 정답기 관례이며 ADR의 결정이 아니다.
    """
    roster = sorted(candidates, key=lambda m: m.user_id)
    if len(roster) > MAX_BRUTE_FORCE_CANDIDATES:
        raise ValueError(
            f"brute force is limited to {MAX_BRUTE_FORCE_CANDIDATES} candidates, got {len(roster)}"
        )
    if len({m.user_id for m in roster}) != len(roster):
        raise ValueError("candidate user ids must be unique")
    orders = [m.order for m in roster]
    if len(set(orders)) != len(orders) or min(orders, default=0) < 0:
        raise ValueError("orders must be distinct non-negative integers")

    usable: list[tuple[tuple[Member, ...], Fraction]] = []
    for size in range(MIN_TABLE_SIZE, MAX_TABLE_SIZE + 1):
        for table in combinations(roster, size):
            if not table_is_valid(table, exclusions):
                continue
            score = table_score(table, policy, met_pairs)
            if score >= policy.min_score:
                usable.append((table, score))

    best_key: tuple[int, Fraction, Fraction, Fraction] | None = None
    best_tables: tuple[tuple[str, ...], ...] = ()

    def visit(start: int, used: frozenset[str], chosen: list[int]) -> None:
        nonlocal best_key, best_tables
        # objective()와 같은 키를 미리 계산한 테이블 점수로 만든다.
        tables = [usable[i][0] for i in chosen]
        scores = [usable[i][1] for i in chosen]
        key = (
            len(used),
            sum((len(t) * s for t, s in zip(tables, scores, strict=True)), Fraction(0)),
            min(scores) if scores else Fraction(0),
            sum((Fraction(1, 2**m.order) for t in tables for m in t), Fraction(0)),
        )
        canonical = tuple(sorted(tuple(m.user_id for m in t) for t in tables))
        if best_key is None or key > best_key or (key == best_key and canonical < best_tables):
            best_key, best_tables = key, canonical
        for index in range(start, len(usable)):
            table = usable[index][0]
            if len(used) + len(table) > capacity:
                continue
            if any(m.user_id in used for m in table):
                continue
            chosen.append(index)
            visit(index + 1, used | {m.user_id for m in table}, chosen)
            chosen.pop()

    visit(0, frozenset(), [])
    assert best_key is not None
    return best_tables, best_key
