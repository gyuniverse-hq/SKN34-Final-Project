"""Persist versioned chunks and reusable AIHub embedding inputs."""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('public.aihub_rag_chunk') IS NOT NULL
               OR to_regclass('public.aihub_rag_embedding') IS NOT NULL THEN
                RAISE EXCEPTION 'G5 tables already exist; verify legacy migration before upgrade';
            END IF;
        END $$
    """)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE aihub_rag_embedding (
            embedding_key text PRIMARY KEY,
            embedding_model text NOT NULL,
            embedding_version text NOT NULL,
            dimensions integer NOT NULL CHECK (dimensions = 3072),
            input_hash text NOT NULL,
            embedding halfvec(3072) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (embedding_model, embedding_version, dimensions, input_hash)
        )
    """)
    op.execute("""
        CREATE TABLE aihub_rag_chunk (
            chunk_id text PRIMARY KEY,
            document_id bigint NOT NULL REFERENCES aihub_knowledge_document,
            extraction_id bigint NOT NULL REFERENCES aihub_document_extraction,
            chunk_index integer NOT NULL CHECK (chunk_index >= 0),
            index_version text NOT NULL,
            source_version text NOT NULL,
            embedding_model text NOT NULL,
            embedding_version text NOT NULL,
            content text NOT NULL CHECK (content <> ''),
            content_hash text NOT NULL,
            source_spans jsonb NOT NULL CHECK (
                jsonb_typeof(source_spans) = 'array' AND jsonb_array_length(source_spans) > 0
            ),
            search_terms tsvector NOT NULL,
            embedding_key text NOT NULL REFERENCES aihub_rag_embedding,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (document_id, index_version, embedding_model, embedding_version, chunk_index)
        )
    """)
    op.execute("""
        CREATE INDEX ix_aihub_rag_embedding_hnsw ON aihub_rag_embedding
        USING hnsw (embedding halfvec_cosine_ops)
    """)
    op.execute("CREATE INDEX ix_aihub_rag_chunk_terms ON aihub_rag_chunk USING gin (search_terms)")
    op.execute("CREATE INDEX ix_aihub_rag_chunk_embedding ON aihub_rag_chunk (embedding_key)")


def downgrade():
    op.drop_table("aihub_rag_chunk")
    op.drop_table("aihub_rag_embedding")
