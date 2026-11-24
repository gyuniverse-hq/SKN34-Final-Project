from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from app.core.errors import ApiError
from app.core.internal_deletion_auth import DELETION_PATH, authenticate_deletion_request
from app.schemas.account_deletion import InternalAccountDeletion
from app.services.owner_deletion_service import OwnerDeletionService

router = APIRouter(include_in_schema=False)


@router.post(DELETION_PATH, status_code=204)
async def delete_account_data(request: Request) -> Response:
    body = await authenticate_deletion_request(request)
    try:
        deletion = InternalAccountDeletion.model_validate_json(body)
    except ValidationError:
        raise ApiError(400, "Invalid internal deletion request", "invalid_request") from None
    await OwnerDeletionService().delete(deletion.owner_id)
    return Response(status_code=204)
