"""Bounded OpenAI embedding batches with response integrity checks."""

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import perf_counter

import httpx

from app.core.errors import UpstreamError
from app.schemas.rag import DIMENSIONS, EMBEDDING_MODEL

logger = logging.getLogger(__name__)
_RETRYABLE_STATUSES = (408, 429, 500, 502, 503, 504)
_QUOTA_ERRORS = (
    "insufficient_quota",
    "billing_hard_limit_reached",
    "credit_balance_exhausted",
    "organization_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
    "project_spend_limit_exceeded",
)


class EmbeddingRequestError(UpstreamError):
    def __init__(self, message: str, attempts: int, *, abort_reason: str | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.abort_reason = abort_reason


def _abort_reason(response: httpx.Response) -> str | None:
    if response.status_code in (401, 403):
        return "authentication"
    if response.status_code == 429:
        try:
            body = response.json()
        except ValueError:
            return None
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and any(
            error.get(field) in _QUOTA_ERRORS for field in ("code", "type")
        ):
            return "quota"
    return None


def _retry_after(value: str, fallback: float) -> float:
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError):
        return fallback
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


@dataclass(frozen=True)
class EmbeddedBatch:
    vectors: list[list[float]]
    input_tokens: int
    attempts: int
    elapsed_ms: int


class OpenAIEmbeddings:
    def __init__(self, client: httpx.AsyncClient, *, retry_wait_limit: float | None = 12):
        self.client = client
        self.retry_wait_limit = retry_wait_limit

    async def embed(self, payloads: list[str]) -> EmbeddedBatch:
        start = perf_counter()
        for attempt in range(1, 4):
            try:
                response = await self.client.post(
                    "embeddings",
                    json={"model": EMBEDDING_MODEL, "dimensions": DIMENSIONS, "input": payloads},
                )
                response.raise_for_status()
                data = response.json()
                rows = sorted(data["data"], key=lambda row: row["index"])
                vectors = [row["embedding"] for row in rows]
                if (
                    data["model"] != EMBEDDING_MODEL
                    or [row["index"] for row in rows] != list(range(len(payloads)))
                    or any(
                        len(vector) != DIMENSIONS
                        or not all(math.isfinite(v) and abs(v) <= 65504 for v in vector)
                        or not any(vector)
                        for vector in vectors
                    )
                ):
                    raise ValueError("Invalid embedding result")
                tokens = int(data["usage"]["prompt_tokens"])
                elapsed = round((perf_counter() - start) * 1000)
                logger.info(
                    "g5_embedding_batch model=%s count=%s tokens=%s attempts=%s ms=%s",
                    EMBEDDING_MODEL,
                    len(payloads),
                    tokens,
                    attempt,
                    elapsed,
                )
                return EmbeddedBatch(vectors, tokens, attempt, elapsed)
            except httpx.HTTPStatusError as exc:
                reason = _abort_reason(exc.response)
                if reason or exc.response.status_code not in _RETRYABLE_STATUSES:
                    raise EmbeddingRequestError(
                        "Embedding service rejected request", attempt, abort_reason=reason
                    ) from exc
                if attempt == 3:
                    raise EmbeddingRequestError(
                        "Embedding service retries exhausted", attempt
                    ) from exc
                delay = _retry_after(
                    exc.response.headers.get("Retry-After", ""), 2 ** (attempt - 1)
                )
                if not math.isfinite(delay) or (
                    self.retry_wait_limit is not None and delay > self.retry_wait_limit
                ):
                    raise EmbeddingRequestError(
                        "Embedding retry delay exceeds the wait limit", attempt
                    ) from exc
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise EmbeddingRequestError("Embedding service unreachable", attempt) from exc
                delay = 2 ** (attempt - 1)
            except (ValueError, TypeError, KeyError) as exc:
                raise EmbeddingRequestError("Invalid embedding service response", attempt) from exc
            await asyncio.sleep(delay)
        raise AssertionError("Unreachable embedding retry state")
