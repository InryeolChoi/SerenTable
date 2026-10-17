"""Passes and mock payments: product choice, idempotent mock charge, entitlement grant."""

import calendar
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_participant,
    require_participant,
    require_user,
)
from serentable.clock import SEOUL, iso, locked_now
from serentable.database import database_engine

router = APIRouter()

# Provisional U03 rules (pending CEO confirmation). Every rule that depends on them reads
# this version, and it is recorded on each payment and entitlement so a later policy can
# be told apart from rows created under this one.
ENTITLEMENT_POLICY_VERSION = "provisional-2026-10-16"
# Official FAQ Q4 prices. Payments snapshot code/version/price/period at purchase.
PRODUCT_VERSION = "faq-2026-10-16"
PRODUCTS = {
    "single": {"name": "1회권", "kind": "SINGLE", "price_krw": 9900, "period_months": None},
    "membership_1m": {
        "name": "멤버십 1개월",
        "kind": "MEMBERSHIP",
        "price_krw": 35000,
        "period_months": 1,
    },
    "membership_3m": {
        "name": "멤버십 3개월",
        "kind": "MEMBERSHIP",
        "price_krw": 75000,
        "period_months": 3,
    },
    "membership_6m": {
        "name": "멤버십 6개월",
        "kind": "MEMBERSHIP",
        "price_krw": 120000,
        "period_months": 6,
    },
}


def add_calendar_months(moment: datetime, months: int) -> datetime:
    """Same Seoul wall-clock time `months` later, clamped to the target month's last day."""
    local = moment.astimezone(SEOUL)
    index = local.month - 1 + months
    year, month = local.year + index // 12, index % 12 + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day)


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    product_code: Literal[tuple(PRODUCTS)]  # type: ignore[valid-type]
    # Mock only: deterministic failure for tests and demos ("실패 시뮬레이션").
    simulate_failure: bool = False


PAYMENT_COLUMNS = """p.id, p.application_id, p.state, p.product_code, p.product_name,
p.product_kind, p.product_version, p.amount_krw, p.period_months, p.policy_version,
p.simulated_failure, p.requested_at, p.completed_at"""
ENTITLEMENT_COLUMNS = """e.id, e.user_id, e.payment_id, e.kind, e.application_id, e.starts_at,
e.expires_at, e.policy_version, p.product_code, p.state AS payment_state,
(SELECT b.application_id FROM entitlement_binding b WHERE b.entitlement_id=e.id AND b.ended_at
IS NULL) AS reserved_application_id,
(SELECT a.state FROM application a WHERE a.id = e.application_id) AS application_state,
(SELECT min(ta.created_at) FROM table_assignment ta
 JOIN entitlement_binding b ON b.application_id=ta.application_id
 WHERE b.entitlement_id=e.id) AS used_at"""


def payment_json(row):
    return {
        "id": str(row["id"]),
        "application_id": str(row["application_id"]),
        "state": row["state"],
        "mock": True,
        "amount_krw": row["amount_krw"],
        "product": {
            "code": row["product_code"],
            "name": row["product_name"],
            "kind": row["product_kind"],
            "version": row["product_version"],
            "price_krw": row["amount_krw"],
            "period_months": row["period_months"],
        },
        "policy_version": row["policy_version"],
        "simulated_failure": row["simulated_failure"],
        "requested_at": iso(row["requested_at"]),
        "completed_at": iso(row["completed_at"]),
    }


