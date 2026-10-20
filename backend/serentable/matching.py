"""Reserved matching: hard-constraint allocation, its automatic execution, and history.

Contract: ``docs/design/matching-contract.md`` (Work #6 Task ①-a, decisions approved
2026-10-17). The approved rules this module implements:

- hard constraints identical to ``tests/oracle/hard_constraints.py`` (the oracle is
  deliberately independent code and is not imported here), plus excluded pairs;
- ADR-0011: every table reaches the policy's minimum score, then seat as many as possible,
  then the participant-weighted score sum, the lowest table score and submission order;
- one live table assignment per application and one confirmed table per user at a time,
  slots processed by ``matches_at`` and then by slot id (U07);
- reallocation across slots (①-c) is not done here.

``age-ordered-dp-v2`` (``plan_allocation`` without a policy) is kept as the starting point
and the regression baseline; the policy search never seats more than it does.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from serentable.auth import Principal, private_response, require_operator
from serentable.clock import iso, locked_now
from serentable.database import database_engine
from serentable.eligibility import CANDIDATES, ELIGIBLE
from serentable.events import SLOT_COLUMNS, slot_json
from serentable.match_resolution import extend_final_failure, lock_matching
from serentable.matching_explanations import member_explanation, table_explanation
from serentable.matching_score import (
    MAX_AGE_GAP,
    Member,
    component_scores,
    policy_from_environment,
    weighted_score,
)

logger = logging.getLogger("serentable.worker")

router = APIRouter()

# Hard constraints, mirroring tests/oracle/hard_constraints.py (kept in step by test, not
# by a shared import).
MIN_TABLE_SIZE = 4
MAX_TABLE_SIZE = 6

BASELINE_ALGORITHM_VERSION = "age-ordered-dp-v2"
ALGORITHM_VERSION = "dp-repair-swap-v1"
BASELINE_RULE_VERSION = "u06-u07-2026-10-17"
RULE_VERSION = "adr-0011-2026-10-17"
# Deterministic bound on improvement passes; the wall clock only guards against a
# pathological input and is reported when it stops the search.
MAX_PASSES = 40
# ADR-0011 amendment 2026-10-19: raised from 5 s so slower hosts finish the 100-person
# search instead of cutting it (measured: one skewed pool 96 seated at 2.9 s, 76 when cut).
SEARCH_SECONDS = 8.0

# Why an application was left unseated; stored per member and shown to participants.
NOT_ENOUGH_ELIGIBLE = "not_enough_eligible"
CAPACITY = "capacity"
UNKNOWN_AGE = "unknown_age"
AGE_GAP = "age_gap"
NO_VALID_TABLE = "no_valid_table"
# The age-only baseline could seat this person, but the search found no table that also
# avoids excluded pairs and reaches the minimum score. A local search proves no more.
NO_QUALIFYING_TABLE = "no_qualifying_table"
# Already confirmed at another slot whose time overlaps this one (PRD §7.4).
OVERLAPPING_CONFIRMATION = "overlapping_confirmation"


@dataclass(frozen=True)
class Participant:
    """One application that may be seated in a slot, in submission order."""

    application_id: str
    birth_year: int | None
    user_id: str = ""
    gender: str = ""
    mbtis: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    self_traits: tuple[str, ...] = ()
    desired_traits: tuple[str, ...] = ()

    def member(self):
        return Member(
            user_id=self.user_id or self.application_id,
            birth_year=self.birth_year,
            gender=self.gender,
            mbtis=self.mbtis,
            interests=self.interests,
            self_traits=self.self_traits,
            desired_traits=self.desired_traits,
        )


@dataclass(frozen=True)
class AllocationPlan:
    tables: tuple[tuple[str, ...], ...]
    unseated: tuple[tuple[str, str], ...]
    seated_count: int
    algorithm_version: str = BASELINE_ALGORITHM_VERSION
    rule_version: str = BASELINE_RULE_VERSION
    table_scores: tuple[Fraction, ...] = ()
    table_components: tuple[dict, ...] = ()
    search_complete: bool = True


def plan_allocation(
    participants, capacity, policy=None, exclusions=frozenset(), met_pairs=frozenset()
):
    """Assign participants to tables, without touching the DB.

    With a ``policy`` this is the ADR-0011 search; without one it is the
    ``age-ordered-dp-v2`` baseline, which knows nothing of scores or exclusions.

    ``participants`` is in submission order, which is also the tie-break: of two
    allocations that seat the same number of people, the one seating earlier applicants
    wins. A participant with no recorded birth year cannot be checked against the age rule
    and is left unseated rather than seated unchecked.
    """
    roster = list(participants)
    if policy is not None:
        return _policy_allocation(roster, capacity, policy, exclusions, met_pairs)
    searchable = [index for index, person in enumerate(roster) if person.birth_year is not None]
    years = [roster[index].birth_year for index in searchable]
    grouped = _ordered_allocation(years, capacity)
    tables = tuple(
        tuple(roster[searchable[index]].application_id for index in members) for members in grouped
    )
    seated = {application_id for table in tables for application_id in table}
    roomy = _seatable_without_capacity(searchable, years, capacity)
    unseated = tuple(
        (person.application_id, _reason(roster, years, searchable, index, capacity, roomy))
        for index, person in enumerate(roster)
        if person.application_id not in seated
    )
    return AllocationPlan(
        tables=tables, unseated=unseated, seated_count=sum(len(table) for table in tables)
    )


def _ordered_allocation(years, capacity):
    """Exact count and submission-priority allocation for the current age-only rules.

    Any valid selected set can be partitioned in birth-year order without crossing
    tables: uncross two overlapping groups by sorting their union, preserving sizes.
    Both spans remain <= 8. Therefore the only unfinished group we need to remember is
    the last one. Equal states have identical possible continuations; retain the largest
    submission-priority bitmask. Arbitrary exclusion edges need a different algorithm.
    """
    # (open group's minimum year, open size, seated count) -> (priority mask, tables)
    states = {(None, 0, 0): (0, ())}
    for index in sorted(range(len(years)), key=lambda i: (years[i], i)):
        year = years[index]
        priority = 1 << (len(years) - 1 - index)
        following = dict(states)  # Skip this participant.

        def retain(key, mask, tables):
            previous = following.get(key)
            if previous is None or mask > previous[0]:
                following[key] = (mask, tables)

        for (minimum, size, seated), (mask, tables) in states.items():
            if seated >= capacity:
                continue
            if size and size < MAX_TABLE_SIZE and year - minimum <= MAX_AGE_GAP:
                retain(
                    (minimum, size + 1, seated + 1),
                    mask | priority,
                    tables[:-1] + (tables[-1] + (index,),),
                )
            if size == 0 or size >= MIN_TABLE_SIZE:
                retain((year, 1, seated + 1), mask | priority, tables + ((index,),))
        states = following
    _, _, tables = max(
        (seated, mask, tables)
        for (_, size, seated), (mask, tables) in states.items()
        if size == 0 or size >= MIN_TABLE_SIZE
    )
    return tables


def _seatable_without_capacity(searchable, years, capacity):
    """Roster indexes the age-only allocation seats when the slot capacity is no limit."""
    if capacity >= len(searchable):
        return frozenset()
    grouped = _ordered_allocation(years, len(searchable))
    return frozenset(searchable[member] for members in grouped for member in members)


def _reason(roster, years, searchable, index, capacity, roomy=frozenset()):
    """Why this application could not be seated, in a wording participants can read.

    ``roomy`` holds the people a slot without a capacity limit would seat; when the full
    slot is what left one of them out, the participant is told it is the capacity.
    """
    if roster[index].birth_year is None:
        return UNKNOWN_AGE
    if len(searchable) < MIN_TABLE_SIZE:
        return NOT_ENOUGH_ELIGIBLE
    if capacity < MIN_TABLE_SIZE or index in roomy:
        return CAPACITY
    position = searchable.index(index)
    others = [year for other, year in enumerate(years) if other != position]
    if not any(abs(years[position] - year) <= MAX_AGE_GAP for year in others):
        return AGE_GAP
    return NO_VALID_TABLE


class _Search:
    """ADR-0011 allocation: start from the DP, keep only tables that pass, then improve.

    Indices refer to ``roster`` (submission order). A candidate table is valid when it has
    4..6 people, an age span within 8, no excluded pair and a score >= the minimum.
    Moves are tried in a fixed order and accepted only when the objective
    (seated, sum n*S, min S, submission mask) strictly improves, so the result is
    deterministic and every accepted state stays valid. This is a local search: it may
    stop short of the global optimum (measured against the exhaustive oracle in tests).
    """

    def __init__(self, roster, capacity, policy, exclusions, met_pairs):
        self.roster, self.capacity, self.policy = roster, capacity, policy
        self.members = [person.member() for person in roster]
        self.exclusions, self.met_pairs = exclusions, met_pairs
        self.priority = [1 << (len(roster) - 1 - index) for index in range(len(roster))]
        self.cache = {}
        self.deadline = time.monotonic() + SEARCH_SECONDS

    def score(self, group):
        """The table's score when it is a valid table, else None (cached by member set)."""
        key = frozenset(group)
        if key not in self.cache:
            self.cache[key] = self._score(key)
        return self.cache[key]

    def _score(self, key):
        if not MIN_TABLE_SIZE <= len(key) <= MAX_TABLE_SIZE:
            return None
        members = [self.members[index] for index in sorted(key)]
        years = [member.birth_year for member in members]
        if max(years) - min(years) > MAX_AGE_GAP:
            return None
        users = [member.user_id for member in members]
        if any(
            frozenset({a, b}) in self.exclusions
            for i, a in enumerate(users)
            for b in users[i + 1 :]
        ):
            return None
        components = component_scores(members, self.met_pairs)
        value = weighted_score(components, self.policy)
        return (value, components) if value >= self.policy.min_score else None

    def objective(self, tables):
        scores = [self.score(table)[0] for table in tables]
        seated = sum(len(table) for table in tables)
        quality = sum(len(table) * value for table, value in zip(tables, scores))
        mask = sum(self.priority[index] for table in tables for index in table)
        return (seated, quality, min(scores, default=Fraction(0)), mask)

    def run(self, start):
        tables = [list(table) for table in start if self.score(table) is not None]
        complete = True
        for _ in range(MAX_PASSES):
            if time.monotonic() > self.deadline:
                complete = False
                break
            improved = self._pass(tables)
            if improved is None:
                break
            tables = improved
        return tables, complete

    def _seated(self, tables):
        return {index for table in tables for index in table}

    def _candidates(self, tables):
        """Neighbouring allocations in a fixed order; each keeps every table valid."""
        seated = self._seated(tables)
        pool = [
            index
            for index in range(len(self.roster))
            if index not in seated and self.members[index].birth_year is not None
        ]
        total = len(seated)
        # 1. Seat a waiting person at a table with room.
        if total < self.capacity:
            for person in pool:
                for t, table in enumerate(tables):
                    if len(table) < MAX_TABLE_SIZE:
                        yield self._replace(tables, {t: table + [person]})
            # 2. Open a new table from waiting people, nearest birth years first.
            yield from self._new_tables(tables, pool, total)
        # 3. Move one person to a table with room.
        for a, source in enumerate(tables):
            if len(source) <= MIN_TABLE_SIZE:
                continue
            for person in source:
                for b, target in enumerate(tables):
                    if a != b and len(target) < MAX_TABLE_SIZE:
                        yield self._replace(
                            tables, {a: [x for x in source if x != person], b: target + [person]}
                        )
        # 4. Swap two people between tables.
        for a in range(len(tables)):
            for b in range(a + 1, len(tables)):
                for x in tables[a]:
                    for y in tables[b]:
                        yield self._replace(
                            tables,
                            {
                                a: [y if i == x else i for i in tables[a]],
                                b: [x if i == y else i for i in tables[b]],
                            },
                        )
        # 5. Give a seat to a waiting person instead.
        for person in pool:
            for t, table in enumerate(tables):
                for x in table:
                    yield self._replace(tables, {t: [person if i == x else i for i in table]})

    def _new_tables(self, tables, pool, total):
        """Open a table around a waiting person, borrowing from tables that can spare one.

        A source table keeps at least four people. Borrowing keeps this move useful when
        an exclusion or the minimum score broke one of the DP's tables.
        """
        home = {index: t for t, table in enumerate(tables) for index in table}
        spare = [index for index, t in home.items() if len(tables[t]) > MIN_TABLE_SIZE]
        ordered = sorted(pool + spare, key=lambda i: (self.members[i].birth_year, i))
        waiting = set(pool)
        for first in sorted(pool, key=lambda i: (self.members[i].birth_year, i)):
            year = self.members[first].birth_year
            window = [
                i
                for i in ordered
                if i != first and abs(self.members[i].birth_year - year) <= MAX_AGE_GAP
            ]
            window = sorted(
                window, key=lambda i: (i not in waiting, abs(self.members[i].birth_year - year), i)
            )
            window = window[: MAX_TABLE_SIZE * 2]
            best = None
            for size in range(MAX_TABLE_SIZE, MIN_TABLE_SIZE - 1, -1):
                for rest in combinations(window, size - 1):
                    group = [first, *rest]
                    borrowed = [i for i in rest if i not in waiting]
                    if total + size - len(borrowed) > self.capacity:
                        continue
                    changes = self._borrow(tables, home, borrowed)
                    if changes is None:
                        continue
                    found = self.score(group)
                    if found is not None and (best is None or found[0] > best[0]):
                        best = (found[0], group, changes)
                if best is not None:
                    break
            if best is not None:
                yield self._replace(tables, best[2], extra=best[1])

    def _borrow(self, tables, home, borrowed):
        changes = {}
        for index in borrowed:
            t = home[index]
            changes[t] = [i for i in changes.get(t, tables[t]) if i != index]
            if len(changes[t]) < MIN_TABLE_SIZE:
                return None
        return changes

    def _replace(self, tables, changes, extra=None):
        candidate = [changes.get(t, table) for t, table in enumerate(tables)]
        if any(self.score(table) is None for table in changes.values()):
            return None
        return candidate + [extra] if extra is not None else candidate

    def _pass(self, tables):
        current = self.objective(tables)
        for candidate in self._candidates(tables):
            if candidate is not None and self.objective(candidate) > current:
                return candidate
            if time.monotonic() > self.deadline:
                return None
        return None


