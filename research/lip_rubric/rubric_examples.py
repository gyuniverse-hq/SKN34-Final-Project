"""Per-check example prompting: show the VLM a human 'yes' and 'no' example for every check, one rubric question at a time.

Examples come from the pool split only (>= 4 of 5 raters agreeing, renders preferred); targets are the test split.
Decision rule, fixed before any VLM result: on the test images,
'대체 가능' if the total-score Spearman CI lower bound > 0 (identical scores for every image count as not > 0), sticker < render < real holds (analyze.kind_order_ok),
and mean per-check agreement with the human majority >= the median single-rater agreement;
'보조만' if only the first two hold; otherwise '쓰지 않음'.

  rubric_examples.py build      -> results/rubric_examples.json, results/rubric_gallery.html (local, faces)
  rubric_examples.py export     -> rubric_examples_pack.zip
  rubric_examples.py run --pack DIR --output CSV [--mock]
  rubric_examples.py analyze    -> results/rubric_examples_summary.json
"""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import random
import statistics
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from common import DATA, HERE, allows_na, checks, cluster_bootstrap, load_json, read_csv, score, sha256, spearman
from judge import QwenJudge, extract_json

PROMPT_VERSION = 'rubric-examples-v1'
FINISH = {'glossy': '글로시', 'satin': '새틴', 'matte': '매트', 'unknown': '알 수 없음'}
FIELDS = ['run_id', 'image_id', 'question', 'status', 'checks_json', 'reason', 'elapsed_seconds', 'attempts', 'error',
          'model_id', 'model_revision', 'prompt_version', 'datetime_utc', 'gpu', 'quantization']
EXAMPLE_PX, FULL_PX, CROP_PX = 224, (360, 480), 384


def load_votes(con, rubric):
    images = {r['image_id']: dict(r) for r in con.execute('SELECT * FROM images WHERE repeat_of IS NULL')}
    votes = defaultdict(dict)
    for r in con.execute("SELECT rater_id,image_id,checks_json FROM human_ratings WHERE rubric_version=? AND rater_id!='R0'", (rubric['version'],)):
        if r['image_id'] in images:
            votes[r['image_id']][r['rater_id']] = json.loads(r['checks_json'])
    return images, votes


def consensus(answers, check_id, need=4):
    """'yes'/'no' when at least `need` raters gave that answer (n/a excluded), else None."""
    vals = [a.get(check_id) for a in answers if a.get(check_id) not in (None, 'na')]
    yes = sum(v == 1 for v in vals); no = sum(v == 0 for v in vals)
    if yes >= need: return 'yes', yes, len(vals)
    if no >= need: return 'no', no, len(vals)
    return None, max(yes, no), len(vals)


def choose_examples(images, votes, rubric, need=4, gallery_size=6):
    kind_rank = {'render': 0, 'real': 1, 'sticker': 2}
    usage = defaultdict(int); chosen = {}; gallery = {}
    for c in checks(rubric):
        cid = c['id']; sides = {'yes': [], 'no': []}
        for i, m in images.items():
            if m['split'] != 'pool' or i not in votes:
                continue
            side, count, n = consensus(list(votes[i].values()), cid, need)
            if side:
                sides[side].append({'image_id': i, 'face_id': m['face_id'], 'kind': m['kind'], 'finish': m['finish'], 'votes': f'{count}/{n}', 'strength': count / n})
        for side in sides:
            sides[side].sort(key=lambda x: (kind_rank[x['kind']], -x['strength'], x['image_id']))
        gallery[cid] = {s: v[:gallery_size] for s, v in sides.items()}
        pick = {}
        for side in ('yes', 'no'):
            pool = [x for x in sides[side] if x['kind'] == sides[side][0]['kind']] if sides[side] else []
            pool = [x for x in pool if x['strength'] == pool[0]['strength']] if pool else []
            other_face = pick.get('yes', {}).get('face_id')
            pool.sort(key=lambda x: (x['face_id'] == other_face, usage[x['image_id']], x['image_id']))
            if pool:
                pick[side] = pool[0]; usage[pool[0]['image_id']] += 1
        chosen[cid] = pick
    return chosen, gallery


