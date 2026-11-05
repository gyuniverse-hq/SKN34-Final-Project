from fastapi import Response


def cache_for(response: Response, seconds: int) -> None:
    """Same caching policy as the Expo API routes' `json(..., { maxAgeSeconds })`."""
    response.headers["Cache-Control"] = f"public, max-age={seconds}, s-maxage={seconds}"
