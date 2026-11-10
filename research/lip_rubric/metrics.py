"""Report-only lip metrics.

flat_ratio: fraction within three L* units of the lip median, as analyze_b.
hf_std: standard deviation of L* minus a Gaussian blur, sigma=max(.8,.012*lip_width).
hf_corr_bare: Pearson correlation of the existing lip_texture linear-luminance fine maps.
highlight_area: fraction of the eroded lip with L* local excess above max(5,2*std)
and L* above its 75th percentile. It is a proxy, not ground-truth reflectance.
edge_width: select the larger endpoint contrast of L* or chroma along each outward
normal, normalize its profile to the endpoint values, and take the median 10–90%
transition width divided by lip width;
low-contrast or nonmonotonic transitions without crossings are omitted.
"""
import argparse
import json
import math
import importlib.util
from pathlib import Path

import cv2
import numpy as np

from common import DATA, ROOT
from build_pack import LIPS_INNER, LIPS_OUTER, mirrored_ring

spec=importlib.util.spec_from_file_location('lip_texture_metrics',ROOT/'research/lip_texture/metrics.py')
old_metrics=importlib.util.module_from_spec(spec); spec.loader.exec_module(old_metrics)

METRIC_VERSION='lip-metrics-v2.1'


def edge_width(lab, ring, width):
    chroma=np.hypot(lab[:,:,1],lab[:,:,2]); fields=[lab[:,:,0],chroma]
    center=ring.mean(axis=0); distances=np.linspace(-.2*width,.2*width,81); widths=[]
    for i,point in enumerate(ring):
        tangent=ring[(i+1)%len(ring)]-ring[(i-1)%len(ring)]; normal=np.array([-tangent[1],tangent[0]],float)
        norm=np.linalg.norm(normal)
        if norm<1e-8: continue
        normal/=norm
        if np.dot(normal,point-center)<0: normal=-normal
        coords=point[None,:]+distances[:,None]*normal[None,:]
        xs=coords[:,0].astype(np.float32).reshape(-1,1); ys=coords[:,1].astype(np.float32).reshape(-1,1)
        profiles=[cv2.remap(f.astype(np.float32),xs,ys,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).ravel() for f in fields]
        changes=[abs(float(np.mean(x[-5:])-np.mean(x[:5]))) for x in profiles]; profile=profiles[int(changes[1]>changes[0])]
        start,end=float(np.mean(profile[:5])),float(np.mean(profile[-5:])); delta=end-start
        if abs(delta)<2: continue
        normed=(profile-start)/delta
        lo=np.flatnonzero(normed>=.1); hi=np.flatnonzero(normed>=.9)
        if len(lo) and len(hi) and hi[0]>lo[0]: widths.append(float((distances[hi[0]]-distances[lo[0]])/width))
    return float(np.median(widths)) if widths else None


def compute(image,bare,page):
    h,w=image.shape[:2]; outer=mirrored_ring(page,LIPS_OUTER,w); inner=mirrored_ring(page,LIPS_INNER,w)
    width=float(outer[:,0].max()-outer[:,0].min())
    if width<2: raise ValueError('invalid lip width')
    mask=np.zeros((h,w),np.uint8); cv2.fillPoly(mask,[np.rint(outer).astype(np.int32)],1); cv2.fillPoly(mask,[np.rint(inner).astype(np.int32)],0)
    radius=max(1,round(width*.03)); mask=cv2.erode(mask,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1)))>0
    if mask.sum()<20: raise ValueError('insufficient lip pixels')
    lab=cv2.cvtColor(image.astype(np.float32)/255,cv2.COLOR_BGR2LAB); L=lab[:,:,0]; values=L[mask]; median=float(np.median(values))
    high=L-cv2.GaussianBlur(L,(0,0),max(.8,.012*width)); weight=mask.astype(np.float32); sigma=max(1.5,.06*width)
    local=L-cv2.GaussianBlur(L*weight,(0,0),sigma)/np.maximum(cv2.GaussianBlur(weight,(0,0),sigma),1e-3)
    highlights=mask & (local>max(5,2*float(local[mask].std()))) & (L>np.percentile(values,75))
    corr=None
    if bare is not None:
        a=old_metrics.fine(old_metrics.lum(old_metrics.to_lin(bare)))[mask]; b=old_metrics.fine(old_metrics.lum(old_metrics.to_lin(image)))[mask]
        if np.std(a)>1e-9 and np.std(b)>1e-9: corr=float(np.corrcoef(a,b)[0,1])
    return {'lum_spread':float(np.percentile(values,95)-np.percentile(values,5)), 'flat_ratio':float(np.mean(np.abs(values-median)<3)), 'hf_std':float(high[mask].std()),'hf_corr_bare':corr,'highlight_area':float(highlights.sum()/mask.sum()),'edge_width':edge_width(lab,outer,width)}


def measure_pack(con, pack=DATA/'pack', work=DATA/'render_work'):
    pack=Path(pack); work=Path(work); pack_hash=__import__('common').sha256(pack/'rating_pack/pack.json')
    rows=[dict(r) for r in con.execute('SELECT * FROM images WHERE pack_id=? AND repeat_of IS NULL',(pack_hash,))]
    if not rows: raise ValueError('import pack first')
    with con:
        for row in rows:
            frame=cv2.imread(row['full_path']); bare=cv2.imread(str(work/'renders/rubric'/f"{row['lapa_stem']}__off.png")) if row['kind']!='real' else None
            if frame is None or (row['kind']!='real' and bare is None): raise FileNotFoundError(row['full_path'])
            page=json.loads((work/'faces'/f"{row['lapa_stem']}.page.json").read_text(encoding='utf8'))
            for name,value in compute(frame,bare,page).items():
                con.execute('INSERT OR IGNORE INTO code_metrics VALUES(?,?,?,?,?)',(row['image_id'],name,value,METRIC_VERSION,pack_hash))


def main():
    import db
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,default=db.DB); p.add_argument('--pack',type=Path,default=DATA/'pack'); p.add_argument('--work',type=Path,default=DATA/'render_work'); a=p.parse_args()
    with db.connect(a.db) as con: measure_pack(con,a.pack,a.work)


if __name__=='__main__': main()