def _policy_allocation(roster, capacity, policy, exclusions, met_pairs):
    searchable = [index for index, person in enumerate(roster) if person.birth_year is not None]
    years = [roster[index].birth_year for index in searchable]
    start = [[searchable[i] for i in table] for table in _ordered_allocation(years, capacity)]
    search = _Search(roster, capacity, policy, exclusions, met_pairs)
    tables, complete = search.run(start)
    tables = sorted((sorted(table) for table in tables), key=lambda table: table[0])
    scored = [search.score(table) for table in tables]
    seated = {index for table in tables for index in table}
    baseline = {index for table in start for index in table}
    roomy = _seatable_without_capacity(searchable, years, capacity)
    unseated = tuple(
        (
            person.application_id,
            _reason(roster, years, searchable, index, capacity, roomy)
            if index not in baseline
            else NO_QUALIFYING_TABLE,
        )
        for index, person in enumerate(roster)
        if index not in seated
    )
    return AllocationPlan(
        tables=tuple(tuple(roster[i].application_id for i in table) for table in tables),
        unseated=unseated,
        seated_count=len(seated),
        algorithm_version=ALGORITHM_VERSION,
        rule_version=RULE_VERSION,
        table_scores=tuple(value for value, _ in scored),
        table_components=tuple(components for _, components in scored),
        search_complete=complete,
    )


