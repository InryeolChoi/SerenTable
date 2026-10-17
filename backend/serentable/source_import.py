"""Private, versioned source preparation. Never creates app users or transactions.

CLI output is aggregate-only. Original cells are transient input, never log messages.
"""

import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from serentable.database import engine_for
from serentable.profile import OPTIONS

RULES_VERSION = "source-preparation-v1"
HEADER_HASH = "1d523a3cc21faa1876a0b020e2dbcaa7fde3032b390a049a9b22746f8fd995de"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class SourceRejected(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value).hexdigest()


def compact(value):
    return re.sub(r"\s+", "", value)


def source_choices(value, choices):
    """Recognize whole labelled choices before touching commas inside parentheses.

    Any unexplained remainder rejects the entire field instead of silently guessing a
    valid-looking substring. Source categories remain separate from app selections.
    """
    remaining = compact(value)
    selected = []
    for code, label in sorted(choices.items(), key=lambda item: -len(compact(item[1]))):
        label = compact(label)
        if label in remaining:
            selected.append(code)
            remaining = remaining.replace(label, "")
    if remaining.strip(",，;/|·"):
        return [], True
    return sorted(set(selected)), False


def normalize(cells):
    def get(column):
        return cells.get(column, "").strip()

    review = [
        "birth_year_unresolved",
        "application_time_unresolved",
        "consent_not_created",
        "payment_not_created",
    ]
    for column, field in [("C", "contact"), ("D", "instagram"), ("G", "occupation")]:
        review.append(f"{field}_not_imported" if get(column) else f"{field}_missing")
    try:
        age = Decimal(get("E"))
        source_age = int(age) if age.is_finite() and age == int(age) and 0 <= age <= 150 else None
    except (InvalidOperation, ValueError, OverflowError):
        source_age = None
    if source_age is None:
        review.append("source_age_invalid")
    mbti = get("H").upper()
    mbtis = sorted(set(re.findall(r"(?<![A-Z])[EI][NS][TF][JP](?![A-Z])", mbti)))
    remainder = re.sub(r"(?<![A-Z])[EI][NS][TF][JP](?![A-Z])", "", mbti)
    if not mbtis:
        review.append("mbti_unrecognized")
    elif remainder.strip(" \t\r\n,，;/|·+&()"):
        mbtis = []
        review.append("mbti_needs_review")
    interests = {
        **{
            key: label
            for key, label in OPTIONS["interests"].items()
            if key not in ("reading", "writing")
        },
        "reading_writing": "독서·글쓰기",
        "exercise": "운동 (헬스, 러닝, 클라이밍 등)",
    }
    normalized = {
        "source_age": source_age,
        "birth_year": None,
        "contact": None,
        "instagram_id": None,
        "occupation": None,
        "mbtis": mbtis,
        "food_status": "unreviewed" if get("Q") else "unknown",
    }
    for column, field, choices in [
        (
            "I",
            "source_regions",
            {
                "hongdae": "홍대/합정",
                "jamsil": "잠실",
                "gangnam": "강남/신논현",
                "euljiro": "을지로/종로",
            },
        ),
        ("J", "source_interests", interests),
        ("K", "source_self_traits", OPTIONS["self_traits"]),
        ("L", "source_desired_traits", OPTIONS["desired_traits"]),
        ("M", "source_meal_budgets", OPTIONS["meal_budget_bands"]),
    ]:
        choices_found, unresolved = source_choices(get(column), choices)
        normalized[field] = choices_found
        if unresolved or not get(column):
            review.append(f"{field}_unresolved")
    review.append("date_year_unknown" if get("N") else "date_missing")
    # Yearless dates, names, arbitrary comments and free text are not replicated into the
    # DB. Their private lineage points to the untouched file/sheet/row for manual review.
    if get("Q"):
        review.append("food_requires_review")
    return normalized, sorted(set(review))


