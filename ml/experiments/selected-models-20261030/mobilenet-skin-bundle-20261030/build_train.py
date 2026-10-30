from pathlib import Path

HERE=Path(__file__).resolve().parent
src=HERE.parent/'pore-backbone-original-20261028/train.py'
s=src.read_text(encoding='utf8')
start=s.index('def datasets(sampling):'); end=s.index('\ndef loaders(',start)
replacement='''def datasets(sampling):
    from skin_analysis.config import digest
    from skin_analysis.smartphone.common import assert_disjoint
    manifest = json.loads((BASE.parent / "data/manifest.json").read_text(encoding="utf8"))
    fp=manifest.pop("fingerprint")
    if digest(manifest)!=fp: raise ValueError("Manifest fingerprint mismatch")
    manifest["fingerprint"]=fp
    assert_disjoint(manifest["records"])
    data=GradeDataset(manifest,TASK,"train",training=True,training_seed=42)
    valid=GradeDataset(manifest,TASK,"valid"); test=GradeDataset(manifest,TASK,"test")
    counts=[sum(r["truth"]==g for r in data.records) for g in range(CLASSES)]
    targets=expand_rare_records(data) if sampling=="sqrt_extra" else counts
    return manifest,data,valid,test,counts,targets
'''
s=s[:start]+replacement+s[end:]
s=s.replace('range(6)', 'range(CLASSES)')
s=s.replace('"train_original": 4112', '"train_original": sum(counts)')
s=s.replace('if record["task"] == "pore" and record["split"] == "train"','if record["task"] == TASK and record["split"] == "train"')
s=s.replace('class_weights(labels, 6, None, exponent=SETTINGS["weight_exponent"])','class_weights(labels, CLASSES, None, exponent=SETTINGS["weight_exponent"])')
s=s.replace('WeightedRegressionLoss(weights.to(device), "huber", delta=SETTINGS["huber_delta"])','TaskLoss(weights.to(device), CLASSES)')
s=s.replace('np.clip(np.floor(score + 0.5), 0, 5)','np.clip(np.floor(score + 0.5), 0, CLASSES-1)')
s=s.replace('"schema": "pore-local-backbone-regression-v1"','"schema": "skin-mobile-grade-regression-v1"')
s=s.replace('"model": model_name,\n        "sampling"','"task": TASK,\n        "classes": CLASSES,\n        "model": model_name,\n        "sampling"')
before=s.index('\ndef main():')
s=s[:before]+'''
class TaskLoss(torch.nn.Module):
    def __init__(self,weights,classes):
        super().__init__();self.register_buffer("weights",weights);self.classes=classes
    def forward(self,logits,labels):
        p=logits.float().reshape(-1).sigmoid(); y=labels.float()/(self.classes-1)
        loss=torch.nn.functional.huber_loss(p,y,delta=.2,reduction="none");w=self.weights[labels.long()]
        return (loss*w).sum()/w.sum()

@torch.inference_mode()
def predictions(model,loader,device):
    model.eval();truth=[];scores=[]
    for images,labels,_ in loader:
        scores.extend(((CLASSES-1)*torch.sigmoid(model(images.to(device,non_blocking=True)).float().reshape(-1))).cpu().tolist());truth.extend(labels.tolist())
    return truth,scores

def summary_metrics(truth,scores):
    from server.nia.metrics import classification
    y=np.asarray(truth,dtype=float);p=np.asarray(scores,dtype=float)
    if not len(y) or not np.isfinite(p).all():raise ValueError("Invalid prediction")
    result=classification(list(map(int,truth)),np.clip(np.floor(p+.5),0,CLASSES-1).astype(int).tolist(),CLASSES)
    result.update(mse=float(np.mean((p-y)**2)),rmse=float(np.sqrt(np.mean((p-y)**2))),continuous_mae=float(np.mean(np.abs(p-y))))
    result["micro_f1"]=result["accuracy"]
    result["mean_prediction_by_grade"]=[float(p[y==g].mean()) if np.any(y==g) else None for g in range(CLASSES)]
    return result
''' +s[before:]
s=s.replace('    parser.add_argument("action", choices=["preflight", "train"])','    parser.add_argument("action", choices=["preflight", "train"])\n    parser.add_argument("--task", choices=["pigmentation","wrinkle"], required=True)')
s=s.replace('    os.chdir(ML_ROOT)\n    device', '    global TASK, CLASSES, BASE\n    TASK=args.task; CLASSES=7 if TASK=="wrinkle" else 6; BASE=BASE / TASK\n    os.chdir(ML_ROOT)\n    device')
(HERE/'train.py').write_text(s,encoding='utf8')
