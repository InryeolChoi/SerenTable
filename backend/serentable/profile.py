"""Owner-only synthetic participant drafts and consent history."""

import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from serentable.auth import (
    Principal,
    private_response,
    require_csrf,
    require_operator,
    require_user,
)
from serentable.database import database_engine

router = APIRouter()
OPTIONS = {
    "mbtis": {
        v: v
        for v in (
            "ISTJ",
            "ISFJ",
            "INFJ",
            "INTJ",
            "ISTP",
            "ISFP",
            "INFP",
            "INTP",
            "ESTP",
            "ESFP",
            "ENFP",
            "ENTP",
            "ESTJ",
            "ESFJ",
            "ENFJ",
            "ENTJ",
        )
    },
    "interests": dict(
        zip(
            (
                "movies_drama",
                "music",
                "reading",
                "writing",
                "exercise",
                "food_cafes",
                "travel",
                "photo_video",
                "exhibitions_performances_art",
                "fashion_beauty",
                "self_development_study",
            ),
            (
                "영화·드라마",
                "음악",
                "독서",
                "글쓰기",
                "운동",
                "맛집·카페 탐방",
                "여행",
                "사진·영상",
                "전시·공연·아트",
                "패션·뷰티",
                "자기계발·공부",
            ),
            strict=True,
        )
    ),
    "self_traits": dict(
        zip(
            (
                "calm",
                "energetic",
                "deep_conversation",
                "light_humor",
                "listener",
                "conversation_leader",
            ),
            (
                "잔잔하고 조용한 편",
                "활기차고 에너지 있는 편",
                "깊은 대화를 좋아함",
                "가볍고 유머 있는 대화를 좋아함",
                "경청을 잘 함",
                "이야기를 이끄는 편",
            ),
            strict=True,
        )
    ),
    "desired_traits": dict(
        zip(
            (
                "similar",
                "different",
                "deep_conversation",
                "comfortable_humor",
                "passionate",
                "calm_stable",
            ),
            (
                "나와 비슷한 사람",
                "나와 다른 자극을 주는 사람",
                "깊은 대화가 되는 사람",
                "편하고 유머 있는 사람",
                "열정 있는 사람",
                "잔잔하고 안정적인 사람",
            ),
            strict=True,
        )
    ),
    "meal_budget_bands": {
        "10000_20000": "10,000~20,000원",
        "20000_30000": "20,000~30,000원",
        "30000_plus": "30,000원 이상 (상관 없음)",
    },
}
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class FoodCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unknown", "none", "specified"] = "unknown"
    details: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "specified" and not self.details:
            raise ValueError("food_details_required")
        if self.status != "specified" and self.details:
            raise ValueError("food_details_conflict")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortText = ""
    display_name: ShortText = ""
    contact: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    instagram_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] = ""
    birth_year: int | None = Field(default=None, strict=True, ge=1000, le=9999)
    gender: ShortText = ""
    occupation: ShortText = ""
    mbtis: list[str] = Field(default_factory=list, max_length=16)
    interests: list[str] = Field(default_factory=list, max_length=11)
    self_traits: list[str] = Field(default_factory=list, max_length=6)
    desired_traits: list[str] = Field(default_factory=list, max_length=6)
    meal_budget_bands: list[str] = Field(default_factory=list, max_length=3)
    food_restrictions: FoodCondition = Field(default_factory=FoodCondition)
    allergies: FoodCondition = Field(default_factory=FoodCondition)

    @field_validator("birth_year")
    @classmethod
    def birth_year_not_future(cls, value):
        if value is not None and value > datetime.now(timezone.utc).year:
            raise ValueError("birth_year_invalid")
        return value

    @field_validator("instagram_id")
    @classmethod
    def instagram_format(cls, value):
        if value and not re.fullmatch(r"[A-Za-z0-9._]{1,30}", value):
            raise ValueError("instagram_format_invalid")
        return value

    @field_validator("mbtis", "interests", "self_traits", "desired_traits", "meal_budget_bands")
    @classmethod
    def canonical_selection(cls, values, info):
        if len(values) != len(set(values)) or any(
            v not in OPTIONS[info.field_name] for v in values
        ):
            raise ValueError("selection_invalid")
        return values


@router.get("/api/profile/options")
def profile_options():
    return {
        field: [{"value": value, "label": label} for value, label in choices.items()]
        for field, choices in OPTIONS.items()
    }


def profile_state(profile):
    data = Profile.model_validate(profile).model_dump() if profile is not None else None
    required = (
        "name",
        "display_name",
        "contact",
        "instagram_id",
        "birth_year",
        "gender",
        "occupation",
        "interests",
        "self_traits",
        "desired_traits",
        "meal_budget_bands",
    )
    missing = [field for field in required if not data or not data[field]]
    return {"profile": data, "complete": not missing, "missing_fields": missing}


def read_profile(connection, user_id):
    return connection.execute(
        text("SELECT data FROM participant_profile WHERE user_id=:id"), {"id": user_id}
    ).scalar()


@router.get("/api/me/profile")
def get_profile(user: Principal = Depends(require_user)):
    try:
        with database_engine().connect() as connection:
            return private_response(profile_state(read_profile(connection, user.id)))
    except SQLAlchemyError:
        raise HTTPException(503, "profile_unavailable") from None


@router.put("/api/me/profile")
def save_profile(payload: Profile, request: Request, user: Principal = Depends(require_user)):
    require_csrf(request)
    try:
        with database_engine().begin() as connection:
            connection.execute(
                text("""INSERT INTO participant_profile(user_id,data)
                VALUES (:id,CAST(:data AS jsonb)) ON CONFLICT(user_id) DO UPDATE
                SET data=EXCLUDED.data, updated_at=CURRENT_TIMESTAMP"""),
                {"id": user.id, "data": payload.model_dump_json()},
            )
        return private_response(profile_state(payload.model_dump()))
    except SQLAlchemyError:
        raise HTTPException(503, "profile_unavailable") from None


