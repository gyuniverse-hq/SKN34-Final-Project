"""Collect CosIng functions from a local PostgreSQL snapshot, with resumable state.

Run from the repository root with COSING_SEARCH_API_KEY set:
  python scripts/data/recommendation/cosing_collect.py --output-dir cosing_full
The script reads the local vishue-postgres-1 container using a read-only SQL
transaction. Re-run the same command to resume the existing snapshot. The
output directory must be new on the first run.
"""
import argparse
import csv
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from cosing_query_compare import ENDPOINT, norm, query_for


BOTANICAL_COMMON_NAME = re.compile(
    r'([A-Za-z][A-Za-z-]+(?:\s+[A-Za-z][A-Za-z-]+){1,3})\s+\(([A-Za-z][A-Za-z -]{2,})\)'
)

CARE_TAGS = {
    '수분': {'SKIN CONDITIONING - EMOLLIENT', 'SKIN CONDITIONING - HUMECTANT',
           'MOISTURISING', 'SKIN CONDITIONING - OCCLUSIVE', 'REFATTING'},
    '유분': {'ANTI-SEBUM', 'ABSORBENT'},
    '민감진정 케어': {'SOOTHING', 'SKIN PROTECTING'},
    '톤잡티 케어': {'EXFOLIATING', 'KERATOLYTIC'},
    '주름 케어': {'UV FILTER', 'SMOOTHING'},
    '트러블 케어': {'KERATOLYTIC', 'EXFOLIATING', 'ANTI-SEBUM'},
    '모공 케어': {'ANTI-SEBUM', 'ASTRINGENT', 'KERATOLYTIC', 'EXFOLIATING'},
}


def normalized_query(name):
    # Only remove parenthetical common names following a multiword botanical
    # name. Never remove punctuation, digits, or arbitrary chemical qualifiers.
    return BOTANICAL_COMMON_NAME.sub(r'\1', name).upper()


def snapshot(container, database, user):
    sql = """BEGIN READ ONLY;
    COPY (SELECT ingredient_id, name_ko, name_en, cas_no_raw
          FROM public.raw_mfds_ingredient WHERE is_current
          ORDER BY ingredient_id) TO STDOUT WITH CSV HEADER;
    ROLLBACK;"""
    proc = subprocess.run(
        ['docker', 'exec', '-i', container, 'psql', '-X', '-q', '-v',
         'ON_ERROR_STOP=1', '-U', user, '-d', database],
        input=sql.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True,
    )
    return list(csv.DictReader(io.StringIO(proc.stdout.decode('utf-8-sig'), newline='')))