# Eligible applications for one slot, in submission order. Paid by the slot close, live
# candidate, SUBMITTED, and not already confirmed in another slot (U07).
TARGET_SQL = f"""SELECT a.id AS application_id, a.user_id,
    (p.data ->> 'birth_year')::int AS birth_year, p.data AS profile,
    EXISTS (
        SELECT 1 FROM match_participation other
        JOIN event_slot os ON os.id = other.event_slot_id
        WHERE other.user_id = a.user_id AND other.state = 'CONFIRMED'
          AND other.event_slot_id <> s.id
          AND os.starts_at < s.ends_at AND s.starts_at < os.ends_at
    ) AS overlap_confirmed
    {CANDIDATES}
    LEFT JOIN participant_profile p ON p.user_id = a.user_id
    WHERE c.event_slot_id = :slot_id AND {ELIGIBLE}
      AND NOT EXISTS (
          SELECT 1 FROM match_participation mp
          WHERE mp.application_id = a.id AND mp.state = 'CONFIRMED')
    ORDER BY a.submitted_at, a.id"""

PARTICIPATION_ROW = """INSERT INTO match_participation
    (application_id, user_id, state, event_slot_id, dining_table_id, match_run_id,
     reason_code, updated_at)
    VALUES (:application, :user, :state, :slot, :table, :run, :reason, :now)
    ON CONFLICT (application_id) DO UPDATE SET
        state = EXCLUDED.state,
        event_slot_id = EXCLUDED.event_slot_id,
        dining_table_id = EXCLUDED.dining_table_id,
        match_run_id = EXCLUDED.match_run_id,
        reason_code = EXCLUDED.reason_code,
        updated_at = EXCLUDED.updated_at
    -- A confirmation is final in ①-b: a later run never overwrites it (U13 is undecided).
    WHERE match_participation.state <> 'CONFIRMED'"""