def gallery_html(rubric, chosen, gallery, image_dir):
    def img(entry, mark):
        src = (Path(image_dir) / f"{entry['image_id']}_crop.png").as_uri()
        border = '3px solid #2f6fdc' if mark else '1px solid #ccc'
        return (f'<figure><img src="{src}" style="border:{border}"><figcaption>{html.escape(entry["votes"])} · '
                f'{FINISH.get(entry["finish"], entry["finish"])} · {entry["kind"]}{" · VLM 예시" if mark else ""}</figcaption></figure>')
    parts = ['<html><head><meta charset="utf-8"><title>립 채점표 v2 기준별 예시</title><style>'
             'body{font-family:"Malgun Gothic",sans-serif;max-width:1200px;margin:24px auto;color:#222}'
             'h2{border-bottom:1px solid #ddd;padding-bottom:4px}.row{display:grid;grid-template-columns:260px 1fr 1fr;gap:12px;margin:14px 0}'
             '.side{display:flex;flex-wrap:wrap;gap:6px}figure{margin:0;width:120px}img{width:120px;height:120px;object-fit:cover}'
             'figcaption{font-size:11px;color:#555}.miss{color:#b3261e}</style></head><body>'
             '<h1>립 채점표 v2 — 체크별 예시 사진</h1><p>사례용 분할(pool)에서 5명 중 4명 이상이 같은 답을 한 사진. 렌더 우선. '
             '파란 테두리는 VLM 프롬프트에 넣는 예시. LaPa 비상업 연구용, 외부 공유 금지.</p>']
    for q in rubric['questions']:
        parts.append(f'<h2>{html.escape(q["title"])}</h2>')
        for c in q['checks']:
            cid = c['id']; g = gallery[cid]; pick = chosen[cid]
            cols = []
            for side, label in (('yes', '예'), ('no', '아니오')):
                items = ''.join(img(e, pick.get(side, {}).get('image_id') == e['image_id']) for e in g[side])
                cols.append(f'<div><b>{label}</b><div class="side">{items or "<span class=miss>예시 없음</span>"}</div></div>')
            parts.append(f'<div class="row"><div><b>{cid.replace("q", "").replace("_", "-")}</b> {html.escape(c["text"])}</div>{"".join(cols)}</div>')
    parts.append('</body></html>')
    return ''.join(parts)


def prompt_parts(question, examples, target, rng):
    parts = [('text', f"아래는 립 메이크업 합성 사진의 자연스러움을 평가하는 체크리스트 중 '{question['title']}' 문항입니다. "
                      '체크마다 사람 평가자들이 "예"라고 답한 사진과 "아니오"라고 답한 사진(입술 확대)을 먼저 보여 줍니다. '
                      '예시와 비교해서 마지막 평가 대상 사진의 각 체크에 1(예) 또는 0(아니오)으로 답하세요. '
                      '"아니오" 예시와 비슷한 문제가 보이면 0을 고르세요. 제품 색이 정확한지는 판단하지 마세요.')]
    for c in question['checks']:
        parts.append(('text', f"체크 {c['id']}: {c['text']}"))
        ex = examples[c['id']]
        sides = [s for s in ('yes', 'no') if s in ex]
        rng.shuffle(sides)
        for side in sides:
            parts.append(('text', '예 예시:' if side == 'yes' else '아니오 예시:'))
            parts.append(('image', f"examples/{ex[side]['image_id']}_crop.png"))
    parts.append(('text', f"평가 대상 (제형: {FINISH.get(target['finish'], target['finish'])}, 입 상태: {target['mouth']}) 전체 화면:"))
    parts.append(('image', f"targets/{target['image_id']}_full.png"))
    parts.append(('text', '평가 대상 입술 확대:'))
    parts.append(('image', f"targets/{target['image_id']}_crop.png"))
    na = [c['id'] for c in question['checks'] if allows_na(c, target['finish'])]
    example = ','.join(f'"{c["id"]}":1' for c in question['checks'])
    parts.append(('text', '반드시 JSON 객체만 출력: {"checks":{' + example + '},"reason":"한 줄"}. 모든 체크 ID에 1 또는 0으로 답합니다.'
                  + (f' 제형이 매트이므로 {", ".join(na)}는 "na"로 답합니다.' if na else '')))
    return parts


