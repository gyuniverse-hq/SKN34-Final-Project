import json,glob,sys,cv2,numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision
lm=vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(base_options=mpp.BaseOptions(model_asset_path='face_landmarker.task'),running_mode=vision.RunningMode.IMAGE,num_faces=1))
S=sys.argv[1]
def crop_of(fr,p):
    x0,x1=p[[33,263]][:,0].min(),p[[33,263]][:,0].max(); cy=(p[33][1]+p[263][1])/2; w=x1-x0; pad=w*0.18
    a,b=int(x0-pad),int(x1+pad); ya,yb=int(cy-w*0.28),int(cy+w*0.18)
    return fr[max(ya,0):yb,max(a,0):b]
for f in sorted(glob.glob('scan_*.json')):
    d=json.load(open(f)); vid=d['video']; rows=d['rows']; dur=d['n']/d['fps']; id=f[5:-5]
    c=[r for r in rows if r['t']>0.25*dur and abs(r['yaw'])<0.12 and min(r['gR'],r['gL'])>0.22]
    c.sort(key=lambda r:-min(r['wR'],r['wL'])); c=c[:60]
    cap=cv2.VideoCapture(vid); sc=[]
    for r in c:
        cap.set(cv2.CAP_PROP_POS_FRAMES,r['f']); ok,fr=cap.read()
        res=lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(fr,cv2.COLOR_BGR2RGB)))
        if not res.face_landmarks: continue
        p=np.array([[q.x*fr.shape[1],q.y*fr.shape[0]] for q in res.face_landmarks[0]])
        cr=crop_of(fr,p)
        if cr.size==0: continue
        g=cv2.cvtColor(cr,cv2.COLOR_BGR2GRAY); g=cv2.resize(g,(400,int(400*g.shape[0]/g.shape[1])))
        sc.append((cv2.Laplacian(g,cv2.CV_64F).var(),r,cr))
    sc.sort(key=lambda x:-x[0]); pick=[]
    for s,r,cr in sc:
        if all(abs(r['t']-q[1]['t'])>12 for q in pick): pick.append((s,r,cr))
        if len(pick)==3: break
    for s,r,cr in pick:
        cr=cv2.resize(cr,(520,int(520*cr.shape[0]/cr.shape[1])))
        cv2.putText(cr,f"{r['t']:.0f}s",(6,22),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,255,255),2)
        cv2.imwrite(f"{S}/lashref/sh_{id}_{int(r['t'])}.jpg",cr,[cv2.IMWRITE_JPEG_QUALITY,80])
    print(id,[(round(r['t']),round(s)) for s,r,_ in pick])
