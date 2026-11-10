import json
import sys
from pathlib import Path

import numpy as np
import pytest

HERE=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(HERE))
from common import checks, icc2, krippendorff_alpha, load_json, read_csv, score, write_csv
from aggregate import aggregate
from analyze import classify, compare
from build_pack import assign_splits, mirrored_ring
from judge import MockJudge, generate_valid, retrieve, run
from make_colab_pack import make_pack

RUBRIC=load_json(HERE/'rubric.json')


def test_rubric_and_score():
    items=checks(RUBRIC); assert len(items)==25 and len({c['id'] for c in items})==25
    assert {c['id'] for c in items if c['na_allowed']}=={'q3_2','q3_3','q3_4'}
    values={c['id']:1 for c in items}; values.update({f'q3_{i}':'na' for i in (2,3,4)})
    assert score(RUBRIC,values,'matte')['total']==5
    with pytest.raises(ValueError): score(RUBRIC,values,'glossy')
    modified=json.loads(json.dumps(RUBRIC)); modified['questions'][2]['checks']=[dict(c,na_allowed=True) for c in modified['questions'][2]['checks']]
    values.update({'q3_1':'na','q3_5':'na'}); assert score(modified,values,'matte')['questions'][2] is None
    assert 0 <= score(modified,values,'matte')['total'] <= 5


def test_identity_split_and_mirror():
    rows=[{'face_id':str(i),'human_label':'bare' if i<24 else 'lipstick','ita_bin':str(i%3)} for i in range(36)]
    split=assign_splits(rows,42); assert split==assign_splits(rows,42)
    assert set(split.values())=={'test','pool'}
    assert np.allclose(mirrored_ring({'x':[2,7],'y':[3,4]},[0,1],10),[[7,3],[2,4]])


def test_known_agreements():
    assert icc2([[1,1],[2,2],[3,3]])['icc_2_1']==pytest.approx(1)
    assert krippendorff_alpha([[0,0],[1,1]])==pytest.approx(1)
    assert krippendorff_alpha([[1,1],[2,2],[3,3]],ordinal=True)==pytest.approx(1)
    assert krippendorff_alpha([[0,1],[0,1]]) < 0


def test_blind_html():
    html=(HERE/'rating/index.html').read_text(encoding='utf8')
    assert all(word not in html for word in ('lapa_stem','shade','kind'))
    assert 'https://' not in html and 'http://' not in html


def test_mock_retrieval_retry():
    pool=[{'image_id':str(i),'face_id':str(i)} for i in range(4)]
    query={'image_id':'q','face_id':'0','finish':'matte','mouth':'closed'}
    embeddings={str(i):np.array([1.0,i+1]) for i in range(4)}; embeddings['q']=np.array([1.,1.])
    assert len(retrieve(query,pool,embeddings,3))==3 and all(x['face_id']!='0' for x in retrieve(query,pool,embeddings,3))
    class Retry(MockJudge):
        def generate(self,*a):
            if not self.calls: self.calls+=1; return 'invalid'
            return super().generate(*a)
    result,attempts,error=generate_valid(Retry(RUBRIC),RUBRIC,query,[],[],2)
    assert result['total']==5 and attempts==2 and error==''


def test_decisions():
    assert classify(.8,.5,.7,[.5,.9],[.1,.5],True)=='대체 가능'
    assert classify(.6,.5,.7,[.1,.8],[-.1,.3],True)=='보조만'
    assert classify(.2,.3,.7,[-.1,.5],[-.3,.1],False)=='쓰지 않음'
    assert classify(None,.3,.7,None,None,False)=='판정 불가'


def test_non_lapa_rejected(tmp_path):
    p=tmp_path/'pack'; (p/'rating_pack').mkdir(parents=True)
    (p/'rating_pack/pack.json').write_text('{}'); (p/'manifest.json').write_text(json.dumps({'pack_sha256':__import__('hashlib').sha256(b'{}').hexdigest()}))
    write_csv(p/'key.csv',[{'random_id':'a','repeat_of':'','lapa_stem':'a','source':'other','source_split':'test','face_id':'1','split':'test','kind':'real','finish':'satin','mouth':'closed'}])
    write_csv(tmp_path/'ratings.csv',[{'image_id':'a','face_id':'1','split':'test','kind':'real','finish':'satin','mouth':'closed'}])
    with pytest.raises(ValueError,match='LaPa'): make_pack(p,tmp_path/'ratings.csv',tmp_path,tmp_path/'out.zip')


