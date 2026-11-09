"""Print a review checklist from the review file: one link per shading / highlighter step, at its start time.

    python -X utf8 research/recipe_eval/review_links.py [--review backend/api/seed/source/look_recipe_review.json]
                                                        [--zones contour highlighter]

A reviewer opens each link, sees which style is applied (contour: jawline | nose | hairline; highlighter:
natural_cheek | glass_c_zone | nose_tip | under_eye_smile | cupid_bow | forehead_center), types it into that
step's "style" in the review file, then sets "approved": true, "reviewer": "<name>" and "lookId".
Nothing is sent anywhere; the links only open public videos.
"""

import argparse
import json
from pathlib import Path

DEFAULT = Path("backend/api/seed/source/look_recipe_review.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, default=DEFAULT)
    parser.add_argument("--zones", nargs="+", default=["contour", "highlighter"])
    args = parser.parse_args()
    entries = json.loads(args.review.read_text(encoding="utf-8"))
    rows = 0
    for entry in entries:
        for step in entry["recipe"]["steps"]:
            if step["zone"] not in args.zones:
                continue
            start = step.get("start_seconds") or 0
            done = "[x]" if entry.get("approved") else "[ ]"
            style = step.get("style") or "?"
            print(f"{done} {entry['video_id']}  {step['zone']:<11} style={style:<16} https://youtu.be/{entry['video_id']}?t={start}")
            rows += 1
    print(f"\n{rows} steps in {len(entries)} videos")


if __name__ == "__main__":
    main()
