"""A/B naturalness test: does the VLM pick the image that the five raters scored higher?

Pairs come from the v2 human scores (no new rating). Each pair is asked twice with the order swapped.
Decision rule, fixed before any VLM result: on clear render-vs-render pairs (|mean difference| >= MDC95),
'대체 가능' if pair accuracy >= the median single-rater agreement and its 95% CI lower bound > 0.5,
'보조만' if only the CI lower bound > 0.5, otherwise '쓰지 않음'.

  pairwise.py build  [--mdc 1.42]        -> results/pairs.csv, results/pairs_truth.csv
  pairwise.py export                      -> pairwise_pack.zip (images + pairs.csv, no human scores)
  pairwise.py run --pack DIR --output CSV [--mock]   (Colab GPU or mock)
  pairwise.py analyze --results CSV       -> results/pairwise_summary.json
"""
import argparse
import csv
import hashlib
import json
import os
import random
import statistics
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from common import DATA, HERE, load_json, read_csv, score, sha256, write_csv
from judge import QwenJudge, extract_json

PROMPT_VERSION = 'pairwise-v1'
FINISH = {'glossy': '글로시', 'satin': '새틴', 'matte': '매트', 'unknown': '알 수 없음'}
FIELDS = ['run_id', 'pair_id', 'order', 'a_id', 'b_id', 'status', 'choice', 'chosen_id', 'confidence', 'reason',
          'elapsed_seconds', 'attempts', 'error', 'model_id', 'model_revision', 'prompt_version', 'datetime_utc', 'gpu', 'quantization']


def human_scores(con, rubric):
    images = {r['image_id']: dict(r) for r in con.execute("SELECT * FROM images WHERE repeat_of IS NULL")}
    per = defaultdict(dict)
    for r in con.execute("SELECT rater_id,image_id,checks_json FROM human_ratings WHERE rubric_version=? AND rater_id!='R0'", (rubric['version'],)):
        if r['image_id'] in images:
            per[r['image_id']][r['rater_id']] = score(rubric, json.loads(r['checks_json']), images[r['image_id']]['finish'])['total']
    return images, per


def build_pairs(images, per, mdc, seed=42, cross_limit=40, max_uses=3):
    rng = random.Random(seed)
    mean = {i: statistics.mean(v.values()) for i, v in per.items()}
    renders = sorted(i for i, m in images.items() if m['kind'] == 'render' and i in mean)
    by_face = defaultdict(list)
    for i in renders:
        by_face[images[i]['face_id']].append(i)
    pairs = []

    def add(kind, a, b):
        left, right = (a, b) if rng.random() < .5 else (b, a)
        pairs.append({'kind': kind, 'left': left, 'right': right})

    for face in sorted(by_face):
        if len(by_face[face]) == 2:
            add('same_face', *by_face[face])
    for s in sorted(i for i, m in images.items() if m['kind'] == 'sticker' and i in mean):
        mates = by_face.get(images[s]['face_id'], [])
        mate = next((i for i in mates if images[i]['shade'] == images[s]['shade']), mates[0] if mates else None)
        if mate:
            add('sticker_vs_render', s, mate)
    reals = sorted(i for i, m in images.items() if m['kind'] == 'real' and i in mean)
    for real, other in zip(reals, rng.sample(renders, len(reals))):
        add('real_vs_render', real, other)
    candidates = [(a, b) for n, a in enumerate(renders) for b in renders[n + 1:]
                  if images[a]['face_id'] != images[b]['face_id'] and abs(mean[a] - mean[b]) >= mdc]
    rng.shuffle(candidates)
    used = defaultdict(int)
    for a, b in candidates:
        if sum(p['kind'] == 'cross_face' for p in pairs) >= cross_limit:
            break
        if used[a] < max_uses and used[b] < max_uses:
            add('cross_face', a, b); used[a] += 1; used[b] += 1
    raters = sorted({r for v in per.values() for r in v})
    for n, p in enumerate(pairs):
        p['pair_id'] = f'p{n + 1:03d}'
        diff = mean[p['right']] - mean[p['left']]
        p['human_diff_right_minus_left'] = round(diff, 4)
        p['human_pref'] = 'right' if diff > 0 else 'left' if diff < 0 else 'tie'
        p['clear'] = int(abs(diff) >= mdc)
        p['rater_votes'] = json.dumps({r: ('right' if per[p['right']][r] > per[p['left']][r] else 'left' if per[p['right']][r] < per[p['left']][r] else 'tie') for r in raters})
        p['left_face'] = images[p['left']]['face_id']; p['right_face'] = images[p['right']]['face_id']
        p['left_finish'] = images[p['left']]['finish']; p['right_finish'] = images[p['right']]['finish']
        p['left_mouth'] = images[p['left']]['mouth']; p['right_mouth'] = images[p['right']]['mouth']
    return pairs


