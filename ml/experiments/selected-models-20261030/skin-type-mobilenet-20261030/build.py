"""Generate a skin-type trainer based on the earlier MobileNet experiment."""
from pathlib import Path

H=Path(__file__).resolve().parent
s=(H.parent/'mobilenet-skin-bundle-20261030/train.py').read_text(encoding='utf8')
s=s.replace('BASE.parent / "data/manifest.json"','BASE / "data/manifest.json"')
s=s.replace('data=GradeDataset(manifest,TASK,"train",training=True,training_seed=42)','data=TypeDataset(manifest,"train",training=True,training_seed=42)')
s=s.replace('valid=GradeDataset(manifest,TASK,"valid"); test=GradeDataset(manifest,TASK,"test")','valid=TypeDataset(manifest,"valid"); test=TypeDataset(manifest,"test")')
s=s.replace('GradeModel(1, pretrained=', 'GradeModel(CLASSES, pretrained=')
s=s.replace('result.shape != (SETTINGS["batch_size"], 1)','result.shape != (SETTINGS["batch_size"], CLASSES)')
s=s.replace('        p=logits.float().reshape(-1).sigmoid(); y=labels.float()/(self.classes-1)\n        loss=torch.nn.functional.huber_loss(p,y,delta=.2,reduction="none");w=self.weights[labels.long()]\n        return (loss*w).sum()/w.sum()','        return torch.nn.functional.cross_entropy(logits.float(),labels.long(),weight=self.weights)')
s=s.replace('scores.extend(((CLASSES-1)*torch.sigmoid(model(images.to(device,non_blocking=True)).float().reshape(-1))).cpu().tolist());truth.extend(labels.tolist())','scores.extend(torch.softmax(model(images.to(device,non_blocking=True)).float(),dim=1).cpu().tolist());truth.extend(labels.tolist())')
s=s.replace('"score": float(score),','"probabilities": score,')
s=s.replace('int(np.clip(np.floor(score + 0.5), 0, CLASSES-1))','int(np.argmax(score))')
s=s.replace('metrics["mse"]','metrics["cross_entropy"]').replace('"valid_mse"','"valid_cross_entropy"').replace('"best_validation_mse"','"best_validation_cross_entropy"')
s=s.replace('            "valid_within_one": metrics["within_one"],\n','')
s=s.replace('    parser.add_argument("--task", choices=["pigmentation","wrinkle"], required=True)','')
s=s.replace('    TASK=args.task; CLASSES=7 if TASK=="wrinkle" else 6; BASE=BASE / TASK','    TASK="skin_type"; CLASSES=3')
s=s.replace('"schema": "skin-mobile-grade-regression-v1"','"schema": "skin-type-softmax-v1"')
start=s.index('def summary_metrics(truth,scores):');end=s.index('\ndef main():',start)
s=s[:start]+'''def summary_metrics(truth,scores):
    from server.nia.metrics import classification
    y=np.asarray(truth,dtype=np.int64);p=np.asarray(scores,dtype=np.float64)
    if p.shape!=(len(y),CLASSES) or not np.isfinite(p).all():raise ValueError("Invalid probabilities")
    result=classification(y.tolist(),p.argmax(axis=1).tolist(),CLASSES)
    result["cross_entropy"]=float(-np.log(np.clip(p[np.arange(len(y)),y],1e-12,1)).mean())
    return result
''' +s[end:]
insert='''\nclass TypeDataset(GradeDataset):
    def __init__(self,manifest,split,training=False,training_seed=None):
        super().__init__(manifest,"skin_type",split,training=training,training_seed=training_seed)
\n'''
pos=s.index('\nclass TaskLoss(');s=s[:pos]+insert+s[pos:]
(H/'train.py').write_text(s,encoding='utf8')
