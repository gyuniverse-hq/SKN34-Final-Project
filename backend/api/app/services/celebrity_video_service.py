from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.schemas.celebrity_video import CelebrityVideo


class CelebrityVideoService:
    def __init__(self, repository: CelebrityVideoRepository) -> None:
        self._repository = repository

    async def list_videos(self) -> list[CelebrityVideo]:
        return await self._repository.list_videos()


def get_celebrity_video_service() -> CelebrityVideoService:
    return CelebrityVideoService(CelebrityVideoRepository())