def entitlement_json(row, now):
    if row["kind"] == "SINGLE":
        # Assignments and confirmation commit together; rolled-back runs never consume
        # a pass. Historical assignments remain even if a future reallocation ends them:
        # ending an assignment must not silently restore a previously used right (U03).
        state = (
            "REFUNDED"
            if row["payment_state"] == "REFUNDED"
            else ("USED" if row["used_at"] is not None else "HELD")
        )
    else:
        state = "ACTIVE" if now < row["expires_at"] else "EXPIRED"
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "product_code": row["product_code"],
        "payment_id": str(row["payment_id"]),
        "application_id": str(row["application_id"]) if row["application_id"] else None,
        # A single pass stays HELD when its application is canceled (no refund, U03/U04);
        # this tells the two apart. Null for memberships.
        "application_state": row["application_state"],
        "starts_at": iso(row["starts_at"]),
        "expires_at": iso(row["expires_at"]),
        "used_at": iso(row["used_at"]),
        "state": state,
        "policy_version": row["policy_version"],
        "reserved_application_id": str(row["reserved_application_id"])
        if row["reserved_application_id"]
        else None,
        "reusable": row["kind"] == "SINGLE"
        and state == "HELD"
        and row["reserved_application_id"] is None,
    }


def payment_details(connection, rows, now):
    """Payments (newest first), coverage and whether a payment is still required, per id.

    An application is covered by the entitlement its own PAID payment granted, or, while it
    is SUBMITTED, by the owner's membership that is active now, started by the earliest
    candidate close and lasts past every candidate start (provisional U03). Whether an
    application is matching-eligible per slot is `serentable.eligibility`'s decision.
    """
    ids = [row["id"] for row in rows]
    details = {
        row["id"]: {"payments": [], "coverage": None, "payment_required": False} for row in rows
    }
    if not ids:
        return details
    for payment in connection.execute(
        text(f"""SELECT {PAYMENT_COLUMNS} FROM payment p
        WHERE p.application_id = ANY(:ids) ORDER BY p.requested_at DESC, p.id"""),
        {"ids": ids},
    ).mappings():
        details[payment["application_id"]]["payments"].append(payment_json(payment))
    for entitlement in connection.execute(
        text(f"""SELECT {ENTITLEMENT_COLUMNS}, b.application_id AS paid_for
        FROM entitlement e JOIN payment p ON p.id = e.payment_id
        JOIN entitlement_binding b ON b.entitlement_id=e.id AND b.ended_at IS NULL
        WHERE b.application_id = ANY(:ids) AND p.state='PAID'"""),
        {"ids": ids},
    ).mappings():
        details[entitlement["paid_for"]]["coverage"] = {
            "source": "payment",
            "entitlement": entitlement_json(entitlement, now),
        }
    for entitlement in connection.execute(
        text(f"""SELECT {ENTITLEMENT_COLUMNS}, p.application_id AS paid_for
        FROM entitlement e JOIN payment p ON p.id=e.payment_id
        WHERE e.kind='MEMBERSHIP' AND p.state='PAID' AND p.application_id=ANY(:ids)"""),
        {"ids": ids},
    ).mappings():
        details[entitlement["paid_for"]]["coverage"] = {
            "source": "payment",
            "entitlement": entitlement_json(entitlement, now),
        }
    for row in rows:
        detail = details[row["id"]]
        if detail["coverage"] is None and row["state"] == "SUBMITTED":
            membership = covering_membership(connection, row["user_id"], row["id"], now)
            if membership is not None:
                detail["coverage"] = {
                    "source": "membership",
                    "entitlement": entitlement_json(membership, now),
                }
        detail["payment_required"] = (
            row["state"] == "SUBMITTED"
            and detail["coverage"] is None
            and bool(
                connection.execute(
                    text(
                        "SELECT 1 FROM application_candidate "
                        "WHERE application_id=:id AND live LIMIT 1"
                    ),
                    {"id": row["id"]},
                ).scalar()
            )
        )
    return details


def latest_candidate_start(connection, application_id):
    return connection.execute(
        text("""SELECT max(s.starts_at) FROM application_candidate c
        JOIN event_slot s ON s.id = c.event_slot_id WHERE c.application_id = :id AND c.live"""),
        {"id": application_id},
    ).scalar()


