import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

HERE=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(HERE))
import db
from aggregate import aggregate_db, pilot_report
from analyze import analyze_db
from bench import compare_runs
from build_pack import require_ita_coverage, LIPS_INNER, LIPS_OUTER, make_plan, assign_splits, SHADES, renderer_version
from common import checks, load_json, read_csv, sha256, write_csv
from judge import MockJudge, run
from metrics import compute
from make_colab_pack import make_pack, export_db

RUBRIC=load_json(HERE/'rubric.json')


def fake_pack(tmp):
    pack=tmp/'pack'; rating=pack/'rating_pack'; (rating/'images').mkdir(parents=True)
    dataset=tmp/'lapa'; (dataset/'images').mkdir(parents=True); (dataset/'labels').mkdir()
    (rating/'rubric.json').write_text(json.dumps(RUBRIC,ensure_ascii=False),encoding='utf8')
    (rating/'pack.json').write_text('{}',encoding='utf8')
    keys=[]; sources={}; hashes={}; renderer={'renderer_commit':'abc','renderer_dirty':False,'tracker_sha256':'t','page_sha256':'p','tuning_json':{},'intensity':.6}
    for i in range(15):
        stem=f'stem{i}'; ident=f'id{i}'; source=dataset/'images'/f'{stem}.jpg'; label=dataset/'labels'/f'{stem}.png'; Image.new('RGB',(8,8),(i,0,0)).save(source); Image.new('L',(8,8)).save(label)
        for suffix in ('full','crop'):
            path=rating/'images'/f'{ident}_{suffix}.png'; Image.new('RGB',(8,8),(i,0,0)).save(path); hashes['rating_pack/images/'+path.name]=sha256(path)
        sources[stem]={'image_sha256':sha256(source),'label_sha256':sha256(label)}
        keys.append({'random_id':ident,'lapa_stem':stem,'face_id':f'face{i}','kind':['render','sticker','real'][i%3],'shade':'red','hex':'#ff0000','finish':'satin','mouth':'closed','ita':'20','ita_bin':'q1','monk':'','yaw':'0','split':'pool' if i<6 else 'test','repeat_of':'','source':'LaPa','source_split':'test','image_sha256':sha256(source),'label_sha256':sha256(label)})
    write_csv(pack/'key.csv',keys)
    manifest={'renderer':renderer,'pack_sha256':sha256(rating/'pack.json'),'rubric_sha256':sha256(rating/'rubric.json'),'sources':sources,'image_files_sha256':hashes}
    (pack/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
    return pack,dataset,keys


def test_db_mock_end_to_end(tmp_path):
    pack,dataset,keys=fake_pack(tmp_path); con=db.connect(tmp_path/'eval.db'); packid=db.import_pack(con,pack)
    assert db.import_pack(con,pack)==packid and con.execute('select count(*) from images').fetchone()[0]==15
    files=[]
    for j in range(5):
        answers=[]
        for i,row in enumerate(keys):
            a={'rater_id':f'R{j+1}','image_id':row['random_id'],'is_repeat':'0','order_index':i+1,'overall':1+i%5,'seconds':30,'note':'','pack_hash':packid,'rubric_version':RUBRIC['version']}
            a.update({c['id']:str(int(k<(i%5+1)*5)) for k,c in enumerate(checks(RUBRIC))});answers.append(a)
        file=tmp_path/f'R{j+1}.csv'; write_csv(file,answers); files.append(file)
        assert db.import_ratings(con,file)==15 and db.import_ratings(con,file)==0
    revised=read_csv(files[0]); revised[0]['overall']='5'; newer=tmp_path/'R1_new.csv'; write_csv(newer,revised)
    import os
    os.utime(newer,ns=(files[0].stat().st_mtime_ns+2_000_000_000,)*2)
    assert db.import_ratings(con,newer)==15
    assert con.execute("select count(*) from human_ratings where rater_id='R1'").fetchone()[0]==15
    assert con.execute("select count(*) from rating_imports where rater_id='R1'").fetchone()[0]==2
    bad=read_csv(files[0]); bad[0]['rubric_version']='lip-rubric-v1'; file=tmp_path/'old.csv';write_csv(file,bad)
    with pytest.raises(ValueError,match='v2'):db.import_ratings(con,file)
    pilot=read_csv(files[0]); [r.update(rater_id='R0') for r in pilot];file=tmp_path/'pilot.csv';write_csv(file,pilot)
    with pytest.raises(ValueError,match='R0'):db.import_ratings(con,file)
    assert pilot_report(file)['estimated_minutes']==27
    for row in pilot: row['seconds']=60
    write_csv(file,pilot); assert len(pilot_report(file)['options'])==2
    aggregate_db(con,tmp_path/'results')
    make_pack(pack,tmp_path/'results/ratings.csv',dataset,tmp_path/'colab.zip')
    assert (tmp_path/'colab.zip').is_file()
    fake=tmp_path/'mockpack';fake.mkdir(); ratings=read_csv(tmp_path/'results/ratings.csv');write_csv(fake/'ratings.csv',ratings)
    write_csv(fake/'meta.csv',[{'image_id':r['random_id'],'face_id':r['face_id'],'split':r['split'],'kind':r['kind'],'finish':r['finish'],'mouth':r['mouth']} for r in keys])
    vectors={r['random_id']:np.array([1.,i+1]) for i,r in enumerate(keys)}; judgefile=tmp_path/'judge.csv'

    class FailZeroShot(MockJudge):
        def generate(self, text, images, examples, item):
            return 'not json' if not examples else super().generate(text, images, examples, item)
    config=load_json(HERE/'judges.json')
    run(fake,judgefile,config,RUBRIC,FailZeroShot(RUBRIC),vectors,True); db.import_judge(con,judgefile)
    assert con.execute("select count(*) from judge_scores where method='zero_shot' and valid=0").fetchone()[0]==9
    retry=MockJudge(RUBRIC); run(fake,judgefile,config,RUBRIC,retry,vectors,True)
    assert retry.calls==9
    db.import_judge(con,judgefile);db.import_judge(con,judgefile)
    assert con.execute('select count(*) from judge_scores').fetchone()[0]==54
    assert con.execute('select count(*) from judge_scores where valid=0').fetchone()[0]==0
    result=analyze_db(con,tmp_path/'results/summary.json'); assert result['decision']=='판정 불가'
    for run_id,offset in [('old',0),('new',1)]:
        con.execute('insert into runs(run_id,kind,started_at) values(?,?,?)',(run_id,'bench','2026'))
        for i,row in enumerate(keys[:4]): con.execute('insert into code_metrics values(?,?,?,?,?)',(row['random_id'],'lum_spread',i+offset,'v2',run_id))
    comp=compare_runs(con,'old','new');assert comp['lum_spread']['delta_new_minus_old']['estimate']==pytest.approx(1)
    con.execute("update images set source='other' where image_id=?",(keys[0]['random_id'],))
    with pytest.raises(ValueError,match='LaPa'): export_db(con,tmp_path/'bad.zip')
    con.close()


def test_missing_ita():
    with pytest.raises(ValueError,match='q4'):require_ita_coverage([{'human_label':'bare','identity_reviewed':'yes','detected':'1','ita_bin':f'q{i}'} for i in (1,2,3)])


def test_v2_pack_plan_is_balanced_and_reproducible():
    rows=[{'face_id':str(i),'human_label':'bare' if i<19 else 'lipstick','ita_bin':'q'+str(i%4+1)} for i in range(25)]
    splits=assign_splits(rows,42); bare,real,items,_=make_plan(rows,splits,42,6)
    assert len(items)==50 and sum(kind=='render' for _,kind,_ in items)==38 and sum(kind=='sticker' for _,kind,_ in items)==6 and sum(kind=='real' for _,kind,_ in items)==6
    for row in bare:
        shades=[shade for r,kind,shade in items if r==row and kind=='render']
        assert len(shades)==2 and SHADES[shades[0]]['texture']!=SHADES[shades[1]]['texture']
    assert all(any(kind==k and splits[r['face_id']]==split for r,kind,shade in items) for k in ('render','sticker','real') for split in ('pool','test'))
    assert [(r['face_id'],k,s) for r,k,s in items]==[(r['face_id'],k,s) for r,k,s in make_plan(rows,splits,42,6)[2]]


def test_renderer_version_records_dirty(monkeypatch,tmp_path,capsys):
    (tmp_path/'page.html').write_text('example',encoding='utf8')
    monkeypatch.setattr('build_pack.subprocess.check_output',lambda args,**kw:' M file\n' if args[1]=='status' else 'abc123\n')
    version=renderer_version(tmp_path)
    assert version['renderer_dirty'] is True and version['renderer_commit']=='abc123'
    assert len(version['tracker_sha256'])==64 and len(version['page_sha256'])==64 and len(version['render_script_sha256'])==4
    assert capsys.readouterr().out


def test_synthetic_texture_metrics():
    import cv2
    page={'x':[0.0]*468,'y':[0.0]*468}; width=200
    for indices,rx,ry in [(LIPS_OUTER,50,24),(LIPS_INNER,15,5)]:
        for j,index in enumerate(indices):
            angle=2*np.pi*j/len(indices); page['x'][index]=width-1-(100+rx*np.cos(angle));page['y'][index]=100+ry*np.sin(angle)
    mask=np.zeros((200,200),np.uint8);cv2.ellipse(mask,(100,100),(50,24),0,0,360,255,-1);cv2.ellipse(mask,(100,100),(15,5),0,0,360,0,-1)
    img=np.full((200,200,3),180,np.uint8);img[mask>0]=[30,50,160]
    flat=compute(img,img,page)
    textured=img.copy(); y,x=np.indices(mask.shape); variation=((np.sin(x*.6)+1)*40).astype(np.uint8)
    for c in range(3): textured[:,:,c]=np.where(mask>0,np.clip(img[:,:,c].astype(int)+variation,0,255),img[:,:,c]).astype(np.uint8)
    details=compute(textured,img,page)
    assert flat['lum_spread']<.1 and flat['hf_std']<.1 and flat['flat_ratio']>.99
    assert details['lum_spread']>flat['lum_spread'] and details['hf_std']>flat['hf_std'] and details['flat_ratio']<flat['flat_ratio']
    blurred=cv2.GaussianBlur(img,(0,0),3)
    smooth=compute(blurred,img,page)
    assert flat['edge_width'] is not None and smooth['edge_width'] is not None and smooth['edge_width']>flat['edge_width']
