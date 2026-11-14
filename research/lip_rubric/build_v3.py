"""Expansion v3: wide-quality blinded packs for one rater (checklist packs + one same-face A/B pack).

Per new bare face (one shade): the current render plus 4 image-space defects (degrade.py), all from the same
rendered frame. A/B uses all 10 pairs inside each face; the checklist packs use 3 of the 5 images per face plus
sticker and real-lipstick anchors. About 10% repeats in every pack. Design levels are never shown or used as labels.

  build_v3.py [--candidates candidates_reviewed_v3.csv] [--faces 50] [--output expansion_v3]
"""
import argparse
import itertools
import json
import math
import random
import shutil
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from build_pack import SHADES, assign_splits, crop_lips, renderer_version, sticker_image, verify_input
from common import DATA, HERE, ROOT, read_csv, sha256, write_csv
from degrade import DEFECTS, LEVELS, apply

SEED = 20261115
PACK_SIZE = 55
OTHER_DEFECTS = [d for d in DEFECTS if d != 'sticker_blend']


def pick_faces(rows, n_bare, n_real, seed):
    rng = random.Random(seed)
    ok = [r for r in rows if r.get('identity_method') == 'one_image_per_source_prefix_v3' and r['detected'] == '1'
          and r.get('identity_reviewed', '').lower() == 'yes']
    by_face = {}
    for r in ok:
        by_face.setdefault(r['face_id'], r)
    bare = [r for r in by_face.values() if r['human_label'] == 'bare']
    real = [r for r in by_face.values() if r['human_label'] == 'lipstick']
    rng.shuffle(bare); rng.shuffle(real)
    bare.sort(key=lambda r: r['ita_bin'])
    groups = defaultdict(list)
    for r in bare:
        groups[r['ita_bin']].append(r)
    chosen = []
    while len(chosen) < n_bare and any(groups.values()):
        for k in sorted(groups):
            if groups[k] and len(chosen) < n_bare:
                chosen.append(groups[k].pop())
    return chosen, real[:n_real]


def plan(bare, seed):
    rng = random.Random(seed); shades = list(SHADES); levels = list(LEVELS)
    other = itertools.cycle(OTHER_DEFECTS); lev = itertools.cycle(levels)
    out = []
    for n, row in enumerate(bare):
        shade = shades[n % len(shades)]
        defects = [('sticker_blend', levels[n % len(levels)])]
        while len(defects) < 4:
            d = next(other)
            if d not in {x[0] for x in defects}:
                defects.append((d, next(lev)))
        rng.shuffle(defects)
        out.append({'row': row, 'shade': shade, 'variants': [('current', '')] + defects})
    return out