def initialize(db, args):
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS ingredients (
        ingredient_id TEXT PRIMARY KEY, name_ko TEXT, input_inci TEXT, mfds_cas TEXT,
        status TEXT NOT NULL, method TEXT, query_name TEXT, http_status INTEGER,
        response_count INTEGER, returned_inci TEXT, cosing_cas TEXT,
        substance_id TEXT, function_names TEXT, detail TEXT, updated_at TEXT)''')
    if db.execute("SELECT 1 FROM metadata WHERE key='snapshot_complete'").fetchone():
        return
    entries = snapshot(args.container, args.database, args.user)
    if not entries:
        raise RuntimeError('Local DB snapshot is empty; no collection started')
    with db:
        for row in entries:
            status = 'pending' if (row['name_en'] or '').strip() else 'missing_english_name'
            db.execute('INSERT INTO ingredients (ingredient_id,name_ko,input_inci,mfds_cas,status) VALUES (?,?,?,?,?)',
                       (row['ingredient_id'], row['name_ko'], row['name_en'], row['cas_no_raw'], status))
        db.execute("INSERT INTO metadata VALUES ('snapshot_complete', ?)",
                   (datetime.now(timezone.utc).isoformat(),))


class StopCollection(Exception):
    pass


def fetch(session, key, name, delay, last_request):
    wait = delay - (time.monotonic() - last_request[0])
    if wait > 0:
        time.sleep(wait)
    last_request[0] = time.monotonic()
    try:
        response = session.post(
            ENDPOINT,
            params={'apiKey': key, 'text': '*', 'pageSize': 100, 'pageNumber': 1},
            files={'query': ('blob', json.dumps(query_for(name, 'terms_inci')), 'application/json')},
            headers={'Accept': 'application/json'}, timeout=30,
        )
    except requests.RequestException as exc:
        raise StopCollection(f'network error: {type(exc).__name__}') from None
    if response.status_code in (401, 403, 429):
        raise StopCollection(f'HTTP {response.status_code}; stopped without retry')
    if response.status_code != 200:
        raise StopCollection(f'HTTP {response.status_code}; pending item preserved')
    try:
        data = response.json()
        hits, total = data['results'], data['totalResults']
        if not isinstance(hits, list) or not isinstance(total, int) or total < 0:
            raise ValueError
        return total, hits
    except (ValueError, KeyError, TypeError):
        raise StopCollection('malformed API response; pending item preserved') from None


def classify(query, total, hits):
    if total == 0 and not hits:
        return 'no_results', None
    if total != len(hits):
        return 'incomplete_response', None
    if total != 1:
        return 'multiple_candidates', None
    try:
        metadata = hits[0]['metadata']
        names = metadata.get('inciName', [])
        sources = metadata.get('esST_DATASOURCE', [])
        ids = metadata.get('substanceId', [])
        functions = metadata.get('functionName', [])
        cas = metadata.get('casNo', [])
        if not all(isinstance(v, list) for v in (names, sources, ids, functions, cas)):
            raise ValueError
        if not all(isinstance(v, str) for v in names + sources + functions + cas):
            raise ValueError
        if not any(norm(name) == norm(query) for name in names):
            return 'name_mismatch', None
        if 'GROWTH_COSING' not in sources:
            return 'wrong_source', None
        if len(ids) != 1 or not str(ids[0]).strip():
            return 'missing_or_multiple_substance_id', None
        return 'accepted' if functions else 'accepted_no_functions', metadata
    except (KeyError, TypeError, ValueError):
        raise StopCollection('malformed metadata; pending item preserved') from None


def collect_one(session, key, row, delay, last_request):
    raw = row['input_inci'].strip().upper()
    alternatives = [('exact', raw)]
    alternate = normalized_query(row['input_inci'].strip())
    if alternate != raw:
        alternatives.append(('normalized', alternate))
    for method, query in alternatives:
        total, hits = fetch(session, key, query, delay, last_request)
        status, metadata = classify(query, total, hits)
        if status == 'no_results' and method == 'exact' and len(alternatives) > 1:
            continue
        payload = {
            'status': status, 'method': method, 'query_name': query, 'http_status': 200,
            'response_count': total, 'returned_inci': '', 'cosing_cas': '',
            'substance_id': '', 'function_names': '', 'detail': '',
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        if metadata is not None:
            payload.update(
                returned_inci=json.dumps(metadata['inciName'], ensure_ascii=False),
                cosing_cas=json.dumps(metadata.get('casNo', []), ensure_ascii=False),
                substance_id=str(metadata['substanceId'][0]),
                function_names=json.dumps(sorted(set(metadata.get('functionName', []))), ensure_ascii=False),
            )
        elif status == 'multiple_candidates':
            payload['detail'] = json.dumps([
                {'inciName': h.get('metadata', {}).get('inciName', []),
                 'substanceId': h.get('metadata', {}).get('substanceId', []),
                 'source': h.get('metadata', {}).get('esST_DATASOURCE', [])}
                for h in hits
            ], ensure_ascii=False)
        return payload
    raise AssertionError('unreachable')


def export(db, output, stop_reason=''):
    rows = db.execute('SELECT * FROM ingredients ORDER BY CAST(ingredient_id AS INTEGER)').fetchall()
    fields = [column[1] for column in db.execute('PRAGMA table_info(ingredients)')]
    with (output / 'cosing_ingredients.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)
    counts = Counter()
    statuses = Counter(row['status'] for row in rows)
    for row in rows:
        if row['status'] == 'accepted':
            counts.update(set(json.loads(row['function_names'])))
    tags_path = output / 'cosing_function_tags.csv'
    care_by_tag = {}
    if tags_path.exists():
        with tags_path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            care_columns = set(CARE_TAGS)
            if fields & care_columns and not care_columns <= fields:
                raise ValueError('Incomplete skin-care columns in existing tag file')
            for row in reader:
                if care_columns <= fields:
                    values = [row[column] for column in CARE_TAGS]
                    if any(value not in ('0', '1') for value in values):
                        raise ValueError('Invalid multi-hot value in existing tag file')
                    care_by_tag[row['functionName']] = values
                elif '피부 케어' in fields:
                    labels = {label.strip() for label in row['피부 케어'].split('|') if label.strip()}
                    if not labels <= care_columns:
                        raise ValueError('Unknown skin-care label in existing tag file')
                    care_by_tag[row['functionName']] = [str(int(column in labels)) for column in CARE_TAGS]
    with tags_path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['functionName', 'ingredient_count', *CARE_TAGS])
        for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            values = care_by_tag.get(tag)
            if values is None:
                values = [str(int(tag in members)) for members in CARE_TAGS.values()]
            writer.writerow([tag, count, *values])
    total = len(rows)
    processed = total - statuses['pending'] - statuses['missing_english_name']
    with_function = statuses['accepted']
    exact = sum(row['status'] in ('accepted', 'accepted_no_functions') and row['method'] == 'exact' for row in rows)
    normalized = sum(row['status'] in ('accepted', 'accepted_no_functions') and row['method'] == 'normalized' for row in rows)
    if not stop_reason and statuses['pending']:
        stop_reason = '중단됨: 대기 중인 성분이 남아 있음'
    lines = ['# CosIng 성분 기능 수집 보고서', '',
             f'- 스냅샷: {total:,}건, 영문명 없음: {statuses["missing_english_name"]:,}건',
             f'- 조회 완료: {processed:,}건, 대기: {statuses["pending"]:,}건',
             f'- 원본명 단일 일치: {exact:,}건, 정규화명 단일 일치: {normalized:,}건',
             f'- 기능 확보: {with_function:,}건 (전체 기준 {with_function / total * 100:.1f}%)',
             f'- 고유 기능 태그: {len(counts):,}개',
             f'- 종료 또는 중단 사유: {stop_reason or "완료"}', '',
             '## 상태별 건수', '']
    lines.extend(f'- {status}: {count:,}' for status, count in sorted(statuses.items()))
    lines += ['', '## 방식과 주의사항', '',
              '식약처 현재 성분 스냅샷을 읽어 원본 영문명으로 검색하고, 검색 결과가 없을 때만 '
              '식물 학명 뒤 괄호 속 일반명을 제거해 재검색했다. GROWTH_COSING 출처의 전체 일치 '
              '단일 후보와 단일 substanceId만 채택했다. 정규화 후보는 원본과 다른 표기이므로 검토가 필요하다. '
              '복수 후보와 미확인 건은 자동 채택하지 않았다. CAS는 원본을 보존하며 동등성 판정에 사용하지 않았다. '
              '빈도는 기능이 있는 성분 행별 중복을 제거해 계산했다.', '',
              '동일 output-dir로 다시 실행하면 기존 스냅샷과 완료 결과를 유지하고 pending부터 이어간다. '
              '401, 403, 429 및 통신·응답 오류는 즉시 중단하고 해당 행을 pending으로 남긴다. '
              '다른 시점의 스냅샷을 수집하려면 새 출력 폴더를 지정한다.', '',
              '## 재현 방법', '',
              '저장소 루트에서 Python requests와 Docker를 사용할 수 있어야 하며 로컬 PostgreSQL 컨테이너가 실행 중이어야 한다. '
              'API 키를 환경변수 COSING_SEARCH_API_KEY에 설정한 뒤 다음 명령을 실행한다.', '',
              '```powershell',
              'python scripts/data/recommendation/cosing_collect.py --output-dir cosing_full_20261107',
              '```', '',
              '기본 컨테이너, DB, 사용자명은 각각 --container, --database, --user로 지정할 수 있다. '
              '요청 간격은 기본 2초이고 --delay로 더 길게 지정할 수 있다. '
              'SQLite 체크포인트가 재시작에 필요하며 CSV와 보고서는 100건마다 갱신된다.', '']
    (output / 'cosing_report.md').write_text('\n'.join(lines), encoding='utf-8')


def export_with_retry(db, output, reason):
    for attempt in range(3):
        try:
            export(db, output, reason)
            return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--container', default='vishue-postgres-1')
    parser.add_argument('--database', default='vishue_db')
    parser.add_argument('--user', default='vishue')
    parser.add_argument('--delay', type=float, default=2.0)
    args = parser.parse_args()
    if args.delay < 2:
        parser.error('delay must be at least 2 seconds')
    key = os.environ.get('COSING_SEARCH_API_KEY', '').strip()
    if not key:
        parser.error('set COSING_SEARCH_API_KEY')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.output_dir / 'cosing_checkpoint.sqlite3')
    db.row_factory = sqlite3.Row
    initialize(db, args)
    session = requests.Session()
    last_request = [0.0]
    reason = ''
    try:
        while True:
            row = db.execute("SELECT * FROM ingredients WHERE status='pending' ORDER BY CAST(ingredient_id AS INTEGER) LIMIT 1").fetchone()
            if row is None:
                break
            result = collect_one(session, key, row, args.delay, last_request)
            with db:
                db.execute('UPDATE ingredients SET ' + ', '.join(f'{field}=?' for field in result) + ' WHERE ingredient_id=?',
                           (*result.values(), row['ingredient_id']))
            processed = db.execute("SELECT count(*) FROM ingredients WHERE status NOT IN ('pending','missing_english_name')").fetchone()[0]
            print(f'{processed}: id={row["ingredient_id"]} {result["method"]} {result["status"]}', flush=True)
            if processed % 100 == 0:
                export_with_retry(db, args.output_dir, '진행 중')
    except (StopCollection, KeyboardInterrupt) as exc:
        reason = str(exc) or '사용자 중단'
        print(reason, file=sys.stderr, flush=True)
    except Exception as exc:
        reason = f'예상치 못한 오류: {type(exc).__name__}'
        print(reason, file=sys.stderr, flush=True)
        raise
    finally:
        export_with_retry(db, args.output_dir, reason)
        db.close()
        session.close()
    return 1 if reason else 0


if __name__ == '__main__':
    raise SystemExit(main())
