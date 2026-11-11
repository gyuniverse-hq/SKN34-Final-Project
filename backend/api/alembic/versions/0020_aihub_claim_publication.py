"""Store explicit ingredient claim publications.

Revision ID: aihub_claim_publication_v1
Revises: aihub_claim_review_v1
"""

import sqlalchemy as sa

from alembic import op

revision = "aihub_claim_publication_v1"
down_revision = "aihub_claim_review_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aihub_claim_publication",
        sa.Column("publication_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "claim_version_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_claim_version.claim_version_id"),
            nullable=False,
        ),
        sa.Column(
            "source_review_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_claim_review.claim_id"),
            nullable=False,
        ),
        sa.Column(
            "release_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_dataset_release.release_id"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_mfds_ingredient.ingredient_id"),
            nullable=False,
        ),
        sa.Column("mfds_source_hash", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("test_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "mfds_source_hash ~ '^[0-9a-f]{64}$' AND btrim(summary) <> '' "
            "AND btrim(source_title) <> '' AND btrim(publisher) <> '' "
            "AND (revoked_at IS NULL OR revoked_at >= published_at)",
            name="ck_aihub_publication_content",
        ),
    )
    op.create_index(
        "uq_aihub_active_publication",
        "aihub_claim_publication",
        ["claim_version_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_aihub_publication_ingredient", "aihub_claim_publication", ["ingredient_id"])
    op.create_index("ix_aihub_publication_review", "aihub_claim_publication", ["source_review_id"])
    op.execute("""
        CREATE FUNCTION aihub_publication_revoke() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
                RETURN NEW;
            END IF;
            IF TG_TABLE_NAME = 'aihub_claim_version' THEN
                UPDATE aihub_claim_publication SET revoked_at = clock_timestamp()
                WHERE revoked_at IS NULL AND claim_version_id IN (
                    SELECT claim_version_id FROM aihub_claim_version
                    WHERE claim_key = NEW.claim_key AND (
                        revision < NEW.revision OR
                        (TG_OP = 'UPDATE' AND claim_version_id = NEW.claim_version_id)
                    )
                );
            ELSIF TG_TABLE_NAME = 'aihub_claim_review' THEN
                UPDATE aihub_claim_publication SET revoked_at = clock_timestamp()
                WHERE revoked_at IS NULL AND source_review_id = NEW.claim_id;
            ELSIF TG_TABLE_NAME = 'aihub_knowledge_document' THEN
                UPDATE aihub_claim_publication SET revoked_at = clock_timestamp()
                WHERE revoked_at IS NULL AND source_review_id IN (
                    SELECT r.claim_id FROM aihub_claim_review r
                    JOIN aihub_knowledge_document d ON d.document_id = r.document_id
                    WHERE d.document_id = NEW.document_id OR (
                        d.source_identifier = NEW.source_identifier
                        AND d.document_id < NEW.document_id
                    )
                );
            ELSE
                UPDATE aihub_claim_publication SET revoked_at = clock_timestamp()
                WHERE revoked_at IS NULL AND (
                    release_id = NEW.release_id OR claim_version_id IN (
                        SELECT qc.claim_version_id FROM aihub_qa_claim qc
                        JOIN aihub_qa_case_raw q ON q.seq = qc.seq
                        WHERE q.release_id = NEW.release_id
                    ) OR source_review_id IN (
                        SELECT r.claim_id FROM aihub_claim_review r
                        JOIN aihub_qa_source_link qs ON qs.document_id = r.document_id
                        JOIN aihub_qa_case_raw q ON q.seq = qs.seq
                        WHERE q.release_id = NEW.release_id
                    )
                );
            END IF;
            RETURN NEW;
        END $$
    """)
    for table, events in (
        ("aihub_claim_version", "INSERT OR UPDATE"),
        ("aihub_claim_review", "UPDATE"),
        ("aihub_knowledge_document", "INSERT OR UPDATE"),
        ("aihub_dataset_release", "UPDATE OF rights_status"),
    ):
        op.execute(
            f"CREATE TRIGGER revoke_claim_publication AFTER {events} ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION aihub_publication_revoke()"
        )
    op.execute("""
        CREATE FUNCTION aihub_publication_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR
                (to_jsonb(NEW) - 'revoked_at') <> (to_jsonb(OLD) - 'revoked_at') THEN
                RAISE EXCEPTION 'Claim publication can only be revoked';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER claim_publication_immutable BEFORE UPDATE ON aihub_claim_publication
        FOR EACH ROW EXECUTE FUNCTION aihub_publication_immutable()
    """)


def downgrade() -> None:
    for table in (
        "aihub_claim_version",
        "aihub_claim_review",
        "aihub_knowledge_document",
        "aihub_dataset_release",
    ):
        op.execute(f"DROP TRIGGER revoke_claim_publication ON {table}")
    op.drop_table("aihub_claim_publication")
    op.execute("DROP FUNCTION aihub_publication_immutable()")
    op.execute("DROP FUNCTION aihub_publication_revoke()")
