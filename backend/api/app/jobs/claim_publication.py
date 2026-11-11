"""Operator entry point for explicit publication and revocation."""

import argparse
import asyncio
from uuid import UUID

from pydantic import ValidationError

from app.core.db import dispose_engine, session_scope
from app.core.errors import ApiError
from app.schemas.claim_publication import ClaimIngredientKey, PublishClaim
from app.services.claim_publication_service import get_claim_publication_service


async def run(args: argparse.Namespace) -> None:
    try:
        async with session_scope() as session, session.begin():
            service = get_claim_publication_service(session)
            if args.command == "revoke":
                changed = await service.revoke(args.publication_id)
                result = "revoked" if changed else "no active publication"
            else:
                result = await service.publish(
                    PublishClaim(
                        claim_version_id=args.claim_version_id,
                        source_review_id=args.source_review_id,
                        release_id=args.release_id,
                        ingredient=ClaimIngredientKey(
                            mfds_ingredient_id=args.ingredient_id, source_hash=args.mfds_source_hash
                        ),
                        source_title=args.source_title,
                        source_url=args.source_url,
                        publisher=args.publisher,
                    )
                )
        print(result)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish", help="Publish exact wording of the reviewed revision")
    for field in ("claim-version-id", "source-review-id", "release-id", "ingredient-id"):
        publish.add_argument(f"--{field}", type=int, required=True)
    for field in ("mfds-source-hash", "source-title", "source-url", "publisher"):
        publish.add_argument(f"--{field}", required=True)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("publication_id", type=UUID)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except ApiError as exc:
        parser.exit(1, f"{exc.code}\n")
    except ValidationError:
        parser.exit(1, "invalid_publication_arguments\n")


if __name__ == "__main__":
    main()
