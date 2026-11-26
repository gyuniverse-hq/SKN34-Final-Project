"""Store the sanitized result of an idempotent conversation state update."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_g7_state_update_result"
down_revision = "0001_g7_persistence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_turns", sa.Column("result_payload", postgresql.JSONB, nullable=True))


def downgrade():
    op.drop_column("chat_turns", "result_payload")