def public_rows(pairs):
    keys = ['pair_id', 'left', 'right', 'left_finish', 'right_finish', 'left_mouth', 'right_mouth']
    return [{k: p[k] for k in keys} for p in pairs]


def prompt(a, b):
    return '\n'.join([
        '두 사진 A와 B는 입술에 립 메이크업을 합성한 결과입니다. 각 사진마다 전체 화면과 입술 확대가 있습니다.',
        '어느 쪽이 실제로 립을 바른 사진처럼 더 자연스러운지 하나를 고르세요. 비슷해 보여도 반드시 하나를 고릅니다.',
        '판단 기준: 입술 주름과 결이 살아 있는지, 윗입술 그늘과 아랫입술 볼륨 같은 명암, 제형에 맞는 반짝임과 위치, 테두리와 입꼬리가 자연스러운지, 색이 필름처럼 떠 보이지 않는지.',
        '제품 색이 정확한지는 판단하지 마세요.',
        f"A 제형: {FINISH.get(a['finish'], a['finish'])}, 입 상태: {a['mouth']}",
        f"B 제형: {FINISH.get(b['finish'], b['finish'])}, 입 상태: {b['mouth']}",
        '반드시 JSON 객체만 출력: {"choice":"A","confidence":3,"reason":"한 줄"}. choice는 "A" 또는 "B", confidence는 1~5 정수.'])


def parse_choice(text):
    obj = extract_json(text)
    if not isinstance(obj, dict) or set(obj) != {'choice', 'confidence', 'reason'}:
        raise ValueError('invalid JSON object fields')
    if obj['choice'] not in ('A', 'B'):
        raise ValueError('choice must be A or B')
    if type(obj['confidence']) is not int or obj['confidence'] not in range(1, 6):
        raise ValueError('confidence must be integer 1–5')
    if not isinstance(obj['reason'], str) or not obj['reason'].strip() or '\n' in obj['reason']:
        raise ValueError('reason must be one nonempty line')
    return obj


class MockPairJudge:
    def __init__(self, pick=lambda text, images: 'A'):
        self.pick = pick; self.calls = 0

    def generate(self, text, images):
        self.calls += 1
        return json.dumps({'choice': self.pick(text, images), 'confidence': 3, 'reason': '모의 실행'}, ensure_ascii=False)


class QwenPairJudge(QwenJudge):
    def generate(self, text, images):
        from qwen_vl_utils import process_vision_info
        labels = ['A 전체 화면:', 'A 입술 확대:', 'B 전체 화면:', 'B 입술 확대:']
        content = []
        for label, image in zip(labels, images):
            content.extend([{'type': 'text', 'text': label}, {'type': 'image', 'image': Path(image).resolve().as_uri()}])
        content.append({'type': 'text', 'text': text})
        messages = [{'role': 'user', 'content': content}]
        rendered = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(text=[rendered], images=image_inputs, videos=video_inputs, padding=True, return_tensors='pt').to('cuda')
        with self.torch.inference_mode():
            generated = self.model.generate(**inputs, **{**self.config['generation'], 'max_new_tokens': 200})
        trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generated)]
        return self.processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]


