"""Load the naturalness Likert criteria shipped with the API image."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.clients.vision_llm_client import NATURALNESS_VERSION, SCORE_KEYS
from app.core.errors import ApiError

_DATA = Path(__file__).resolve().parents[1] / "data" / "criteria_naturalness_techlang.json"


@lru_cache(maxsize=1)
def load_naturalness_criteria() -> dict:
    try:
        payload = json.loads(_DATA.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApiError(500, "naturalness criteria file missing", "criteria_missing") from exc
    except json.JSONDecodeError as exc:
        raise ApiError(500, "naturalness criteria file invalid", "criteria_invalid") from exc

    version = payload.get("version")
    items = payload.get("items")
    if version != NATURALNESS_VERSION:
        raise ApiError(
            500,
            f"criteria version {version!r} != {NATURALNESS_VERSION!r}",
            "criteria_version_mismatch",
        )
    if not isinstance(items, list):
        raise ApiError(500, "naturalness criteria items missing", "criteria_invalid")
    ids = tuple(item.get("id") for item in items)
    if ids != SCORE_KEYS:
        raise ApiError(500, "criteria item ids do not match SCORE_KEYS", "criteria_invalid")
    for item in items:
        likert = item.get("likert")
        if not isinstance(likert, dict) or set(likert) != {"1", "2", "3", "4", "5"}:
            raise ApiError(500, f"bad likert for {item.get('id')}", "criteria_invalid")
    return payload


def get_naturalness_criteria() -> dict:
    payload = load_naturalness_criteria()
    return {
        "version": payload["version"],
        "title": payload["title"],
        "scale": {
            "min": payload["scale"]["min"],
            "max": payload["scale"]["max"],
            "note": payload["scale"].get("note", ""),
        },
        "items": [
            {
                "id": item["id"],
                "label": item["label"],
                "text": item["text"],
                "likert": {str(k): str(v) for k, v in item["likert"].items()},
            }
            for item in payload["items"]
        ],
    }
