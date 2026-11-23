"""Read verified document records from the local Java extractor."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.schemas.knowledge import DocumentExtraction


def validate_database_url(value: str) -> str:
    url = make_url(value)
    # asyncpg accepts a second host in the URL query string. Require explicit authority only.
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in ("localhost", "127.0.0.1", "::1")
        or url.query
    ):
        raise ValueError("Only explicit loopback PostgreSQL URLs are accepted")
    return value


async def extract_documents(archive: Path, jar: Path) -> AsyncIterator[DocumentExtraction]:
    if not await asyncio.to_thread(archive.is_file) or not await asyncio.to_thread(jar.is_file):
        raise ValueError("Archive and built extractor JAR must exist")
    process = await asyncio.create_subprocess_exec(
        "java",
        "-Xmx1g",
        "-jar",
        str(jar),
        str(archive),
        "--emit-records",
        stdout=asyncio.subprocess.PIPE,
        limit=256 * 1024 * 1024,
    )
    try:
        assert process.stdout is not None
        async for line in process.stdout:
            try:
                yield DocumentExtraction.model_validate_json(line)
            except ValidationError as exc:
                issues = [(e["loc"], e["type"]) for e in exc.errors(include_input=False)]
                raise ValueError(f"Invalid extractor record: {issues}") from None
        if await process.wait():
            raise RuntimeError("Extractor failed; results are incomplete")
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
