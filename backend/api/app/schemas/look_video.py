"""Rows planned by the look video jobs before they reach the database."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedVideo:
    """A youtube_videos row and its unpublished makeup_looks row (register_look_videos)."""

    id: str
    look_id: str
    video_id: str
    youtube_url: str
    start_seconds: int
    title: str
    channel_name: str
    thumbnail_url: str
    description: str | None
    analysis_status: str
    is_new: bool
