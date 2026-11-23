"""Offline/mock or local GPU VLM rubric judging with face-excluded crop retrieval."""
import argparse
import csv
import itertools
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from common import allows_na, checks, cluster_bootstrap, load_json, read_csv, score, sha256, spearman


def retrieve(query, pool, embeddings, k=3):
    candidates=[]; q=np.asarray(embeddings[query['image_id']],dtype=float); qn=np.linalg.norm(q)
    if not qn: raise ValueError('zero target embedding')
    for row in pool:
        if row['face_id']==query['face_id'] or row['image_id']==query['image_id']: continue
        v=np.asarray(embeddings[row['image_id']],dtype=float); denom=qn*np.linalg.norm(v)
        if denom: candidates.append((float(np.dot(q,v)/denom), row['image_id'], row))
    candidates.sort(key=lambda x:(-x[0],x[1]))
    if len(candidates)<k: raise ValueError('not enough eligible pool examples')
    return [x[2] for x in candidates[:k]]


def knn_leave_one_face_out(records, embeddings, k=3, kind='render'):
    """Predict each image's human total as the mean of its k most similar rated images of other faces, over all splits."""
    rows=[r for r in records if r['kind']==kind]
    predictions=[]
    for target in rows:
        neighbors=retrieve(target,rows,embeddings,k)
        predictions.append({'image_id':target['image_id'],'face_id':target['face_id'],'finish':target['finish'],
                            'human_total':float(target['total_mean']),'predicted_total':float(np.mean([float(r['total_mean']) for r in neighbors])),
                            'neighbors':[r['image_id'] for r in neighbors]})
    observations=[{'face_id':p['face_id'],'x':p['human_total'],'y':p['predicted_total']} for p in predictions]
    boot=cluster_bootstrap(observations,lambda rs:spearman([r['x'] for r in rs],[r['y'] for r in rs]))
    mae=float(np.mean([abs(p['human_total']-p['predicted_total']) for p in predictions])) if predictions else None
    return {'kind':kind,'k':k,'n':len(predictions),'spearman':boot['estimate'],'spearman_ci95':boot['ci95'],'mae':mae,'predictions':predictions}


def extract_json(text):
    """Return the first JSON object in a model reply that may wrap it in a code fence or prose."""
    start=text.find('{')
    if start<0: raise ValueError('no JSON object in response')
    obj,_=json.JSONDecoder().raw_decode(text[start:])
    return obj


def parse_response(text, rubric, finish):
    obj=extract_json(text)
    if not isinstance(obj,dict) or set(obj)!= {'checks','overall','reason'} or not isinstance(obj['checks'],dict):
        raise ValueError('invalid JSON object fields')
    expected={c['id'] for c in checks(rubric)}
    if set(obj['checks'])!=expected: raise ValueError('checks do not match rubric')
    for item in checks(rubric):
        value=obj['checks'][item['id']]
        if isinstance(value,bool) or not (type(value) is int and value in (0,1) or value=='na' and allows_na(item,finish)):
            raise ValueError(f"invalid check {item['id']}")
    if type(obj['overall']) is not int or obj['overall'] not in range(1,6): raise ValueError('overall must be integer 1–5')
    if not isinstance(obj['reason'],str) or not obj['reason'].strip() or '\n' in obj['reason']:
        raise ValueError('reason must be one nonempty line')
    calculated=score(rubric,obj['checks'],finish)
    return {**obj,'total':calculated['total'],'questions':calculated['questions']}


def prompt(rubric, item):
    lines=['입술 메이크업이 실제로 바른 것처럼 자연스러운지 평가하세요. 제품색 정확도나 위치 IoU를 판단하지 마세요.',
           f"제형: {item['finish']}; 입 상태: {item['mouth']}",
           '아래 각 항목을 pass=1, fail=0으로 평가하세요. na는 허용된 조건에만 사용하세요.']
    for q in rubric['questions']:
        lines.append(q['title']+' — '+q['hint'])
        for c in q['checks']:
            lines.append(f"{c['id']}: {c['text']}" + (' [na 허용]' if allows_na(c,item['finish']) else ''))
    lines.append(rubric['overall']['question'])
    lines.extend(f"{n}: {text}" for n,text in rubric['overall']['scale'].items())
    lines.append('반드시 JSON 객체만 출력: {"checks":{"q1_1":1,...},"overall":1,"reason":"한 줄"}. 모든 체크 ID가 필요합니다.')
    return '\n'.join(lines)


class MockJudge:
    def __init__(self, rubric): self.rubric=rubric; self.calls=0
    def generate(self, text, images, examples, item):
        self.calls+=1
        return json.dumps({'checks':{c['id']:1 for c in checks(self.rubric)},'overall':4,'reason':'모의 실행'},ensure_ascii=False)


