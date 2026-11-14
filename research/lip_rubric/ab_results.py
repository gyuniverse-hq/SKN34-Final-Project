"""Summarize same-face A/B choices from the v3 A/B pack.

  ab_results.py <rater_ab.csv> [--key expansion_v3/ab_key.csv]  -> results/ab_v3_summary.json, results/ab_v3_scores.csv

Reports the repeat consistency (same pair asked again with sides swapped), how often each defect lost to the current
render, and one Bradley-Terry naturalness score per image (within-face comparisons only). Design levels are only used
to describe the result, never as labels.
"""
import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from common import DATA, read_csv, write_csv


def load(key_path, result_paths):
    key = {r['pair_id']: r for r in read_csv(key_path)}
    answers = {}
    for path in result_paths:
        for r in read_csv(path):
            if r['pair_id'] in key and r['choice'] in ('left', 'right', 'same'):
                answers[r['pair_id']] = r
    return key, answers


def winner(k, a):
    return None if a['choice'] == 'same' else (k['left'] if a['choice'] == 'left' else k['right'])


def bradley_terry(comparisons, iterations=200):
    items = sorted({x for c in comparisons for x in c[:2]})
    score = {i: 1.0 for i in items}
    wins = defaultdict(float)
    for a, b, w in comparisons:
        wins[a] += w; wins[b] += 1 - w
    for _ in range(iterations):
        new = {}
        for i in items:
            denom = sum(1 / (score[a] + score[b]) for a, b, _ in comparisons if i in (a, b))
            new[i] = (wins[i] + 0.5) / (denom + 1e-9)
        mean = math.exp(statistics.mean(math.log(v) for v in new.values()))
        score = {i: v / mean for i, v in new.items()}
    return {i: math.log(v) for i, v in score.items()}


def summarize(key, answers):
    originals = {p: k for p, k in key.items() if not k['repeat_of']}
    consistency = []
    for p, k in key.items():
        if k['repeat_of'] and p in answers and k['repeat_of'] in answers:
            consistency.append(winner(k, answers[p]) == winner(originals[k['repeat_of']], answers[k['repeat_of']]))
    variant = {}
    for k in key.values():
        variant[k['left']] = (k['left_variant'], k['left_level']); variant[k['right']] = (k['right_variant'], k['right_level'])
    vs_current = defaultdict(lambda: [0, 0, 0])
    comparisons = []
    for p, k in originals.items():
        if p not in answers:
            continue
        w = winner(k, answers[p])
        comparisons.append((k['left'], k['right'], 0.5 if w is None else float(w == k['left'])))
        for side, other in (('left', 'right'), ('right', 'left')):
            if k[f'{side}_variant'] == 'current' and k[f'{other}_variant'] != 'current':
                name = f"{k[f'{other}_variant']}:{k[f'{other}_level']}"
                vs_current[name][0 if w == k[side] else 1 if w == k[other] else 2] += 1
    bt = bradley_terry(comparisons) if comparisons else {}
    same = sum(a['choice'] == 'same' for a in answers.values())
    return {
        'pairs_answered': len(answers), 'pairs_total': len(key), 'same_rate': same / len(answers) if answers else None,
        'repeat_consistency': statistics.mean(consistency) if consistency else None, 'repeat_pairs': len(consistency),
        'current_vs_defect': {n: {'current_wins': v[0], 'defect_wins': v[1], 'same': v[2], 'current_win_rate': v[0] / max(1, v[0] + v[1])}
                              for n, v in sorted(vs_current.items())},
        'mean_score_by_design': {f'{a}:{b}': statistics.mean(s for i, s in bt.items() if variant.get(i) == (a, b))
                                 for a, b in sorted(set(variant.values())) if any(variant.get(i) == (a, b) for i in bt)},
    }, bt, variant


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('results', nargs='+', type=Path); p.add_argument('--key', type=Path, default=DATA / 'expansion_v3/ab_key.csv')
    a = p.parse_args()
    key, answers = load(a.key, a.results)
    summary, bt, variant = summarize(key, answers)
    out = DATA / 'results'; out.mkdir(parents=True, exist_ok=True)
    (out / 'ab_v3_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    faces = {}
    for k in key.values():
        faces[k['left']] = faces[k['right']] = (k['face_id'], k['split'])
    write_csv(out / 'ab_v3_scores.csv', [{'image_id': i, 'face_id': faces[i][0], 'split': faces[i][1], 'variant': variant[i][0], 'level': variant[i][1], 'bt_score': round(s, 4)}
                                         for i, s in sorted(bt.items(), key=lambda x: -x[1])])
    print(json.dumps({k: summary[k] for k in ('pairs_answered', 'same_rate', 'repeat_consistency')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