def parse_question(text, question, finish):
    obj = extract_json(text)
    if not isinstance(obj, dict) or set(obj) != {'checks', 'reason'} or not isinstance(obj['checks'], dict):
        raise ValueError('invalid JSON object fields')
    ids = [c['id'] for c in question['checks']]
    if set(obj['checks']) != set(ids):
        raise ValueError('checks do not match question')
    for c in question['checks']:
        v = obj['checks'][c['id']]
        if isinstance(v, bool) or not (type(v) is int and v in (0, 1) or v == 'na' and allows_na(c, finish)):
            raise ValueError(f"invalid check {c['id']}")
    if not isinstance(obj['reason'], str) or not obj['reason'].strip() or '\n' in obj['reason']:
        raise ValueError('reason must be one nonempty line')
    return obj


class MockContentJudge:
    def __init__(self, answer=lambda parts, question: 1):
        self.answer = answer; self.calls = 0

    def generate(self, parts, question):
        self.calls += 1
        return json.dumps({'checks': {c['id']: self.answer(parts, c) for c in question['checks']}, 'reason': '모의 실행'}, ensure_ascii=False)


class QwenContentJudge(QwenJudge):
    def __init__(self, config, root):
        super().__init__(config); self.root = Path(root)

    def generate(self, parts, question):
        from qwen_vl_utils import process_vision_info
        content = [{'type': 'text', 'text': v} if k == 'text' else {'type': 'image', 'image': (self.root / v).resolve().as_uri()} for k, v in parts]
        messages = [{'role': 'user', 'content': content}]
        rendered = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(text=[rendered], images=image_inputs, videos=video_inputs, padding=True, return_tensors='pt').to('cuda')
        with self.torch.inference_mode():
            generated = self.model.generate(**inputs, **{**self.config['generation'], 'max_new_tokens': 300})
        trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generated)]
        return self.processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]


