from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.admin_repository import AdminRepository


def require_staff(roles=("admin", "viewer")):
    """Service dependency: core/auth stays independent of repositories."""

    async def dependency(
        user: AuthUser = Depends(require_user), session: AsyncSession = Depends(get_session)
    ):
        if not get_settings().admin_enabled:
            raise ApiError(503, "Admin service is not enabled", "admin_unavailable")
        row = await AdminRepository(session).role(user.id)
        if row is None or row.role not in roles:
            raise ApiError(403, "Staff permission required", "forbidden")
        return {"userId": user.id, "email": user.email, "role": row.role}

    return dependency


staff_user = require_staff()
admin_user = require_staff(("admin",))


async def grant_role(user_id, role):
    from app.core.db import session_scope

    async with session_scope() as session:
        repo = AdminRepository(session)
        async with repo.transaction():
            await repo.catalog_lock()
            if not await repo.member_exists(user_id):
                raise ApiError(404, "Member must accept terms first", "not_found")
            previous = await repo.role(user_id)
            before = {"role": previous.role} if previous else None
            await repo.set_role(user_id, role)
            repo.audit(None, "staff_role", "staff", user_id, before, {"role": role}, "operator-job")
