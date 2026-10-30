"""Build an auditable real-data-only skin-type inventory; never train."""
import csv,hashlib,json,sys
from collections import Counter
from pathlib import Path
from PIL import Image

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];ML=ROOT/'ml';sys.path[:0]=[str(ROOT),str(ML/'src')]
from skin_analysis.config import digest

DATA=ML/'data/028.한국인 피부상태 측정 데이터/3.개방데이터/1.데이터'
META=DATA/'Other/Other/메타데이터/meta_data.csv'
SOURCE=ML/'runs/pore-unsharp75-contrast40-20261028/manifest/manifest.json'
mapping={'건성':0,'중성':1,'지성':2}
def main():
 m=json.loads(SOURCE.read_text(encoding='utf8'));fingerprint=m.pop('fingerprint')
 if digest(m)!=fingerprint:raise ValueError('source manifest fingerprint mismatch')
 owner={}
 for r in m['records']:
  if r['subject'] in owner and owner[r['subject']]!=r['split']:raise ValueError('subject split overlap')
  owner[r['subject']]=r['split']
 with META.open(encoding='utf-8-sig',newline='') as f:meta=list(csv.DictReader(f))
 result=[];excluded=Counter();seen=set();photo_hashes={}
 for row in meta:
  subject=row['subject_no'].strip().zfill(4); label=row['얼굴피부타입'].strip()
  if subject in seen:raise ValueError('duplicate subject');
  seen.add(subject)
  if subject not in owner:excluded['outside_existing_split']+=1;continue
  if label not in mapping:excluded['label:'+label]+=1;continue
  for angle in ('F','L','R'):
   candidates=[]
   for partition,folder in [('Training','TS'),('Validation','VS')]:
    folderpath=DATA/partition/'01.원천데이터'/folder/'3. 스마트폰'/subject
    candidates.extend(folderpath.glob(f'{subject}_03_{angle}.jpg'))
   if len(candidates)!=1:excluded[f'{angle}_photo_count_{len(candidates)}']+=1;continue
   path=candidates[0];raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
   if sha in photo_hashes and photo_hashes[sha]!=owner[subject]:raise ValueError('identical image across splits')
   photo_hashes[sha]=owner[subject]
   with Image.open(path) as image: width,height=image.size; image.verify()
   result.append({'subject':subject,'split':owner[subject],'label':label,'class_index':mapping[label],'angle':angle,'path':str(path.resolve()),'sha256':sha,'size':[width,height]})
 stats={s:{label:sum(r['split']==s and r['label']==label for r in result) for label in mapping} for s in ['train','valid','test']}
 info={'source_manifest_fingerprint':fingerprint,'meta_sha256':hashlib.sha256(META.read_bytes()).hexdigest(),'mapping':mapping,'selection':'exact label 3 classes only; mixed and extreme dry not mapped','input':'original smartphone F/L/R photos per subject; ROI / face cropping policy pending','split':'existing person split seed42','counts':stats,'excluded':dict(excluded),'records':result}
 info['fingerprint']=digest(info);(HERE/'inventory.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'counts':stats,'excluded':dict(excluded),'images':len(result)},ensure_ascii=False))
if __name__=='__main__':main()
