"""Build separate blinded v2 packs from previously reviewed LaPa test faces.

The variants are experimental renderer settings, not predicted human scores.
Outputs and intermediate face images stay under the ignored research/data directory.
"""
import argparse
import json
import random
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

import cv2

from common import DATA, HERE, ROOT, read_csv, sha256, write_csv
from build_pack import SHADES, assign_splits, crop_lips, renderer_version, sticker_image, verify_input

SEED = 20261114
VARIANTS = {
    'current': {},
    'low_detail': {'creaseGain': 0.25, 'opaqueShadeGamma': 0.3, 'hlKeep': [0, 0.15], 'hlSparkle': 0},
    'strong_gloss': {'glossGain': 6, 'lipSheen': 0.8, 'glossCavity': 0, 'glossTone': [0.7, 0.6, 0]},
}


def select_new(rows, original_key, original_manifest):
    used = {row['face_id'] for row in original_key}
    used.update(row['face_id'] for row in original_manifest['practice_sources'])
    unique = {}
    for row in rows:
        if (row['face_id'] and row['face_id'] not in used and row['detected'] == '1'
                and row['human_label'] in ('bare', 'lipstick')
                and row['identity_reviewed'].lower() in ('yes', 'true', '1')):
            if row['face_id'] in unique and unique[row['face_id']]['human_label'] != row['human_label']:
                raise ValueError(f"동일 인물의 화장 여부가 충돌합니다: {row['face_id']}")
            unique.setdefault(row['face_id'], row)
    return list(unique.values())