def run(root, output, config, adapter, mock=False, retries=2, seed=42):
    root = Path(root); output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    rubric = load_json(root / 'rubric.json'); examples = load_json(root / 'rubric_examples.json')['examples']
    targets = read_csv(root / 'targets.csv')
    run_id = hashlib.sha256(json.dumps({'config': config, 'examples': sha256(root / 'rubric_examples.json'), 'targets': sha256(root / 'targets.csv'),
                                        'prompt': PROMPT_VERSION, 'mock': mock}, sort_keys=True).encode()).hexdigest()
    existing = read_csv(output) if output.exists() else []
    if existing and any(r['run_id'] != run_id for r in existing):
        raise ValueError('output contains a different experiment; use a new path')
    done = {(r['image_id'], r['question']) for r in existing if r['status'] == 'ok'}
    gpu = 'mock'
    if not mock:
        import torch
        gpu = torch.cuda.get_device_name(0)
    with output.open('a', encoding='utf8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not existing:
            writer.writeheader(); f.flush(); os.fsync(f.fileno())
        for target in targets:
            for q in rubric['questions']:
                if (target['image_id'], q['id']) in done:
                    continue
                rng = random.Random(f"{seed}:{target['image_id']}:{q['id']}")
                parts = prompt_parts(q, examples, target, rng)
                begin = time.perf_counter(); result = None; error = ''; excerpt = ''; attempts = 0
                for attempts in range(1, retries + 2):
                    answer = ''
                    try:
                        extra = [('text', f'이전 응답 오류: {error}. JSON만 다시 출력하세요.')] if error else []
                        answer = adapter.generate(parts + extra, q)
                        result = parse_question(answer, q, target['finish']); break
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        error = str(exc); excerpt = ' '.join(str(answer).split())[:200]
                writer.writerow({'run_id': run_id, 'image_id': target['image_id'], 'question': q['id'], 'status': 'ok' if result else 'failed',
                                 'checks_json': json.dumps(result['checks'], ensure_ascii=False) if result else '', 'reason': result['reason'] if result else '',
                                 'elapsed_seconds': round(time.perf_counter() - begin, 3), 'attempts': attempts, 'error': '' if result else f'{error} | 응답 앞부분: {excerpt}',
                                 'model_id': 'mock' if mock else config['vlm']['model_id'], 'model_revision': 'mock' if mock else config['vlm']['revision'],
                                 'prompt_version': PROMPT_VERSION, 'datetime_utc': datetime.now(timezone.utc).isoformat(), 'gpu': gpu, 'quantization': config['vlm']['quantization']})
                f.flush(); os.fsync(f.fileno()); done.add((target['image_id'], q['id']))
    return run_id


def majority(vals):
    vals = [v for v in vals if v in (0, 1)]
    if not vals or sum(vals) * 2 == len(vals): return None
    return int(sum(vals) * 2 > len(vals))


def analyze(rubric, images, votes, rows, zero_shot=None):
    from analyze import kind_order_ok
    by_image = defaultdict(dict)
    for r in rows:
        if r['status'] == 'ok':
            by_image[r['image_id']].update(json.loads(r['checks_json']))
    cids = [c['id'] for c in checks(rubric)]
    complete = [i for i, a in by_image.items() if set(a) == set(cids) and i in images and i in votes]
    human_total = {i: statistics.mean(score(rubric, a, images[i]['finish'])['total'] for a in votes[i].values()) for i in complete}
    vlm_total = {i: score(rubric, by_image[i], images[i]['finish'])['total'] for i in complete}
    obs = [{'face_id': images[i]['face_id'], 'x': human_total[i], 'y': vlm_total[i]} for i in complete]
    corr = cluster_bootstrap(obs, lambda rs: spearman([r['x'] for r in rs], [r['y'] for r in rs]))
    kinds = {k: [vlm_total[i] for i in complete if images[i]['kind'] == k] for k in ('sticker', 'render', 'real')}
    means = {k: statistics.mean(v) if v else None for k, v in kinds.items()}
    triples = [(a, b, c) for a in kinds['sticker'] for b in kinds['render'] for c in kinds['real']]
    triples_fraction = sum(a < b < c for a, b, c in triples) / len(triples) if triples else None
    per_check = {}; rater_agree = defaultdict(list)
    for cid in cids:
        agree = []; vlm_yes = []; human_yes = []
        for i in complete:
            answers = [a.get(cid) for a in votes[i].values()]
            m = majority(answers); v = by_image[i].get(cid)
            if v in (0, 1): vlm_yes.append(v)
            human_yes.extend(x for x in answers if x in (0, 1))
            if m is not None and v in (0, 1): agree.append(int(v == m))
        for rater in sorted({r for i in complete for r in votes[i]}):
            vals = []
            for i in complete:
                own = votes[i].get(rater, {}).get(cid)
                m = majority([a.get(cid) for r, a in votes[i].items() if r != rater])
                if own in (0, 1) and m is not None: vals.append(int(own == m))
            if vals: rater_agree[rater].append(statistics.mean(vals))
        zs = None
        if zero_shot:
            zvals = []
            for i in complete:
                m = majority([a.get(cid) for a in votes[i].values()]); z = zero_shot.get(i, {}).get(cid)
                if m is not None and z in (0, 1): zvals.append(int(z == m))
            zs = statistics.mean(zvals) if zvals else None
        per_check[cid] = {'agreement': statistics.mean(agree) if agree else None, 'n': len(agree), 'vlm_yes_rate': statistics.mean(vlm_yes) if vlm_yes else None,
                          'human_yes_rate': statistics.mean(human_yes) if human_yes else None, 'zero_shot_agreement': zs}
    rater_mean = {r: statistics.mean(v) for r, v in rater_agree.items()}
    human_median = statistics.median(rater_mean.values()) if rater_mean else None
    agreements = [v['agreement'] for v in per_check.values() if v['agreement'] is not None]
    mean_agree = statistics.mean(agreements) if agreements else None
    order_ok = kind_order_ok(means, triples_fraction)
    ci_ok = corr['ci95'] is not None and corr['ci95'][0] > 0
    decision = '판정 불가' if not complete else '대체 가능' if ci_ok and order_ok and mean_agree is not None and human_median is not None and mean_agree >= human_median \
        else '보조만' if ci_ok and order_ok else '쓰지 않음'
    return {'prompt_version': PROMPT_VERSION, 'images': len(complete), 'total_spearman': corr, 'kind_means': means, 'ordered_triples_fraction': triples_fraction,
            'order_ok': order_ok, 'mean_check_agreement': mean_agree, 'human_rater_check_agreement': {'per_rater': rater_mean, 'median': human_median},
            'vlm_full_score_rate': statistics.mean(v == 5 for v in vlm_total.values()) if vlm_total else None, 'per_check': per_check, 'decision': decision}


def resized(path, size):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('RGB'); im.thumbnail(size if isinstance(size, tuple) else (size, size))
        buf = io.BytesIO(); im.save(buf, 'PNG'); return buf.getvalue()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('build'); sub.add_parser('export').add_argument('--output', type=Path, default=DATA / 'rubric_examples_pack.zip')
    r = sub.add_parser('run'); r.add_argument('--pack', required=True, type=Path); r.add_argument('--output', required=True, type=Path); r.add_argument('--mock', action='store_true')
    a = sub.add_parser('analyze'); a.add_argument('--results', type=Path, default=DATA / 'results/rubric_examples_results.csv')
    args = p.parse_args()
    rubric = load_json(HERE / 'rubric.json')
    if args.command == 'run':
        config = load_json(args.pack / 'judges.json')
        if not args.mock and not config['vlm'].get('revision'):
            raise ValueError('judges.json에 VLM 리비전이 필요합니다')
        adapter = MockContentJudge() if args.mock else QwenContentJudge(config['vlm'], args.pack)
        print(run(args.pack, args.output, config, adapter, args.mock)); return
    import db
    con = db.connect(db.DB)
    images, votes = load_votes(con, rubric)
    if args.command == 'build':
        chosen, gallery = choose_examples(images, votes, rubric)
        examples = {cid: {s: {k: e[k] for k in ('image_id', 'face_id', 'kind', 'finish', 'votes')} for s, e in pick.items()} for cid, pick in chosen.items()}
        (DATA / 'results/rubric_examples.json').write_text(json.dumps({'rubric_version': rubric['version'], 'need': 4, 'examples': examples}, ensure_ascii=False, indent=2), encoding='utf8')
        image_dir = Path(next(iter(images.values()))['crop_path']).parent
        (DATA / 'results/rubric_gallery.html').write_text(gallery_html(rubric, chosen, gallery, image_dir), encoding='utf8')
        missing = [cid for cid, pick in chosen.items() if len(pick) < 2]
        print(json.dumps({'checks': len(chosen), 'missing_side': missing, 'example_images': len({e['image_id'] for pick in chosen.values() for e in pick.values()})}, ensure_ascii=False))
    elif args.command == 'export':
        bad = con.execute("SELECT COUNT(*) FROM images WHERE source!='LaPa' OR source_split!='test'").fetchone()[0]
        if bad:
            raise ValueError('LaPa test 이외의 출처가 발견되었습니다')
        ex = load_json(DATA / 'results/rubric_examples.json')
        ex_ids = sorted({e['image_id'] for pick in ex['examples'].values() for e in pick.values()})
        if any(images[i]['split'] != 'pool' for i in ex_ids):
            raise ValueError('예시는 pool 분할에서만 고릅니다')
        targets = sorted(i for i, m in images.items() if m['split'] == 'test')
        out = Path(args.output)
        if out.exists():
            raise FileExistsError(out)
        buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=['image_id', 'finish', 'mouth']); w.writeheader()
        for i in targets:
            w.writerow({'image_id': i, 'finish': images[i]['finish'], 'mouth': images[i]['mouth']})
        with zipfile.ZipFile(out, 'x', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('targets.csv', buf.getvalue()); z.write(DATA / 'results/rubric_examples.json', 'rubric_examples.json'); z.write(HERE / 'rubric.json', 'rubric.json')
            for name in ('judges.json', 'judge.py', 'common.py', 'rubric_examples.py'):
                z.write(HERE / name, name)
            for i in ex_ids:
                if sha256(images[i]['full_path']) != images[i]['file_sha256']: raise ValueError('이미지 해시 불일치: ' + i)
                z.writestr(f'examples/{i}_crop.png', resized(images[i]['crop_path'], EXAMPLE_PX))
            for i in targets:
                if sha256(images[i]['full_path']) != images[i]['file_sha256']: raise ValueError('이미지 해시 불일치: ' + i)
                z.writestr(f'targets/{i}_full.png', resized(images[i]['full_path'], FULL_PX)); z.writestr(f'targets/{i}_crop.png', resized(images[i]['crop_path'], CROP_PX))
        print(f'{out}: SHA-256 {sha256(out)} ({len(ex_ids)} example images, {len(targets)} targets)')
    else:
        zero = None
        jr = DATA / 'results/judge_results.csv'
        if jr.exists():
            zero = {}
            for r in read_csv(jr):
                if r['method'] == 'A' and r['status'] == 'ok':
                    zero[r['image_id']] = json.loads(r['checks_json'])
        summary = analyze(rubric, images, votes, read_csv(args.results), zero)
        out = DATA / 'results/rubric_examples_summary.json'
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
        print(out, summary['decision'])


if __name__ == '__main__':
    main()
