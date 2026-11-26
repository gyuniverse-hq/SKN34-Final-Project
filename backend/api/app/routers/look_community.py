from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from pydantic import ValidationError

from app.core.auth import AuthUser, require_user
from app.core.errors import ApiError
from app.schemas.look_community import (
    LookPost,
    LookPostContent,
    LookPostModeration,
    LookPostReport,
    LookPostViewer,
    ReportedLookPost,
)
from app.services.admin_auth_service import admin_user
from app.services.look_community_service import (
    MAX_LOOK_UPLOAD,
    LookCommunityService,
    get_look_community_service,
)

router = APIRouter(tags=["look-community"])
PUBLIC = "/api/look-community"
ADMIN = "/api/admin/look-community"


@router.get(PUBLIC)
async def feed(
    response: Response,
    offset: int = Query(0, ge=0, le=10000),
    popular: bool = False,
    service: LookCommunityService = Depends(get_look_community_service),
) -> list[LookPost]:
    response.headers["Cache-Control"] = "no-store"
    return await service.feed(offset, popular)


@router.get(PUBLIC + "/mine")
async def mine(
    response: Response,
    offset: int = Query(0, ge=0, le=10000),
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> list[LookPost]:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.feed(offset, owner=user.id)


@router.get(PUBLIC + "/{post_id}")
async def detail(
    post_id: UUID,
    response: Response,
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPost:
    response.headers["Cache-Control"] = "no-store"
    return await service.detail(post_id)


@router.get(PUBLIC + "/{post_id}/photo")
async def photo(
    post_id: UUID, service: LookCommunityService = Depends(get_look_community_service)
) -> Response:
    return Response(
        await service.image(post_id),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(PUBLIC + "/{post_id}/viewer")
async def viewer(
    post_id: UUID,
    response: Response,
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPostViewer:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.viewer(post_id, user.id)


async def _save(
    post_id: UUID,
    content: str,
    consent: bool,
    image: UploadFile | None,
    user: AuthUser,
    service: LookCommunityService,
    *,
    create: bool,
) -> LookPost:
    if (create or image is not None) and not consent:
        raise ApiError(400, "Confirm that the photo will be public", "look_consent_required")
    try:
        body = LookPostContent.model_validate_json(content)
    except ValidationError:
        raise ApiError(400, "Invalid post content", "invalid_request") from None
    data = await image.read(MAX_LOOK_UPLOAD + 1) if image is not None else None
    return await service.save(post_id, user.id, body, data, create=create)


@router.post(PUBLIC + "/{post_id}", status_code=201)
async def create(
    post_id: UUID,
    content: str = Form(max_length=6000),
    consent: bool = Form(False),
    image: UploadFile | None = File(None),
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPost:
    return await _save(post_id, content, consent, image, user, service, create=True)


@router.patch(PUBLIC + "/{post_id}")
async def edit(
    post_id: UUID,
    content: str = Form(max_length=6000),
    consent: bool = Form(False),
    image: UploadFile | None = File(None),
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPost:
    return await _save(post_id, content, consent, image, user, service, create=False)


@router.delete(PUBLIC + "/{post_id}", status_code=204)
async def remove(
    post_id: UUID,
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> Response:
    await service.delete(post_id, user.id)
    return Response(status_code=204)


@router.post(PUBLIC + "/{post_id}/recommend")
async def recommend(
    post_id: UUID,
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPost:
    return await service.interact(post_id, user.id)


@router.post(PUBLIC + "/{post_id}/report")
async def report(
    post_id: UUID,
    body: LookPostReport,
    user: AuthUser = Depends(require_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPost:
    return await service.interact(post_id, user.id, body.reason)


@router.get(ADMIN)
async def reported(
    response: Response,
    offset: int = Query(0, ge=0, le=10000),
    _user=Depends(admin_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> list[ReportedLookPost]:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.reported(offset)


@router.get(ADMIN + "/{post_id}/photo")
async def moderation_photo(
    post_id: UUID,
    _user=Depends(admin_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> Response:
    return Response(
        await service.image(post_id, include_hidden=True),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch(ADMIN + "/{post_id}")
async def moderate(
    post_id: UUID,
    body: LookPostModeration,
    _user=Depends(admin_user),
    service: LookCommunityService = Depends(get_look_community_service),
) -> LookPostModeration:
    await service.moderate(post_id, body.hidden)
    return body
