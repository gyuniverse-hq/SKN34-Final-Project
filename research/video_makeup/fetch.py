"""Download a public tutorial for local measurement (video only, no audio, at most 1080p).

Run: research/ar_evaluation/.venv/Scripts/python.exe research/video_makeup/fetch.py VIDEO_ID [VIDEO_ID ...]
Output: research/data/video_makeup/<id>/video.mp4 (git-ignored; AR_SPEC 6-12 research exception).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yt_dlp

from common import video_dir

# H.264 first: OpenCV's FFmpeg build reads it everywhere; AV1 often fails to decode.
FORMAT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080][ext=mp4]/b[height<=1080]"


def fetch(video_id: str) -> Path:
    out = video_dir(video_id) / "video.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    opts = {
        "format": FORMAT,
        "outtmpl": str(out),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="+")
    args = ap.parse_args()
    for video_id in args.video_ids:
        try:
            path = fetch(video_id)
            print(f"{video_id}: {path.stat().st_size / 1e6:.1f} MB")
        except yt_dlp.utils.DownloadError as exc:
            print(f"{video_id}: download failed ({exc})")


if __name__ == "__main__":
    main()
