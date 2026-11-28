import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend/chatbot'))
from app.clients.catalog_client import CatalogClient
from app.schemas.catalog import OptionSearchRequest
async def main():
 r={'mode':'actual Catalog HTTP','cases':[]}
 for category in ['lip','base']:
  try:
   v=await CatalogClient('http://127.0.0.1:19834').search_options(OptionSearchRequest(category=category,max_price_krw=20000))
   r['cases'].append({'category':category,'status':v.status,'items':len(v.items),'products':len(v.products),'checkedAt':str(v.checked_at),'scope':v.checked_scope.model_dump(mode='json',by_alias=True)})
  except Exception as e:
   r['cases'].append({'category':category,'error':type(e).__name__,'cause':str(e.__cause__)})
 (ROOT/'reports/g8/parent/completion-restore-catalog-probe.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(r,ensure_ascii=True))
asyncio.run(main())
