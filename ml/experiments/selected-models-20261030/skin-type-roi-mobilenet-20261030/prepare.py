import json,sys
from pathlib import Path
from collections import Counter
H=Path(__file__).resolve().parent;ML=H.parents[1];sys.path.insert(0,str(ML/'src'))
from skin_analysis.config import digest
from skin_analysis.smartphone.common import assert_disjoint,file_hash
def read(p):return json.loads(p.read_text(encoding='utf8'))
def main():
 inv=read(ML/'runs/skin-type-mobilenet-20261030/inventory.json');fp=inv.pop('fingerprint');assert digest(inv)==fp
 base=read(ML/'runs/mobilenet-skin-bundle-20261030/data/manifest.json');bf=base.pop('fingerprint');assert digest(base)==bf
 if file_hash(Path(base['root'])/base['pixel_cache']['path'])!=base['pixel_cache']['sha256']:raise ValueError('Pixel cache hash mismatch')
 subjects={}
 for x in inv['records']:
  pair=(x['split'],x['class_index']);prior=subjects.setdefault(x['subject'],pair)
  if prior!=pair:raise ValueError('Subject labels/splits disagree')
 rows=[]
 for r in base['records']:
  if r['task']!='pigmentation' or r['facepart'] not in (1,5,6) or r['subject'] not in subjects:continue
  split,label=subjects[r['subject']]
  if r['split']!=split:raise ValueError('Split mismatch')
  row={**r,'task':'skin_type','truth':label};rows.append(row)
 assert_disjoint(rows)
 m={'schema':'skin-type-roi-v1','root':base['root'],'pixel_cache':base['pixel_cache'],'records':rows,'source_inventory':fp,'source_roi':bf,'classes':['건성','중성','지성'],'preprocessing':'existing 256x256 forehead and left/right cheek ROI, unsharp75%, contrast1.4, imagenet norm'};m['fingerprint']=digest(m)
 d=H/'data';d.mkdir(exist_ok=True);(d/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8')
 for split in ('train','valid','test'):
  xs=[x for x in rows if x['split']==split];print(split,'roi',len(xs),'subjects',len({x['subject'] for x in xs}),'classes',dict(Counter(x['truth'] for x in xs)),'areas',dict(Counter(x['facepart'] for x in xs)))
if __name__=='__main__':main()
