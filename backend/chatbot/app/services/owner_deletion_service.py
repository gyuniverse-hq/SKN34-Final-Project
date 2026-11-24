"""Block a trusted owner and remove G7 data without exposing a deletion route."""

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import get_chat_sessionmaker
from app.core.errors import ApiError
from app.repositories.chat_session_repository import get_chat_sessions
from app.repositories.checkpoint_repository import CheckpointRepository
from app.repositories.owner_deletion_repository import OwnerDeletionRepository, legacy_owner_access
from app.services.conversation_service import require_persistence


class OwnerDeletionService:
    @staticmethod
    def access(owner_id: str | None):
        return legacy_owner_access(owner_id)

    async def delete(self, owner_id: str) -> None:
        """The future internal caller must authenticate and authorize the owner first."""
        if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 64:
            raise ValueError("Invalid owner ID")
        settings = get_settings()
        resume_only = not settings.g7_persistence_enabled
        if not resume_only or not settings.g7_owner_deletion_guard_enabled:
            require_persistence()
        elif settings.env not in {"local", "test"} or not settings.chat_database_url:
            raise ApiError(503, "Persistent chat is unavailable", "persistence_unavailable")
        try:
            sessions = get_chat_sessionmaker()
            async with sessions.begin() as session:
                repo = OwnerDeletionRepository(session)
                should_delete = (
                    await repo.resume(owner_id) if resume_only else await repo.block(owner_id)
                )
                threads = await repo.threads(owner_id) if should_delete else []

            try:
                await get_chat_sessions().delete_owner(owner_id)
            except ApiError as exc:
                raise ApiError(
                    503, "Account deletion is incomplete", "account_deletion_incomplete"
                ) from exc
            if not should_delete:
                return

            checkpoints = CheckpointRepository(settings.chat_database_url)
            for thread_id in threads:
                try:
                    await checkpoints.delete_thread(thread_id)
                except Exception as exc:
                    raise ApiError(
                        503, "Account deletion is incomplete", "account_deletion_incomplete"
                    ) from exc

            async with sessions.begin() as session:
                await OwnerDeletionRepository(session).purge(owner_id)
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(
                503, "Account deletion is incomplete", "account_deletion_incomplete"
            ) from exc
