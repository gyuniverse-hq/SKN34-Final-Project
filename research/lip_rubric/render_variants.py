"""Render quality variants (quality_variants.VARIANTS) with the app renderer and build a local comparison sheet.

  render_variants.py --work DIR --faces a,b --shades glossy_rose,matte_red --tag pilot [--variants L5_current,D3_gloss] [--sheet out.png]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from build_pack import crop_lips
from common import ROOT
from quality_variants import VARIANTS


def render(work, faces, shades, tag, names):
    configs = []
    for name in names:
        configs += ['--config', f'{name}={json.dumps(VARIANTS[name], separators=(",", ":"))}']
    subprocess.run([sys.executable, str(ROOT / 'research/lip_texture/render.py'), '--tag', tag, '--faces', ','.join(faces), '--shades', ','.join(shades),
                    '--data-dir', str(work), '--offline-strict', '--no-freeze', *configs], cwd=ROOT, check=True)


def sheet(work, faces, shades, tag, names, out, cell=220):
    rows = []
    for face in faces:
        page = json.loads((Path(work) / 'faces' / f'{face}.page.json').read_text(encoding='utf8'))
        for shade in shades:
            tiles = []
            for name in names:
                img = cv2.imread(str(Path(work) / 'renders' / tag / f'{face}__{shade}__{name}.png'))
                tile = cv2.resize(crop_lips(img, page), (cell, cell)) if img is not None else np.full((cell, cell, 3), 255, np.uint8)
                tiles.append(tile)
            rows.append(np.hstack(tiles))
    head = np.full((28, cell * len(names), 3), 255, np.uint8)
    for i, name in enumerate(names):
        cv2.putText(head, name, (i * cell + 4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), np.vstack([head, *rows]))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--work', type=Path, required=True); p.add_argument('--faces', required=True); p.add_argument('--shades', required=True)
    p.add_argument('--tag', required=True); p.add_argument('--variants', default=','.join(VARIANTS)); p.add_argument('--sheet', type=Path)
    p.add_argument('--sheet-only', action='store_true')
    a = p.parse_args()
    faces, shades, names = a.faces.split(','), a.shades.split(','), a.variants.split(',')
    a.work = a.work.resolve()
    if not a.sheet_only:
        render(a.work, faces, shades, a.tag, names)
    if a.sheet:
        print(sheet(a.work, faces, shades, a.tag, names, a.sheet))


if __name__ == '__main__':
    main()