def covering_membership(connection, user_id, application_id, now):
    """The owner's active membership lasting past every candidate start, if any.

    It must have started by the earliest candidate close: a membership bought after the
    close (for another application) never covers this one retroactively.
    """
    return (
        connection.execute(
            text(f"""WITH bounds AS (
                SELECT max(s.starts_at) AS latest_start, min(s.closes_at) AS earliest_close
                FROM application_candidate c JOIN event_slot s ON s.id = c.event_slot_id
                WHERE c.application_id = :application_id AND c.live)
            SELECT {ENTITLEMENT_COLUMNS} FROM entitlement e
            JOIN payment p ON p.id = e.payment_id CROSS JOIN bounds b
            WHERE e.user_id = :user_id AND e.kind = 'MEMBERSHIP' AND p.state='PAID'
              AND e.starts_at <= least(:now, b.earliest_close)
              AND e.expires_at > :now AND e.expires_at > b.latest_start
            ORDER BY e.expires_at DESC, e.id LIMIT 1"""),
            {"user_id": user_id, "application_id": application_id, "now": now},
        )
        .mappings()
        .first()
    )


def read_payment(connection, payment_id):
    row = (
        connection.execute(
            text(f"SELECT {PAYMENT_COLUMNS} FROM payment p WHERE p.id = :id"), {"id": payment_id}
        )
        .mappings()
        .one()
    )
    return payment_json(row)


@router.post("/api/me/applications/{application_id}/payments")
def pay_for_application(
    application_id: uuid.UUID,
    payload: PaymentInput,
    user: Principal = Depends(require_csrf_participant),
):
    product = PRODUCTS[payload.product_code]
    payment_id = uuid.uuid4()
    try:
        with database_engine().begin() as connection:
            # Serialize this participant's payments so replay, coverage and the one-live-
            # attempt rule see every committed payment; unique constraints are the backstop.
            connection.execute(
                text("SELECT id FROM app_user WHERE id = :id FOR UPDATE"), {"id": user.id}
            )
            prior = (
                connection.execute(
                    text("""SELECT id, application_id, product_code, simulated_failure
                    FROM payment WHERE user_id = :user_id AND request_key = :key"""),
                    {"user_id": user.id, "key": payload.request_key},
                )
                .mappings()
                .first()
            )
            if prior is not None:
                if (prior["application_id"], prior["product_code"], prior["simulated_failure"]) != (
                    application_id,
                    payload.product_code,
                    payload.simulate_failure,
                ):
                    raise HTTPException(409, "request_key_reused")
                return private_response({"payment": read_payment(connection, prior["id"])})
            application = (
                connection.execute(
                    text("""SELECT id, user_id, state FROM application
                    WHERE id = :id AND user_id = :user_id FOR NO KEY UPDATE"""),
                    {"id": application_id, "user_id": user.id},
                )
                .mappings()
                .first()
            )
            # Another participant's id is indistinguishable from a missing one.
            if application is None:
                raise HTTPException(404, "application_not_found")
            if application["state"] != "SUBMITTED":
                raise HTTPException(409, "application_not_payable")
            # FOR SHARE makes a close/match step that locks the slots FOR UPDATE wait for this
            # payment; the deadline is judged after the lock waits, by the database clock,
            # and that clock also stamps the payment and any membership it grants.
            closes = list(
                connection.execute(
                    text("""SELECT s.closes_at FROM application_candidate c
                    JOIN event_slot s ON s.id = c.event_slot_id
                    WHERE c.application_id = :id AND c.live FOR SHARE OF s"""),
                    {"id": application_id},
                ).scalars()
            )
            now = locked_now(connection)
            if not closes or min(closes) <= now:
                raise HTTPException(409, "payment_closed")
            coverage = payment_details(connection, [application], now)[application_id]["coverage"]
            if coverage is not None:
                raise HTTPException(
                    409,
                    "payment_already_paid"
                    if coverage["source"] == "payment"
                    else "entitlement_already_covers",
                )
            if product["kind"] == "MEMBERSHIP" and add_calendar_months(
                now, product["period_months"]
            ) <= latest_candidate_start(connection, application_id):
                raise HTTPException(409, "membership_too_short")
            connection.execute(
                text("""INSERT INTO payment
                (id, application_id, user_id, request_key, state, product_code, product_name,
                 product_kind, product_version, amount_krw, period_months, policy_version,
                 simulated_failure, requested_at)
                VALUES (:id, :application_id, :user_id, :key, 'PENDING', :code, :name, :kind,
                 :version, :amount, :period, :policy, :fail, :now)"""),
                {
                    "id": payment_id,
                    "application_id": application_id,
                    "user_id": user.id,
                    "key": payload.request_key,
                    "code": payload.product_code,
                    "name": product["name"],
                    "kind": product["kind"],
                    "version": PRODUCT_VERSION,
                    "amount": product["price_krw"],
                    "period": product["period_months"],
                    "policy": ENTITLEMENT_POLICY_VERSION,
                    "fail": payload.simulate_failure,
                    "now": now,
                },
            )
            complete_mock_payment(
                connection,
                payment_id,
                user.id,
                application_id,
                product,
                payload.simulate_failure,
                now,
            )
            payment = read_payment(connection, payment_id)
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", "")
        if constraint == "payment_application_live":
            raise HTTPException(409, "payment_already_paid") from None
        if constraint == "payment_user_request":
            raise HTTPException(409, "request_key_reused") from None
        raise HTTPException(503, "payment_unavailable") from None
    except SQLAlchemyError:
        raise HTTPException(503, "payment_unavailable") from None
    response = private_response({"payment": payment})
    response.status_code = 201
    return response