def run_due_matches():
    """Run every slot whose matching time has passed and that has no successful run.

    Slots run oldest first, which is what makes a multi-slot application resolve to its
    earliest slot (U07). Returns one summary per run that actually happened.
    """
    with database_engine().connect() as connection:
        now = locked_now(connection)
        due = (
            connection.execute(
                text("""SELECT s.id FROM event_slot s
                WHERE s.matches_at <= :now
                  AND NOT EXISTS (SELECT 1 FROM match_run r
                                  WHERE r.event_slot_id = s.id AND r.state = 'SUCCEEDED')
                ORDER BY s.matches_at, s.id"""),
                {"now": now},
            )
            .scalars()
            .all()
        )
    summaries = []
    for slot_id in due:
        summary = run_slot_matching(slot_id)
        if summary is not None:
            summaries.append(summary)
    return summaries


def run_slot_matching(slot_id):
    """Match one slot inside one transaction. Returns a summary, or None when not run."""
    try:
        with database_engine().begin() as connection:
            return _execute(connection, slot_id)
    except IntegrityError as error:
        if _constraint(error) == "match_run_slot_running":
            # Another runner holds this slot's live generation; the next cycle decides.
            return None
        logger.error("matching_run_failed")
        return _record_exception(slot_id)
    except SQLAlchemyError:
        logger.error("matching_run_failed")
        return _record_exception(slot_id)


