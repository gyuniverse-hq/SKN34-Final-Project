"""Private v2 evaluation database. No face data leaves the research data directory."""
import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from common import DATA, HERE, checks, load_json, read_csv, score, sha256

VERSION='lip-rubric-v2'
DB=DATA/'eval.db'


def now(): return datetime.now(timezone.utc).isoformat()


def connect(path=DB):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path); con.row_factory=sqlite3.Row; con.execute('PRAGMA foreign_keys=ON')
    con.executescript((HERE/'schema.sql').read_text(encoding='utf8')); return con


def import_pack(con, pack):
    pack=Path(pack).resolve(); rating=pack/'rating_pack'; manifest=load_json(pack/'manifest.json'); rubric=load_json(rating/'rubric.json')
    if rubric['version']!=VERSION: raise ValueError('v2 rubric required')
    manifest_hash=sha256(pack/'manifest.json'); pack_hash=sha256(rating/'pack.json')
    if pack_hash!=manifest['pack_sha256'] or sha256(rating/'rubric.json')!=manifest['rubric_sha256']: raise ValueError('pack hash mismatch')
    data=read_csv(pack/'key.csv'); seen={}
    for r in data:
        if r['source']!='LaPa' or r['source_split']!='test': raise ValueError('LaPa source required')
        source=manifest.get('sources',{}).get(r['lapa_stem'],{})
        if source.get('image_sha256')!=r['image_sha256'] or source.get('label_sha256')!=r['label_sha256']: raise ValueError('source manifest mismatch')
        if r['face_id'] in seen and seen[r['face_id']]!=r['split']: raise ValueError('identity split leakage')
        seen[r['face_id']]=r['split']
        for suffix in ('full','crop'):
            rel=f"rating_pack/images/{r['random_id']}_{suffix}.png"; path=pack/rel
            if sha256(path)!=manifest['image_files_sha256'][rel]: raise ValueError('image hash mismatch')
    version=manifest['renderer']; pack_id=pack_hash; stamp=now()
    with con:
        con.execute('INSERT OR IGNORE INTO rubric_versions VALUES(?,?,?)',(VERSION,sha256(rating/'rubric.json'),json.dumps(rubric,ensure_ascii=False)))
        old=con.execute('SELECT sha256 FROM rubric_versions WHERE version=?',(VERSION,)).fetchone()
        if old['sha256']!=sha256(rating/'rubric.json'): raise ValueError('version reused with different rubric')
        con.execute('INSERT OR IGNORE INTO packs VALUES(?,?,?,?,?,?)',(pack_id,manifest_hash,pack_hash,VERSION,stamp,str(pack)))
        existing_pack=con.execute('SELECT manifest_sha256,rubric_version FROM packs WHERE pack_id=?',(pack_id,)).fetchone()
        if existing_pack['manifest_sha256']!=manifest_hash or existing_pack['rubric_version']!=VERSION: raise ValueError('pack id reused with different manifest')
        for r in data:
            benchmark_id=hashlib.sha256(json.dumps([r[x] for x in ('lapa_stem','face_id','kind','shade','image_sha256')],ensure_ascii=False).encode()).hexdigest()
            values={'image_id':r['random_id'],'file_sha256':sha256(rating/'images'/f"{r['random_id']}_full.png"),'lapa_stem':r['lapa_stem'],'face_id':r['face_id'],'kind':r['kind'],'shade':r['shade'],'hex':r['hex'],'finish':r['finish'],'mouth':r['mouth'],'ita':r['ita'] or None,'ita_bin':r['ita_bin'],'monk':r['monk'],'yaw':r['yaw'] or None,'split':r['split'],'repeat_of':r['repeat_of'] or None,'benchmark_id':benchmark_id,'renderer_commit':version['renderer_commit'],'renderer_dirty':int(version['renderer_dirty']),'tracker_sha256':version['tracker_sha256'],'page_sha256':version['page_sha256'],'tuning_json':json.dumps(version['tuning_json']),'intensity':version['intensity'],'pack_id':pack_id,'created_at':stamp,'source':r['source'],'source_split':r['source_split'],'source_image_sha256':r['image_sha256'],'label_sha256':r['label_sha256'],'full_path':str(rating/'images'/f"{r['random_id']}_full.png"),'crop_path':str(rating/'images'/f"{r['random_id']}_crop.png")}
            values['render_script_sha256']=json.dumps(version.get('render_script_sha256',{}),sort_keys=True)
            fields=','.join(values); con.execute(f"INSERT OR IGNORE INTO images({fields}) VALUES({','.join('?' for _ in values)})",tuple(values.values()))
            existing=con.execute('SELECT file_sha256,pack_id FROM images WHERE image_id=?',(r['random_id'],)).fetchone()
            if existing['file_sha256']!=values['file_sha256'] or existing['pack_id']!=pack_id: raise ValueError('image id collision')
        con.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',(pack_id,'pack',version['renderer_commit'],int(version['renderer_dirty']),version['tracker_sha256'],version['page_sha256'],json.dumps(version['tuning_json']),None,stamp,'pack import'))
    return pack_id