class QwenJudge:
    def __init__(self, config):
        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration
        self.torch=torch; self.config=config; self.processor=AutoProcessor.from_pretrained(config['model_id'],revision=config['revision'])
        quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_compute_dtype=torch.float16) if config['quantization']=='4bit' else None
        self.model=Qwen2_5_VLForConditionalGeneration.from_pretrained(config['model_id'],revision=config['revision'],torch_dtype=torch.float16,
            device_map='auto',quantization_config=quant).eval()
    def generate(self, text, images, examples, item):
        from qwen_vl_utils import process_vision_info
        content=[]
        for ex in examples:
            content.extend([{'type':'text','text':'사례 (사람 평가): '+json.dumps(ex['rating'],ensure_ascii=False)},
                            {'type':'image','image':Path(ex['crop']).resolve().as_uri()}])
        content.extend([{'type':'text','text':'평가 대상 전체 화면:'},{'type':'image','image':Path(images[0]).resolve().as_uri()},
                        {'type':'text','text':'평가 대상 확대:'},{'type':'image','image':Path(images[1]).resolve().as_uri()},
                        {'type':'text','text':text}])
        messages=[{'role':'user','content':content}]; rendered=self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
        image_inputs,video_inputs=process_vision_info(messages)
        inputs=self.processor(text=[rendered],images=image_inputs,videos=video_inputs,padding=True,return_tensors='pt').to('cuda')
        with self.torch.inference_mode(): generated=self.model.generate(**inputs,**self.config['generation'])
        trimmed=[out[len(inp):] for inp,out in zip(inputs.input_ids,generated)]
        return self.processor.batch_decode(trimmed,skip_special_tokens=True,clean_up_tokenization_spaces=False)[0]


def generate_valid(adapter, rubric, item, images, examples, retries):
    error=''; excerpt=''
    for attempt in range(retries+1):
        answer=''
        try:
            answer=adapter.generate(prompt(rubric,item)+(f'\n이전 응답 오류: {error}. JSON만 다시 출력하세요.' if error else ''),images,examples,item)
            return parse_response(answer,rubric,item['finish']),attempt+1,''
        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            error=str(exc); excerpt=' '.join(str(answer).split())[:200]
    return None,retries+1,f'{error} | 응답 앞부분: {excerpt}'


def embed_crops(rows, root, config):
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor
    model=CLIPModel.from_pretrained(config['model_id'],revision=config['revision']).to('cuda').eval()
    processor=CLIPProcessor.from_pretrained(config['model_id'],revision=config['revision'])
    vectors={}
    for row in rows:
        with Image.open(root/'images'/f"{row['image_id']}_crop.png") as image:
            inputs=processor(images=image.convert('RGB'),return_tensors='pt').to('cuda')
        with torch.inference_mode():
            result=model.get_image_features(**inputs)
            if hasattr(result,'pooler_output'): result=result.pooler_output
        vectors[row['image_id']]=result[0].float().cpu().numpy()
    return vectors


FIELDS=['run_id','rubric_version','image_id','face_id','method','repeat','status','checks_json','overall','total','questions_json','reason','neighbors','elapsed_seconds','attempts','error','model_id','model_revision','embedding_model_id','embedding_revision','datetime_utc','gpu','quantization','k']