def _execute(connection, slot_id):
    lock_matching(connection)
    slot = (
        connection.execute(
            text("SELECT id, capacity, matches_at FROM event_slot WHERE id = :id FOR UPDATE"),
            {"id": slot_id},
        )
        .mappings()
        .first()
    )
    if slot is None:
        return None
    # Read the clock after the lock: a lock wait that outlasts matches_at must be judged
    # after it, and a generation another runner finished meanwhile must not run again.
    now = locked_now(connection)
    if slot["matches_at"] > now:
        return None
    if connection.execute(
        text("""SELECT 1 FROM match_run WHERE event_slot_id = :id AND state = 'SUCCEEDED'"""),
        {"id": slot_id},
    ).scalar():
        return None
    connection.execute(
        text("""UPDATE match_run SET state = 'ABANDONED', reason_code = 'stale_generation',
        finished_at = :now WHERE event_slot_id = :id AND state = 'RUNNING'"""),
        {"id": slot_id, "now": now},
    )
    attempt = (
        connection.execute(
            text("SELECT coalesce(max(attempt), 0) FROM match_run WHERE event_slot_id = :id"),
            {"id": slot_id},
        ).scalar()
        or 0
    ) + 1
    run_id = uuid.uuid4()
    policy = policy_from_environment()
    connection.execute(
        text("""INSERT INTO match_run
        (id, event_slot_id, attempt, state, algorithm_version, rule_version, seated_count,
         started_at, policy)
        VALUES (:id, :slot, :attempt, 'RUNNING', :algorithm, :rule, 0, :started,
                CAST(:policy AS jsonb))"""),
        {
            "id": run_id,
            "slot": slot_id,
            "attempt": attempt,
            "algorithm": ALGORITHM_VERSION,
            "rule": RULE_VERSION,
            "started": now,
            "policy": json.dumps(policy.snapshot()),
        },
    )
    rows = connection.execute(text(TARGET_SQL), {"slot_id": slot_id, "now": now}).mappings().all()
    owners = {str(row["application_id"]): row["user_id"] for row in rows}
    users = [row["user_id"] for row in rows]
    participants = [_participant(row) for row in rows if not row["overlap_confirmed"]]
    by_application = {p.application_id: p.member() for p in participants}
    penalized_pairs = _pairs(connection, MET_SQL, users, slot_id)
    previous_pairs = _pairs(connection, PREVIOUS_MET_SQL, users, slot_id)
    transfers = dict(
        connection.execute(
            text("""SELECT application_id,count(*)
        FROM match_resolution WHERE action='TRANSFER' AND application_id=ANY(:ids)
        GROUP BY application_id"""),
            {"ids": [row["application_id"] for row in rows]},
        ).all()
    )
    plan = plan_allocation(
        participants,
        slot["capacity"],
        policy=policy,
        exclusions=_pairs(connection, EXCLUSION_SQL, users),
        met_pairs=penalized_pairs,
    )
    unseated = plan.unseated + tuple(
        (str(row["application_id"]), OVERLAPPING_CONFIRMATION)
        for row in rows
        if row["overlap_confirmed"]
    )
    for members, score, components in zip(
        plan.tables, plan.table_scores, plan.table_components, strict=True
    ):
        table_id = uuid.uuid4()
        seated_members = [by_application[application_id] for application_id in members]
        connection.execute(
            text("""INSERT INTO dining_table
            (id, match_run_id, event_slot_id, member_count, score, components, explanation)
            VALUES (:id, :run, :slot, :count, :score, CAST(:components AS jsonb),
                    CAST(:explanation AS jsonb))"""),
            {
                "id": table_id,
                "run": run_id,
                "slot": slot_id,
                "count": len(members),
                "explanation": json.dumps(
                    table_explanation(seated_members, previous_pairs, penalized_pairs)
                ),
                "score": _two_places(score),
                "components": json.dumps(
                    {k: None if v is None else _two_places(v) for k, v in components.items()}
                ),
            },
        )
        for application_id in members:
            user_id = owners[application_id]
            connection.execute(
                text("""INSERT INTO table_assignment
                (id, dining_table_id, event_slot_id, application_id, user_id)
                VALUES (:id, :table, :slot, :application, :user)"""),
                {
                    "id": uuid.uuid4(),
                    "table": table_id,
                    "slot": slot_id,
                    "application": application_id,
                    "user": user_id,
                },
            )
            connection.execute(
                text("""INSERT INTO match_run_member
                (match_run_id, application_id, user_id, outcome, dining_table_id, explanation)
                VALUES (:run, :application, :user, 'SEATED', :table,
                        CAST(:explanation AS jsonb))"""),
                {
                    "run": run_id,
                    "application": application_id,
                    "user": user_id,
                    "table": table_id,
                    "explanation": json.dumps(
                        member_explanation(
                            by_application[application_id],
                            [p for p in seated_members if p.user_id != str(user_id)],
                            previous_pairs,
                            transfers.get(uuid.UUID(application_id), 0),
                            _two_places,
                        )
                    ),
                },
            )
            _record_participation(
                connection,
                application_id,
                user_id,
                "CONFIRMED",
                slot_id,
                table_id,
                run_id,
                None,
                now,
            )
    for application_id, reason in unseated:
        connection.execute(
            text("""INSERT INTO match_run_member
            (match_run_id, application_id, user_id, outcome, reason_code)
            VALUES (:run, :application, :user, 'UNSEATED', :reason)"""),
            {
                "run": run_id,
                "application": application_id,
                "user": owners[application_id],
                "reason": reason,
            },
        )
        _record_participation(
            connection,
            application_id,
            owners[application_id],
            # Seated elsewhere at that time: this application simply ends, with nothing
            # to choose. Every other unseated application awaits a resolution choice.
            "NO_MATCH" if reason == OVERLAPPING_CONFIRMATION else "ALTERNATIVE_OFFERED",
            None,
            None,
            run_id,
            reason,
            now,
        )
        if reason != OVERLAPPING_CONFIRMATION:
            from serentable.participant_notices import matching_failed

            matching_failed(connection, owners[application_id], application_id, run_id, reason, now)
    finished = locked_now(connection)
    connection.execute(
        text("""UPDATE match_run SET state = 'SUCCEEDED', seated_count = :seated,
        finished_at = :finished, search_complete = :complete WHERE id = :id"""),
        {
            "seated": plan.seated_count,
            "finished": finished,
            "complete": plan.search_complete,
            "id": run_id,
        },
    )
    for application_id, reason in unseated:
        if reason != OVERLAPPING_CONFIRMATION:
            extend_final_failure(connection, application_id, finished)
    return {
        "event_slot_id": str(slot_id),
        "match_run_id": str(run_id),
        "attempt": attempt,
        "state": "SUCCEEDED",
        "seated_count": plan.seated_count,
        "tables": [list(table) for table in plan.tables],
        "unseated": [
            {"application_id": application_id, "reason_code": reason}
            for application_id, reason in unseated
        ],
    }