POLICY_VERSION = "demo-2026-10-16"
POLICIES = [
    {
        "purpose": "privacy",
        "version": POLICY_VERSION,
        "required": True,
        "title": "합성 데모 정보 수집·이용 동의",
        "body": "심사용 합성 정보만 입력합니다. 프로필과 선호는 매칭 흐름 검증에 사용하며 운영자가 "
        "확인할 수 있습니다. 연락처·Instagram·이름 원문·출생연도는 다른 참가자에게 "
        "공개하지 않습니다. 실제 개인정보를 입력하지 마십시오. 정식 운영용 처리방침이 아닙니다.",
    },
    {
        "purpose": "operation",
        "version": POLICY_VERSION,
        "required": True,
        "title": "합성 데모 운영 정책 동의",
        "body": "모의 결제·매칭·안내를 검증하는 심사용 서비스입니다. 실제 결제·예약·연락은 "
        "발생하지 않습니다. 동의 상태를 변경할 수 있으며 신청 가능 여부는 제출 시 "
        "다시 확인합니다. 보관·삭제 날짜와 미정 운영 정책은 별도 확정이 필요합니다.",
    },
]


class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["privacy", "operation"]
    version: str = Field(min_length=1, max_length=64)
    accepted: bool = Field(strict=True)


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consents: list[ConsentDecision] = Field(max_length=2)

    @model_validator(mode="after")
    def supported(self):
        if len({item.purpose for item in self.consents}) != len(self.consents):
            raise ValueError("duplicate_consent_purpose")
        if any(item.version != POLICY_VERSION for item in self.consents):
            raise ValueError("consent_version_unsupported")
        return self


@router.get("/api/consent/policies")
def consent_policies():
    return {"policies": POLICIES}


def consent_state(connection, user_id):
    rows = (
        connection.execute(
            text("""SELECT DISTINCT ON (purpose)
        purpose, version, accepted, recorded_at FROM consent_record
        WHERE user_id=:id ORDER BY purpose, id DESC"""),
            {"id": user_id},
        )
        .mappings()
        .all()
    )
    consents = [dict(row) | {"recorded_at": row["recorded_at"].isoformat()} for row in rows]
    complete = all(
        any(
            item["purpose"] == purpose and item["version"] == POLICY_VERSION and item["accepted"]
            for item in consents
        )
        for purpose in ("privacy", "operation")
    )
    return {"consents": consents, "complete": complete}


@router.get("/api/me/consents")
def get_consents(user: Principal = Depends(require_user)):
    try:
        with database_engine().connect() as connection:
            return private_response(consent_state(connection, user.id))
    except SQLAlchemyError:
        raise HTTPException(503, "consent_unavailable") from None


@router.put("/api/me/consents")
def save_consents(payload: ConsentInput, request: Request, user: Principal = Depends(require_user)):
    require_csrf(request)
    try:
        with database_engine().begin() as connection:
            # Serialize all purpose changes for this owner, including first writes.
            connection.execute(
                text("SELECT id FROM app_user WHERE id=:id FOR UPDATE"), {"id": user.id}
            )
            current = {
                item["purpose"]: item for item in consent_state(connection, user.id)["consents"]
            }
            for item in payload.consents:
                prior = current.get(item.purpose)
                if (
                    prior
                    and prior["version"] == item.version
                    and prior["accepted"] == item.accepted
                ):
                    continue
                connection.execute(
                    text("""INSERT INTO consent_record
                    (user_id,purpose,version,accepted) VALUES (:id,:purpose,:version,:accepted)"""),
                    {"id": user.id, **item.model_dump()},
                )
            result = consent_state(connection, user.id)
        return private_response(result)
    except SQLAlchemyError:
        raise HTTPException(503, "consent_unavailable") from None


@router.get("/api/admin/participants")
def list_participants(operator: Principal = Depends(require_operator)):
    try:
        with database_engine().connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT u.id, u.login_id, p.data
                FROM app_user u LEFT JOIN participant_profile p ON p.user_id=u.id
                WHERE u.role='participant' ORDER BY u.login_id""")
                )
                .mappings()
                .all()
            )
            return private_response(
                {
                    "participants": [
                        {
                            "id": str(row["id"]),
                            "login_id": row["login_id"],
                            "display_name": (row["data"] or {}).get("display_name", ""),
                            "profile_complete": profile_state(row["data"])["complete"],
                        }
                        for row in rows
                    ]
                }
            )
    except SQLAlchemyError:
        raise HTTPException(503, "profile_unavailable") from None


@router.get("/api/admin/participants/{participant_id}")
def participant_detail(participant_id: UUID, operator: Principal = Depends(require_operator)):
    try:
        with database_engine().connect() as connection:
            user = (
                connection.execute(
                    text("""SELECT id,login_id,role FROM app_user
                WHERE id=:id AND role='participant'"""),
                    {"id": participant_id},
                )
                .mappings()
                .first()
            )
            if user is None:
                raise HTTPException(404, "participant_not_found")
            profile = profile_state(read_profile(connection, participant_id))
            consent = consent_state(connection, participant_id)
            return private_response(
                {
                    "user": {
                        "id": str(user["id"]),
                        "login_id": user["login_id"],
                        "role": user["role"],
                    },
                    "profile": profile["profile"],
                    "profile_complete": profile["complete"],
                    "missing_fields": profile["missing_fields"],
                    "consents": consent["consents"],
                    "consents_complete": consent["complete"],
                }
            )
    except SQLAlchemyError:
        raise HTTPException(503, "profile_unavailable") from None
