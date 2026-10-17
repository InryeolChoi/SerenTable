"""Private source preparation through the external CLI and real PostgreSQL."""

import hashlib
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

HEADERS = [
    "타임스탬프",
    "이름(가명)",
    "연락처 (한 번 더 오타 확인!)",
    "Instagram ID \n(어떤 분인지 확인하기 위한 단계입니다. \n"
    "확인 후 바로 비공개로 돌리셔도 됩니다)",
    "나이",
    "성별",
    "직업 (구체적으로)\nEx. 마케터, 개발자, 간호사, 디자이너..",
    "MBTI",
    "참석 가능 지역 (복수 체크)\n*서울권 외 희망 지역은 '기타'란에 구체적으로 작성\n"
    "(Ex. 김포 구래동, 수원 인계동, 부산 서면역 등)",
    "나의 요즘 관심사는? (복수 선택)",
    "나는 어떤 사람인가요? (복수 선택)",
    "어떤 사람을 만나고 싶으신가요? (복수 선택)",
    "식사에 얼마까지 쓸 수 있으신가요? (복수 선택 가능)",
    "참가 가능한 날짜 ",
    "참가권 선택\n(참가비 입금은 문자로 안내드립니다.)",
    "와썹하우스는 일회성 인연이 아닌, 지속적인 관계 유지를 위해 오픈 단톡방이 만들어집니다. "
    "개인정보 수집 및 이용 동의하시나요?\n(식사 후 퇴장하셔도 무방합니다.)",
    "못 먹는 음식이 있으신가요? ",
]


