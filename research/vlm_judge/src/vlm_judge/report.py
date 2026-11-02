from __future__ import annotations

import base64
import csv
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from scipy.stats import spearmanr

from vlm_judge.images import jpeg, load_image

BANDS = ['<=2', '2-4', '4-6', '6-10', '>10']
AMOUNTS = ['none', 'slight(<=10%)', 'moderate(10-25%)', 'severe(>25%)']
TEXTURE_FIELDS = ('contrast_closer', 'highlight_closer', 'texture_closer')


def majority(values: list):
    if not values:
        return None
    counts = Counter(values)
    top = counts.most_common()
    return top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else 'tie'


def wilson(success: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = success / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total))/denominator
    margin = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator
    return [max(0, center-margin), min(1, center+margin)]


def ordinal(values: list[str], options: list[str]) -> str | None:
    if not values:
        return None
    # Conservative upper median for an even number of ordinal observations.
    ordered = sorted(options.index(v) for v in values)
    return options[ordered[len(ordered)//2]]


def fraction(num: int, den: int) -> str:
    return f'{num}/{den} ({num/den:.1%})' if den else '자료 없음'


def status(ok: bool | None) -> str:
    return '자료 없음' if ok is None else '합격' if ok else '미달'


def human_compare(path: Path, singles: dict, config: dict) -> dict | None:
    if not path.exists():
        return None
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    scores, guesses, reasons = [], [], Counter()
    for row in rows:
        image_id = row.get('image_id', '').strip()
        v = singles.get(image_id)
        if not v:
            continue
        try:
            scores.append((float(row['score']), v['naturalness']))
        except (ValueError, KeyError, TypeError):
            pass
        truthy = row.get('guess_real', '').strip().lower()
        if truthy in ('true', '1', 'yes', 'real', 'real_makeup', 'false', '0', 'no', 'ar', 'ar_virtual'):
            guess = truthy in ('true', '1', 'yes', 'real', 'real_makeup')
            guesses.append(guess == (v['guess'] == 'real_makeup'))
        for label in row.get('reasons', '').replace(';', ',').split(','):
            if label.strip():
                reasons[label.strip()] += 1
    rho = None
    if len(scores) >= 3:
        res = spearmanr([x[0] for x in scores], [x[1] for x in scores]).statistic
        if math.isfinite(res):
            rho = float(res)
    agreement = sum(guesses)/len(guesses) if guesses else None
    t = config['thresholds']
    if rho is None or agreement is None:
        level = '판단 불가'
    elif rho >= t['human_replace_spearman'] and agreement >= t['human_replace_agreement']:
        level = '대체 가능'
    elif rho >= t['human_assist_spearman']:
        level = '보조만'
    else:
        level = '쓰지 않음'
    return {'score_pairs': len(scores), 'spearman': rho, 'guess_pairs': len(guesses),
            'guess_agreement': agreement, 'human_reasons': dict(reasons), 'level': level}


def generate_report(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    config, sets = manifest['config'], manifest['sets']
    calls = [json.loads(line) for line in (run_dir / 'raw' / 'calls.jsonl').read_text(encoding='utf-8').splitlines() if line]
    valid = [c for c in calls if c['status'] == 'ok']
    per_set, singles = [], {}
    texture_wins = Counter()
    texture_den = Counter()
    ar_guesses, pair_guesses, real_scores, ar_scores, none_count = [], [], [], [], []
    region_counts, reason_counts = Counter(), Counter()
    overflow_ok, missing_ok = [], []
    consistency, swapped, first = [], [], []
    for item in sets:
        sc = [c for c in valid if c['set_id'] == item['id']]
        row = {'set_id': item['id'], 'crop': item['meta'].get('crop', 'unknown')}
        for role in ('bare', 'ar'):
            row[role + '_color_band'] = ordinal([c['normalized']['color_band'] for c in sc if c['kind'] == 'color' and c['order'][1] == role], BANDS)
        ar_band, bare_band = row['ar_color_band'], row['bare_color_band']
        row['ar_color_score'] = 5 - BANDS.index(ar_band) if ar_band else None
        row['bare_color_score'] = 5 - BANDS.index(bare_band) if bare_band else None
        row['color_pass'] = (BANDS.index(ar_band) <= BANDS.index(config['thresholds']['color_pass_max_band']) and BANDS.index(ar_band) < BANDS.index(bare_band)) if ar_band and bare_band else None
        row['color_target'] = ar_band == config['thresholds']['color_target_band'] if ar_band else None
        place = [c['normalized'] for c in sc if c['kind'] == 'placement']
        row['placement_score'] = statistics.median([p['placement_score'] for p in place]) if place else None
        row['placement_pass'] = row['placement_score'] >= config['thresholds']['placement_pass'] if place else None
        for key, target in [('overflow', overflow_ok), ('missing', missing_ok)]:
            result = ordinal([p[key] for p in place], AMOUNTS)
            row[key] = result
            if result:
                target.append(AMOUNTS.index(result) <= 1)
        for key, options in [('edge', ['natural_soft', 'slightly_sharp', 'sticker_sharp', 'blurry_bleed']), ('corner_fade', ['natural', 'too_strong', 'too_weak'])]:
            row[key] = majority([p[key] for p in place])
        tex = [c for c in sc if c['kind'] == 'texture']
        for field in TEXTURE_FIELDS:
            outcome = majority([c['normalized'][field] for c in tex])
            row[field] = outcome
            if outcome:
                texture_den[field] += 1
                texture_wins[field] += outcome == 'ar'
        row['texture_ar_wins'] = sum(row[field] == 'ar' for field in TEXTURE_FIELDS) if tex else None
        for role in ('ar', 'bare'):
            for attr in ('finish_look', 'plastic_look'):
                row[f'{role}_{attr}'] = majority([c['normalized'][f'{role}_{attr}'] for c in tex]) if tex else None
        for role, scores in [('real', real_scores), ('ar', ar_scores)]:
            responses = [c['normalized'] for c in sc if c['kind'] == 'natural_single' and c['order'] == [role]]
            if not responses:
                continue
            naturalness = statistics.median([r['naturalness'] for r in responses])
            guess = majority([r['guess'] for r in responses])
            scores.append(naturalness)
            if role == 'ar':
                if guess != 'tie':
                    ar_guesses.append(guess == 'ar_virtual')
                none_count.append(sum('none' in r['awkward_regions'] for r in responses) > len(responses)/2)
                for label in {x for r in responses for x in r['awkward_regions'] if x != 'none'}:
                    region_counts[label] += sum(label in r['awkward_regions'] for r in responses) > len(responses)/2
                for label in {x for r in responses for x in r['awkward_reasons'] if x != 'none'}:
                    reason_counts[label] += sum(label in r['awkward_reasons'] for r in responses) > len(responses)/2
            singles[f"{item['id']}/{role}"] = {'naturalness': naturalness, 'guess': guess}
            row[role + '_naturalness'] = naturalness
            row[role + '_guess'] = guess
        pairs = [c for c in sc if c['kind'] == 'natural_pair']
        if pairs:
            # Choosing real means correctly identifying which image is physically made up.
            pair_outcome = majority([c['normalized']['choice'] for c in pairs])
            if pair_outcome != 'tie':
                pair_guesses.append(pair_outcome == 'real')
        grouped = defaultdict(list)
        for c in sc:
            k = c['kind']
            field = {'color': 'color_band', 'placement': 'placement_score', 'texture': 'contrast_closer',
                     'natural_single': 'guess', 'natural_pair': 'choice'}[k]
            subject = c['order'][1] if k == 'color' else c['order'][0] if k == 'natural_single' else 'pair'
            grouped[(k, subject)].append(c['normalized'][field])
            if k == 'texture':
                first.append(c['response']['contrast_closer'] == 'X')
            elif k == 'natural_pair':
                first.append(c['response']['choice'] == 'X')
        for observations in grouped.values():
            if len(observations) > 1:
                counts = Counter(observations)
                consistency.append(max(counts.values()) / len(observations))
        for kind, field in [('texture', 'contrast_closer'), ('natural_pair', 'choice')]:
            for repeat in range(config['repeats']):
                pair = [c for c in sc if c['kind'] == kind and c['repeat'] == repeat]
                if len(pair) == 2:
                    swapped.append(pair[0]['normalized'][field] != pair[1]['normalized'][field])
        per_set.append(row)
    texture = {f: {'wins': texture_wins[f], 'total': texture_den[f],
                   'pass': texture_wins[f] / texture_den[f] >= config['thresholds']['texture_win_fraction'] if texture_den[f] else None} for f in TEXTURE_FIELDS}
    single_accuracy = sum(ar_guesses)/len(ar_guesses) if ar_guesses else None
    pair_accuracy = sum(pair_guesses)/len(pair_guesses) if pair_guesses else None
    ar_mean = statistics.mean(ar_scores) if ar_scores else None
    nat_pass = (single_accuracy <= config['thresholds']['naturalness_accuracy_max'] and pair_accuracy <= config['thresholds']['naturalness_accuracy_max'] and ar_mean >= config['thresholds']['naturalness_score_min']) if single_accuracy is not None and pair_accuracy is not None and ar_mean is not None else None
    color_passes = [r['color_pass'] for r in per_set if r['color_pass'] is not None]
    place_passes = [r['placement_pass'] for r in per_set if r['placement_pass'] is not None]
    tokens_in = sum(c.get('input_tokens') or 0 for c in calls)
    tokens_out = sum(c.get('output_tokens') or 0 for c in calls)
    pi, po = config.get('price_per_1m_input_usd'), config.get('price_per_1m_output_usd')
    charged = [c for c in calls if not c.get('cache_hit') and c['status'] == 'ok']
    incomplete_attempts = any(any(a['status'] != 'ok' for a in c.get('attempts', [])) for c in calls)
    cost = (tokens_in*pi + tokens_out*po)/1e6 if pi is not None and po is not None and not incomplete_attempts and all(c.get('input_tokens') is not None and c.get('output_tokens') is not None for c in charged) else None
    human = human_compare(Path(manifest['data']) / 'human' / 'responses.csv', singles, config)
    summary = {'prompt_version': manifest['prompt_version'], 'model': manifest['model'], 'sets': len(sets),
        'calls': len(calls), 'api_attempts': sum(len(c.get('attempts', [])) for c in calls), 'valid': len(valid), 'invalid': sum(c['status']=='invalid' for c in calls), 'errors': sum(c['status']=='error' for c in calls),
        'mean_latency_s': statistics.mean(c['latency_s'] for c in calls) if calls else None,
        'input_tokens': tokens_in, 'output_tokens': tokens_out, 'cost_usd': cost,
        'color_pass': {'passed': sum(color_passes), 'total': len(color_passes)},
        'placement_pass': {'passed': sum(place_passes), 'total': len(place_passes)}, 'texture': texture,
        'naturalness': {'single_accuracy': single_accuracy, 'single_wilson95': wilson(sum(ar_guesses), len(ar_guesses)), 'single_n': len(ar_guesses),
                       'pair_accuracy': pair_accuracy, 'pair_wilson95': wilson(sum(pair_guesses), len(pair_guesses)), 'pair_n': len(pair_guesses),
                       'real_mean': statistics.mean(real_scores) if real_scores else None, 'ar_mean': ar_mean, 'pass': nat_pass,
                       'none': sum(none_count), 'regions': dict(region_counts), 'reasons': dict(reason_counts)},
        'consistency': {'repeat_agreement_mean': statistics.mean(consistency) if consistency else None,
                        'swap_change_fraction': statistics.mean(swapped) if swapped else None,
                        'first_choice_fraction': statistics.mean(first) if first else None},
        'human': human, 'excluded_no_bare': [s['id'] for s in sets if not s['bare']]}
    (run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    columns = sorted({key for row in per_set for key in row})
    with (run_dir / 'per_set.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(per_set)
    fmt = lambda x: '자료 없음' if x is None else f'{x:.3f}'
    texture_text = ' / '.join(f'{f}: {fraction(v["wins"],v["total"])} {status(v["pass"])}' for f,v in texture.items())
    reason = reason_counts.most_common(1)[0][0] if reason_counts else '자료 없음'
    lines = ['# VISHUE AR 메이크업 품질 평가 · VLM 추정', '', '## 1. 결론 먼저 (3줄)',
        f'- 색상 합격 {fraction(sum(color_passes),len(color_passes))}, 위치 합격 {fraction(sum(place_passes),len(place_passes))}.',
        f'- 질감: {texture_text}. 자연스러움: {status(nat_pass)}.',
        f'- 가장 많이 지적된 이유: {reason}.', '', '## 2. 4지표 카드',
        '| 지표 | VLM 결과 | 합격선/목표 | 판정 |', '|---|---|---|---|',
        f'| 색상일치 | {fraction(sum(color_passes),len(color_passes))} 세트 합격 | AR ≤ 2-4, bare보다 가까움; 목표 ≤2 | 세트별 |',
        f'| 위치·경계 | {fraction(sum(place_passes),len(place_passes))} 세트 합격 | 중앙값 ≥ {config["thresholds"]["placement_pass"]} | 세트별 |',
        f'| 질감·광택 | {texture_text} | 각 항목 승리 ≥ 절반 | 항목별 |',
        f'| 자연스러움 | 단일 {fmt(single_accuracy)}, 쌍 {fmt(pair_accuracy)}, AR 점수 {fmt(ar_mean)} | 정답률 각각 ≤65%, AR ≥3.5 | {status(nat_pass)} |',
        '', '## 3. 지표별 상세', '| 세트 | bare 색 | AR 색 | 색 판정 | 목표 | 위치 점수 | 넘침 | 빠짐 | 경계 | 입꼬리 | 명암 승자 | 광택 승자 | 결 승자 |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in per_set:
        vals = [r['set_id'], r['bare_color_band'], r['ar_color_band'], status(r['color_pass']), status(r['color_target']), r['placement_score'], r['overflow'], r['missing'], r['edge'], r['corner_fade'], *[r[f] for f in TEXTURE_FIELDS]]
        lines.append('| ' + ' | '.join(str(x) if x is not None else '—' for x in vals) + ' |')
    lines += [f'\n색상 전체 중앙 구간: bare {ordinal([r["bare_color_band"] for r in per_set if r["bare_color_band"]], BANDS) or "자료 없음"}, AR {ordinal([r["ar_color_band"] for r in per_set if r["ar_color_band"]], BANDS) or "자료 없음"}.',
        f'넘침 slight 이하 {fraction(sum(overflow_ok),len(overflow_ok))}, 빠짐 slight 이하 {fraction(sum(missing_ok),len(missing_ok))}.',
        f'맨얼굴 없어 색 비교·질감에서 제외: {", ".join(summary["excluded_no_bare"]) or "없음"}.',
        f'자연스러움: AR 판별 정답률 단일 {fmt(single_accuracy)} (n={len(ar_guesses)}, Wilson 95% {summary["naturalness"]["single_wilson95"]}), 쌍 {fmt(pair_accuracy)} (n={len(pair_guesses)}, Wilson 95% {summary["naturalness"]["pair_wilson95"]}).',
        f'평균 점수 real {fmt(summary["naturalness"]["real_mean"])}, AR {fmt(ar_mean)}; AR 어색한 곳 없음 {fraction(sum(none_count),len(none_count))}.',
        f'AR 지적 부위/이유(세트별 다수결): {dict(region_counts)} / {dict(reason_counts)}; 분모 {len(none_count)}. 추측 동률은 정확도 분모에서 제외.',
        '', '## 4. 일관성', f'반복 일치율 평균 {fmt(summary["consistency"]["repeat_agreement_mean"])}; 순서 바꿈 결론 변경률 {fmt(summary["consistency"]["swap_change_fraction"])}; 첫 번째 선택률 {fmt(summary["consistency"]["first_choice_fraction"])}. 질감은 명암 항목 기준.',
        '', '## 5. 사람 설문 비교', json.dumps(human, ensure_ascii=False) if human else '사람 설문 없음.',
        '', '## 6. 실행 정보', f'모델 {manifest["model"]}; 실행 {manifest["created_at"]}; PROMPT_VERSION {manifest["prompt_version"]}; 세트 {len(sets)}; 호출 {len(calls)} (유효 {len(valid)}); 평균 지연 {fmt(summary["mean_latency_s"])}초; 비용 USD {fmt(cost)}.',
        '', '## 7. 한계', '①②③은 측정값이 아니라 VLM이 사진을 보고 고른 구간이다',
        '사진의 조명·정렬 차이와 작은 표본, 모델의 위치 편향이 결과에 영향을 줄 수 있다. 신뢰구간은 세트 단위이며 통계적 독립성을 보장하지 않는다.']
    md = '\n'.join(lines) + '\n'
    (run_dir / 'report.md').write_text(md, encoding='utf-8')
    # The local-only HTML embeds thumbnails; it is not intended for publication.
    thumbs = []
    for item in sets:
        parts = []
        for role in ('bare', 'real', 'ar'):
            if item[role]:
                try:
                    image = load_image(Path(item[role]))
                    for label, box in [('전체', None), ('크롭', item['meta'].get('crop_box_relative'))]:
                        raw = jpeg(image, box)
                        parts.append(f'<figure><img src="data:image/jpeg;base64,{base64.b64encode(raw).decode()}"><figcaption>{role} {label}</figcaption></figure>')
                except OSError:
                    parts.append(f'<p>{role}: 이미지 없음</p>')
        thumbs.append(f'<h3>{html.escape(item["id"])}</h3><div class="images">{"".join(parts)}</div>')
    body = '<html lang="ko"><meta charset="utf-8"><title>VLM 추정 보고서</title><style>body{font:14px Malgun Gothic,sans-serif;margin:2em}pre{white-space:pre-wrap;overflow-wrap:anywhere}.images{display:flex;flex-wrap:wrap}figure{margin:6px}img{max-width:160px;max-height:160px}</style><body><pre>' + html.escape(md) + '</pre><h2>세트별 이미지 (로컬 전용)</h2>' + ''.join(thumbs) + '</body></html>'
    (run_dir / 'report.html').write_text(body, encoding='utf-8')
    return summary