def run(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def prepare(rows, work):
    (work / 'src').mkdir(parents=True, exist_ok=True)
    dataset = ROOT / 'research/data/LaPa/test'
    for r in rows:
        verify_input(r, dataset)
        shutil.copyfile(dataset / 'images' / f"{r['lapa_stem']}.jpg", work / 'src' / f"{r['lapa_stem']}.jpg")
    scripts = ROOT / 'research/lip_texture'
    run([sys.executable, scripts / 'prep.py', '--data-dir', work])
    run(['node', scripts / 'build_html.mjs', '--data-dir', work])
    for r in rows:
        run([sys.executable, scripts / 'dump_landmarks.py', r['lapa_stem'], '--data-dir', work, '--offline-strict'])
    run(['node', scripts / 'build_html.mjs', '--data-dir', work])


def render_all(items, real, work):
    scripts = ROOT / 'research/lip_texture'
    by_shade = defaultdict(list)
    for it in items:
        by_shade[it['shade']].append(it['row']['lapa_stem'])
    for shade, stems in by_shade.items():
        run([sys.executable, scripts / 'render.py', '--tag', 'v3', '--faces', ','.join(stems), '--shades', shade, '--config', 'current=',
             '--data-dir', work, '--offline-strict', '--no-freeze'])
    if real:
        run([sys.executable, scripts / 'render.py', '--tag', 'v3', '--faces', ','.join(r['lapa_stem'] for r in real), '--data-dir', work,
             '--offline-strict', '--no-freeze', '--off-only'])


def entry(row, ident, kind, shade, variant, level, split):
    finish = SHADES[shade]['texture'] if shade else row.get('finish') or 'unknown'
    return {'random_id': ident, 'lapa_stem': row['lapa_stem'], 'face_id': row['face_id'], 'kind': kind, 'shade': shade,
            'variant': variant, 'level': level, 'hex': SHADES[shade]['hex'] if shade else '', 'finish': finish,
            'mouth': row['mouth'], 'ita': row['ita'], 'ita_bin': row['ita_bin'], 'monk': row['monk'], 'yaw': row['yaw_proxy'],
            'split': split, 'repeat_of': '', 'source': 'LaPa', 'source_split': 'test', 'image_sha256': row['image_sha256'],
            'label_sha256': row['label_sha256'], 'tuning_json': json.dumps({'defect': variant, 'level': level} if level else {}, sort_keys=True)}


def make_images(items, real, work, splits, rng, n_stickers):
    rendered = work / 'renders/v3'; images = {}
    for n, it in enumerate(items):
        row, shade = it['row'], it['shade']; stem = row['lapa_stem']
        page = json.loads((work / 'faces' / f'{stem}.page.json').read_text(encoding='utf8'))
        base = cv2.imread(str(rendered / f'{stem}__{shade}__current.png')); off = cv2.imread(str(rendered / f'{stem}__off.png'))
        if base is None or off is None or base.shape[:2] != (960, 720):
            raise ValueError(f'렌더 실패: {stem}')
        for variant, level in it['variants']:
            frame = base if variant == 'current' else apply(base, off, page, SHADES[shade]['hex'], variant, LEVELS[level], seed=n * 31 + len(variant))
            ident = f'{rng.getrandbits(128):032x}'
            images[ident] = (entry(row, ident, 'render', shade, variant, level, splits[row['face_id']]), frame, crop_lips(frame, page))
            it.setdefault('ids', []).append(ident)
        if n < n_stickers:
            ident = f'{rng.getrandbits(128):032x}'; frame = sticker_image(off, page, SHADES[shade]['hex'])
            images[ident] = (entry(row, ident, 'sticker', shade, 'flat_sticker', '', splits[row['face_id']]), frame, crop_lips(frame, page))
            it['sticker'] = ident
    for row in real:
        stem = row['lapa_stem']; page = json.loads((work / 'faces' / f'{stem}.page.json').read_text(encoding='utf8'))
        off = cv2.imread(str(rendered / f'{stem}__off.png'))
        if off is None:
            raise ValueError(f'렌더 실패: {stem}')
        ident = f'{rng.getrandbits(128):032x}'
        images[ident] = (entry(row, ident, 'real', '', 'real', '', splits[row['face_id']]), off, crop_lips(off, page))
    return images


def write_images(folder, ids, images):
    folder.mkdir(parents=True, exist_ok=True); hashes = {}
    for i in ids:
        _, frame, crop = images[i]
        for suffix, im in (('full', frame), ('crop', crop)):
            f = folder / f'{i}_{suffix}.png'
            if not f.exists() and not cv2.imwrite(str(f), im):
                raise IOError(f)
            hashes[f.name] = sha256(f)
    return hashes


def checklist_packs(output, items, real, images, rng, version, seed):
    chosen = []
    for it in items:
        ids = it['ids']; chosen += [ids[0]] + rng.sample(ids[1:], 2)
        if 'sticker' in it: chosen.append(it['sticker'])
    chosen += [i for i, v in images.items() if v[0]['kind'] == 'real']
    rng.shuffle(chosen)
    groups = [[] for _ in range(math.ceil(len(chosen) / PACK_SIZE))]
    for i in chosen:
        face = images[i][0]['face_id']
        min(groups, key=lambda g: (sum(images[x][0]['face_id'] == face for x in g), len(g))).append(i)
    v2 = DATA / 'pack/rating_pack'; old = json.loads((v2 / 'pack.json').read_text(encoding='utf8'))
    rubric_text = (HERE / 'rubric.json').read_text(encoding='utf8')
    if json.loads(rubric_text) != json.loads((v2 / 'rubric.json').read_text(encoding='utf8')):
        raise ValueError('기존 v2 채점표와 현재 채점표가 다릅니다')
    for n, group in enumerate(groups, 1):
        pack = output / f'checklist_{n:02d}'; rating = pack / 'rating_pack'
        key = [dict(images[i][0]) for i in group]
        hashes = {f'rating_pack/images/{k}': v for k, v in write_images(rating / 'images', group, images).items()}
        for src in rng.sample(key, max(1, round(len(key) * 0.1))):
            ident = f'{rng.getrandbits(128):032x}'; rep = dict(src, random_id=ident, repeat_of=src['random_id']); key.append(rep)
            for suffix in ('full', 'crop'):
                f = rating / 'images' / f'{ident}_{suffix}.png'; shutil.copyfile(rating / 'images' / f"{src['random_id']}_{suffix}.png", f)
                hashes[f'rating_pack/images/{f.name}'] = sha256(f)
        public = [{'id': k['random_id'], 'finish': k['finish'], 'mouth': k['mouth'], 'is_repeat': bool(k['repeat_of'])} for k in key]
        rng.shuffle(public)
        (rating / 'practice').mkdir(exist_ok=True); practice = []
        for item in old['practice']:
            ident = f'{rng.getrandbits(128):032x}'
            for suffix in ('full', 'crop'):
                shutil.copyfile(v2 / 'practice' / f"{item['id']}_{suffix}.png", rating / 'practice' / f'{ident}_{suffix}.png')
            practice.append(dict(item, id=ident))
        (rating / 'pack.json').write_text(json.dumps({'version': 2, 'items': public, 'practice': practice}, ensure_ascii=False, indent=2), encoding='utf8')
        guide = json.loads((v2 / 'guide.json').read_text(encoding='utf8'))
        for example in guide.values():
            for side in ('pass', 'fail'):
                name = example.get(side, {}).get('image')
                if name:
                    shutil.copyfile(v2 / name, rating / name)
        (rating / 'guide.json').write_text(json.dumps(guide, ensure_ascii=False, indent=2), encoding='utf8')
        shutil.copyfile(v2 / 'rubric.json', rating / 'rubric.json')
        page = (HERE / 'rating/index.html').read_text(encoding='utf8')
        page = page.replace("a.download=code+'_ratings.csv'", "a.download=code+'_'+packHash.slice(0,8)+'_ratings.csv'")
        (rating / 'index.html').write_text(page, encoding='utf8')
        write_csv(pack / 'key.csv', key)
        sources = {k['lapa_stem']: {'image_sha256': k['image_sha256'], 'label_sha256': k['label_sha256']} for k in key}
        manifest = {'seed': seed, 'source': 'LaPa test; non-commercial research', 'sources': sources, 'image_files_sha256': hashes,
                    'pack_sha256': sha256(rating / 'pack.json'), 'rubric_sha256': sha256(rating / 'rubric.json'), 'renderer': version,
                    'design': 'expansion v3: current render + image-space defects (degrade.py); levels are not labels'}
        (pack / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
        print(f'{pack.name}: {len(group)} + {len(key) - len(group)} repeats')


def ab_pack(output, items, images, rng):
    folder = output / 'ab_pack'; pairs = []
    for it in items:
        for a, b in itertools.combinations(it['ids'], 2):
            left, right = (a, b) if rng.random() < .5 else (b, a)
            pairs.append({'left': left, 'right': right})
    rng.shuffle(pairs)
    for p in rng.sample(pairs, max(1, round(len(pairs) * 0.1))):
        pairs.append({'left': p['right'], 'right': p['left'], 'repeat_of': p})
    rng.shuffle(pairs)
    key, public = [], []
    for n, p in enumerate(pairs, 1):
        pid = f'ab{n:04d}'; p['pair_id'] = pid
    for p in pairs:
        L, R = images[p['left']][0], images[p['right']][0]
        key.append({'pair_id': p['pair_id'], 'left': p['left'], 'right': p['right'], 'face_id': L['face_id'], 'split': L['split'],
                    'left_variant': L['variant'], 'left_level': L['level'], 'right_variant': R['variant'], 'right_level': R['level'],
                    'repeat_of': p['repeat_of']['pair_id'] if 'repeat_of' in p else ''})
        public.append({'pair_id': p['pair_id'], 'left': p['left'], 'right': p['right'], 'finish': L['finish'], 'mouth': L['mouth']})
    ids = sorted({p['left'] for p in pairs} | {p['right'] for p in pairs})
    hashes = write_images(folder / 'images', ids, images)
    pack_id = sha256_text(json.dumps(public, sort_keys=True))
    html = (HERE / 'rating/ab.html').read_text(encoding='utf8').replace('__PAIRS__', json.dumps(public)).replace('__PACK__', pack_id)
    (folder / 'index.html').write_text(html, encoding='utf8')
    write_csv(output / 'ab_key.csv', key)
    (output / 'ab_manifest.json').write_text(json.dumps({'pack_id': pack_id, 'pairs': len(pairs), 'images': len(ids), 'image_files_sha256': hashes}, indent=2), encoding='utf8')
    print(f'ab_pack: {len(pairs)} pairs ({sum(1 for k in key if k["repeat_of"])} repeats), {len(ids)} images')


def sha256_text(text):
    import hashlib
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def zip_folder(folder, zpath, arc):
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob('*'):
            if f.is_file():
                z.write(f, Path(arc) / f.relative_to(folder))


def build(candidates, output, n_faces, n_real, n_stickers, seed):
    output = output.resolve()
    if not output.is_relative_to(DATA.resolve()):
        raise ValueError('얼굴 이미지는 Git 제외 연구 데이터 폴더에만 저장합니다')
    if output.exists():
        raise FileExistsError(f'기존 묶음을 덮어쓰지 않습니다: {output}')
    bare, real = pick_faces(read_csv(candidates), n_faces, n_real, seed)
    if len(bare) < 10:
        raise ValueError(f'새 맨입술 얼굴이 부족합니다({len(bare)}명). face_review.py로 표시 후 merge 하세요')
    rng = random.Random(seed)
    splits = assign_splits(bare + real, seed)
    items = plan(bare, seed)
    work = output / 'work'
    prepare(bare + real, work)
    version = renderer_version(work)
    render_all(items, real, work)
    images = make_images(items, real, work, splits, rng, n_stickers)
    checklist_packs(output, items, real, images, rng, version, seed)
    ab_pack(output, items, images, rng)
    for pack in sorted(output.glob('checklist_*')):
        zip_folder(pack / 'rating_pack', output / f'{pack.name}.zip', 'rating_pack')
    zip_folder(output / 'ab_pack', output / 'ab_pack.zip', 'ab_pack')
    design = Counter((v[0]['variant'], v[0]['level']) for v in images.values())
    print('faces', len(bare), 'bare,', len(real), 'real; images', len(images)); print('design', dict(design))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--candidates', type=Path, default=DATA / 'candidates_reviewed_v3.csv')
    p.add_argument('--output', type=Path, default=DATA / 'expansion_v3')
    p.add_argument('--faces', type=int, default=50); p.add_argument('--real', type=int, default=6); p.add_argument('--stickers', type=int, default=6)
    p.add_argument('--seed', type=int, default=SEED)
    a = p.parse_args()
    build(a.candidates, a.output, a.faces, a.real, a.stickers, a.seed)


if __name__ == '__main__':
    main()