# Excluded pairs among this slot's applicants (MAT-05), and pairs who already shared a
# confirmed table in an earlier successful run (MAT-06). A pair who each chose MEET_AGAIN
# for the other (at any shared table) is not counted as previously met (ADR-0014 U08).
EXCLUSION_SQL = """SELECT DISTINCT user_low, user_high FROM participant_exclusion
    WHERE user_low = ANY(:users) AND user_high = ANY(:users)"""
PREVIOUS_MET_SQL = """SELECT DISTINCT a.user_id, b.user_id FROM table_assignment a
    JOIN table_assignment b ON b.dining_table_id = a.dining_table_id AND b.user_id <> a.user_id
    JOIN dining_table t ON t.id = a.dining_table_id
    JOIN match_run m ON m.id = t.match_run_id AND m.state = 'SUCCEEDED'
    WHERE a.user_id = ANY(:users) AND b.user_id = ANY(:users) AND t.event_slot_id <> :slot"""
MET_SQL = (
    PREVIOUS_MET_SQL
    + """
      AND NOT (EXISTS (SELECT 1 FROM person_preference p WHERE p.rater_id = a.user_id
                       AND p.target_id = b.user_id AND p.choice = 'MEET_AGAIN')
               AND EXISTS (SELECT 1 FROM person_preference p WHERE p.rater_id = b.user_id
                           AND p.target_id = a.user_id AND p.choice = 'MEET_AGAIN'))"""
)


def _pairs(connection, sql, users, slot_id=None):
    rows = connection.execute(text(sql), {"users": users, "slot": slot_id}).all()
    return frozenset(frozenset({str(a), str(b)}) for a, b in rows)


