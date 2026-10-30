from fastapi import APIRouter, Depends, Response

from app.core.http import cache_for
from app.schemas.celebrity_video import CelebrityVideosResponse
from app.services.celebrity_video_service import CelebrityVideoService, get_celebrity_video_service

router = APIRouter(prefix="/api/celebrity-videos", tags=["celebrity-videos"])


@router.get("", response_model=CelebrityVideosResponse)
async def list_celebrity_videos(
    response: Response, service: CelebrityVideoService = Depends(get_celebrity_video_service)
) -> CelebrityVideosResponse:
    videos = await service.list_videos()
    cache_for(response, 300)
    return CelebrityVideosResponse(videos=videos)
