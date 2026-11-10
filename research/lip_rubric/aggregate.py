"""Aggregate blinded human ratings, agreement and report-only renderer metrics."""
import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from common import DATA, HERE, checks, cluster_bootstrap, icc2, krippendorff_alpha, load_json, read_csv, score, sha256, spearman, write_csv


def parse_ratings(files, key, rubric, pack_path=None):
    by_rater = {}; issues = []; versions = set(); hashes = set()
    for path in sorted(map(Path, files), key=lambda p: (p.stat().st_mtime_ns, str(p))):
        rows = read_csv(path)
        if not rows:
            issues.append({"file": str(path), "issue": "empty"}); continue
        ids = {r.get("rater_id", "").strip() for r in rows}
        if len(ids) != 1 or not re.fullmatch(r"R[0-9]+", next(iter(ids), ""), flags=re.I):
            raise ValueError(f"{path}: 익명 평가자 코드 R1 형식 한 개가 필요합니다")
        rater = next(iter(ids)).upper()
        if rater in by_rater:
            issues.append({"rater":rater,"issue":"duplicate_submission_latest_file_used","replaced":by_rater[rater][0],"selected":str(path)})
        by_rater[rater] = (str(path), rows)
    result = []
    for rater, (path, rows) in by_rater.items():
        seen = set()
        for row in rows:
            image_id = row.get("image_id", "")
            if image_id not in key:
                raise ValueError(f"{path}: unknown image_id {image_id}")
            if image_id in seen:
                raise ValueError(f"{path}: duplicate image_id {image_id}")
            seen.add(image_id)
            hashes.add(row.get("pack_hash", "")); versions.add(row.get("rubric_version", ""))
            if row.get("is_repeat", "").lower() not in ({"1", "true"} if key[image_id].get("repeat_of") else {"0", "false"}):
                raise ValueError(f"{path}: repeat flag mismatch for {image_id}")
            try:
                result_score = score(rubric, row, key[image_id]["finish"])
                overall = int(row.get("overall", "")); seconds = float(row.get("seconds", ""))
                if overall not in range(1, 6) or seconds < 0:
                    raise ValueError("overall/seconds out of range")
            except (ValueError, TypeError):
                issues.append({"rater":rater,"image_id":image_id,"issue":"incomplete_or_invalid_excluded"}); continue
            result.append({"rater":rater,"image_id":image_id,"score":result_score,"overall":overall,"seconds":seconds,"path":path})
        missing = sorted(set(key) - seen)
        if missing:
            issues.append({"rater":rater,"issue":"missing_images", "count":len(missing), "image_ids":missing})
    if not by_rater or len(hashes) != 1 or "" in hashes or versions != {rubric["version"]}:
        raise ValueError("pack_hash 또는 rubric_version이 없거나 제출 파일 간 일치하지 않습니다")
    if pack_path and sha256(pack_path) != next(iter(hashes)):
        raise ValueError("pack_hash does not match pack.json")
    for rater in by_rater:
        mine = [r for r in result if r['rater'] == rater]
        if mine:
            median = statistics.median(r['seconds'] for r in mine)
            for row in mine:
                if row['seconds'] < median / 3:
                    issues.append({"rater":rater,"image_id":row['image_id'],"issue":"fast_flag_not_excluded","seconds":row['seconds'],"median":median})
    return result, issues, next(iter(hashes))


