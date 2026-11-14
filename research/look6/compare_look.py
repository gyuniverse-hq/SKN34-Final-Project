"""Side-by-side sheet: bare | current AR (store state) | look-mode AR (render-only finish) | the video's finished frame."""
from __future__ import annotations

import argparse
import json

import cv2
from mediapipe.tasks.python import BaseOptions, vision

from blend_modes import DATA, ROOT, crop, landmarks, sheet, tile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', default='e1gSkUdG6Bo')
    args = parser.parse_args()
    directory = DATA / args.video
    frames = json.loads((directory / 'frames.json').read_text(encoding='utf-8'))
    final_name = frames['selected'].get('final')
    read = lambda p: cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)  # noqa: E731
    bare, before, after = read(directory / 'baseline/off.png'), read(directory / 'baseline/all.png'), read(directory / 'look_mode/all.png')
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / 'research/data/models/face_landmarker.task')), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as det:
        pts = landmarks(det, bare)
        tiles = [tile(crop(bare, pts), 'bare'), tile(crop(before, pts), 'current AR'), tile(crop(after, pts), 'look mode AR')]
        if final_name:
            final = read(DATA / 'manual' / final_name)
            tiles.append(tile(crop(final, landmarks(det, final)), 'video final'))
    out = directory / 'look_mode' / 'compare.jpg'
    sheet(tiles, out)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
