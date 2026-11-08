"""Remove the skincare refresh tracking table and its triggers."""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TABLES = (
    "products", "shades", "raw_oy_product", "raw_oy_product_option",
    "raw_oy_price_snapshot", "raw_oy_option_ingredient", "raw_oy_review_summary",
    "rec_mapping", "rec_mapping_ingredient", "rec_evidence", "rec_ingredient_link",
)


def upgrade():
    op.execute("DROP TRIGGER skincare_deleted ON skincare_serving")
    for table in TABLES:
        op.execute(f"DROP TRIGGER skincare_dirty ON {table}")
    op.execute("DROP FUNCTION mark_skincare_dirty()")
    op.drop_table("skincare_refresh_state")


def downgrade():
    op.create_table(
        "skincare_refresh_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("revision", sa.BigInteger, nullable=False),
        sa.Column("published_revision", sa.BigInteger, nullable=False),
    )
    op.execute("INSERT INTO skincare_refresh_state VALUES (1, 0, -1)")
    op.execute("""
        CREATE FUNCTION mark_skincare_dirty() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          UPDATE skincare_refresh_state SET revision = revision + 1 WHERE id = 1;
          RETURN NULL;
        END $$
    """)
    for table in TABLES:
        op.execute(f"""CREATE TRIGGER skincare_dirty AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION mark_skincare_dirty()""")
    op.execute("""CREATE TRIGGER skincare_deleted AFTER DELETE OR TRUNCATE ON skincare_serving
        FOR EACH STATEMENT EXECUTE FUNCTION mark_skincare_dirty()""")
