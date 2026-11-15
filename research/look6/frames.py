"""Record available manual captures and conservative per-zone eligibility.

Run score.py first. Filename numbers are labels, never actual video times.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data' / 'look6'
VIDEOS = ('ZAozXs-ZZik', '4QR0tre9yBI', 'kWI7_DkDjZ0', 'n5otfjJSSQc', 'e1gSkUdG6Bo', 'fDqBPI1SaWY')
ZONES = ('lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'brow', 'contour', 'highlighter', 'foundation')


def main():
    scored = json.loads((DATA / 'manual' / 'scores.json').read_text(encoding='utf-8'))['frames']
    for video in VIDEOS:
        rows = [row for row in scored if row['video'] == video]
        frames = {kind: [dict(file=row['file'], problems=row['problems'], metrics=row['metrics'])
                         for row in rows if row['kind'] == kind]
                  for kind in ('bare', 'final', 'left', 'right', 'open')}
        bare = next((r for r in frames['bare'] if all(p == 'mouth open' for p in r['problems'])), None)
        final = next((r for r in frames['final'] if not r['problems']), None)
        valid_angle = any(not r['problems'] for kind in ('left', 'right') for r in frames[kind])
        zones = {}
        for zone in ZONES:
            reasons = []
            if not bare or not final:
                reasons.append('usable bare and final are required')
            if zone == 'lip' and bare and 'mouth open' in bare['problems']:
                reasons.append('bare mouth is open; lip registration is unreliable')
            zones[zone] = {'exploratory': not reasons, 'validation': valid_angle and not reasons,
                           'reasons': reasons + ([] if valid_angle else ['no qualifying left/right angle'])}
        result = {'videoId': video, 'filenameNumbersAreTimestamps': False, 'frames': frames,
                  'selected': {'bare': bare['file'] if bare else None, 'final': final['file'] if final else None},
                  'zones': zones, 'note': 'Automated checks do not establish makeup status or local occlusions; manual review is required.'}
        out = DATA / video
        out.mkdir(parents=True, exist_ok=True)
        (out / 'frames.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(video, 'selected', result['selected'], 'validation angle', valid_angle)


if __name__ == '__main__':
    main()
