"""Tests for the ADR-0011 scoring oracle.

Every expected value is hand-computed from ADR-0011 (shown in comments), never from the
oracle itself.
"""

import random
from fractions import Fraction

import pytest

from oracle.scoring import (
    DEFAULT_POLICY,
    Member,
    Policy,
    best_allocation,
    component_scores,
    objective,
    table_is_valid,
    table_score,
    validate_allocation,
)

ZERO = Fraction(0)
AGE_ONLY = {"age": Fraction(1), "gender": ZERO, "mbti": ZERO, "interest": ZERO}
AGE_ONLY |= {"trait": ZERO, "new": ZERO}


def member(
    user_id: str,
    birth_year: int | None = 1995,
    gender: str = "",
    mbtis: tuple[str, ...] = (),
    interests: tuple[str, ...] = (),
    self_traits: tuple[str, ...] = (),
    desired_traits: tuple[str, ...] = (),
    order: int = 0,
) -> Member:
    return Member(user_id, birth_year, gender, mbtis, interests, self_traits, desired_traits, order)


def pair(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


# 손계산 기준 테이블(4명, P = 6)
P1 = member(
    "p1", 1995, "남성", ("INTJ",), ("hiking", "coffee"), ("calm", "deep_conversation"),
    ("deep_conversation",), order=0,
)  # fmt: skip
P2 = member(
    "p2", 1997, "여성", ("ENTJ",), ("coffee",), ("light_humor",),
    ("comfortable_humor", "calm_stable"), order=1,
)  # fmt: skip
P3 = member("p3", 1999, " 여성 ", ("INFP", "ISFP"), (), (), (), order=2)
P4 = member(
    "p4", 1995, "기타", ("intj", "XXXX"), ("hiking",), ("energetic", "calm", "deep_conversation"),
    ("similar",), order=3,
)  # fmt: skip
TABLE = (P1, P2, P3, P4)
MET = frozenset({pair("p1", "p2"), pair("p1", "outsider")})


def test_age_component():
    # 최대 1999 − 최소 1995 = 4 → 100 × (1 − 4/8) = 50
    assert component_scores(TABLE, MET)["age"] == 50


def test_gender_component_counts_trimmed_male_and_female_only():
    # 남성: p1, 여성: p2·" 여성 "(공백 제거), "기타"는 제외 → m=1, f=2, k=3
    # 100 × min(1, 2) / ⌊3/2⌋ = 100 × 1/1 = 100
    assert component_scores(TABLE, MET)["gender"] == 100


def test_gender_component_six_people_two_men_four_women():
    # m=2, f=4, k=6 → 100 × 2 / 3 = 200/3
    genders = ["남성", "남성", "여성", "여성", "여성", "여성"]
    table = [member(f"g{i}", gender=g) for i, g in enumerate(genders)]
    assert component_scores(table)["gender"] == Fraction(200, 3)


def test_mbti_component_uses_minimum_distance_and_skips_invalid_types():
    # p4의 "intj"(소문자)·"XXXX"는 무효 → p4가 포함된 쌍 제외
    # p1-p2: INTJ/ENTJ d=1 → 95
    # p1-p3: INTJ/INFP d=2, INTJ/ISFP d=3 → min 2 → 90
    # p2-p3: ENTJ/INFP d=3, ENTJ/ISFP d=4 → min 3 → 85
    # 평균 (95 + 90 + 85) / 3 = 90
    assert component_scores(TABLE, MET)["mbti"] == 90


def test_interest_component_jaccard_mean():
    # p1{hiking,coffee}-p2{coffee} 1/2→50, p1-p3{} 0/2→0, p1-p4{hiking} 1/2→50,
    # p2-p3 0/1→0, p2-p4 0/2→0, p3-p4 0/1→0 (모두 빈 쌍 없음, 6쌍)
    # 평균 100/6 = 50/3
    assert component_scores(TABLE, MET)["interest"] == Fraction(50, 3)


def test_interest_pair_skipped_only_when_both_empty():
    # a{x}-b{x} 100, c·d 비어 있음: a-c 0, a-d 0, b-c 0, b-d 0, c-d 제외 → 5쌍
    # 평균 100/5 = 20
    table = [
        member("a", interests=("x",)),
        member("b", interests=("x",)),
        member("c"),
        member("d"),
    ]
    assert component_scores(table)["interest"] == 20


def test_trait_component_ordered_pair_mean():
    # p3은 D가 비어 i에서 제외 → i ∈ {p1, p2, p4}, 순서쌍 9개
    # p1 D={deep_conversation}: p2 0, p3 0, p4 1           → 합 1
    # p2 D={comfortable_humor, calm_stable}:
    #   p1 (0+1)/2, p3 (0+0)/2, p4 (0+1)/2                 → 합 1
    # p4 D={similar}: Jaccard(p4 본인 {energetic,calm,deep}, j 본인)
    #   p1 {calm,deep} 2/3, p2 {light_humor} 0/4, p3 {} 0/3 → 합 2/3
    # 평균 (1 + 1 + 2/3) / 9 = 8/27 → × 100 = 800/27
    assert component_scores(TABLE, MET)["trait"] == Fraction(800, 27)


def test_trait_different_with_both_empty_self_traits_is_one():
    # ADR 모호점(문자 그대로): "1 − Jaccard(둘 다 비면 0)" → 1 − 0 = 1
    # a D={different}, 모두 본인 성향 없음 → a의 순서쌍 3개 모두 1 → 100
    table = [member("a", desired_traits=("different",)), member("b"), member("c"), member("d")]
    assert component_scores(table)["trait"] == 100


def test_new_component():
    # P = 6, 이전에 만난 쌍 p1-p2 하나(p1-outsider는 테이블 밖) → 100 × (1 − 1/6) = 250/3
    assert component_scores(TABLE, MET)["new"] == Fraction(250, 3)


def test_default_weighted_table_score():
    # 모두 계산 가능, Σw = 1
    # .25×50 + .20×100 + .15×90 + .15×50/3 + .10×800/27 + .15×250/3
    # = 12.5 + 20 + 13.5 + 2.5 + 80/27 + 12.5 = 61 + 80/27 = 1727/27
    assert table_score(TABLE, DEFAULT_POLICY, MET) == Fraction(1727, 27)


# 계산 불가·재정규화 테이블: 성별 k=1, MBTI·관심사·희망 성향 모두 비어 있음
UNSCORABLE = (
    member("u1", 1996, "남성", order=0),
    member("u2", 1998, "기타", order=1),
    member("u3", 1997, "", order=2),
    member("u4", 1996, "unknown", order=3),
)


def test_uncomputable_components_are_none():
    scores = component_scores(UNSCORABLE)
    # 성별 k = 1 < 2, MBTI 유효 쌍 0, 관심사 쌍 모두 양쪽 비어 0, 희망 성향 순서쌍 0
    assert scores["gender"] is None
    assert scores["mbti"] is None
    assert scores["interest"] is None
    assert scores["trait"] is None
    # age: 1998 − 1996 = 2 → 100 × (1 − 2/8) = 75, new: 만난 쌍 없음 → 100
    assert scores["age"] == 75
    assert scores["new"] == 100


def test_renormalizes_over_computable_components():
    # (.25×75 + .15×100) / (.25 + .15) = (18.75 + 15) / .4 = 84.375 = 675/8
    assert table_score(UNSCORABLE) == Fraction(675, 8)


def test_minimum_score_boundary_is_inclusive():
    ids = [("u1", "u2", "u3", "u4")]
    at_minimum = Policy(DEFAULT_POLICY.weights, Fraction(675, 8))
    just_above = Policy(DEFAULT_POLICY.weights, Fraction(675, 8) + Fraction(1, 10**9))

    assert validate_allocation(ids, UNSCORABLE, 10, at_minimum) == []
    assert validate_allocation(ids, UNSCORABLE, 10, just_above) == [
        f"table 0: score {Fraction(675, 8)} below minimum {just_above.min_score}"
    ]


def test_table_validity_rules():
    four = [member(c) for c in "abcd"]
    assert table_is_valid(four)
    assert not table_is_valid(four[:3])  # H3: 3명
    assert not table_is_valid([member(c) for c in "abcdefg"])  # H3: 7명
    assert table_is_valid([member("a", 1990), member("b"), member("c"), member("d", 1998)])
    assert not table_is_valid([member("a", 1990), member("b"), member("c"), member("d", 1999)])
    assert not table_is_valid([member("a", None), *four[1:]])  # H4: 출생연도 없음
    assert not table_is_valid(four, frozenset({pair("b", "d")}))  # H5
    assert not table_is_valid([four[0], *four])  # 같은 테이블 안 user_id 중복


def test_validate_allocation_catches_exclusion_duplicate_unknown_and_capacity():
    people = [member(c, order=i) for i, c in enumerate("abcdefgh")]
    lenient = Policy(DEFAULT_POLICY.weights, ZERO)

    excluded = validate_allocation(
        [("a", "b", "c", "d")], people, 10, lenient, frozenset({pair("a", "c")})
    )
    assert excluded == ["table 0: hard constraint violated"]

    duplicated = validate_allocation(
        [("a", "b", "c", "d"), ("d", "e", "f", "g")], people, 10, lenient
    )
    assert duplicated == ["table 1: d already seated at table 0"]

    unknown = validate_allocation([("a", "b", "c", "zz")], people, 10, lenient)
    assert unknown == ["table 0: not a candidate ['zz']"]

    over = validate_allocation([("a", "b", "c", "d"), ("e", "f", "g", "h")], people, 7, lenient)
    assert over == ["seated 8 exceeds capacity 7"]


# 그리디 반례: 연령 점수만 쓰는 정책(가중치 age=1), 최소 점수 50.
# a,b,c,d: 2000년생 / e,f,g,h: 1996년생 / 제외 쌍 e-f, g-h
# - {a,b,c,d}: 차 0 → 100. 1996년생만으로 4명 이상은 {e,f,g,h}뿐인데 제외 쌍 때문에 무효.
#   두 연령이 섞인 테이블은 차 4 → 50. 따라서 점수 최고 테이블은 {a,b,c,d} 하나뿐(100).
# - 그리디가 {a,b,c,d}를 먼저 고정하면 남는 {e,f,g,h}는 무효 → 앉은 인원 4.
# - 각 테이블에 2000년생 2명 + {e,f} 중 1명 + {g,h} 중 1명을 두면 두 테이블 모두 50 ≥ 50
#   → 앉은 인원 8. Σ n·S = 4×50 + 4×50 = 400, 최저 50.
GREEDY_POLICY = Policy(AGE_ONLY, Fraction(50))
GREEDY_PEOPLE = [member(c, 2000, order=i) for i, c in enumerate("abcd")] + [
    member(c, 1996, order=4 + i) for i, c in enumerate("efgh")
]
GREEDY_EXCLUSIONS = frozenset({pair("e", "f"), pair("g", "h")})


def test_greedy_highest_table_first_seats_fewer():
    by_id = {m.user_id: m for m in GREEDY_PEOPLE}
    top = [by_id[c] for c in "abcd"]
    rest = [by_id[c] for c in "efgh"]
    assert table_score(top, GREEDY_POLICY) == 100
    assert not table_is_valid(rest, GREEDY_EXCLUSIONS)

    tables, key = best_allocation(GREEDY_PEOPLE, 10, GREEDY_POLICY, GREEDY_EXCLUSIONS)

    # 동점 배정은 정렬된 테이블 튜플의 사전식 최소를 고른다(정답기 관례).
    assert tables == (("a", "b", "e", "g"), ("c", "d", "f", "h"))
    # 제출 우선 키: 8명 모두 앉음 → Σ 2^(−order), order 0..7 = 2 − 2^(−7) = 255/128
    assert key == (8, Fraction(400), Fraction(50), Fraction(255, 128))
    chosen = [[by_id[uid] for uid in table] for table in tables]
    assert objective(chosen, GREEDY_POLICY) == key
    assert validate_allocation(tables, GREEDY_PEOPLE, 10, GREEDY_POLICY, GREEDY_EXCLUSIONS) == []


def test_capacity_limits_best_allocation():
    # 정원 7이면 두 테이블(8명)은 불가 → {a,b,c,d} 하나(100)가 최선
    tables, key = best_allocation(GREEDY_PEOPLE, 7, GREEDY_POLICY, GREEDY_EXCLUSIONS)
    # 정원 7 → 테이블 하나만 가능(두 테이블은 최소 8명). 인원이 품질보다 먼저이므로
    # {a,b,c,d}(4명, 100)보다 6명 테이블이 낫다. 유효한 6명 테이블은 2000년생 4명 전원 +
    # {e,f} 중 1명 + {g,h} 중 1명뿐(제외 쌍) → 모두 50, Σ = 6×50 = 300, 최저 50.
    # 제출 우선: e(4) > f(5), g(6) > h(7) → {a,b,c,d,e,g}, 키 = 1+1/2+1/4+1/8+1/16+1/64
    assert tables == (("a", "b", "c", "d", "e", "g"),)
    assert key == (6, Fraction(300), Fraction(50), Fraction(125, 64))


def test_submission_order_breaks_ties_toward_earlier_applicants():
    # 전원 1995년생(연령 점수 100), 정원 4라 5명 테이블은 불가.
    # 모든 4명 조합이 인원 4·Σ 400·최저 100으로 같으므로 제출 우선: 가장 늦은 e를 뺀다.
    people = [member(c, order=i) for i, c in enumerate("abcde")]
    tables, key = best_allocation(people, 4, GREEDY_POLICY)
    assert tables == (("a", "b", "c", "d"),)
    assert key[3] == Fraction(15, 8)  # 1 + 1/2 + 1/4 + 1/8


def test_empty_allocation_when_nothing_is_valid():
    people = [member(c, order=i) for i, c in enumerate("abc")]
    assert best_allocation(people, 10) == ((), (0, ZERO, ZERO, ZERO))


def test_best_allocation_is_deterministic_under_input_shuffle():
    expected = best_allocation(GREEDY_PEOPLE, 10, GREEDY_POLICY, GREEDY_EXCLUSIONS)
    rng = random.Random(20261017)
    for _ in range(5):
        shuffled = GREEDY_PEOPLE[:]
        rng.shuffle(shuffled)
        assert best_allocation(shuffled, 10, GREEDY_POLICY, GREEDY_EXCLUSIONS) == expected


def test_best_allocation_rejects_more_than_ten_candidates():
    with pytest.raises(ValueError):
        best_allocation([member(f"x{i}", order=i) for i in range(11)], 20)
