from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from vlm_judge.images import ImageSet, jpeg, lip_box, load_image
from vlm_judge.judge_adapter import JudgeClient
from vlm_judge.schemas import SCHEMAS

PROJECT = Path(__file__).resolve().parents[2]
PROMPT_VERSION = 'vlm-judge-v1'


def make_plan(sets: list[ImageSet], config: dict, only: set[str], seed: int) -> list[dict]:
    rng, tasks = random.Random(seed), []
    for item in sets:
        for repeat in range(config['repeats']):
            if 'color' in only:
                for role in (['ar', 'bare'] if item.bare else ['ar']):
                    tasks.append({'set_id': item.id, 'kind': 'color', 'repeat': repeat, 'order': ['real', role]})
            if 'placement' in only:
                tasks.append({'set_id': item.id, 'kind': 'placement', 'repeat': repeat, 'order': ['real', 'ar']})
            if 'texture' in only and item.bare:
                order = ['ar', 'bare']
                rng.shuffle(order)
                for pair in (order, order[::-1]) if config['swap_order'] else (order,):
                    tasks.append({'set_id': item.id, 'kind': 'texture', 'repeat': repeat, 'order': ['real', *pair]})
            if 'naturalness' in only:
                order = ['real', 'ar']
                rng.shuffle(order)
                for role in order:
                    tasks.append({'set_id': item.id, 'kind': 'natural_single', 'repeat': repeat, 'order': [role]})
                rng.shuffle(order)
                for pair in (order, order[::-1]) if config['swap_order'] else (order,):
                    tasks.append({'set_id': item.id, 'kind': 'natural_pair', 'repeat': repeat, 'order': pair})
    rng.shuffle(tasks)
    return tasks


def normalized(kind: str, order: list[str], response: dict) -> dict:
    value = dict(response)
    if kind == 'texture':
        for field in ('contrast_closer', 'highlight_closer', 'texture_closer'):
            v = value[field]
            value[field] = {'X': order[1], 'Y': order[2], 'tie': 'tie'}[v]
        for attr in ('finish_look', 'plastic_look'):
            value[order[1] + '_' + attr] = value.pop('x_' + attr)
            value[order[2] + '_' + attr] = value.pop('y_' + attr)
    elif kind == 'natural_pair':
        value['choice'] = order[0] if value['choice'] == 'X' else order[1]
    return value


def cache_key(task: dict, model: str, prompt: str, image_bytes: list[bytes]) -> str:
    h = hashlib.sha256()
    for data in image_bytes:
        h.update(len(data).to_bytes(8, 'big'))
        h.update(data)
    h.update(json.dumps({'version': PROMPT_VERSION, 'prompt': prompt, 'model': model,
                         'kind': task['kind'], 'repeat': task['repeat'],
                         'order': task['order']}, sort_keys=True).encode())
    return h.hexdigest()


