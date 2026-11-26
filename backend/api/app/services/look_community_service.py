from io import BytesIO
from uuid import UUID

import anyio
from fastapi import Depends
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.look_community_repository import LookCommunityRepository
from app.schemas.look_community import LookPost, LookPostContent, LookPostViewer, ReportedLookPost

MAX_LOOK_UPLOAD = 2 * 1024 * 1024


def prepare_public_photo(data: bytes) -> bytes:
    if len(data) > MAX_LOOK_UPLOAD:
        raise ApiError(413, "Choose a photo under 2 MB", "look_photo_too_large")
    try:
        with Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as photo:
            if photo.width * photo.height > 20_000_000 or getattr(photo, "n_frames", 1) != 1:
                raise ValueError("Invalid photo dimensions or frame count")
            result = ImageOps.exif_transpose(photo).convert("RGB")
            result.thumbnail((1280, 1280))
            result.info.clear()
            out = BytesIO()
            # Encode only pixel data. EXIF, GPS and other embedded metadata are discarded.
            result.save(out, "JPEG", quality=85, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise ApiError(
            400, "Choose a single JPEG, PNG, or WebP image", "look_photo_invalid"
        ) from None


class LookCommunityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.posts = LookCommunityRepository(session)

    async def feed(
        self, offset: int, popular: bool = False, owner: str | None = None
    ) -> list[LookPost]:
        return await self.posts.feed(offset, popular, owner)

    async def detail(self, post_id: UUID, owner: str | None = None) -> LookPost:
        post = await self.posts.detail(post_id, owner)
        if post is None:
            raise ApiError(404, "Look post unavailable", "look_post_missing")
        return post

    async def image(self, post_id: UUID, include_hidden: bool = False) -> bytes:
        image = await self.posts.image(post_id, include_hidden)
        if image is None:
            raise ApiError(404, "Look photo unavailable", "look_post_missing")
        return image

    async def viewer(self, post_id: UUID, member: str) -> LookPostViewer:
        viewer = await self.posts.viewer(post_id, member)
        if viewer is None:
            raise ApiError(404, "Look post unavailable", "look_post_missing")
        return viewer

    async def save(
        self,
        post_id: UUID,
        owner: str,
        content: LookPostContent,
        photo: bytes | None,
        *,
        create: bool,
    ) -> LookPost:
        image = (
            await anyio.to_thread.run_sync(prepare_public_photo, photo)
            if photo is not None
            else None
        )
        if create and image is None:
            raise ApiError(400, "Choose a photo to publish", "look_photo_required")
        if not await self.posts.is_member(owner):
            raise ApiError(403, "Complete your account setup first", "look_member_required")
        saved = await self.posts.save(post_id, owner, content, image, create=create)
        if not saved and (not create or not await self.posts.owned(post_id, owner)):
            raise ApiError(404, "Look post unavailable", "look_post_missing")
        post = await self.detail(post_id, owner)
        await self.session.commit()
        return post

    async def delete(self, post_id: UUID, owner: str) -> None:
        if not await self.posts.delete(post_id, owner):
            raise ApiError(404, "Look post unavailable", "look_post_missing")
        await self.session.commit()

    async def interact(self, post_id: UUID, owner: str, reason: str | None = None) -> LookPost:
        if not await self.posts.is_member(owner):
            raise ApiError(403, "Complete your account setup first", "look_member_required")
        if not await self.posts.interact(post_id, owner, reason):
            raise ApiError(
                409, "This action is unavailable for this post", "look_action_unavailable"
            )
        post = await self.detail(post_id)
        await self.session.commit()
        return post

    async def reported(self, offset: int) -> list[ReportedLookPost]:
        return await self.posts.reported(offset)

    async def moderate(self, post_id: UUID, hidden: bool) -> None:
        if not await self.posts.set_hidden(post_id, hidden):
            raise ApiError(404, "Look post unavailable", "look_post_missing")
        await self.session.commit()


def get_look_community_service(
    session: AsyncSession = Depends(get_session),
) -> LookCommunityService:
    return LookCommunityService(session)