def complete_mock_payment(
    connection, payment_id, user_id, application_id, product, simulate_failure, now
):
    """The mock processor, in the same transaction: PENDING -> FAILED with nothing granted,
    or PENDING -> PAID with exactly one entitlement. No real charge happens."""
    if simulate_failure:
        connection.execute(
            text("UPDATE payment SET state = 'FAILED', completed_at = :now WHERE id = :id"),
            {"id": payment_id, "now": now},
        )
        return
    connection.execute(
        text("UPDATE payment SET state = 'PAID', completed_at = :now WHERE id = :id"),
        {"id": payment_id, "now": now},
    )
    single = product["kind"] == "SINGLE"
    entitlement_id = uuid.uuid4()
    connection.execute(
        text("""INSERT INTO entitlement
        (id, user_id, payment_id, kind, application_id, starts_at, expires_at, policy_version)
        VALUES (:id, :user_id, :payment_id, :kind, :application_id, :starts, :expires,
         :policy)"""),
        {
            "id": entitlement_id,
            "user_id": user_id,
            "payment_id": payment_id,
            "kind": product["kind"],
            "application_id": application_id if single else None,
            # Provisional U03: a membership starts at payment completion.
            "starts": now,
            "expires": None if single else add_calendar_months(now, product["period_months"]),
            "policy": ENTITLEMENT_POLICY_VERSION,
        },
    )

    if single:
        connection.execute(
            text("""INSERT INTO entitlement_binding
            (id,entitlement_id,application_id,user_id,started_at)
            VALUES(:id,:id,:app,:user,:now)"""),
            {"id": entitlement_id, "app": application_id, "user": user_id, "now": now},
        )


@router.get("/api/me/entitlements")
def list_own_entitlements(user: Principal = Depends(require_participant)):
    try:
        with database_engine().connect() as connection:
            now = locked_now(connection)
            rows = connection.execute(
                text(f"""SELECT {ENTITLEMENT_COLUMNS} FROM entitlement e
                JOIN payment p ON p.id = e.payment_id
                WHERE e.user_id = :user_id ORDER BY e.starts_at DESC, e.id"""),
                {"user_id": user.id},
            ).mappings()
            entitlements = [entitlement_json(row, now) for row in rows]
    except SQLAlchemyError:
        raise HTTPException(503, "payment_unavailable") from None
    return private_response({"entitlements": entitlements})


@router.get("/api/products")
def list_products(user: Principal = Depends(require_user)):
    return private_response(
        {
            "mock": True,
            "product_version": PRODUCT_VERSION,
            "policy_version": ENTITLEMENT_POLICY_VERSION,
            "products": [{"code": code, **product} for code, product in PRODUCTS.items()],
        }
    )