def run(root, output, config, rubric, adapter, embeddings, mock=False):
    if rubric.get('version') != 'lip-rubric-v2': raise ValueError('v2 rubric required')
    root=Path(root); output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    meta=read_csv(root/'meta.csv'); ratings={r['image_id']:r for r in read_csv(root/'ratings.csv')}
    records=[dict(r,**{k:v for k,v in ratings[r['image_id']].items() if k not in r}) for r in meta if r['image_id'] in ratings]
    pool=[r for r in records if r['split']=='pool' and all(str(r.get(c['id'],'')) in ('0','1','na') for c in checks(rubric))]
    test=[r for r in records if r['split']=='test']; k=int(config['neighbors'])
    if not test: raise ValueError('no evaluated test records')
    provenance=json.dumps({'config':config,'rubric':rubric,'meta_sha256':sha256(root/'meta.csv'),'ratings_sha256':sha256(root/'ratings.csv'),'mock':mock},sort_keys=True,ensure_ascii=False)
    import hashlib
    run_id=hashlib.sha256(provenance.encode()).hexdigest()
    existing=read_csv(output) if output.exists() else []
    if existing and any(r['run_id']!=run_id for r in existing): raise ValueError('output contains a different experiment; use a new path')
    done={(r['image_id'],r['method'],int(r['repeat'])) for r in existing if r['status']=='ok'}
    gpu='mock'
    if not mock:
        import torch
        gpu=torch.cuda.get_device_name(0)
    with output.open('a',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        if not existing: writer.writeheader(); f.flush(); os.fsync(f.fileno())
        for target in test:
            neighbor_rows=retrieve(target,pool,embeddings,k)
            cases=[{'crop':root/'images'/f"{r['image_id']}_crop.png",'rating':{'checks':{c['id']:r[c['id']] for c in checks(rubric)},'total_mean':r['total_mean']}} for r in neighbor_rows]
            permutations=list(itertools.permutations(range(k)))
            if len(permutations)<4: raise ValueError('three distinct repeat orders need k >= 3')
            plans=[('A',0,[]),('B',0,cases)] + [('B',i,[cases[j] for j in permutations[i]]) for i in (1,2,3)] + [('C',0,cases)]
            for method,repeat,examples in plans:
                token=(target['image_id'],method,repeat)
                if token in done: continue
                begin=time.perf_counter(); err=''; attempts=0; result=None
                if method=='C':
                    q=[float(np.mean([float(r[f'q{i}_mean']) for r in neighbor_rows])) for i in range(1,6)]
                    predicted={}
                    for c in checks(rubric):
                        vals=[r[c['id']] for r in neighbor_rows if r[c['id']] in ('0','1')]
                        predicted[c['id']] = int(sum(map(int,vals)) > len(vals)/2) if vals and sum(map(int,vals))*2 != len(vals) else ('na' if not vals and allows_na(c,target['finish']) else None)
                    result={'checks':predicted,'overall':None,'total':float(np.mean([float(r['total_mean']) for r in neighbor_rows])),'questions':q,'reason':'이웃 평균'}
                else:
                    result,attempts,err=generate_valid(adapter,rubric,target,[root/'images'/f"{target['image_id']}_full.png",root/'images'/f"{target['image_id']}_crop.png"],examples,int(config['retry_count']))
                row={'run_id':run_id,'rubric_version':rubric['version'],'image_id':target['image_id'],'face_id':target['face_id'],'method':method,'repeat':repeat,'status':'ok' if result else 'failed',
                    'checks_json':json.dumps(result['checks'],ensure_ascii=False) if result else '', 'overall':result['overall'] if result else '',
                    'total':result['total'] if result else '', 'questions_json':json.dumps(result['questions']) if result else '',
                    'reason':result['reason'] if result else '', 'neighbors':json.dumps([r['image_id'] for r in neighbor_rows] if method!='A' else []),
                    'elapsed_seconds':round(time.perf_counter()-begin,3),'attempts':attempts,'error':err,'model_id':'mock' if mock else config['vlm']['model_id'],
                    'model_revision':'mock' if mock else config['vlm']['revision'],'embedding_model_id':'mock' if mock else config['embedding']['model_id'],
                    'embedding_revision':'mock' if mock else config['embedding']['revision'],'datetime_utc':datetime.now(timezone.utc).isoformat(),
                    'gpu':gpu,'quantization':config['vlm']['quantization'],'k':k}
                writer.writerow(row); f.flush(); os.fsync(f.fileno()); done.add(token)
    return run_id


def main():
    p=argparse.ArgumentParser(); p.add_argument('--pack',required=True,type=Path); p.add_argument('--output',type=Path); p.add_argument('--mock',action='store_true')
    p.add_argument('--knn-output',type=Path,help='leave-one-face-out nearest-k mean over all rendered images (JSON)')
    p.add_argument('--knn-only',action='store_true',help='write --knn-output and skip the VLM')
    a=p.parse_args(); config=load_json(a.pack/'judges.json'); rubric=load_json(a.pack/'rubric.json')
    if a.knn_only and not a.knn_output: p.error('--knn-only requires --knn-output')
    if not a.knn_only and not a.output: p.error('--output is required unless --knn-only')
    needed=['embedding'] if a.knn_only else ['embedding','vlm']
    if not a.mock and not all(config[name].get('revision') for name in needed):
        raise ValueError('모델 카드와 라이선스를 확인한 뒤 judges.json에 사용하는 모델의 정확한 revision을 입력하세요')
    ratings=read_csv(a.pack/'ratings.csv'); meta=read_csv(a.pack/'meta.csv'); ids={r['image_id'] for r in ratings}
    items=[r for r in meta if r['image_id'] in ids]
    if a.mock:
        rng=random.Random(config.get('seed',42)); embeddings={r['image_id']:np.array([rng.random() for _ in range(16)]) for r in items}
    else:
        embeddings=embed_crops(items,a.pack,config['embedding'])
    if a.knn_output:
        by_id={r['image_id']:r for r in ratings}; records=[dict(r,**{k:v for k,v in by_id[r['image_id']].items() if k not in r}) for r in items]
        report=knn_leave_one_face_out(records,embeddings,int(config['neighbors']))
        report['embedding_model_id']='mock' if a.mock else config['embedding']['model_id']
        report['embedding_revision']='mock' if a.mock else config['embedding']['revision']
        a.knn_output.parent.mkdir(parents=True,exist_ok=True); a.knn_output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(f"knn n={report['n']} spearman={report['spearman']} ci95={report['spearman_ci95']} mae={report['mae']}")
        if a.knn_only: return
    adapter=MockJudge(rubric) if a.mock else QwenJudge(config['vlm'])
    print(run(a.pack,a.output,config,rubric,adapter,embeddings,a.mock))


if __name__=='__main__': main()
