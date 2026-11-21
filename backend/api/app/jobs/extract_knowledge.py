"""Stream the local Java extractor. No DB connection unless --database-url is supplied."""

import argparse
import asyncio
import json
from collections import Counter
from contextlib import aclosing
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.knowledge_extraction_service import extract_documents, validate_database_url
from app.services.knowledge_ingest_service import ingest_extraction


async def run(archive: Path, jar: Path, database_url: str | None, *, apply: bool = False):
    if apply and not database_url:
        raise ValueError("--apply requires --database-url")
    engine = create_async_engine(validate_database_url(database_url)) if database_url else None
    sessions = async_sessionmaker(engine) if engine else None
    counts = Counter()
    try:
        async with aclosing(extract_documents(archive, jar)) as documents:
            async for result in documents:
                counts[f"{result.detected_format}.{result.status}"] += 1
                counts["blocks"] += len(result.blocks)
                if sessions:
                    async with sessions() as session:
                        outcome = await ingest_extraction(session, result, apply=apply)
                        counts[outcome] += 1
        print(json.dumps(dict(counts), sort_keys=True))
        return dict(counts)
    finally:
        if engine:
            await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--database-url", type=validate_database_url)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.archive, args.jar, args.database_url, apply=args.apply))


if __name__ == "__main__":
    main()
