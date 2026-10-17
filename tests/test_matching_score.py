"""ADR-0011 table score and policy, checked against hand-computed values.

The expected numbers are worked out by hand in the comments, not recomputed with the
engine's formulas, so a wrong formula cannot agree with itself.
"""

from fractions import Fraction

from serentable.matching_score import DEFAULT_POLICY, Member, component_scores, table_score


def member(user_id, birth_year, gender, mbtis, interests, self_traits, desired):
    return Member(
        user_id=user_id,
        birth_year=birth_year,
        gender=gender,
        mbtis=tuple(mbtis),
        interests=tuple(interests),
        self_traits=tuple(self_traits),
        desired_traits=tuple(desired),
    )


A = member("a", 1995, "남성", ["INTJ"], ["music", "reading"], ["calm"], ["deep_conversation"])
B = member("b", 1997, "여성", ["INTP"], ["music"], ["deep_conversation"], ["calm_stable"])
C = member("c", 1999, "남성", ["ENFP"], ["travel"], ["energetic"], ["similar"])
D = member("d", 1995, "여성", [], ["music", "reading"], ["calm", "listener"], ["different"])
MET = frozenset({frozenset({"a", "b"})})


def test_each_component_matches_the_hand_calculation():
    scores = component_scores([A, B, C, D], MET)
    # Birth years 1995..1999: spread 4 of the allowed 8 -> 100 * (1 - 4/8).
    assert scores["age"] == 50
    # Two men and two women out of four known -> 100 * 2 / floor(4/2).
    assert scores["gender"] == 100
    # D has no MBTI, so only AB (1 letter differs, 95), AC (3, 85), BC (2, 90) count.
    assert scores["mbti"] == 90
    # Jaccard per pair: AB 1/2, AC 0, AD 1, BC 0, BD 1/2, CD 0 -> 2 over 6 pairs.
    assert scores["interest"] == Fraction(100, 3)
    # Ordered pairs: A wants deep talk (B yes) 1; B wants calm/listener (A, D) 2;
    # C wants similar (no shared self traits) 0; D wants different: A 1/2, B 1, C 1.
    # 5.5 over 12 ordered pairs.
    assert scores["trait"] == Fraction(1100, 24)
    # A and B met before: 1 of 6 pairs is not new.
    assert scores["new"] == Fraction(250, 3)


def test_the_weighted_score_matches_the_hand_calculation():
    # .25*50 + .20*100 + .15*90 + .15*100/3 + .10*1100/24 + .15*250/3
    # = 12.5 + 20 + 13.5 + 5 + 55/12 + 12.5 = 817/12
    assert table_score([A, B, C, D], DEFAULT_POLICY, MET) == Fraction(817, 12)


def test_an_incomputable_component_drops_out_and_the_rest_are_reweighted():
    unknown = [
        member(
            m.user_id,
            m.birth_year,
            "기록한 성별",
            m.mbtis,
            m.interests,
            m.self_traits,
            m.desired_traits,
        )
        for m in (A, B, C, D)
    ]
    assert component_scores(unknown, MET)["gender"] is None
    # Without gender (.20): (817/12 - 20) / .80 = (577/12) / (4/5) = 2885/48.
    assert table_score(unknown, DEFAULT_POLICY, MET) == Fraction(2885, 48)


def test_the_default_policy_is_the_recorded_hypothesis():
    weights = DEFAULT_POLICY.weights
    assert sum(weights.values()) == 1
    assert (weights["age"], weights["gender"], weights["mbti"]) == (
        Fraction(1, 4),
        Fraction(1, 5),
        Fraction(3, 20),
    )
    assert DEFAULT_POLICY.min_score == 60
