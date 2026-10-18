"""Work #9 shared foundation: the audit row commits or rolls back with its change."""

import pytest
from serentable.audit import record_audit
from serentable.database import database_engine
from sqlalchemy import text
from support import truncate


def operator_id():
    with database_engine().connect() as connection:
        return connection.execute(
            text("SELECT id FROM app_user WHERE role = 'operator' LIMIT 1")
        ).scalar_one()


def audit_rows():
    with database_engine().connect() as connection:
        return connection.execute(
            text("SELECT action, target_type, target_id, reason, after_state FROM operator_audit")
        ).all()


def test_audit_is_recorded_with_its_change_and_rolled_back_with_it(seeded_database):
    truncate("operator_audit")
    actor = operator_id()
    with pytest.raises(RuntimeError), database_engine().begin() as connection:
        record_audit(connection, actor, "test_change", "probe", "lost", reason="rolled back")
        raise RuntimeError("the change failed")
    assert audit_rows() == []
    with database_engine().begin() as connection:
        record_audit(
            connection, actor, "test_change", "probe", "kept", reason="why", after={"n": 1}
        )
    assert audit_rows() == [("test_change", "probe", "kept", "why", {"n": 1})]
    truncate("operator_audit")
