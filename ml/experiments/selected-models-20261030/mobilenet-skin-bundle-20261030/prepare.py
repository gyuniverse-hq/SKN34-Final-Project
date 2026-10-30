import hashlib, json, sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]; ML=ROOT/'ml'; sys.path[:0]=[str(ROOT),str(ML/'src')]
from skin_analysis.config import digest
from server.nia.imaging import crop_bounds

SOURCE=ML/'runs/pore-unsharp75-contrast40-20261028/manifest/manifest.json'
DATA=ML/'data/028.한국인 피부상태 측정 데이터/3.개방데이터/1.데이터'
def main():
 m=json.loads(SOURCE.read_text(encoding='utf8')); old=m.pop('fingerprint'); assert digest(m)==old
 records=[r for r in m['records'] if r['task'] in ('pigmentation','wrinkle')]; ids={r['id'].split(':')[0] for r in records}; lookup={}
 for partition, labeldir in (('Training','TL'),('Validation','VL')):
  base=DATA/partition/'02.라벨링데이터'/labeldir/'3. 스마트폰'
  for p in base.glob('*/*.json'):
   j=json.loads(p.read_text(encoding='utf-8-sig')); meta=j['images']; subject=j['info']['id']; part=meta['facepart']; rid=digest([(subject,j['info']['filename']),part])
   if rid in ids:
    if rid in lookup: raise ValueError('duplicate ROI identifier')
    photo=DATA/partition/'01.원천데이터'/('TS' if partition=='Training' else 'VS')/'3. 스마트폰'/subject/j['info']['filename']; lookup[rid]=(photo,meta,j)
 if set(lookup)!=ids: raise ValueError(f'missing source ROI: {len(ids-set(lookup))}')
 grouped={}
 for r in records: grouped.setdefault(r['id'].split(':')[0],[]).append(r)
 out=HERE/'data'; out.mkdir(exist_ok=True); tmp=out/'pixels.tmp.npy'; pix=np.lib.format.open_memmap(tmp,mode='w+',dtype='uint8',shape=(len(grouped),256,256,3))
 photos={}; hashes={}
 for i,(rid,items) in enumerate(grouped.items()):
  path,meta,j=lookup[rid]
  if path not in photos:
   raw=path.read_bytes(); image=cv2.imdecode(np.frombuffer(raw,dtype=np.uint8),cv2.IMREAD_COLOR)
   if image is None: raise ValueError(f'bad image {path}')
   photos[path]=image; hashes[path]=hashlib.sha256(raw).hexdigest()
  image=photos[path]; h,w=image.shape[:2]
  if (w,h)!=(meta['width'],meta['height']) or any(r['image_sha256']!=hashes[path] for r in items): raise ValueError(f'image mismatch {path}')
  x1,y1,x2,y2=crop_bounds(meta['bbox'],w,h,meta['facepart']); crop=cv2.resize(image[y1:y2,x1:x2],(256,256),interpolation=cv2.INTER_LINEAR); ok,encoded=cv2.imencode('.jpg',crop)
  if not ok or any(hashlib.sha256(encoded.tobytes()).hexdigest()!=r['crop_sha256'] for r in items): raise ValueError(f'crop hash mismatch {rid}')
  decoded=cv2.imdecode(encoded,cv2.IMREAD_COLOR); im=Image.fromarray(cv2.cvtColor(decoded,cv2.COLOR_BGR2RGB)); im=ImageEnhance.Contrast(im.filter(ImageFilter.UnsharpMask(radius=1,percent=75,threshold=0))).enhance(1.4);pix[i]=np.asarray(im)
  for r in items: r['cache_index']=i
  if i%250==0: print(f'ROI {i}/{len(grouped)}',flush=True)
  if len(photos)>50: photos.clear();hashes.clear()
 pix.flush();del pix; target=out/'pixels-fixed.npy';tmp.replace(target)
 sha=hashlib.sha256()
 with target.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk)
 m['records']=records;m['root']=str(out.resolve());m['pixel_cache']={'path':target.name,'sha256':sha.hexdigest(),'count':len(grouped),'dtype':'uint8','shape':[256,256,3]};m['fixed_texture_preprocessing_baked']=True;m['source_manifest_fingerprint']=old;m['fingerprint']=digest(m)
 (out/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8');print(f'Prepared {len(records)} records, {len(grouped)} ROI',flush=True)
if __name__=='__main__':main()
