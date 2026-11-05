from app.clients.youtube_client import YoutubeClient, get_youtube_client
from app.core.errors import UpstreamError
from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.repositories.style_look_repository import StyleLookRepository


class CuratedVideoCheckService:
    def __init__(self, youtube: YoutubeClient, celebrities, styles):
        self.youtube = youtube
        self.celebrities = celebrities
        self.styles = styles

    async def check(self, start: int = 0) -> list[dict]:
        videos = [("celebrity", video.id) for video in await self.celebrities.list_videos()]
        videos += [("style", look.id) for look in await self.styles.list_looks()]
        results = []
        for index in range(start, len(videos), 50):
            batch = videos[index : index + 50]
            try:
                details = {
                    v.video_id: v
                    for v in await self.youtube.get_video_details([v[1] for v in batch])
                }
            except UpstreamError as exc:
                # Do not include request URLs or credentials in the output.
                quota_exhausted = "(403)" in str(exc)
                failed = videos[index:] if quota_exhausted else batch
                results.extend(
                    {"index": i, "source": src, "videoId": vid, "status": "lookup_failed"}
                    for i, (src, vid) in enumerate(failed, index)
                )
                if quota_exhausted:
                    return results
                continue
            for offset, (source, video_id) in enumerate(batch):
                detail = details.get(video_id)
                status = (
                    "unavailable"
                    if detail is None
                    else "not_public"
                    if detail.privacy_status != "public"
                    else "not_embeddable"
                    if not detail.embeddable
                    else "available"
                )
                results.append(
                    {
                        "index": index + offset,
                        "source": source,
                        "videoId": video_id,
                        "status": status,
                    }
                )
        return results


def get_curated_video_check_service() -> CuratedVideoCheckService:
    return CuratedVideoCheckService(
        get_youtube_client(), CelebrityVideoRepository(), StyleLookRepository()
    )