def aggregate(files, key_path, rubric_path, output_dir, pack_path=None):
    rubric = load_json(rubric_path); key_rows = read_csv(key_path)
    key = {r['random_id']:r for r in key_rows}
    if len(key) != len(key_rows):
        raise ValueError("duplicate random_id in key")
    parsed, issues, pack_hash = parse_ratings(files, key, rubric, pack_path)
    originals = [r for r in parsed if not key[r['image_id']].get('repeat_of')]
    if not originals:
        raise ValueError("완료된 원본 채점이 없습니다")
    groups = defaultdict(list)
    for r in originals: groups[r['image_id']].append(r)
    output = []
    for image_id, rows in sorted(groups.items()):
        meta = key[image_id]; result = {"image_id":image_id,"face_id":meta['face_id'],"split":meta['split'],"kind":meta['kind'],
            "finish":meta['finish'],"mouth":meta['mouth'],"ita":meta.get('ita',''),"ita_bin":meta.get('ita_bin',''),"monk":meta.get('monk',''),
            "rater_count":len(rows),"total_mean":statistics.mean(r['score']['total'] for r in rows if r['score']['total'] is not None),
            "overall_mean":statistics.mean(r['overall'] for r in rows)}
        for i in range(5):
            vals = [r['score']['questions'][i] for r in rows if r['score']['questions'][i] is not None]
            result[f'q{i+1}_mean'] = statistics.mean(vals) if vals else ''
        for check in checks(rubric):
            values = [r['score']['checks'][check['id']] for r in rows]
            counts = Counter(values); most = counts.most_common()
            result[check['id']] = most[0][0] if len(most) == 1 or most[0][1] > most[1][1] else 'tie'
        output.append(result)
    raters = sorted({r['rater'] for r in originals})
    lookup = {(r['image_id'],r['rater']):r for r in originals}
    balanced = [i for i in groups if all((i,r) in lookup for r in raters)]
    matrix = [[lookup[i,r]['score']['total'] for r in raters] for i in balanced]
    icc = icc2(matrix)
    ordinal = krippendorff_alpha([[r['overall'] for r in rows] for rows in groups.values()], ordinal=True)
    alphas = {}
    for check in checks(rubric):
        alphas[check['id']] = krippendorff_alpha([[r['score']['checks'][check['id']] if r['score']['checks'][check['id']] != 'na' else None for r in rows] for rows in groups.values()])
    repeats = []
    for r in parsed:
        original_id = key[r['image_id']].get('repeat_of')
        if not original_id or (original_id,r['rater']) not in lookup:
            continue
        first = lookup[original_id,r['rater']]
        pairs = [(first['score']['checks'][c['id']],r['score']['checks'][c['id']]) for c in checks(rubric)]
        repeats.append({"rater":r['rater'],"original_id":original_id,"repeat_id":r['image_id'],
            "total_abs_difference":abs(first['score']['total']-r['score']['total']),"check_agreement":sum(a==b for a,b in pairs)/len(pairs)})
    ordering = []
    for rater in raters:
        mine = [r for r in originals if r['rater']==rater]
        vals = {kind:[r['score']['total'] for r in mine if key[r['image_id']]['kind']==kind] for kind in ('sticker','render','real')}
        means = {k:statistics.mean(v) if v else None for k,v in vals.items()}
        verdict = means['sticker'] < means['render'] < means['real'] if all(x is not None for x in means.values()) else None
        ordering.append({"rater":rater,"means":means,"expected_order":verdict})
    render = [r for r in output if r['kind']=='render']
    metrics = {}
    for dimension in ('all','finish','mouth','ita_bin','monk'):
        names = ['all'] if dimension=='all' else sorted({str(r[dimension]) or 'unknown' for r in render})
        metrics[dimension] = {}
        for name in names:
            subset = [r for r in render if dimension=='all' or (str(r[dimension]) or 'unknown')==name]
            metrics[dimension][name] = {k:cluster_bootstrap(subset,lambda x, field=k:statistics.mean(float(r[field]) for r in x if r[field]!='') if any(r[field]!='' for r in x) else None) for k in ('total_mean','q1_mean','q2_mean','q3_mean','q4_mean','q5_mean')}
    result_dir = Path(output_dir); result_dir.mkdir(parents=True, exist_ok=True)
    ratings = result_dir / 'ratings.csv'; write_csv(ratings, output)
    summary = {"status":"measured", "source_files":[str(Path(x)) for x in files], "key_path":str(key_path),"rubric_path":str(rubric_path),
        "ratings_path":str(ratings),"pack_hash":pack_hash,"rubric_version":rubric['version'],"issues":issues,"rater_count":len(raters),
        "completed_original_scores":len(originals),"icc_balanced_complete_cases":icc,"overall_ordinal_alpha":ordinal,"checks_nominal_alpha":alphas,
        "repeat_pairs":repeats,"checklist_overall_spearman":spearman([r['score']['total'] for r in originals],[r['overall'] for r in originals]),
        "expected_order_per_rater":ordering,"render_report_only":metrics}
    path = result_dir/'human_summary.json'; path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    return summary


def main():
    p = argparse.ArgumentParser(); p.add_argument('ratings', nargs='+', type=Path)
    p.add_argument('--key',type=Path,default=DATA/'pack/key.csv'); p.add_argument('--rubric',type=Path,default=HERE/'rubric.json')
    p.add_argument('--pack',type=Path,default=DATA/'pack/rating_pack/pack.json'); p.add_argument('--output',type=Path,default=DATA/'results')
    a=p.parse_args(); result=aggregate(a.ratings,a.key,a.rubric,a.output,a.pack); print(json.dumps({"raters":result['rater_count'],"output":str(a.output)},ensure_ascii=False))


if __name__=='__main__': main()
