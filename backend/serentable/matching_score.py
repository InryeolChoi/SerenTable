"""Table quality score and matching policy (ADR-0011), without the database.

Every component is 0..100 but keeps its natural spread; none is stretched to fill the
range. A component that cannot be computed for a table drops out and the remaining
weights are rescaled. Arithmetic is exact so ties compare the same on every machine.
"""

import os
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations, permutations

POLICY_VERSION = "prd-weighted-v1"
MAX_AGE_GAP = 8
MBTI_TYPES = frozenset(a + b + c + d for a in "IE" for b in "SN" for c in "TF" for d in "JP")
GENDERS = ("남성", "여성")
# Desired trait -> self traits that satisfy it (ADR-0011 §3). similar/different compare
# the two people's self traits instead.
TRAIT_MATCHES = {
    "deep_conversation": {"deep_conversation"},
    "comfortable_humor": {"light_humor"},
    "calm_stable": {"calm", "listener"},
    "passionate": {"energetic", "conversation_leader"},
}


@dataclass(frozen=True)
class Member:
    user_id: str
    birth_year: int | None
    gender: str = ""
    mbtis: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    self_traits: tuple[str, ...] = ()
    desired_traits: tuple[str, ...] = ()


@dataclass(frozen=True)
class Policy:
    weights: dict = field(hash=False)
    min_score: Fraction
    version: str = POLICY_VERSION

    def snapshot(self):
        """JSON-ready values recorded with each run."""
        return {
            "version": self.version,
            "weights": {key: str(value) for key, value in self.weights.items()},
            "min_score": str(self.min_score),
        }


DEFAULT_WEIGHTS = {
    "age": Fraction(1, 4),
    "gender": Fraction(1, 5),
    "mbti": Fraction(3, 20),
    "interest": Fraction(3, 20),
    "trait": Fraction(1, 10),
    "new": Fraction(3, 20),
}
# The weights are a design hypothesis, not estimated from satisfaction data. 50 is a
# development value until the 40..80 sensitivity analysis is approved (ADR-0011 §4).
DEFAULT_POLICY = Policy(weights=DEFAULT_WEIGHTS, min_score=Fraction(50))


def policy_from_environment():
    """MATCHING_MIN_SCORE overrides the minimum score; weights stay at the recorded set."""
    raw = os.getenv("MATCHING_MIN_SCORE", "").strip()
    if not raw:
        return DEFAULT_POLICY
    value = Fraction(raw)
    if not 0 <= value <= 100:
        raise ValueError("MATCHING_MIN_SCORE must be between 0 and 100")
    return Policy(weights=DEFAULT_WEIGHTS, min_score=value)


def _jaccard(left, right):
    union = set(left) | set(right)
    return Fraction(len(set(left) & set(right)), len(union)) if union else None


def _mbti_pair(left, right):
    a = [value for value in left if value in MBTI_TYPES]
    b = [value for value in right if value in MBTI_TYPES]
    if not a or not b:
        return None
    differing = min(sum(x != y for x, y in zip(p, q)) for p in a for q in b)
    return 100 - 5 * differing


def _trait_satisfaction(wanting, other):
    if not wanting.desired_traits:
        return None
    total = Fraction(0)
    for desired in wanting.desired_traits:
        if desired in ("similar", "different"):
            similarity = _jaccard(wanting.self_traits, other.self_traits) or Fraction(0)
            total += similarity if desired == "similar" else 1 - similarity
        else:
            total += 1 if TRAIT_MATCHES.get(desired, set()) & set(other.self_traits) else 0
    return total / len(wanting.desired_traits)


def _mean(values):
    present = [value for value in values if value is not None]
    return Fraction(sum(present), len(present)) if present else None


def component_scores(members, met_pairs=frozenset()):
    """Each ADR-0011 component for one table; None when it cannot be computed."""
    years = [m.birth_year for m in members]
    pairs = list(combinations(members, 2))
    known = [m.gender.strip() for m in members if m.gender.strip() in GENDERS]
    men, women = known.count(GENDERS[0]), known.count(GENDERS[1])
    interest = _mean(_jaccard(a.interests, b.interests) for a, b in pairs)
    trait = _mean(_trait_satisfaction(a, b) for a, b in permutations(members, 2))
    met = sum(frozenset({a.user_id, b.user_id}) in met_pairs for a, b in pairs)
    return {
        "age": 100 * (1 - Fraction(max(years) - min(years), MAX_AGE_GAP)),
        "gender": (100 * Fraction(min(men, women), len(known) // 2) if len(known) >= 2 else None),
        "mbti": _mean(_mbti_pair(a.mbtis, b.mbtis) for a, b in pairs),
        "interest": None if interest is None else 100 * interest,
        "trait": None if trait is None else 100 * trait,
        "new": 100 * (1 - Fraction(met, len(pairs))),
    }


def weighted_score(components, policy):
    available = {k: v for k, v in components.items() if v is not None}
    weight = sum(policy.weights[k] for k in available)
    return sum(policy.weights[k] * v for k, v in available.items()) / weight


def table_score(members, policy=DEFAULT_POLICY, met_pairs=frozenset()):
    return weighted_score(component_scores(members, met_pairs), policy)
