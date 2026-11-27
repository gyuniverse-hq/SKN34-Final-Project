from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.curated_video_rows import mention_payloads, published_looks
from app.schemas.celebrity_video import CelebrityVideo

# Same order as the app profiles (constants/celebrities.ts). Unknown ids follow by id.
CELEBRITY_ORDER = ("karina", "wonyoung", "sullyoon", "winter", "jennie", "haerin", "wony")


def _order(look) -> tuple[int, str, int]:
    celebrity_id = look["celebrity_id"]
    if celebrity_id in CELEBRITY_ORDER:
        return CELEBRITY_ORDER.index(celebrity_id), "", look["catalog_position"]
    return len(CELEBRITY_ORDER), celebrity_id, look["catalog_position"]


class CelebrityVideoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_videos(self) -> list[CelebrityVideo]:
        looks = await published_looks(self._session, "celebrity")
        products = await mention_payloads(self._session, "celebrity")
        looks = sorted(looks, key=_order)
        return [
            CelebrityVideo.model_validate(
                {
                    "id": look["video_id"],
                    "celebrityId": look["celebrity_id"],
                    "number": look["catalog_position"],
                    "startSeconds": look["catalog_start_seconds"] or 0,
                    "linkStatus": look["catalog_link_status"],
                    "title": look["catalog_title"],
                    "channelName": look["channel_name"] or "",
                    "products": products.get(look["video_id"], []),
                }
            )
            for look in looks
        ]
