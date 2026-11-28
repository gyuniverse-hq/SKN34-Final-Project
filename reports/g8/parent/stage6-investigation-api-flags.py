"""Current Catalog G5 authorization dependency; synthetic token, no HTTP/DB/model."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend/api'))
from app.core.config import get_settings
from app.core.errors import ApiError
from app.routers.rag import authorized

rows = []
for enabled, supplied in [(False, 'synthetic-probe-token'), (True, 'wrong'), (True, 'synthetic-probe-token')]:
    with patch.object(get_settings(), 'g5_enabled', enabled), patch.object(get_settings(), 'g5_internal_token', 'synthetic-probe-token'):
        try:
            authorized(supplied)
            result = 'allowed'
        except ApiError as exc:
            result = exc.code
        rows.append({'enabled': enabled, 'tokenMatches': supplied == 'synthetic-probe-token', 'result': result})
assert [r['result'] for r in rows] == ['g5_disabled', 'g5_forbidden', 'allowed']
(ROOT / 'reports/g8/parent/stage6-investigation-api-flags.json').write_text(json.dumps({'mode': 'actual authorization dependency; synthetic configuration; no HTTP/DB/model', 'results': rows}, indent=2), encoding='utf-8')
print('Catalog G5 dependency: OFF blocked; wrong token blocked; matching token allowed. 3 PASS; external calls 0.')
