import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/g8/parent'
prior = json.loads((OUT/'stage6-remediation-final-sources.json').read_text(encoding='utf-8'))
paths = {x['path'] for x in prior}
paths.update(['lib/api.ts', 'hooks/useChatConversations.ts', 'app/chat.tsx', 'metro.config.js', 'package.json'])
result = {'at': datetime.now(timezone.utc).isoformat(), 'head': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(), 'branch': subprocess.check_output(['git','branch','--show-current'],text=True).strip(), 'source': [{'path': p, 'sha256': hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in sorted(paths)], 'scope': 'Investigation only; new stage6-investigation-* evidence; no product/config edits, merge or PR', 'flagsScope': 'G8 entry/follow-up/persisted-context paths and G1/G5/G7 intersections, not exhaustive G1-G7 audit'}
(OUT/'stage6-investigation-baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('Baseline', result['head'], len(result['source']), 'source hashes')
