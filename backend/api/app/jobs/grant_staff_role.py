"""Operator only. Never exposed as an API."""

import argparse
import asyncio

from app.core.db import dispose_engine
from app.services.admin_auth_service import grant_role


async def run(args):
    try:
        await grant_role(args.user_id, None if args.revoke else args.role)
    finally:
        await dispose_engine()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--role", choices=("admin", "viewer"))
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    if bool(args.role) == args.revoke:
        parser.error("choose --role or --revoke")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
