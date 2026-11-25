"""Keep the versioned troubleshooting schema registered with Alembic."""

import io
import re

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from app.core.db import Base
from app.models.makeup_troubleshooting import PREFIX

TABLE_COLUMNS = {
    "release": (
        "dataset_version provenance dataset_sha256 created_at publish_status "
        "reviewed_by reviewed_at"
    ),
    "problem": (
        "dataset_version problem_id category_number category question clarifying_conditions "
        "selection_evidence_status"
    ),
    "situation": (
        "dataset_version situation_id problem_id selection_condition solution_draft "
        "original_evidence_cell solution_evidence_scope safety_class service_status "
        "reviewed_by reviewed_at approval_basis"
    ),
    "source": (
        "dataset_version source_id source_role title links metadata source_type publisher "
        "checked_at usage_status reviewed_by reviewed_at"
    ),
    "problem_evidence": (
        "dataset_version problem_id evidence_position source_id source_role relation scope "
        "survey_products_nonzero survey_products_with_data metadata"
    ),
    "situation_evidence": (
        "dataset_version situation_id reference_position source_id source_role source_note "
        "evidence_summary applies_to limitation"
    ),
}


def _migration():
    config = Config()
    config.set_main_option("script_location", "alembic")
    return ScriptDirectory.from_config(config).get_revision("0037").module


def _render(operation):
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=postgresql.dialect(), opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        operation()
    return output.getvalue()


def test_troubleshooting_metadata_and_migration_column_order():
    migration = _migration()
    assert migration.down_revision == "0036"
    expected = {PREFIX + name: fields.split() for name, fields in TABLE_COLUMNS.items()}
    metadata = {
        name: list(table.c.keys())
        for name, table in Base.metadata.tables.items()
        if name.startswith(PREFIX)
    }
    assert metadata == expected
    assert sum(map(len, metadata.values())) == 57
    sql = _render(migration.upgrade)
    ddl = {
        name: re.findall(r"^    (\w+) (?:text|integer|smallint|jsonb|timestamptz)\b", body, re.M)
        for name, body in re.findall(r"CREATE TABLE (\w+) \(\n(.*?)\n\);", sql, re.S)
    }
    assert ddl == expected
    assert "CREATE VIEW makeup_troubleshooting_serving" in sql
    assert "evidence.reference_count > 0 AND evidence.all_eligible IS TRUE" in sql
    assert "WHERE publish_status = 'approved'" in sql
    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE FROM" not in sql


def test_downgrade_removes_view_before_only_its_own_tables():
    sql = _render(_migration().downgrade)
    assert sql.lstrip().startswith("DROP VIEW makeup_troubleshooting_serving")
    assert re.findall(r"DROP TABLE (\w+);", sql) == [
        PREFIX + name
        for name in (
            "situation_evidence",
            "problem_evidence",
            "source",
            "situation",
            "problem",
            "release",
        )
    ]