def import_ratings(con, file):
    file=Path(file); rows=read_csv(file)
    if not rows: raise ValueError('empty CSV')
    if {r.get('rubric_version') for r in rows}!={VERSION}: raise ValueError('v2 rubric required')
    raters={r.get('rater_id','').upper() for r in rows}
    if len(raters)!=1 or not re.fullmatch(r'R\d+',next(iter(raters))): raise ValueError('one anonymous rater required')
    rater=next(iter(raters))
    if rater=='R0': raise ValueError('R0 pilot is excluded from the database')
    digest=sha256(file); existing=con.execute('SELECT 1 FROM rating_imports WHERE source_csv_sha256=?',(digest,)).fetchone()
    if existing:return 0
    mtime=file.stat().st_mtime_ns
    rubric_row=con.execute('SELECT json FROM rubric_versions WHERE version=?',(VERSION,)).fetchone()
    if rubric_row is None: raise ValueError('import pack first')
    rubric=json.loads(rubric_row['json']); prepared=[]; seen=set(); pack_hashes=set()
    for r in rows:
        image=con.execute('SELECT * FROM images WHERE image_id=?',(r['image_id'],)).fetchone()
        if image is None or r['image_id'] in seen: raise ValueError('unknown or duplicate image')
        seen.add(r['image_id']); pack_hashes.add(r.get('pack_hash'))
        if r.get('pack_hash')!=image['pack_id']: raise ValueError('pack hash mismatch')
        if str(r.get('is_repeat','')).lower() not in ({'1','true'} if image['repeat_of'] else {'0','false'}): raise ValueError('repeat mismatch')
        try:
            answer=score(rubric,r,image['finish']); overall=int(r['overall']); seconds=float(r['seconds'])
            if overall not in range(1,6) or not math.isfinite(seconds) or seconds<0: raise ValueError('invalid score')
        except (ValueError,TypeError): continue
        prepared.append((rater,r['image_id'],VERSION,json.dumps(answer['checks']),overall,seconds,r.get('note',''),digest,now(),int(r.get('order_index') or 0)))
    if len(pack_hashes)!=1: raise ValueError('mixed packs')
    if not prepared: raise ValueError('완료된 채점이 없어 기존 제출을 보존합니다')
    pack_id=next(iter(pack_hashes))
    latest=con.execute('SELECT MAX(source_mtime_ns) AS stamp FROM rating_imports WHERE rater_id=? AND pack_id=?',(rater,pack_id)).fetchone()['stamp']
    if latest is not None and mtime<latest: raise ValueError('older resubmission refused')
    with con:
        con.execute('DELETE FROM human_ratings WHERE rater_id=? AND rubric_version=? AND image_id IN (SELECT image_id FROM images WHERE pack_id=?)',(rater,VERSION,pack_id))
        con.executemany('INSERT INTO human_ratings VALUES(?,?,?,?,?,?,?,?,?,?)',prepared)
        con.execute('INSERT INTO rating_imports VALUES(?,?,?,?,?,?,?)',(digest,rater,pack_id,str(file),now(),len(prepared),mtime))
    return len(prepared)


def import_metrics(con, file):
    rows=read_csv(file)
    with con:
        for r in rows:
            con.execute('INSERT OR IGNORE INTO code_metrics VALUES(?,?,?,?,?)',(r['image_id'],r['metric'],float(r['value']) if r['value'] else None,r['metric_version'],r['run_id']))


def import_judge(con, file):
    rows=read_csv(file); methods={'A':'zero_shot','B':'rag','C':'knn_mean','zero_shot':'zero_shot','rag':'rag','knn_mean':'knn_mean'}
    if not rows or {r.get('rubric_version') for r in rows}!={VERSION}: raise ValueError('v2 judge CSV required')
    with con:
        for r in rows:
            meta=con.execute('SELECT pack_id FROM images WHERE image_id=?',(r['image_id'],)).fetchone()
            if not meta: raise ValueError('unknown image')
            rubric=con.execute('SELECT rubric_version FROM packs WHERE pack_id=?',(meta['pack_id'],)).fetchone()
            if not rubric or rubric['rubric_version']!=VERSION: raise ValueError('v2 pack required')
            con.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',(r['run_id'],'judge',None,None,None,None,None,None,now(),json.dumps({'source':str(file),'sha256':sha256(file)})))
            con.execute('INSERT OR IGNORE INTO judge_scores VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(r['run_id'],r['image_id'],methods[r['method']],int(r['repeat']),r['model_id'],r['model_revision'],int(r['k']),r['checks_json'],float(r['overall']) if r['overall'] else None,float(r['total']) if r['total'] else None,r['reason'],float(r['elapsed_seconds']),int(r['status']=='ok'),r['questions_json'],json.dumps(r)))


def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,default=DB); sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init'); sub.add_parser('summary')
    for name in ('import-pack','import-ratings','import-metrics','import-judge'): sub.add_parser(name).add_argument('path',type=Path)
    exp=sub.add_parser('export-colab'); exp.add_argument('--output',type=Path,default=DATA/'colab_pack.zip')
    a=p.parse_args(); con=connect(a.db)
    if a.command=='import-pack': print(import_pack(con,a.path))
    elif a.command=='import-ratings': print(import_ratings(con,a.path))
    elif a.command=='import-metrics': import_metrics(con,a.path)
    elif a.command=='import-judge': import_judge(con,a.path)
    elif a.command=='export-colab':
        from make_colab_pack import export_db
        export_db(con,a.output)
    elif a.command=='summary':
        print(json.dumps({table:con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('packs','images','human_ratings','runs','code_metrics','judge_scores')}))
    con.close()


if __name__=='__main__': main()