def read_source(path):
    if path.stat().st_size > 20_000_000:
        raise SourceRejected("source_too_large")
    content = path.read_bytes()
    checksum = digest(content)
    with ZipFile(BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > 1000 or sum(member.file_size for member in members) > 100_000_000:
            raise SourceRejected("source_too_large")
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = book.findall("s:sheets/s:sheet", NS)
        if len(sheets) != 1 or sheets[0].attrib["name"] != "설문지 응답 시트1":
            raise SourceRejected("source_layout_invalid")
        relations = {
            item.attrib["Id"]: item
            for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        relation = relations[sheets[0].attrib[f"{{{REL}}}id"]]
        if relation.attrib.get("TargetMode") == "External":
            raise SourceRejected("source_layout_invalid")
        target = relation.attrib["Target"]
        member = (
            target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        )
        if not member.startswith("xl/worksheets/"):
            raise SourceRejected("source_layout_invalid")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(item.itertext())
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        root = ET.fromstring(archive.read(member))
        rows = {}
        for row in root.findall("s:sheetData/s:row", NS):
            number = int(row.attrib["r"])
            if number in rows or number < 1 or number > 10000:
                raise SourceRejected("source_layout_invalid")
            cells = {}
            for cell in row.findall("s:c", NS):
                if cell.find("s:f", NS) is not None:
                    raise SourceRejected("source_formula_not_allowed")
                reference = re.fullmatch(r"([A-Z]+)([0-9]+)", cell.attrib["r"])
                if reference is None or int(reference[2]) != number or reference[1] in cells:
                    raise SourceRejected("source_layout_invalid")
                value = cell.findtext("s:v", default="", namespaces=NS)
                if cell.attrib.get("t") == "s":
                    index = int(value)
                    if not 0 <= index < len(strings):
                        raise SourceRejected("source_layout_invalid")
                    value = strings[index]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(item.text or "" for item in cell.findall("s:is//s:t", NS))
                if len(value) > 4000:
                    raise SourceRejected("source_cell_too_large")
                if reference[1] not in set("ABCDEFGHIJKLMNOPQ") and value.strip():
                    raise SourceRejected("source_layout_invalid")
                cells[reference[1]] = value
            rows[number] = cells
        headers = [rows.get(2, {}).get(column, "").strip() for column in "ABCDEFGHIJKLMNOPQ"]
        if digest(json.dumps(headers, ensure_ascii=False).encode()) != HEADER_HASH:
            raise SourceRejected("source_headers_invalid")
        responses = []
        for number, cells in sorted(rows.items()):
            if number > 2 and any(value.strip() for value in cells.values()):
                normalized, review = normalize(cells)
                responses.append({"row": number, "data": normalized, "review": review})
        if not responses or len(responses) > 5000:
            raise SourceRejected("source_response_count_invalid")
    if digest(path.read_bytes()) != checksum:
        raise SourceRejected("source_changed")
    return checksum, sheets[0].attrib["name"], responses


def summarize(checksum, responses, rules_version=RULES_VERSION):
    return {
        "source_sha256": checksum,
        "rules_version": rules_version,
        "response_count": len(responses),
        "mbti_counts": dict(
            sorted(Counter(value for row in responses for value in row["data"]["mbtis"]).items())
        ),
        "source_interest_counts": dict(
            sorted(
                Counter(
                    value for row in responses for value in row["data"]["source_interests"]
                ).items()
            )
        ),
        "review_counts": dict(
            sorted(Counter(code for row in responses for code in row["review"]).items())
        ),
    }


def preparation_engine():
    value = os.environ.get("SOURCE_DATABASE_URL")
    if not value:
        raise SourceRejected("source_database_required")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or url.host not in ("localhost", "127.0.0.1", "::1"):
        raise SourceRejected("source_database_must_be_local")
    if not (url.database or "").startswith("serentable_source_"):
        raise SourceRejected("source_database_not_private")
    if os.environ.get("APP_ENV") == "production":
        raise SourceRejected("source_import_not_in_production")
    app_url = os.environ.get("DATABASE_URL")
    if app_url:
        app = make_url(app_url)
        hosts = {"localhost", "127.0.0.1", "::1"}
        same_host = app.host == url.host or app.host in hosts and url.host in hosts
        if same_host and (app.port or 5432) == (url.port or 5432) and app.database == url.database:
            raise SourceRejected("source_database_is_application_database")
    return engine_for(value)


def report_batch(connection, batch_id):
    batch = (
        connection.execute(
            text(
                "SELECT source_sha256, rules_version, response_count "
                "FROM source_private.import_batch WHERE id = :id"
            ),
            {"id": batch_id},
        )
        .mappings()
        .first()
    )
    if batch is None:
        raise SourceRejected("source_batch_not_found")
    responses = [
        {"data": row["normalized_data"], "review": row["review_codes"]}
        for row in connection.execute(
            text(
                "SELECT normalized_data, review_codes FROM source_private.response_staging "
                "WHERE batch_id = :id"
            ),
            {"id": batch_id},
        ).mappings()
    ]
    if len(responses) != batch["response_count"]:
        raise SourceRejected("source_batch_incomplete")
    return {
        "batch_id": str(batch_id),
        **summarize(batch["source_sha256"], responses, batch["rules_version"]),
    }


def load_source(checksum, sheet_name, responses):
    engine = preparation_engine()
    with engine.begin() as connection:
        batch_id = uuid.uuid4()
        created = connection.execute(
            text("""INSERT INTO source_private.import_batch
            (id, source_sha256, rules_version, response_count)
            VALUES (:id, :sha, :rules, :count)
            ON CONFLICT (source_sha256, rules_version) DO NOTHING RETURNING id"""),
            {"id": batch_id, "sha": checksum, "rules": RULES_VERSION, "count": len(responses)},
        ).scalar()
        if created is not None:
            connection.execute(
                text("""INSERT INTO source_private.response_staging
                (batch_id, sheet_name, source_row_number, normalized_data, review_codes)
                VALUES (:id, :sheet, :row, CAST(:data AS jsonb), CAST(:review AS jsonb))"""),
                [
                    {
                        "id": batch_id,
                        "sheet": sheet_name,
                        "row": row["row"],
                        "data": json.dumps(row["data"], ensure_ascii=False),
                        "review": json.dumps(row["review"]),
                    }
                    for row in responses
                ],
            )
        else:
            batch_id = connection.execute(
                text(
                    "SELECT id FROM source_private.import_batch "
                    "WHERE source_sha256 = :sha AND rules_version = :rules"
                ),
                {"sha": checksum, "rules": RULES_VERSION},
            ).scalar_one()
        return {"created": created is not None, **report_batch(connection, batch_id)}


def main():
    parser = argparse.ArgumentParser(
        description="Private source preparation; aggregate output only"
    )
    parser.add_argument("command", choices=["preview", "load", "report"])
    parser.add_argument("source", help="Local XLSX path, or a batch UUID for report")
    args = parser.parse_args()
    try:
        if args.command == "report":
            batch_id = uuid.UUID(args.source)
            with preparation_engine().connect() as connection:
                result = report_batch(connection, batch_id)
        else:
            checksum, sheet, responses = read_source(Path(args.source))
            result = (
                load_source(checksum, sheet, responses)
                if args.command == "load"
                else summarize(checksum, responses)
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except SourceRejected as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, BadZipFile, KeyError, ValueError, ET.ParseError, SQLAlchemyError):
        print("source_preparation_failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