def test_end_to_end_mock(tmp_path):
    # Fully synthetic metadata and ratings only: no real faces or face images.
    rows=[]
    for i in range(15):
        rows.append({'random_id':f'i{i}', 'face_id':f'f{i}', 'split':'pool' if i<6 else 'test', 'kind':['sticker','render','real'][i%3], 'finish':'satin','mouth':'closed','ita':'30','ita_bin':'mid','monk':'','repeat_of':''})
    key=tmp_path/'key.csv'; write_csv(key,rows); raters=[]
    for j in range(3):
        answers=[]
        for i,row in enumerate(rows):
            a={'rater_id':f'R{j+1}','image_id':row['random_id'],'is_repeat':'0','overall':str(1+i%5),'seconds':'20','pack_hash':'mockhash','rubric_version':RUBRIC['version']}
            a.update({c['id']:str(int(k<(i%5+1)*5)) for k,c in enumerate(checks(RUBRIC))}); answers.append(a)
        file=tmp_path/f'r{j}.csv'; write_csv(file,answers); raters.append(file)
    aggregate(raters,key,HERE/'rubric.json',tmp_path/'results')
    pack=tmp_path/'mockpack'; pack.mkdir(); ratings=read_csv(tmp_path/'results/ratings.csv')
    write_csv(pack/'ratings.csv',ratings); write_csv(pack/'meta.csv',[{'image_id':r['random_id'],'face_id':r['face_id'],'split':r['split'],'kind':r['kind'],'finish':r['finish'],'mouth':r['mouth']} for r in rows])
    config=load_json(HERE/'judges.json'); vectors={r['random_id']:np.array([1.,i+1]) for i,r in enumerate(rows)}
    target=tmp_path/'judges.csv'; adapter=MockJudge(RUBRIC); run(pack,target,config,RUBRIC,adapter,vectors,True); calls=adapter.calls
    run(pack,target,config,RUBRIC,adapter,vectors,True); assert adapter.calls==calls
    report=compare(tmp_path/'results/ratings.csv',key,HERE/'rubric.json',target,raters,tmp_path/'summary.json')
    assert report['decision']=='판정 불가' and len(read_csv(target))==9*6


def test_rating_page_file_url(tmp_path):
    from PIL import Image
    from playwright.sync_api import sync_playwright
    import shutil
    folder=tmp_path/'rating_pack'; images=folder/'images'; images.mkdir(parents=True)
    shutil.copyfile(HERE/'rating/index.html',folder/'index.html'); shutil.copyfile(HERE/'rubric.json',folder/'rubric.json')
    (folder/'guide.json').write_text('{}',encoding='utf8'); items=[]
    for i in range(20):
        ident=f'{i:032x}'; items.append({'id':ident,'finish':'satin','mouth':'closed','is_repeat':False})
        for suffix in ('full','crop'): Image.new('RGB',(8,8),(i,0,0)).save(images/f'{ident}_{suffix}.png')
    duplicate='f'*32
    for suffix in ('full','crop'): shutil.copyfile(images/f'{0:032x}_{suffix}.png',images/f'{duplicate}_{suffix}.png')
    items.append({'id':duplicate,'finish':'satin','mouth':'closed','is_repeat':True})
    (folder/'pack.json').write_text(json.dumps({'items':items}),encoding='utf8')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(); errors=[]; page.on('pageerror',lambda e:errors.append(str(e))); page.goto((folder/'index.html').as_uri())
        page.locator('#rater').fill('R1'); page.locator('#folder').set_input_files(str(folder)); page.locator('#begin').click()
        page.wait_for_selector('#app:not([hidden])'); assert '연습' in page.locator('#progressLabel').inner_text()
        state=page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('lip-rubric:'))))")
        assert abs(state['mainOrder'].index(f'{0:032x}')-state['mainOrder'].index(duplicate))>=16
        page.locator('#items .line').first.get_by_text('통과',exact=True).click()
        assert page.locator('#items .line').first.get_by_text('통과',exact=True).get_attribute('aria-pressed')=='true'
        assert not errors; browser.close()
