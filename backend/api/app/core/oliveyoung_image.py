import re

# Collected thumbs used thumbnails10/ (no slash). The CDN now serves thumbnails/10/.
_GLUED_THUMB = re.compile(
    r"^(https://image\.oliveyoung\.co\.kr/cfimages/cf-goods/uploads/images/)thumbnails(\d+)/"
)


def public_oliveyoung_image_url(url: str) -> str:
    """URL the app can load. Empty stays empty."""
    if not url:
        return url
    return _GLUED_THUMB.sub(r"\1thumbnails/\2/", url, count=1)
