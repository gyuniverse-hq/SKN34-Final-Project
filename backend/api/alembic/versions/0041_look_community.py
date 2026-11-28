"""Add public look posts, recommendations, and reports."""

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ddl = """
        CREATE TABLE look_posts (
            id uuid PRIMARY KEY,
            owner_id varchar(64) NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            title varchar(80) NOT NULL,
            description varchar(500) NOT NULL,
            products jsonb NOT NULL,
            photo bytea NOT NULL,
            hidden boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX look_posts_public_recent ON look_posts (created_at DESC, id) WHERE NOT hidden;
        CREATE INDEX look_posts_owner_recent ON look_posts (owner_id, created_at DESC);
        CREATE TABLE look_post_votes (
            post_id uuid NOT NULL REFERENCES look_posts(id) ON DELETE CASCADE,
            member_id varchar(64) NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            PRIMARY KEY (post_id, member_id)
        );
        CREATE TABLE look_post_reports (
            post_id uuid NOT NULL REFERENCES look_posts(id) ON DELETE CASCADE,
            member_id varchar(64) NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            reason varchar(300) NOT NULL,
            PRIMARY KEY (post_id, member_id)
        );
    """
    for statement in ddl.strip().rstrip(";").split(";"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE look_post_reports, look_post_votes, look_posts")
