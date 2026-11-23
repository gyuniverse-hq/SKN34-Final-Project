"""Index explicitly requested documents or resume a corpus run."""

import argparse
import asyncio
import json
import logging

from app.core.db import dispose_engine
from app.services.rag_index_service import index_sources


async def run(args):
    try:
        result = await index_sources(args.document_ids, local=args.local, dry_run=args.dry_run)
        print(json.dumps(result.report(), ensure_ascii=False))
        return int(bool(result.failed_documents))
    finally:
        await dispose_engine()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--document-ids", nargs="+", type=int)
    group.add_argument("--all", action="store_true")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
