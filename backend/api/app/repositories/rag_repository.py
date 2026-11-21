"""Data access for the opt-in G5 index and original document blocks."""

import json

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rag import (
    DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
    INDEX_VERSION,
    RagLocation,
)

PROFILE = {
    "model": EMBEDDING_MODEL,
    "embedding_version": EMBEDDING_VERSION,
    "index_version": INDEX_VERSION,
    "dimensions": DIMENSIONS,
}
VISIBLE = """
    d.rights_status <> 'blocked'
    AND d.review_status NOT IN ('rejected', 'rights_blocked')
    AND (:local OR (d.rights_status = 'service_approved' AND d.review_status = 'approved'))
"""
CURRENT = """
    e.verified AND e.status = 'success' AND e.source_sha256 = d.content_sha256
"""
CHUNK_PROFILE = """
    c.index_version = :index_version AND c.embedding_model = :model
    AND c.embedding_version = :embedding_version
    AND c.source_version = e.source_sha256
"""
CHUNK_SOURCE = """
    JOIN aihub_document_extraction e ON e.extraction_id = c.extraction_id
    JOIN aihub_knowledge_document d ON d.document_id = c.document_id
    AND d.document_id = e.document_id
"""
CHUNK_FIELDS = """
    c.chunk_id, c.document_id, c.extraction_id, c.source_version, e.file_id,
    c.source_spans, c.content, coalesce(d.title_raw, '') AS title
"""


class RagRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def rows(self, query, parameters):
        return (await self.session.execute(text(query), parameters)).mappings().all()

    async def sources(self, ids: list[int] | None, *, local: bool):
        return await self.rows(
            f"""
            SELECT DISTINCT ON (d.document_id) d.document_id, e.extraction_id,
              e.source_sha256, e.file_id, coalesce(d.title_raw, '') AS title
            FROM aihub_knowledge_document d
            JOIN aihub_document_extraction e USING (document_id)
            WHERE {CURRENT} AND {VISIBLE}
              AND (CAST(:ids AS bigint[]) IS NULL OR d.document_id = ANY(CAST(:ids AS bigint[])))
            ORDER BY d.document_id, e.created_at DESC, e.extraction_id DESC
        """,
            {"ids": ids, "local": local},
        )

    async def blocks(self, extraction_id: int):
        return await self.rows(
            """
            SELECT block_order, block_type, text_raw, text_sha256, source_locator
            FROM aihub_document_block WHERE extraction_id = :eid ORDER BY block_order
        """,
            {"eid": extraction_id},
        )

    async def lock(self, key: str):
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    async def stored_keys(self, keys: list[str]) -> set[str]:
        rows = await self.rows(
            """
            SELECT embedding_key FROM aihub_rag_embedding
            WHERE embedding_key = ANY(CAST(:keys AS text[]))
              AND embedding_model = :model AND embedding_version = :embedding_version
              AND dimensions = :dimensions
        """,
            PROFILE | {"keys": keys},
        )
        return {row["embedding_key"] for row in rows}

    async def save_embeddings(self, records):
        if not records:
            return
        statement = text("""
            INSERT INTO aihub_rag_embedding (
                embedding_key, embedding_model, embedding_version, dimensions, input_hash, embedding
            ) VALUES (
                :key, :model, :embedding_version, :dimensions, :hash, CAST(:vector AS halfvec)
            )
            ON CONFLICT (embedding_key) DO NOTHING
        """)
        await self.session.execute(statement, [PROFILE | row for row in records])

    async def replace_chunks(self, source, records, *, local: bool):
        doc = source["document_id"]
        await self.lock(f"g5-doc:{doc}")
        active = await self.sources([doc], local=local)
        if len(active) != 1 or dict(active[0]) != dict(source):
            raise ValueError(f"Source changed while indexing document {doc}")
        current = await self.rows(
            """
            SELECT chunk_id, source_version,
                   content_hash, source_spans, embedding_key, extraction_id
            FROM aihub_rag_chunk
            WHERE document_id = :doc AND index_version = :index_version
              AND embedding_model = :model AND embedding_version = :embedding_version
        """,
            PROFILE | {"doc": doc},
        )
        existing = {row["chunk_id"]: row for row in current}
        changed = []
        for record in records:
            old = existing.pop(record["chunk_id"], None)
            candidate = PROFILE | record
            if old is not None and (
                old["source_version"],
                old["content_hash"],
                old["source_spans"],
                old["embedding_key"],
                old["extraction_id"],
            ) == (
                candidate["source_version"],
                candidate["content_hash"],
                json.loads(candidate["spans"]),
                candidate["embedding_key"],
                candidate["eid"],
            ):
                continue
            changed.append(candidate)
        if changed:
            q = text("""
                INSERT INTO aihub_rag_chunk (
                    chunk_id, document_id, extraction_id, chunk_index,
                    index_version, source_version,
                    embedding_model, embedding_version, content, content_hash, source_spans,
                    search_terms, embedding_key
                ) VALUES (
                    :chunk_id, :doc, :eid, :idx, :index_version, :source_version, :model,
                    :embedding_version, :content, :content_hash, CAST(:spans AS jsonb),
                    to_tsvector('simple', :terms), :embedding_key
                )
                ON CONFLICT (chunk_id) DO UPDATE SET
                    extraction_id = excluded.extraction_id,
                    source_version = excluded.source_version,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    source_spans = excluded.source_spans, search_terms = excluded.search_terms,
                    embedding_key = excluded.embedding_key, updated_at = now()
            """)
            await self.session.execute(q, changed)
        if existing:
            await self.session.execute(
                text("DELETE FROM aihub_rag_chunk WHERE chunk_id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": list(existing)},
            )
        return len(changed), len(existing)

    async def keyword(self, terms, *, local):
        if not terms:
            return []
        return await self.rows(
            f"""
            SELECT {CHUNK_FIELDS},
              ts_rank_cd(c.search_terms, to_tsquery('simple', :terms)) AS score
            FROM aihub_rag_chunk c {CHUNK_SOURCE}
            WHERE {CHUNK_PROFILE}
              AND {CURRENT} AND {VISIBLE}
              AND c.search_terms @@ to_tsquery('simple', :terms)
            ORDER BY score DESC, c.chunk_id LIMIT 80
        """,
            PROFILE | {"terms": terms, "local": local},
        )

    async def vector(self, query, *, local):
        # Keep exact cosine ranking because the HNSW comparison missed valid evidence.
        return await self.rows(
            f"""
            SELECT {CHUNK_FIELDS}, 1 - nearest.distance AS score
            FROM (
                SELECT v.embedding_key, v.embedding <=>
                       CAST(:query AS halfvec) AS distance
                FROM aihub_rag_embedding v
                WHERE v.embedding_model = :model AND v.embedding_version = :embedding_version
                  AND v.dimensions = :dimensions
                  AND EXISTS (
                    SELECT 1 FROM aihub_rag_chunk c {CHUNK_SOURCE}
                    WHERE c.embedding_key = v.embedding_key AND {CHUNK_PROFILE}
                      AND {CURRENT} AND {VISIBLE}
                  )
                ORDER BY (v.embedding <=> CAST(:query AS halfvec)) + 0.0, v.embedding_key
                LIMIT 80
            ) nearest
            JOIN aihub_rag_chunk c USING (embedding_key) {CHUNK_SOURCE}
            WHERE {CHUNK_PROFILE}
              AND {CURRENT} AND {VISIBLE}
            ORDER BY nearest.distance, c.chunk_id LIMIT 80
        """,
            PROFILE | {"query": json.dumps(query, separators=(",", ":")), "local": local},
        )

    async def original(self, location: RagLocation, *, local: bool):
        return await self.rows(
            f"""
            SELECT b.block_order, b.block_type, b.text_raw, b.text_sha256, b.source_locator
            FROM aihub_document_block b
            JOIN aihub_document_extraction e USING (extraction_id)
            JOIN aihub_knowledge_document d USING (document_id)
            WHERE d.document_id = :doc AND e.extraction_id = :eid
              AND e.source_sha256 = :source AND {CURRENT} AND {VISIBLE}
              AND b.block_order BETWEEN greatest(:ord - 190, 0) AND :ord + 1
              AND (b.block_order >= :ord - 1 OR (
                  b.block_type = 'paragraph' AND char_length(b.text_raw) <= 128
              ))
            ORDER BY b.block_order
        """,
            {
                "doc": location.document_id,
                "eid": location.extraction_id,
                "source": location.source_version,
                "ord": location.block_order,
                "local": local,
            },
        )

    async def section_seeds(self, question, *, local: bool):
        return await self.rows(
            f"""
            SELECT d.document_id, e.extraction_id, e.source_sha256 AS source_version,
              e.file_id, coalesce(d.title_raw, '') AS title, b.block_order,
              word_similarity(:q, b.text_raw) AS score
            FROM aihub_document_block b
            JOIN aihub_document_extraction e USING (extraction_id)
            JOIN aihub_knowledge_document d USING (document_id)
            WHERE b.block_type = 'paragraph' AND char_length(b.text_raw) BETWEEN 6 AND 3000
              AND {CURRENT} AND {VISIBLE} AND EXISTS (
                SELECT 1 FROM aihub_rag_chunk c
                WHERE c.extraction_id = e.extraction_id AND {CHUNK_PROFILE}
              )
            ORDER BY score DESC, document_id, b.block_order LIMIT 80
        """,
            PROFILE | {"q": question, "local": local},
        )

    async def qa_seeds(self, question, *, local: bool):
        return await self.rows(
            f"""
            WITH ranked AS (
                SELECT seq, subject_id, similarity(:q, question_text) AS similarity,
                       word_similarity(:q, question_text) AS score,
                       lower(trim(:q)) = lower(trim(question_text)) AS exact
                FROM aihub_qa_case
                ORDER BY score DESC, seq LIMIT 160
            )
            SELECT r.seq, a.source_position, d.document_id, e.extraction_id,
              e.source_sha256 AS source_version, e.file_id, coalesce(d.title_raw, '') AS title,
              a.candidates, r.score
            FROM ranked r JOIN aihub_quote_alignment a USING (seq)
            JOIN aihub_document_extraction e USING (extraction_id)
            JOIN aihub_knowledge_document d ON d.document_id = e.document_id
            WHERE NOT EXISTS (
                SELECT 1 FROM ranked duplicate WHERE duplicate.subject_id = r.subject_id
                AND (duplicate.exact OR duplicate.similarity >= 0.7)
            ) AND a.verified AND a.status IN ('exact', 'normalized')
              AND a.document_id = d.document_id AND {CURRENT} AND {VISIBLE}
            ORDER BY r.score DESC, r.seq, a.source_position
        """,
            {"q": question, "local": local},
        )