def _participant(row):
    profile = row["profile"] or {}
    return Participant(
        application_id=str(row["application_id"]),
        birth_year=row["birth_year"],
        user_id=str(row["user_id"]),
        gender=profile.get("gender") or "",
        mbtis=tuple(profile.get("mbtis") or ()),
        interests=tuple(profile.get("interests") or ()),
        self_traits=tuple(profile.get("self_traits") or ()),
        desired_traits=tuple(profile.get("desired_traits") or ()),
    )


def _two_places(value):
    """Exact half-up rounding of a non-negative score to two decimals, as text."""
    cents = int(Fraction(value) * 100 + Fraction(1, 2))
    return f"{cents // 100}.{cents % 100:02d}"


def _record_participation(
    connection, application_id, user_id, state, slot_id, table_id, run_id, reason, now
):
    connection.execute(
        text(PARTICIPATION_ROW),
        {
            "application": application_id,
            "user": user_id,
            "state": state,
            "slot": slot_id,
            "table": table_id,
            "run": run_id,
            "reason": reason,
            "now": now,
        },
    )


def _record_exception(slot_id, reason="runner_error"):
    """Preserve a run that could not finish, for the operator rather than as a silent skip.

    The failed transaction rolled back, so this opens a new one; if that also fails there
    is nothing left to record and the next cycle simply tries again.
    """
    try:
        with database_engine().begin() as connection:
            lock_matching(connection)
            slot = connection.execute(
                text("SELECT id FROM event_slot WHERE id = :id FOR UPDATE"), {"id": slot_id}
            ).scalar()
            if (
                slot is None
                or connection.execute(
                    text("""SELECT 1 FROM match_run
                WHERE event_slot_id = :id AND state = 'SUCCEEDED'"""),
                    {"id": slot_id},
                ).scalar()
            ):
                return None
            now = locked_now(connection)
            targets = (
                connection.execute(text(TARGET_SQL), {"slot_id": slot_id, "now": now})
                .mappings()
                .all()
            )
            connection.execute(
                text("""UPDATE match_run SET state = 'ABANDONED',
                reason_code = 'stale_generation', finished_at = :now
                WHERE event_slot_id = :id AND state = 'RUNNING'"""),
                {"id": slot_id, "now": now},
            )
            attempt = (
                connection.execute(
                    text(
                        "SELECT coalesce(max(attempt), 0) FROM match_run WHERE event_slot_id = :id"
                    ),
                    {"id": slot_id},
                ).scalar()
                or 0
            ) + 1
            run_id = uuid.uuid4()
            connection.execute(
                text("""INSERT INTO match_run
                (id, event_slot_id, attempt, state, algorithm_version, rule_version,
                 seated_count, reason_code, started_at, finished_at)
                VALUES (:id, :slot, :attempt, 'FAILED', :algorithm, :rule, 0, :reason, :now,
                        :now)"""),
                {
                    "id": run_id,
                    "slot": slot_id,
                    "attempt": attempt,
                    "algorithm": ALGORITHM_VERSION,
                    "rule": RULE_VERSION,
                    "reason": reason,
                    "now": now,
                },
            )
            for target in targets:
                application_id, user_id = target["application_id"], target["user_id"]
                connection.execute(
                    text("""INSERT INTO match_run_member
                    (match_run_id, application_id, user_id, outcome, reason_code)
                    VALUES (:run, :application, :user, 'EXCEPTION', :reason)"""),
                    {
                        "run": run_id,
                        "application": application_id,
                        "user": user_id,
                        "reason": reason,
                    },
                )
                _record_participation(
                    connection,
                    application_id,
                    user_id,
                    "EXCEPTION",
                    None,
                    None,
                    run_id,
                    reason,
                    now,
                )
    except SQLAlchemyError:
        return None
    return {"event_slot_id": str(slot_id), "state": "FAILED", "reason_code": reason}


def _constraint(error):
    return getattr(getattr(error.orig, "diag", None), "constraint_name", "")