def run(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def build(output, seed):
    output = output.resolve()
    if not output.is_relative_to(DATA.resolve()):
        raise ValueError('얼굴 이미지는 Git 제외 연구 데이터 폴더에만 저장합니다')
    if output.exists():
        raise FileExistsError(f'기존 묶음을 덮어쓰지 않습니다: {output}')
    original = DATA / 'pack'
    old_key = read_csv(original / 'key.csv')
    old_manifest = json.loads((original / 'manifest.json').read_text(encoding='utf8'))
    rows = select_new(read_csv(DATA / 'candidates_reviewed.csv'), old_key, old_manifest)
    bare = [r for r in rows if r['human_label'] == 'bare']
    real = [r for r in rows if r['human_label'] == 'lipstick']
    if not bare or not real:
        raise ValueError('이전 평가와 다른, 검토된 맨입술과 실제 립 이미지가 필요합니다')
    dataset = ROOT / 'research/data/LaPa/test'
    for row in rows:
        verify_input(row, dataset)
    rnd = random.Random(seed)
    splits = assign_splits(rows, seed)
    output.mkdir(parents=True)
    work = output / 'work'
    (work / 'src').mkdir(parents=True)
    for row in rows:
        shutil.copyfile(dataset / 'images' / (row['lapa_stem'] + '.jpg'), work / 'src' / (row['lapa_stem'] + '.jpg'))
    scripts = ROOT / 'research/lip_texture'
    run([sys.executable, scripts / 'prep.py', '--data-dir', work])
    run(['node', scripts / 'build_html.mjs', '--data-dir', work])
    for row in rows:
        run([sys.executable, scripts / 'dump_landmarks.py', row['lapa_stem'], '--data-dir', work, '--offline-strict'])
    run(['node', scripts / 'build_html.mjs', '--data-dir', work])
    version = renderer_version(work)
    configs = sum((['--config', name + '=' + json.dumps(config, separators=(',', ':'))] for name, config in VARIANTS.items()), [])
    for row in bare:
        run([sys.executable, scripts / 'render.py', '--tag', 'expansion', '--faces', row['lapa_stem'],
             '--data-dir', work, '--offline-strict', '--no-freeze', *configs])
    for row in real:
        run([sys.executable, scripts / 'render.py', '--tag', 'expansion', '--faces', row['lapa_stem'],
             '--data-dir', work, '--offline-strict', '--no-freeze', '--off-only'])

    candidates = []
    for row in rows:
        stem = row['lapa_stem']
        rendered = work / 'renders/expansion'
        off = cv2.imread(str(rendered / f'{stem}__off.png'))
        page = json.loads((work / 'faces' / f'{stem}.page.json').read_text(encoding='utf8'))
        if off is None or off.shape[:2] != (960, 720):
            raise ValueError(f'렌더 실패: {stem}')
        entries = [('real', '', '', off)] if row['human_label'] == 'lipstick' else [
            ('render', shade, variant, cv2.imread(str(rendered / f'{stem}__{shade}__{variant}.png')))
            for shade in SHADES for variant in VARIANTS]
        if row['human_label'] == 'bare':
            shade = list(SHADES)[len(candidates) % len(SHADES)]
            entries.append(('sticker', shade, 'flat_sticker', sticker_image(off, page, SHADES[shade]['hex'])))
        for kind, shade, variant, frame in entries:
            if frame is None or frame.shape != off.shape:
                raise ValueError(f'누락된 이미지: {stem}/{shade}/{variant}')
            candidates.append((row, kind, shade, variant, frame, crop_lips(frame, page)))

    # Spread face, texture and variants across independent, roughly 50-image sessions.
    rnd.shuffle(candidates)
    groups = [[] for _ in range((len(candidates) + 45) // 46)]
    for item in candidates:
        group = min(groups, key=lambda g: (sum(x[0]['face_id'] == item[0]['face_id'] for x in g), len(g)))
        group.append(item)
    practice_source = original / 'rating_pack'
    old_pack = json.loads((practice_source / 'pack.json').read_text(encoding='utf8'))
    for number, group in enumerate(groups, 1):
        pack = output / f'pack_{number:02d}'
        rating = pack / 'rating_pack'
        images = rating / 'images'
        images.mkdir(parents=True)
        (rating / 'practice').mkdir()
        hashes, sources, key, public = {}, {}, [], []
        for row, kind, shade, variant, frame, crop in group:
            ident = f'{rnd.getrandbits(128):032x}'
            for suffix, image in [('full', frame), ('crop', crop)]:
                file = images / f'{ident}_{suffix}.png'
                if not cv2.imwrite(str(file), image):
                    raise IOError(file)
                hashes[f'rating_pack/images/{file.name}'] = sha256(file)
            finish = SHADES[shade]['texture'] if shade else row.get('finish') or 'unknown'
            entry = {'random_id': ident, 'lapa_stem': row['lapa_stem'], 'face_id': row['face_id'], 'kind': kind,
                     'shade': shade, 'variant': variant, 'hex': SHADES[shade]['hex'] if shade else '', 'finish': finish,
                     'mouth': row['mouth'], 'ita': row['ita'], 'ita_bin': row['ita_bin'], 'monk': row['monk'],
                     'yaw': row['yaw_proxy'], 'split': splits[row['face_id']], 'repeat_of': '', 'source': 'LaPa',
                     'source_split': 'test', 'image_sha256': row['image_sha256'], 'label_sha256': row['label_sha256'],
                     'tuning_json': json.dumps(VARIANTS.get(variant, {}), sort_keys=True)}
            key.append(entry)
            public.append({'id': ident, 'finish': finish, 'mouth': row['mouth'], 'is_repeat': False})
            sources[row['lapa_stem']] = {'image_sha256': row['image_sha256'], 'label_sha256': row['label_sha256']}
        for source in rnd.sample(key, min(4, len(key))):
            ident = f'{rnd.getrandbits(128):032x}'
            repeated = dict(source, random_id=ident, repeat_of=source['random_id'])
            key.append(repeated)
            for suffix in ('full', 'crop'):
                file = images / f'{ident}_{suffix}.png'
                shutil.copyfile(images / f"{source['random_id']}_{suffix}.png", file)
                hashes[f'rating_pack/images/{file.name}'] = sha256(file)
            public.append({'id': ident, 'finish': source['finish'], 'mouth': source['mouth'], 'is_repeat': True})
        rnd.shuffle(public)
        practice = []
        for item in old_pack['practice']:
            ident = f'{rnd.getrandbits(128):032x}'
            for suffix in ('full', 'crop'):
                shutil.copyfile(practice_source / 'practice' / f"{item['id']}_{suffix}.png", rating / 'practice' / f'{ident}_{suffix}.png')
            practice.append(dict(item, id=ident))
        (rating / 'pack.json').write_text(json.dumps({'version': 2, 'items': public, 'practice': practice}, ensure_ascii=False, indent=2), encoding='utf8')
        guide = json.loads((practice_source / 'guide.json').read_text(encoding='utf8'))
        for example in guide.values():
            for side in ('pass', 'fail'):
                name = example.get(side, {}).get('image')
                if name:
                    source = (practice_source / name).resolve()
                    if source.parent != (practice_source / 'images').resolve():
                        raise ValueError('가이드 이미지 경로 오류')
                    shutil.copyfile(source, images / source.name)
        (rating / 'guide.json').write_text(json.dumps(guide, ensure_ascii=False, indent=2), encoding='utf8')
        if json.loads((HERE / 'rubric.json').read_text(encoding='utf8')) != json.loads((practice_source / 'rubric.json').read_text(encoding='utf8')):
            raise ValueError('기존 v2 채점표와 현재 채점표가 다릅니다')
        shutil.copyfile(practice_source / 'rubric.json', rating / 'rubric.json')
        page = (HERE / 'rating/index.html').read_text(encoding='utf8')
        original_download = "a.download=code+'_ratings.csv'"
        if page.count(original_download) != 1:
            raise ValueError('평가 CSV 파일명 코드를 확인하세요')
        page = page.replace(original_download, "a.download=code+'_'+packHash.slice(0,8)+'_ratings.csv'")
        (rating / 'index.html').write_text(page, encoding='utf8')
        write_csv(pack / 'key.csv', key)
        manifest = {'seed': seed, 'source': 'LaPa test; non-commercial research', 'sources': sources,
                    'image_files_sha256': hashes, 'pack_sha256': sha256(rating / 'pack.json'),
                    'rubric_sha256': sha256(rating / 'rubric.json'), 'renderer': version,
                    'variants': VARIANTS, 'note': 'Variants are not human score labels. Practice images are reused from v2.'}
        (pack / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
        with zipfile.ZipFile(output / f'rating_pack_{number:02d}.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in rating.rglob('*'):
                if file.is_file():
                    archive.write(file, Path('rating_pack') / file.relative_to(rating))
        print(f'{pack.name}: {len(group)} originals + {len(key)-len(group)} repeats', flush=True)
    print('New faces:', len(bare), 'bare,', len(real), 'real. Originals:', len(candidates), flush=True)
    print('Composition:', dict(Counter(item[1] for item in candidates)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DATA / 'expansion_20261114')
    parser.add_argument('--seed', type=int, default=SEED)
    args = parser.parse_args()
    build(args.output, args.seed)