async def run(data: Path, sets: list[ImageSet], config: dict, client: JudgeClient,
              only: set[str], seed: int, no_cache: bool = False) -> Path:
    run_root = data / 'runs'
    run_root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir = run_root / base
    suffix = 1
    while run_dir.exists():
        run_dir = run_root / f'{base}-{suffix}'
        suffix += 1
    (run_dir / 'raw').mkdir(parents=True)
    cache = run_root / '.cache'
    cache.mkdir(exist_ok=True)
    selected = {item.id: item for item in sets}
    prepared = {}
    for item in sets:
        images = {role: load_image(path) for role, path in [('real', item.real), ('ar', item.ar), ('bare', item.bare)] if path}
        model_path = Path(config['landmarker_model']) if config.get('landmarker_model') else None
        box, crop = lip_box(images.get('bare', images['real']), model_path)
        prepared[item.id] = {role: {'full': jpeg(im), 'crop': jpeg(im, box)} for role, im in images.items()}
        item.meta['crop'] = crop
        item.meta['crop_box_relative'] = box
    tasks = make_plan(sets, config, only, seed)
    sem = asyncio.Semaphore(config['max_concurrency'])
    prompts = {kind: (PROJECT / 'prompts' / f'{kind}.md').read_text(encoding='utf-8') for kind in SCHEMAS}

    async def one(task: dict) -> dict:
        item, kind, order = selected[task['set_id']], task['kind'], task['order']
        variant = 'full' if kind.startswith('natural') else 'crop'
        payload = [prepared[item.id][role][variant] for role in order]
        labels = (['Reference', 'Candidate'] if kind in {'color', 'placement'} else
                  ['Reference', 'Candidate X', 'Candidate Y'] if kind == 'texture' else
                  ['Candidate'] if kind == 'natural_single' else ['Candidate X', 'Candidate Y'])
        images = list(zip(labels, payload, strict=True))
        key = cache_key(task, config['model'], prompts[kind], payload)
        cache_file = cache / f'{key}.json'
        result = {**task, 'image_paths': [str(getattr(item, role)) for role in order],
                  'crop': item.meta['crop'], 'cache_hit': False}
        if not no_cache and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding='utf-8'))
                result.update(cached)
                result['cache_hit'] = True
                result['latency_s'] = 0.0
                result['input_tokens'] = result['output_tokens'] = 0
                return result
            except (OSError, ValueError, KeyError):
                pass
        started = time.monotonic()
        result['attempts'] = []
        async with sem:
            invalid_attempts, transient_attempts = 0, 0
            while True:
                attempt_started = time.monotonic()
                try:
                    answer = await asyncio.wait_for(client.judge(prompts[kind], images, SCHEMAS[kind]), timeout=config['timeout_s'])
                    response = SCHEMAS[kind].model_validate(answer.value).model_dump()
                    result['attempts'].append({'status': 'ok', 'latency_s': round(time.monotonic()-attempt_started, 3), 'response': response, 'input_tokens': answer.input_tokens, 'output_tokens': answer.output_tokens})
                    result.update(status='ok', response=response, normalized=normalized(kind, order, response),
                                  input_tokens=answer.input_tokens, output_tokens=answer.output_tokens)
                    break
                except ValidationError:
                    result['attempts'].append({'status': 'invalid', 'latency_s': round(time.monotonic()-attempt_started, 3)})
                    invalid_attempts += 1
                    if invalid_attempts >= 3:
                        result.update(status='invalid', response=None, normalized=None)
                        break
                except Exception as exc:  # noqa: BLE001 -- isolate provider errors without leaking request text
                    code = getattr(exc, 'code', getattr(exc, 'status_code', None))
                    result['attempts'].append({'status': 'error', 'error_type': type(exc).__name__, 'latency_s': round(time.monotonic()-attempt_started, 3)})
                    if code not in (429, 500, 502, 503, 504) or transient_attempts >= config['max_retries']:
                        # Never write exception text, which may contain request data or credentials.
                        result.update(status='error', error_type=type(exc).__name__, response=None, normalized=None)
                        break
                    await asyncio.sleep(min(2 ** transient_attempts, 30))
                    transient_attempts += 1
        result['latency_s'] = round(time.monotonic() - started, 3)
        if result['status'] == 'ok':
            cache_file.write_text(json.dumps({k: result[k] for k in ('status', 'response', 'normalized', 'input_tokens', 'output_tokens')}, ensure_ascii=False), encoding='utf-8')
        return result

    results = await asyncio.gather(*(one(task) for task in tasks))
    with (run_dir / 'raw' / 'calls.jsonl').open('w', encoding='utf-8') as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + '\n')
    manifest = {'model': config['model'], 'config': config, 'prompt_version': PROMPT_VERSION,
                'seed': seed, 'data': str(data.resolve()), 'sets': [{'id': s.id, 'real': str(s.real), 'ar': str(s.ar), 'bare': str(s.bare) if s.bare else None, 'meta': s.meta} for s in sets],
                'created_at': datetime.now().isoformat(timespec='seconds'), 'planned_calls': len(tasks)}
    (run_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    from vlm_judge.report import generate_report
    generate_report(run_dir)
    return run_dir
