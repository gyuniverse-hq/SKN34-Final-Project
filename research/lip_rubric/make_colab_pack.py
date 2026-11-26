"""Package only reviewed LaPa-derived data after verifying provenance and hashes."""
import argparse
import csv
import io
import json
import zipfile
from pathlib import Path

from common import DATA, HERE, ROOT, load_json, read_csv, sha256


def make_pack(pack, ratings_path, dataset, output):
    pack, dataset, output = map(Path, (pack, dataset, output))
    manifest = load_json(pack / 'manifest.json')
    if load_json(pack / 'rating_pack/rubric.json').get('version')!='lip-rubric-v2':
        raise ValueError('v2 rubric required')
    keys = read_csv(pack / 'key.csv')
    ratings = read_csv(ratings_path)
    originals = {r['random_id']: r for r in keys if not r['repeat_of']}
    if len(originals) != sum(not r['repeat_of'] for r in keys):
        raise ValueError('duplicate image ID')
    if not ratings or len({r['image_id'] for r in ratings}) != len(ratings):
        raise ValueError('ratings missing or duplicated')
    if any(r['image_id'] not in originals for r in ratings):
        raise ValueError('rating does not match an original image')
    if {r['image_id'] for r in ratings} != set(originals):
        raise ValueError('모든 원본 이미지에 최소 한 명의 v2 본 채점이 필요합니다')
    for r in ratings:
        key = originals[r['image_id']]
        if any(r.get(k) != key.get(k) for k in ('face_id', 'split', 'kind', 'finish', 'mouth')):
            raise ValueError('ratings와 key의 이미지 정보가 다릅니다')
    if sha256(pack / 'rating_pack/pack.json') != manifest['pack_sha256']:
        raise ValueError('pack.json hash mismatch')
    splits = {}
    for row in keys:
        stem = row['lapa_stem']
        if row.get('source') != 'LaPa' or row.get('source_split') != 'test' or Path(stem).name != stem:
            raise ValueError('LaPa test 이외의 출처가 발견되었습니다')
        for folder, ext, field in [('images', '.jpg', 'image_sha256'), ('labels', '.png', 'label_sha256')]:
            source = dataset / folder / (stem + ext)
            if not source.is_file() or sha256(source) != row[field] or manifest['sources'].get(stem, {}).get(field) != row[field]:
                raise ValueError('LaPa 원본 해시 불일치: ' + stem)
        if row['face_id'] in splits and splits[row['face_id']] != row['split']:
            raise ValueError('같은 얼굴이 pool과 test에 존재합니다')
        splits[row['face_id']] = row['split']
        for suffix in ('full', 'crop'):
            name = f"rating_pack/images/{row['random_id']}_{suffix}.png"
            if sha256(pack / name) != manifest['image_files_sha256'].get(name):
                raise ValueError('채점 이미지 해시 불일치: ' + name)
    if sha256(pack / 'rating_pack/rubric.json') != manifest['rubric_sha256']:
        raise ValueError('rubric hash mismatch')
    selected = [originals[r['image_id']] for r in ratings]
    fields = ['image_id', 'face_id', 'split', 'kind', 'finish', 'mouth']
    text = io.StringIO(newline=''); writer = csv.DictWriter(text, fieldnames=fields); writer.writeheader()
    for row in selected:
        writer.writerow({**{k: row[k] for k in fields if k != 'image_id'}, 'image_id': row['random_id']})
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists(): raise FileExistsError(output)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('meta.csv', text.getvalue())
        z.write(ratings_path, 'ratings.csv')
        z.write(pack / 'rating_pack/rubric.json', 'rubric.json')
        for name in ('judges.json', 'judge.py', 'common.py'):
            z.write(HERE / name, name)
        for row in selected:
            for suffix in ('full', 'crop'):
                name = f"{row['random_id']}_{suffix}.png"
                z.write(pack / 'rating_pack/images' / name, 'images/' + name)
    print(f'{output}: SHA-256 {sha256(output)}')


def export_db(con, output):
    from aggregate import aggregate_db
    bad=con.execute("SELECT COUNT(*) FROM images WHERE source!='LaPa' OR source_split!='test'").fetchone()[0]
    if bad: raise ValueError('LaPa test 이외의 출처가 발견되었습니다')
    packs=con.execute("SELECT pack_path FROM packs WHERE rubric_version='lip-rubric-v2'").fetchall()
    if len(packs)!=1: raise ValueError('정확히 하나의 v2 채점 묶음이 필요합니다')
    aggregate_db(con,DATA/'results')
    make_pack(Path(packs[0]['pack_path']),DATA/'results/ratings.csv',ROOT/'research/data/LaPa/test',output)


def main():
    import db
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, default=db.DB)
    p.add_argument('--output', type=Path, default=DATA / 'colab_pack.zip')
    a = p.parse_args()
    with db.connect(a.db) as con: export_db(con,a.output)


if __name__ == '__main__': main()