def participation_details(connection, application_ids):
    """application id -> the stored matching axis for it (or None when no run touched it)."""
    if not application_ids:
        return {}
    details = {application_id: None for application_id in application_ids}
    introductions = {}
    # Only a current, confirmed assignment grants access to that same table's names.
    # Never serialize profile JSON or identifiers belonging to another participant.
    for member in connection.execute(
        text("""SELECT own.application_id, p.data ->> 'display_name' AS display_name
        FROM table_assignment own
        JOIN match_participation mp ON mp.application_id = own.application_id
          AND mp.dining_table_id = own.dining_table_id AND mp.state = 'CONFIRMED'
        JOIN table_assignment peer ON peer.dining_table_id = own.dining_table_id
          AND peer.ended_at IS NULL
        LEFT JOIN participant_profile p ON p.user_id = peer.user_id
        WHERE own.application_id = ANY(:ids) AND own.ended_at IS NULL
        ORDER BY peer.created_at, peer.id"""),
        {"ids": list(application_ids)},
    ).mappings():
        introductions.setdefault(member["application_id"], []).append(
            {"display_name": member["display_name"] or "참가자"}
        )
    for row in connection.execute(
        text("""SELECT mp.application_id, mp.state, mp.reason_code, mp.event_slot_id,
            mp.dining_table_id, t.member_count
        FROM match_participation mp
        LEFT JOIN dining_table t ON t.id = mp.dining_table_id
        WHERE mp.application_id = ANY(:ids)"""),
        {"ids": list(application_ids)},
    ).mappings():
        details[row["application_id"]] = {
            "state": row["state"],
            "reason_code": row["reason_code"],
            "event_slot_id": str(row["event_slot_id"]) if row["event_slot_id"] else None,
            "table": (
                {
                    "id": str(row["dining_table_id"]),
                    "member_count": row["member_count"],
                    "members": introductions.get(row["application_id"], []),
                }
                if row["dining_table_id"]
                else None
            ),
        }
    return details


@router.get("/api/admin/match-runs")
def list_match_runs(operator: Principal = Depends(require_operator)):
    """Read-only matching history (PRD 이야기 47). No start, confirm or edit action."""
    try:
        with database_engine().connect() as connection:
            now = locked_now(connection)
            runs = (
                connection.execute(
                    text(f"""SELECT m.id AS run_id, m.attempt, m.state, m.seated_count,
                    m.reason_code, m.algorithm_version, m.rule_version, m.started_at,
                    m.finished_at, m.policy, m.search_complete,
                    {SLOT_COLUMNS}
                    FROM match_run m
                    JOIN event_slot s ON s.id = m.event_slot_id
                    JOIN region r ON r.code = s.region_code
                    ORDER BY s.matches_at DESC, m.attempt DESC""")
                )
                .mappings()
                .all()
            )
            members, tables = {}, {}
            if runs:
                for row in connection.execute(
                    text("""SELECT match_run_id, id, member_count, score, components, explanation
                    FROM dining_table WHERE match_run_id = ANY(:ids)
                    ORDER BY score DESC NULLS LAST, id"""),
                    {"ids": [run["run_id"] for run in runs]},
                ).mappings():
                    tables.setdefault(str(row["match_run_id"]), []).append(
                        {
                            "id": str(row["id"]),
                            "member_count": row["member_count"],
                            # Runs before ADR-0011 recorded no score.
                            "score": None if row["score"] is None else f"{row['score']:.2f}",
                            "components": row["components"],
                            "explanation": row["explanation"],
                        }
                    )
                for row in connection.execute(
                    text("""SELECT m.match_run_id, m.outcome, m.reason_code, m.dining_table_id,
                    m.application_id, u.login_id, m.explanation
                    FROM match_run_member m
                    JOIN app_user u ON u.id = m.user_id
                    WHERE m.match_run_id = ANY(:ids)
                    ORDER BY u.login_id"""),
                    {"ids": [run["run_id"] for run in runs]},
                ).mappings():
                    members.setdefault(str(row["match_run_id"]), []).append(
                        {
                            "application_id": str(row["application_id"]),
                            "login_id": row["login_id"],
                            "explanation": row["explanation"],
                            "outcome": row["outcome"],
                            "reason_code": row["reason_code"],
                            "dining_table_id": (
                                str(row["dining_table_id"]) if row["dining_table_id"] else None
                            ),
                        }
                    )
    except SQLAlchemyError:
        raise HTTPException(503, "matching_unavailable") from None
    return private_response(
        {
            "match_runs": [
                {
                    "id": str(run["run_id"]),
                    "attempt": run["attempt"],
                    "state": run["state"],
                    "seated_count": run["seated_count"],
                    "reason_code": run["reason_code"],
                    "algorithm_version": run["algorithm_version"],
                    "rule_version": run["rule_version"],
                    "started_at": iso(run["started_at"]),
                    "finished_at": iso(run["finished_at"]),
                    "event_slot": slot_json(run, now),
                    "policy": run["policy"],
                    "search_complete": run["search_complete"],
                    "tables": tables.get(str(run["run_id"]), []),
                    "members": members.get(str(run["run_id"]), []),
                }
                for run in runs
            ]
        }
    )
