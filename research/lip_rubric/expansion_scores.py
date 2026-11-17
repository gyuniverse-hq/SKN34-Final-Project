"""Summarize scored expansion packs by human-rated score, keeping identities private."""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from common import DATA, HERE, load_json, score, write_csv


def summarize(images, ratings, rubric, minimum_raters=5):
    if minimum_raters < 1:
        raise ValueError('최소 평가자 수는 1 이상이어야 합니다')
    grouped = defaultdict(list)
    for rating in ratings:
        grouped[rating['image_id']].append(rating)
    output, bins = [], Counter()
    for image in images:
        if image['repeat_of']:
            continue
        rated = grouped[image['image_id']]
        totals = [score(rubric, json.loads(r['checks_json']), image['finish'])['total'] for r in rated]
        totals = [value for value in totals if value is not None]
        complete = len(totals) >= minimum_raters
        mean = sum(totals) / len(totals) if complete else None
        band = min(4, int(mean)) if mean is not None else None
        if band is not None:
            bins[(image['kind'], band)] += 1
        output.append({'image_id': image['image_id'], 'face_id': image['face_id'], 'split': image['split'],
                       'kind': image['kind'], 'finish': image['finish'], 'rater_count': len(totals),
                       'total_mean': round(mean, 4) if mean is not None else '',
                       'band': f'{band}-{band + 1}' if band is not None else '',
                       'pack_id': image['pack_id'], 'tuning_json': image['tuning_json']})
    return output, dict(Counter({f'{kind} {band}-{band+1}': count for (kind, band), count in bins.items()}))


def run(database, expansion, output, minimum_raters):
    output = output.resolve()
    if not output.is_relative_to(DATA.resolve()):
        raise ValueError('평가 결과는 Git 제외 연구 데이터 폴더에만 저장합니다')
    if output.exists():
        raise FileExistsError(f'기존 결과를 덮어쓰지 않습니다: {output}')
    if not database.is_file():
        raise FileNotFoundError(database)
    packs = sorted(expansion.glob('pack_*/manifest.json'))
    if not packs:
        raise ValueError('추가 묶음이 없습니다')
    pack_ids = [load_json(path)['pack_sha256'] for path in packs]
    with closing(sqlite3.connect(database)) as con:
        con.row_factory = sqlite3.Row
        known = {row[0] for row in con.execute('select pack_id from packs')}
        if set(pack_ids) - known:
            raise ValueError('먼저 추가 묶음을 모두 DB에 등록하세요')
        placeholders = ','.join('?' for _ in pack_ids)
        images = [dict(row) for row in con.execute(f'select * from images where pack_id in ({placeholders})', pack_ids)]
        ratings = [dict(row) for row in con.execute(
            f"select h.* from human_ratings h join images i using(image_id) where i.pack_id in ({placeholders}) and h.rater_id != 'R0' and h.rubric_version = 'lip-rubric-v2'", pack_ids)]
    rows, bands = summarize(images, ratings, load_json(HERE / 'rubric.json'), minimum_raters)
    output.mkdir(parents=True)
    write_csv(output / 'scores.csv', rows)
    summary = {'minimum_raters': minimum_raters, 'original_images': len(rows),
               'scored_images': sum(row['total_mean'] != '' for row in rows),
               'unscored_images': sum(row['total_mean'] == '' for row in rows),
               'bands_by_kind': bands, 'band_definition': '[0,1), [1,2), [2,3), [3,4), [4,5]',
               'note': '평균 총점은 사람 채점 결과이며 같은 얼굴의 여러 사진은 독립 인물이 아님'}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, default=DATA / 'eval.db')
    p.add_argument('--expansion', type=Path, default=DATA / 'expansion_20261114')
    p.add_argument('--output', type=Path, default=DATA / 'expansion_20261114/score_summary')
    p.add_argument('--min-raters', type=int, default=5)
    a = p.parse_args()
    run(a.db, a.expansion, a.output, a.min_raters)