def workbook(path, *, formula=False, bad_header=False, regions="홍대/합정", age="25"):
    """Independent synthetic values, never a source-data copy."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = Element("worksheet", xmlns=ns)
    data = SubElement(root, "sheetData")
    headers = list(HEADERS)
    if bad_header:
        headers[7] = "unexpected field"
    rows = [(2, headers)]
    for row_number, mbti in [(3, " Entj "), (5, "INFP, ENFP"), (7, "WNTJ")]:
        rows.append(
            (
                row_number,
                [
                    "",
                    "PRIVATE-SENTINEL-SAME-NAME",
                    "",
                    "",
                    age,
                    "여성",
                    "",
                    mbti,
                    regions,
                    "운동 (헬스, 러닝, 클라이밍 등), 독서·글쓰기",
                    "경청을 잘 함",
                    "나와 비슷한 사람",
                    "10,000~20,000원",
                    "10/15 (목), 10/22 (목)",
                    "1회권",
                    "동의",
                    "",
                ],
            )
        )
    for number, values in rows:
        row = SubElement(data, "row", r=str(number))
        for index, value in enumerate(values):
            cell = SubElement(row, "c", r=f"{chr(65 + index)}{number}", t="inlineStr")
            if formula and number == 3 and index == 7:
                SubElement(cell, "f").text = "1+1"
            SubElement(SubElement(cell, "is"), "t").text = value
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="'
            + ns
            + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="설문지 응답 시트1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", tostring(root, encoding="utf-8"))
    return path


def cli(*args, environment=None):
    result = subprocess.run(
        [sys.executable, "-m", "serentable.source_import", *map(str, args)],
        env={**os.environ, "PYTHONPATH": "backend", **(environment or {})},
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    return result


def test_preview_normalizes_choices_without_inventing_identity_or_changing_source(tmp_path):
    source = workbook(tmp_path / "synthetic.xlsx")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = cli("preview", source)
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["response_count"] == 3
    assert body["source_sha256"] == before
    assert body["mbti_counts"] == {"ENFP": 1, "ENTJ": 1, "INFP": 1}
    assert body["review_counts"]["birth_year_unresolved"] == 3
    assert body["review_counts"]["contact_missing"] == 3
    assert body["review_counts"]["mbti_unrecognized"] == 1
    assert body["review_counts"]["date_year_unknown"] == 3
    assert body["source_interest_counts"]["reading_writing"] == 3
    assert body["source_interest_counts"]["exercise"] == 3
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.fixture
def source_database():
    original = make_url(os.environ["TEST_DATABASE_URL"])
    name = "serentable_source_test_" + uuid.uuid4().hex[:12]
    admin = create_engine(
        original.set(drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = original.set(database=name).render_as_string(hide_password=False)
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env={**os.environ, "PYTHONPATH": "backend", "DATABASE_URL": url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield {"SOURCE_DATABASE_URL": url}
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_load_is_atomic_idempotent_and_reported_through_the_cli(tmp_path, source_database):
    source = workbook(tmp_path / "synthetic.xlsx")
    first = cli("load", source, environment=source_database)
    assert first.returncode == 0, first.stderr
    loaded = json.loads(first.stdout)
    assert loaded["created"] is True and loaded["response_count"] == 3
    second = cli("load", source, environment=source_database)
    assert second.returncode == 0, second.stderr
    replayed = json.loads(second.stdout)
    assert replayed["created"] is False and replayed["batch_id"] == loaded["batch_id"]
    report = cli("report", loaded["batch_id"], environment=source_database)
    assert report.returncode == 0, report.stderr
    assert json.loads(report.stdout)["response_count"] == 3
    assert json.loads(report.stdout)["mbti_counts"] == {"ENFP": 1, "ENTJ": 1, "INFP": 1}


@pytest.mark.parametrize(
    "change, error",
    [
        ({"formula": True}, "source_formula_not_allowed"),
        ({"bad_header": True}, "source_headers_invalid"),
    ],
)
def test_unsupported_input_is_rejected_without_echoing_its_contents(tmp_path, change, error):
    source = workbook(tmp_path / "synthetic.xlsx", **change)
    result = cli("preview", source)
    assert result.returncode == 2
    assert result.stderr.strip() == error
    assert result.stdout == ""


def test_concurrent_loads_create_one_batch(tmp_path, source_database):
    source = workbook(tmp_path / "synthetic.xlsx")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: cli("load", source, environment=source_database), range(2))
        )
    assert [result.returncode for result in results] == [0, 0]
    loaded = [json.loads(result.stdout) for result in results]
    assert len({result["batch_id"] for result in loaded}) == 1
    assert sorted(result["created"] for result in loaded) == [False, True]
    assert [result["response_count"] for result in loaded] == [3, 3]


def test_partial_database_failure_rolls_back_the_batch_and_can_retry(tmp_path, source_database):
    source = workbook(tmp_path / "synthetic.xlsx")
    engine = create_engine(
        make_url(source_database["SOURCE_DATABASE_URL"]).set(drivername="postgresql+psycopg")
    )
    with engine.begin() as connection:
        connection.execute(
            text("""CREATE FUNCTION source_private.test_failure() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN IF NEW.source_row_number = 5 THEN
          RAISE EXCEPTION 'PRIVATE-SENTINEL-FAILURE'; END IF; RETURN NEW; END $$""")
        )
        connection.execute(
            text("""CREATE TRIGGER test_failure BEFORE INSERT
        ON source_private.response_staging FOR EACH ROW
        EXECUTE FUNCTION source_private.test_failure()""")
        )
    failed = cli("load", source, environment=source_database)
    assert failed.returncode == 2 and failed.stdout == ""
    assert failed.stderr.strip() == "source_preparation_failed"
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER test_failure ON source_private.response_staging"))
        connection.execute(text("DROP FUNCTION source_private.test_failure()"))
    retried = cli("load", source, environment=source_database)
    assert retried.returncode == 0, retried.stderr
    assert json.loads(retried.stdout)["created"] is True
    assert json.loads(retried.stdout)["response_count"] == 3
    engine.dispose()


def test_source_schema_denies_a_role_without_explicit_grants(source_database):
    engine = create_engine(
        make_url(source_database["SOURCE_DATABASE_URL"]).set(drivername="postgresql+psycopg")
    )
    role = "source_read_probe_" + uuid.uuid4().hex[:12]
    with engine.begin() as connection:
        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
    try:
        with pytest.raises(DBAPIError) as rejected:
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL ROLE "{role}"'))
                connection.execute(text("SELECT count(*) FROM source_private.response_staging"))
        assert rejected.value.orig.sqlstate == "42501"
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP ROLE "{role}"'))
        engine.dispose()


def test_load_rejects_the_application_database_and_remote_targets(tmp_path, source_database):
    source = workbook(tmp_path / "synthetic.xlsx")
    same = cli(
        "load",
        source,
        environment={**source_database, "DATABASE_URL": source_database["SOURCE_DATABASE_URL"]},
    )
    assert same.returncode == 2
    assert same.stderr.strip() == "source_database_is_application_database"
    remote = cli(
        "load",
        source,
        environment={
            "SOURCE_DATABASE_URL": "postgresql://local-only@db.invalid/serentable_source_test"
        },
    )
    assert remote.returncode == 2
    assert remote.stderr.strip() == "source_database_must_be_local"


def test_connection_options_cannot_override_the_checked_database_destination(tmp_path):
    source = workbook(tmp_path / "synthetic.xlsx")
    # Port 1 is deliberately closed loopback, so RED cannot contact a real target.
    result = cli(
        "load",
        source,
        environment={
            "SOURCE_DATABASE_URL": "postgresql://local-only@127.0.0.1:1/serentable_source_test?dbname=unrelated_db&hostaddr=127.0.0.1",
        },
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "source_database_options_not_allowed"


def test_libpq_environment_cannot_override_the_checked_destination(tmp_path):
    source = workbook(tmp_path / "synthetic.xlsx")
    result = cli(
        "load",
        source,
        environment={
            "SOURCE_DATABASE_URL": "postgresql://local-only@127.0.0.1:1/serentable_source_test",
            "PGHOSTADDR": "127.0.0.1",
        },
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "source_database_environment_options_not_allowed"


@pytest.mark.parametrize("regions", ["잠실강남/신논현", "/"])
def test_unseparated_or_empty_choice_tokens_are_reviewed_instead_of_guessed(tmp_path, regions):
    source = workbook(tmp_path / "synthetic.xlsx", regions=regions)
    result = cli("preview", source)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["review_counts"]["source_regions_unresolved"] == 3


def test_unbounded_age_exponents_are_reviewed_without_allocating_a_large_integer(tmp_path):
    source = workbook(tmp_path / "synthetic.xlsx", age="1E1000000000")
    result = cli("preview", source)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["review_counts"]["source_age_invalid"] == 3