def run(root, output, config, adapter, mock=False, retries=2):
    root = Path(root); output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    pairs = read_csv(root / 'pairs.csv')
    if not pairs:
        raise ValueError('no pairs')
    run_id = hashlib.sha256(json.dumps({'config': config, 'pairs_sha256': sha256(root / 'pairs.csv'), 'prompt': PROMPT_VERSION, 'mock': mock}, sort_keys=True).encode()).hexdigest()
    existing = read_csv(output) if output.exists() else []
    if existing and any(r['run_id'] != run_id for r in existing):
        raise ValueError('output contains a different experiment; use a new path')
    done = {(r['pair_id'], int(r['order'])) for r in existing if r['status'] == 'ok'}
    gpu = 'mock'
    if not mock:
        import torch
        gpu = torch.cuda.get_device_name(0)
    with output.open('a', encoding='utf8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not existing:
            writer.writeheader(); f.flush(); os.fsync(f.fileno())
        for p in pairs:
            sides = {'left': {'id': p['left'], 'finish': p['left_finish'], 'mouth': p['left_mouth']},
                     'right': {'id': p['right'], 'finish': p['right_finish'], 'mouth': p['right_mouth']}}
            for order, (a, b) in enumerate((('left', 'right'), ('right', 'left'))):
                if (p['pair_id'], order) in done:
                    continue
                A, B = sides[a], sides[b]
                images = [root / 'images' / f"{A['id']}_full.png", root / 'images' / f"{A['id']}_crop.png",
                          root / 'images' / f"{B['id']}_full.png", root / 'images' / f"{B['id']}_crop.png"]
                begin = time.perf_counter(); result = None; error = ''; excerpt = ''; attempts = 0
                for attempts in range(1, retries + 2):
                    answer = ''
                    try:
                        answer = adapter.generate(prompt(A, B) + (f'\n이전 응답 오류: {error}. JSON만 다시 출력하세요.' if error else ''), images)
                        result = parse_choice(answer); break
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        error = str(exc); excerpt = ' '.join(str(answer).split())[:200]
                row = {'run_id': run_id, 'pair_id': p['pair_id'], 'order': order, 'a_id': A['id'], 'b_id': B['id'],
                       'status': 'ok' if result else 'failed', 'choice': result['choice'] if result else '',
                       'chosen_id': (A['id'] if result['choice'] == 'A' else B['id']) if result else '',
                       'confidence': result['confidence'] if result else '', 'reason': result['reason'] if result else '',
                       'elapsed_seconds': round(time.perf_counter() - begin, 3), 'attempts': attempts,
                       'error': '' if result else f'{error} | 응답 앞부분: {excerpt}',
                       'model_id': 'mock' if mock else config['vlm']['model_id'], 'model_revision': 'mock' if mock else config['vlm']['revision'],
                       'prompt_version': PROMPT_VERSION, 'datetime_utc': datetime.now(timezone.utc).isoformat(), 'gpu': gpu,
                       'quantization': config['vlm']['quantization']}
                writer.writerow(row); f.flush(); os.fsync(f.fileno()); done.add((p['pair_id'], order))
    return run_id


def bootstrap_mean(values, seed=42, n=2000):
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return {'estimate': statistics.mean(values) if values else None, 'ci95': None, 'n': len(values)}
    rng = np.random.default_rng(seed); arr = np.array(values, float)
    samples = [float(rng.choice(arr, len(arr)).mean()) for _ in range(n)]
    return {'estimate': float(arr.mean()), 'ci95': [float(x) for x in np.percentile(samples, [2.5, 97.5])], 'n': len(values)}


def decide(acc, ceiling):
    if acc['estimate'] is None or acc['ci95'] is None:
        return '판정 불가'
    if acc['ci95'][0] > .5 and ceiling is not None and acc['estimate'] >= ceiling:
        return '대체 가능'
    if acc['ci95'][0] > .5:
        return '보조만'
    return '쓰지 않음'


def analyze(truth_rows, result_rows):
    truth = {p['pair_id']: p for p in truth_rows}
    by_pair = defaultdict(dict)
    for r in result_rows:
        if r['status'] == 'ok' and r['pair_id'] in truth:
            by_pair[r['pair_id']][int(r['order'])] = r
    records = []
    for pid, p in truth.items():
        got = by_pair.get(pid, {})
        if p['human_pref'] == 'tie' or len(got) < 2:
            continue
        preferred = p[p['human_pref']]
        correct = [int(got[o]['chosen_id'] == preferred) for o in (0, 1)]
        records.append({'pair_id': pid, 'kind': p['kind'], 'clear': int(p['clear']), 'score': statistics.mean(correct),
                        'consistent': int(got[0]['chosen_id'] == got[1]['chosen_id']), 'chose_a': [int(got[o]['choice'] == 'A') for o in (0, 1)],
                        'votes': json.loads(p['rater_votes']), 'pref': p['human_pref']})

    def group(rows):
        return {'pairs': len(rows), 'accuracy': bootstrap_mean([r['score'] for r in rows]),
                'order_consistency': statistics.mean(r['consistent'] for r in rows) if rows else None,
                'chose_first_rate': statistics.mean(x for r in rows for x in r['chose_a']) if rows else None}

    def ceiling(rows):
        raters = sorted({k for r in rows for k in r['votes']})
        out = {}
        for who in raters:
            agree = []
            for r in rows:
                own = r['votes'][who]
                others = [v for k, v in r['votes'].items() if k != who and v != 'tie']
                if not others:
                    continue
                majority = 'right' if others.count('right') > others.count('left') else 'left' if others.count('left') > others.count('right') else 'tie'
                if majority == 'tie':
                    continue
                agree.append(.5 if own == 'tie' else float(own == majority))
            if agree:
                out[who] = statistics.mean(agree)
        return {'per_rater': out, 'median': statistics.median(out.values()) if out else None}

    rr_clear = [r for r in records if r['clear'] and r['kind'] in ('cross_face', 'same_face')]
    summary = {'prompt_version': PROMPT_VERSION, 'pairs_scored': len(records),
               'all': group(records), 'clear': group([r for r in records if r['clear']]),
               'clear_render_vs_render': group(rr_clear),
               'by_kind': {k: group([r for r in records if r['kind'] == k]) for k in sorted({r['kind'] for r in records})},
               'human_ceiling_clear_render_vs_render': ceiling(rr_clear)}
    summary['decision'] = decide(summary['clear_render_vs_render']['accuracy'], summary['human_ceiling_clear_render_vs_render']['median'])
    return summary


def export(con, output):
    bad = con.execute("SELECT COUNT(*) FROM images WHERE source!='LaPa' OR source_split!='test'").fetchone()[0]
    if bad:
        raise ValueError('LaPa test 이외의 출처가 발견되었습니다')
    pairs = read_csv(DATA / 'results/pairs.csv')
    ids = sorted({p['left'] for p in pairs} | {p['right'] for p in pairs})
    rows = {r['image_id']: dict(r) for r in con.execute(f"SELECT image_id,full_path,crop_path,file_sha256 FROM images WHERE image_id IN ({','.join('?' * len(ids))})", ids)}
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        z.write(DATA / 'results/pairs.csv', 'pairs.csv')
        for name in ('judges.json', 'judge.py', 'common.py', 'pairwise.py'):
            z.write(HERE / name, name)
        for i in ids:
            if sha256(rows[i]['full_path']) != rows[i]['file_sha256']:
                raise ValueError('이미지 해시 불일치: ' + i)
            z.write(rows[i]['full_path'], f'images/{i}_full.png'); z.write(rows[i]['crop_path'], f'images/{i}_crop.png')
    print(f'{output}: SHA-256 {sha256(output)} ({len(pairs)} pairs, {len(ids)} images)')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('--mdc', type=float, default=1.42, help='MDC95 per image (research/reports/lip_rubric_eval.md)')
    sub.add_parser('export').add_argument('--output', type=Path, default=DATA / 'pairwise_pack.zip')
    r = sub.add_parser('run'); r.add_argument('--pack', required=True, type=Path); r.add_argument('--output', required=True, type=Path); r.add_argument('--mock', action='store_true')
    a = sub.add_parser('analyze'); a.add_argument('--results', type=Path, default=DATA / 'results/pairwise_results.csv')
    args = p.parse_args()
    if args.command in ('build', 'export'):
        import db
        con = db.connect(db.DB)
        if args.command == 'build':
            images, per = human_scores(con, load_json(HERE / 'rubric.json'))
            pairs = build_pairs(images, per, args.mdc)
            write_csv(DATA / 'results/pairs_truth.csv', pairs); write_csv(DATA / 'results/pairs.csv', public_rows(pairs))
            counts = defaultdict(int)
            for x in pairs:
                counts[(x['kind'], x['clear'])] += 1
            print(json.dumps({f'{k}{" clear" if c else ""}': v for (k, c), v in sorted(counts.items())}, ensure_ascii=False))
        else:
            export(con, args.output)
    elif args.command == 'run':
        config = load_json(args.pack / 'judges.json')
        if not args.mock and not config['vlm'].get('revision'):
            raise ValueError('judges.json에 VLM 리비전이 필요합니다')
        adapter = MockPairJudge() if args.mock else QwenPairJudge(config['vlm'])
        print(run(args.pack, args.output, config, adapter, args.mock))
    else:
        summary = analyze(read_csv(DATA / 'results/pairs_truth.csv'), read_csv(args.results))
        out = DATA / 'results/pairwise_summary.json'
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
        print(out, summary['decision'])


if __name__ == '__main__':
    main()
