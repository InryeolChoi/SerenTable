"""Minimal immutable operator explanations, built from the planner's exact input."""

from collections import Counter
from itertools import combinations

from serentable.matching_score import GENDERS, MBTI_TYPES, individual_trait_scores


def table_explanation(members, previous_pairs, penalized_pairs):
    genders = Counter(m.gender for m in members if m.gender in GENDERS)
    mbtis = Counter(t for m in members for t in set(m.mbtis) if t in MBTI_TYPES)
    interests = Counter(i for m in members for i in set(m.interests))
    pairs = [frozenset((a.user_id, b.user_id)) for a, b in combinations(members, 2)]
    return {
        "version": 1,
        "birth_year_min": min(m.birth_year for m in members),
        "birth_year_max": max(m.birth_year for m in members),
        "gender_counts": dict(sorted(genders.items())),
        "gender_unknown_count": len(members) - sum(genders.values()),
        "mbti_counts": dict(sorted(mbtis.items())),
        "mbti_unknown_count": sum(not (set(m.mbtis) & MBTI_TYPES) for m in members),
        "shared_interests": [
            {"code": key, "count": count}
            for key, count in sorted(interests.items(), key=lambda item: (-item[1], item[0]))
            if count >= 2
        ],
        "previous_pair_count": sum(pair in previous_pairs for pair in pairs),
        "newness_penalized_pair_count": sum(pair in penalized_pairs for pair in pairs),
    }


def member_explanation(member, peers, previous_pairs, transfers, reallocations, format_score):
    return {
        "version": 1,
        "trait_satisfaction": {
            code: format_score(score)
            for code, score in individual_trait_scores(member, peers).items()
        },
        "previous_peer_count": sum(
            frozenset((member.user_id, peer.user_id)) in previous_pairs for peer in peers
        ),
        "transfer_count": transfers,
        # PRD §7.2: earlier unseated runs that continued to another consented candidate
        # slot without a participant choice (a choice to move is counted as a transfer).
        "reallocation_count": reallocations,
    }
