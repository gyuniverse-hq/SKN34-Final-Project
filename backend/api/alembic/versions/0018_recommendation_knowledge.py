"""Install the versioned recommendation knowledge base and rebuild local-ID joins."""

import hashlib
import json
from pathlib import Path

import sqlalchemy as sa

from alembic import context, op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

SEED = Path(__file__).resolve().parents[2] / "seed" / "recommendation_v03"
TABLES = (
    "rec_concern",
    "rec_evidence",
    "rec_ingredient_dictionary",
    "rec_mapping",
    "rec_mapping_ingredient",
    "rec_mapping_evidence",
)
OLD_TABLES = (
    *TABLES[:5],
    "rec_manual_review_candidate",
    "rec_ingredient_link",
    "rec_concern_match",
    "skincare_serving",
)


def verified_file(name, digest):
    raw = (SEED / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"Incorrect recommendation release file: {name}")
    return json.loads(raw)


def upgrade():
    db = op.get_bind()
    tables = verified_file(
        "dataset.json", "cd4646492224a606e0c3d98d9b543f999b19aea30a8de241e5a769c43e9b7cb9"
    )["tables"]
    policy = verified_file(
        "identity.json", "c60c7bc5d5489a6a399cb57c3d31461b175a805484f093815db625aec57132d0"
    )
    db.execute(sa.text("SELECT pg_advisory_xact_lock(7284732)"))
    db.execute(sa.text("LOCK TABLE " + ", ".join(OLD_TABLES) + " IN ACCESS EXCLUSIVE MODE"))
    replace = context.get_x_argument(as_dictionary=True).get("replace_recommendations") == "v0.3"
    if not replace and any(
        db.scalar(sa.text(f"SELECT EXISTS(SELECT FROM {t})")) for t in OLD_TABLES
    ):
        raise RuntimeError("Back up recommendation data and supply -x replace_recommendations=v0.3")
    # No CASCADE. An unexpected dependent table must abort the entire transaction.
    op.execute("TRUNCATE " + ", ".join(OLD_TABLES))
    op.drop_table("rec_manual_review_candidate")
    op.execute("""ALTER TABLE rec_mapping DROP COLUMN evidence_id, DROP COLUMN ingredient_codes,
        DROP COLUMN mapping_status, DROP COLUMN human_mapping_review, DROP COLUMN ai_paper_review,
        DROP COLUMN re_review_required, DROP COLUMN requirements_scope,
        DROP COLUMN legacy_runtime_enabled,
        DROP COLUMN operational_review, DROP COLUMN operational_reviewed_at,
        ADD COLUMN applicability_scope text NOT NULL,
        ADD CONSTRAINT ck_rec_scope CHECK
        (applicability_scope IN ('ingredient_level','formula_specific'))""")
    op.execute("""ALTER TABLE rec_evidence DROP COLUMN ai_paper_review,
        ADD COLUMN study_type text NOT NULL,
        ADD COLUMN publication_year integer, ALTER COLUMN title SET NOT NULL,
        ALTER COLUMN source_url SET NOT NULL, ADD CONSTRAINT ck_rec_study_type CHECK
        (study_type IN ('human_intervention','human_observational','in_vitro','animal',
                        'method_validation','review','other'))""")
    op.execute("ALTER TABLE rec_ingredient_dictionary DROP COLUMN source_match_status")
    op.execute("""ALTER TABLE rec_ingredient_link DROP CONSTRAINT ck_rec_link_method,
        DROP CONSTRAINT ck_rec_link_provenance, DROP COLUMN reviewed_by, DROP COLUMN reviewed_at,
        DROP COLUMN note, ADD CONSTRAINT ck_rec_link_method CHECK
        (link_method IN ('standard_id','exact_name','verified_alias','verified_group_member'))""")
    op.execute("""ALTER TABLE rec_mapping_ingredient ADD CONSTRAINT ck_rec_component_order
                  CHECK(component_order >= 1)""")
    op.execute("""CREATE TABLE rec_mapping_evidence (
        mapping_id text REFERENCES rec_mapping NOT NULL,
        evidence_id text REFERENCES rec_evidence NOT NULL,
        supported_endpoint text NOT NULL, study_conditions jsonb NOT NULL DEFAULT '{}',
        applicability_note text NOT NULL, PRIMARY KEY(mapping_id,evidence_id),
        CONSTRAINT ck_rec_study_conditions CHECK(jsonb_typeof(study_conditions)='object'))""")
    op.create_index("ix_rec_mapping_evidence_evidence_id", "rec_mapping_evidence", ["evidence_id"])
    for table in TABLES:
        db.execute(
            sa.text(
                f"INSERT INTO {table} SELECT * FROM "
                f"jsonb_populate_recordset(NULL::{table}, CAST(:rows AS jsonb))"
            ),
            {"rows": json.dumps(tables[table])},
        )
    if db.scalar(
        sa.text("""SELECT EXISTS (SELECT 1 FROM rec_mapping m
        LEFT JOIN rec_mapping_ingredient i USING(mapping_id) GROUP BY m.mapping_id
        HAVING (m.mapping_type='single' AND count(i.ingredient_code)<>1)
        OR (m.mapping_type='combination' AND count(i.ingredient_code)<2)
        OR NOT EXISTS (SELECT FROM rec_mapping_evidence e WHERE e.mapping_id=m.mapping_id))""")
    ):
        raise ValueError("Invalid mapping components or missing evidence")
    db.execute(sa.text((SEED / "link.sql").read_text("utf-8")), {"policy": json.dumps(policy)})
    db.execute(sa.text((SEED / "match.sql").read_text("utf-8")))


def downgrade():
    raise RuntimeError(
        "Restore the pre-0018 recommendation backup to recover historical review data."
    )
