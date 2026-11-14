"""Generate corrected pool-only displays; never overwrite pilot boards or scores."""
from pathlib import Path
import os
from zipfile import ZipFile
from datetime import datetime, timezone
import csv, io, json, hashlib, statistics
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parents[1] / 'data' / 'lip_teacher_20261113'

COLS=[f'q{q}_{i}' for q in range(1,6) for i in range(1,6)]
RATERS=['R1','R4','R5']
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def font(size,bold=False):
    name='segoeuib.ttf' if bold else 'segoeui.ttf'
    return ImageFont.truetype(str(Path('C:/Windows/Fonts')/name),size)
def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
    SOURCE = Path(os.environ["LIP_RUBRIC_SOURCE"])
    original=BASE/'calibration/pool_labels.json'
    labels=json.loads(original.read_text(encoding='utf-8'))
    protected=[original,BASE/'predictions.locked.json',BASE/'protocol.json',*sorted((BASE/'calibration').glob('*.jpg'))]
    before={str(p.relative_to(BASE)):digest(p) for p in protected}
    corrected=[];changes=[]
    for row in labels:
        qmeans=[]
        for q in range(1,6):
            per_rater=[]
            for r in range(3):
                vals=[row['votes'][f'q{q}_{i}'][r] for i in range(1,6)]
                valid=[int(v) for v in vals if v!='na']
                assert valid
                per_rater.append(statistics.mean(valid))
            qmeans.append(statistics.mean(per_rater))
        assert abs(sum(qmeans)-row['total'])<1e-12,(row['alias'],qmeans,row['total'])
        updated={**row,'qmeans':qmeans}
        corrected.append(updated)
        if any(abs(a-b)>1e-12 for a,b in zip(qmeans,row['qmeans'])):
            changes.append({'alias':row['alias'],'original_qmeans':row['qmeans'],'corrected_qmeans':qmeans,'total_unchanged':row['total']})
    target=BASE/'calibration/pool_labels_corrected.json';write(target,corrected)
    raw={}
    for rater in RATERS:
        with (SOURCE/f'{rater}_ratings.csv').open(encoding='utf-8-sig',newline='') as f:
            raw[rater]={r['image_id']:r for r in csv.DictReader(f)}
    boarddir=BASE/'calibration_corrected';boarddir.mkdir(exist_ok=True)
    with ZipFile(SOURCE/'colab_pack.zip') as z:
        metadata=list(csv.DictReader(io.StringIO(z.read('meta.csv').decode('utf-8-sig'))))
        ordered_pool=sorted([r for r in metadata if r['split']=='pool'],key=lambda r:r['image_id'])
        mapped=[]
        for row in corrected:
            signature=tuple(str(v) for c in COLS for v in row['votes'][c])
            # The original scorer board assigned P aliases in sorted image-id order.
            # Verify every raw vote as well; signatures alone can be identical.
            m=ordered_pool[int(row['alias'][1:])-1]
            expected=tuple(raw[w][m['image_id']][c] for c in COLS for w in RATERS)
            assert signature==expected,row['alias']
            assert row['finish']==m['finish'] and row['kind']==m['kind']
            mapped.append((row,m))
        for start in range(0,len(mapped),4):
            batch=mapped[start:start+4]
            board=Image.new('RGB',(1800,1540),(242,243,245));d=ImageDraw.Draw(board)
            d.text((28,12),'CORRECTED POOL CALIBRATION - future use only; not used in completed pilot',font=font(28,True),fill='#1f2937')
            for j,(row,m) in enumerate(batch):
                x=20+(j%2)*890;y=65+(j//2)*730
                d.rounded_rectangle((x,y,x+870,y+710),radius=10,fill='white',outline='#d1d5db',width=2)
                d.text((x+18,y+15),f"{row['alias']}  |  {row['finish']}  |  {row['kind']}  |  Total {row['total']:.2f}/5",font=font(27,True),fill='#111827')
                summary='  '.join(f'Q{q+1} {v:.3f}' for q,v in enumerate(row['qmeans']))
                d.text((x+18,y+59),summary,font=font(23),fill='#374151')
                d.text((x+18,y+95),'Per-rater applicable-check mean, then average across R1/R4/R5',font=font(19),fill='#4b5563')
                for kind,bounds in [('full',(x+18,y+135,360,480)),('crop',(x+405,y+145,440,440))]:
                    im=Image.open(io.BytesIO(z.read(f"images/{m['image_id']}_{kind}.png"))).convert('RGB')
                    px,py,w,h=bounds;im.thumbnail((w,h),Image.Resampling.LANCZOS)
                    board.paste(im,(px+(w-im.width)//2,py+(h-im.height)//2))
                d.text((x+18,y+640),'Original pilot boards and predictions remain unchanged.',font=font(19),fill='#6b7280')
                if row['alias'] in {v['alias'] for v in changes}:
                    d.text((x+18,y+670),'Q3 display corrected after scoring; total was already correct.',font=font(19,True),fill='#92400e')
            board.save(boarddir/f'pool_{start+1:02d}_{min(start+4,len(mapped)):02d}.jpg',quality=93)
        write(boarddir/'manifest.json',[{'alias':r['alias'],'source_image_id':m['image_id'],'split':'pool'} for r,m in mapped])
    after={str(p.relative_to(BASE)):digest(p) for p in protected}
    assert before==after,'Protected pilot artifacts changed'
    record={'corrected_utc':datetime.now(timezone.utc).isoformat(),
      'original_artifact':'calibration/pool_labels.json','original_used_in_this_pilot':True,
      'original_boards_used_in_this_pilot':True,'corrected_artifact':'calibration/pool_labels_corrected.json',
      'corrected_boards':'calibration_corrected','corrected_artifacts_used_in_this_pilot':False,
      'deviation':'Three pool Q3 displays used pooled applicable answers rather than average of individually NA-normalized rater question scores. All displayed totals were already correct.',
      'discovered_after_prediction_lock':True,'action':'Preserve completed pilot. Use corrected displays only for a future independent validation; no test rescoring.',
      'formula':'For each rater: sum yes/no answers / count non-NA answers within each question; then average the3rater question values.',
      'corrected_images':len(corrected),'changed_question_display_images':len(changes),'changes':changes,
      'all34_question_means_sum_to_total':True,'protected_files_unchanged':True,'protected_sha256':before}
    write(BASE/'calibration_correction.json',record)
    print(json.dumps({'corrected_labels':len(corrected),'changed_images':[v['alias'] for v in changes],'boards':len(list(boarddir.glob('*.jpg'))),'protected_unchanged':before==after}))
if __name__=='__main__':main()
