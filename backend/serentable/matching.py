"""Reserved matching: hard-constraint allocation, its automatic execution, and history.

Contract: ``docs/design/matching-contract.md`` (Work #6 Task ①-a, decisions approved
2026-10-17). The approved rules this module implements:

- hard constraints only, identical to ``tests/oracle/hard_constraints.py`` (the oracle is
  deliberately independent code and is not imported here);
- seat as many participants as the hard constraints allow, and break a tie by submission
  order (U06);
- one live table assignment per application, slots processed by ``matches_at`` and then by
  slot id, applications already CONFIRMED elsewhere excluded (U07);
- nothing else: matching scores, gender ratio, MBTI (U05), table splitting/merging and
  reallocation (①-c) are not decided and are not done here.

Scoring is absent, so the reported ``seated_count`` means what the oracle's
``max_seatable()`` means and the two are compared directly in tests.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import cache
from itertools import combinations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from serentable.auth import Principal, private_response, require_operator
from serentable.clock import iso, locked_now
from serentable.database import database_engine
from serentable.eligibility import CANDIDATES, ELIGIBLE
from serentable.events import SLOT_COLUMNS, slot_json

logger = logging.getLogger("serentable.worker")

router = APIRouter()

# Hard constraints, mirroring tests/oracle/hard_constraints.py (kept in step by test, not
# by a shared import).
MIN_TABLE_SIZE = 4
MAX_TABLE_SIZE = 6
MAX_AGE_GAP = 8

# The oracle brute-forces up to twelve participants and refuses larger input. The runner
# cannot refuse a slot, so larger inputs fall back to a deterministic greedy pass. Seat
# count optimality above twelve is therefore not claimed (execution scale is U19).
MAX_EXHAUSTIVE_PARTICIPANTS = 12

ALGORITHM_VERSION = "hard-constraints-v1"
RULE_VERSION = "u06-u07-2026-10-17"

# Why an application was left unseated; stored per member and shown to participants.
NOT_ENOUGH_ELIGIBLE = "not_enough_eligible"
CAPACITY = "capacity"
UNKNOWN_AGE = "unknown_age"
AGE_GAP = "age_gap"
NO_VALID_TABLE = "no_valid_table"


@dataclass(frozen=True)
class Participant:
    """One application that may be seated in a slot, in submission order."""

    application_id: str
    birth_year: int | None


@dataclass(frozen=True)
class AllocationPlan:
    tables: tuple[tuple[str, ...], ...]
    unseated: tuple[tuple[str, str], ...]
    seated_count: int
    algorithm_version: str = ALGORITHM_VERSION
    rule_version: str = RULE_VERSION


def plan_allocation(participants, capacity):
    """Assign participants to tables under the hard constraints, without touching the DB.

    ``participants`` is in submission order, which is also the tie-break: of two
    allocations that seat the same number of people, the one seating earlier applicants
    wins. A participant with no recorded birth year cannot be checked against the age rule
    and is left unseated rather than seated unchecked.
    """
    roster = list(participants)
    searchable = [index for index, person in enumerate(roster) if person.birth_year is not None]
    years = [roster[index].birth_year for index in searchable]
    if len(years) <= MAX_EXHAUSTIVE_PARTICIPANTS:
        grouped = _exhaustive(years, capacity)
    else:
        grouped = _greedy(years, capacity)
    tables = tuple(
        tuple(roster[searchable[index]].application_id for index in members) for members in grouped
    )
    seated = {application_id for table in tables for application_id in table}
    unseated = tuple(
        (person.application_id, _reason(roster, years, searchable, index, capacity))
        for index, person in enumerate(roster)
        if person.application_id not in seated
    )
    return AllocationPlan(
        tables=tables, unseated=unseated, seated_count=sum(len(table) for table in tables)
    )


def _age_gap_ok(years, members):
    values = [years[index] for index in members]
    return max(values) - min(values) <= MAX_AGE_GAP


def _exhaustive(years, capacity):
    """Backtracking search for the maximum seated count, submission order as tie-break."""

    @cache
    def best(remaining, room):
        # (seated count, per-position seated flag in submission order, tables)
        if len(remaining) < MIN_TABLE_SIZE or room < MIN_TABLE_SIZE:
            return 0, (0,) * len(remaining), ()
        first, rest = remaining[0], remaining[1:]
        count, flags, tables = best(rest, room)
        flags = (0,) + flags
        for size in range(MIN_TABLE_SIZE - 1, min(MAX_TABLE_SIZE, room)):
            for others in combinations(rest, size):
                members = (first,) + others
                if not _age_gap_ok(years, members):
                    continue
                left = tuple(index for index in rest if index not in others)
                rest_count, rest_flags, rest_tables = best(left, room - len(members))
                sub = iter(rest_flags)
                candidate_flags = (1,) + tuple(
                    1 if index in others else next(sub) for index in rest
                )
                candidate_count = len(members) + rest_count
                if (candidate_count, candidate_flags) > (count, flags):
                    count, flags = candidate_count, candidate_flags
                    tables = (members,) + rest_tables
        return count, flags, tables

    _, _, tables = best(tuple(range(len(years))), capacity)
    return tables


def _greedy(years, capacity):
    """Deterministic fallback beyond the exhaustive bound: seat in submission order."""
    tables: list[list[int]] = []
    for index in range(len(years)):
        for table in tables:
            if len(table) >= MAX_TABLE_SIZE or len(table) >= capacity:
                continue
            if _age_gap_ok(years, [*table, index]):
                table.append(index)
                break
        else:
            if sum(len(table) for table in tables) + MIN_TABLE_SIZE <= capacity:
                tables.append([index])
    # A table that never reached four members is not a table at all.
    complete = [table for table in tables if len(table) >= MIN_TABLE_SIZE]
    while sum(len(table) for table in complete) > capacity:
        complete.pop()
    return [tuple(table) for table in complete]


def _reason(roster, years, searchable, index, capacity):
    """Why this application could not be seated, in a wording participants can read."""
    if roster[index].birth_year is None:
        return UNKNOWN_AGE
    if len(searchable) < MIN_TABLE_SIZE:
        return NOT_ENOUGH_ELIGIBLE
    if capacity < MIN_TABLE_SIZE:
        return CAPACITY
    position = searchable.index(index)
    others = [year for other, year in enumerate(years) if other != position]
    if not any(abs(years[position] - year) <= MAX_AGE_GAP for year in others):
        return AGE_GAP
    return NO_VALID_TABLE


# Eligible applications for one slot, in submission order. Paid by the slot close, live
# candidate, SUBMITTED, and not already confirmed in another slot (U07).
TARGET_SQL = f"""SELECT a.id AS application_id, a.user_id,
    (p.data ->> 'birth_year')::int AS birth_year
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
    connection.execute(
        text("""INSERT INTO match_run
        (id, event_slot_id, attempt, state, algorithm_version, rule_version, seated_count,
         started_at)
        VALUES (:id, :slot, :attempt, 'RUNNING', :algorithm, :rule, 0, :started)"""),
        {
            "id": run_id,
            "slot": slot_id,
            "attempt": attempt,
            "algorithm": ALGORITHM_VERSION,
            "rule": RULE_VERSION,
            "started": now,
        },
    )
    rows = connection.execute(text(TARGET_SQL), {"slot_id": slot_id, "now": now}).mappings().all()
    owners = {str(row["application_id"]): row["user_id"] for row in rows}
    plan = plan_allocation(
        [
            Participant(application_id=str(row["application_id"]), birth_year=row["birth_year"])
            for row in rows
        ],
        slot["capacity"],
    )
    for members in plan.tables:
        table_id = uuid.uuid4()
        connection.execute(
            text("""INSERT INTO dining_table (id, match_run_id, event_slot_id, member_count)
            VALUES (:id, :run, :slot, :count)"""),
            {"id": table_id, "run": run_id, "slot": slot_id, "count": len(members)},
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
                (match_run_id, application_id, user_id, outcome, dining_table_id)
                VALUES (:run, :application, :user, 'SEATED', :table)"""),
                {
                    "run": run_id,
                    "application": application_id,
                    "user": user_id,
                    "table": table_id,
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
    for application_id, reason in plan.unseated:
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
            "NO_MATCH",
            None,
            None,
            run_id,
            reason,
            now,
        )
    finished = locked_now(connection)
    connection.execute(
        text("""UPDATE match_run SET state = 'SUCCEEDED', seated_count = :seated,
        finished_at = :finished WHERE id = :id"""),
        {"seated": plan.seated_count, "finished": finished, "id": run_id},
    )
    return {
        "event_slot_id": str(slot_id),
        "match_run_id": str(run_id),
        "attempt": attempt,
        "state": "SUCCEEDED",
        "seated_count": plan.seated_count,
        "tables": [list(table) for table in plan.tables],
        "unseated": [
            {"application_id": application_id, "reason_code": reason}
            for application_id, reason in plan.unseated
        ],
    }


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
    targets = _safe_targets(slot_id)
    try:
        with database_engine().begin() as connection:
            now = locked_now(connection)
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
            for application_id, user_id in targets:
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


def _safe_targets(slot_id):
    try:
        with database_engine().connect() as connection:
            now = locked_now(connection)
            return [
                (row["application_id"], row["user_id"])
                for row in connection.execute(
                    text(TARGET_SQL), {"slot_id": slot_id, "now": now}
                ).mappings()
            ]
    except SQLAlchemyError:
        return []


def _constraint(error):
    return getattr(getattr(error.orig, "diag", None), "constraint_name", "")


def participation_details(connection, application_ids):
    """application id -> the stored matching axis for it (or None when no run touched it)."""
    if not application_ids:
        return {}
    details = {application_id: None for application_id in application_ids}
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
                {"id": str(row["dining_table_id"]), "member_count": row["member_count"]}
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
                    m.finished_at,
                    {SLOT_COLUMNS}
                    FROM match_run m
                    JOIN event_slot s ON s.id = m.event_slot_id
                    JOIN region r ON r.code = s.region_code
                    ORDER BY s.matches_at DESC, m.attempt DESC""")
                )
                .mappings()
                .all()
            )
            members = {}
            if runs:
                for row in connection.execute(
                    text("""SELECT m.match_run_id, m.outcome, m.reason_code, m.dining_table_id,
                    m.application_id, u.login_id
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
                    "members": members.get(str(run["run_id"]), []),
                }
                for run in runs
            ]
        }
    )
