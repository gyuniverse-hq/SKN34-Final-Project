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
    keys = read_csv(pack / 'key.csv')
    ratings = read_csv(ratings_path)
    originals = {r['random_id']: r for r in keys if not r['repeat_of']}
    if len(originals) != sum(not r['repeat_of'] for r in keys):
        raise ValueError('duplicate image ID')
    if not ratings or len({r['image_id'] for r in ratings}) != len(ratings):
        raise ValueError('ratings missing or duplicated')
    if any(r['image_id'] not in originals for r in ratings):
        raise ValueError('rating does not match an original image')
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack', type=Path, default=DATA / 'pack')
    p.add_argument('--ratings', type=Path, default=DATA / 'results/ratings.csv')
    p.add_argument('--dataset', type=Path, default=ROOT / 'research/data/LaPa/test')
    p.add_argument('--output', type=Path, default=DATA / 'colab_pack.zip')
    a = p.parse_args()
    if a.dataset.resolve() != (ROOT / 'research/data/LaPa/test').resolve():
        raise ValueError('로컬 LaPa test 경로만 허용합니다')
    make_pack(a.pack, a.ratings, a.dataset, a.output)


if __name__ == '__main__': main()
