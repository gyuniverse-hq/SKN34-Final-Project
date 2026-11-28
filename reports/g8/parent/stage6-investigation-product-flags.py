"""G1/G8 intersection through real parent and product services; synthetic I/O."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'backend/chatbot'))
from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.schemas.catalog import CatalogIngredients
from app.services.chat_service import ChatService
from tests.conftest import FakeGraph
from tests.test_beauty_consultation import Catalog, PlanLlm
from tests.test_g4_option_search import OptionCatalog
from tests.test_ingredient_consultation import context, evidence

class EntryModel(PlanLlm):
    def __init__(self,operation,**plan):
        super().__init__(**plan);self.operation=operation;self.parent_calls=[]
    async def complete_with_tools(self,messages,tools,*,required_tool=None):
        self.parent_calls.append(required_tool);d=json.loads(messages[-1]['content'])
        args={'planId':d['planId'],'version':d['version'],'action':'continue','additions':[{'capability':'product','productOperation':self.operation,'quote':d['utterance']}]}
        return {'choices':[{'message':{'tool_calls':[{'function':{'name':required_tool,'arguments':json.dumps(args)}}]}}]},0

class IngredientCatalog(Catalog):
    def __init__(self):
        super().__init__();self.ingredient_calls=[]
        for p in self.products:
            p.shades=[p.shades[0].model_copy(update={'id':f'{p.id}-03','name':'03 Rose'})]
    async def get_ingredients(self,pid,shade,**kwargs):
        self.ingredient_calls.append({'product':pid,'shade':shade})
        return CatalogIngredients.model_validate(evidence(pid,shade,name=kwargs.get('ingredient_name') or '향료'))

async def main():
    settings=get_settings();rows=[]
    for g1 in (False,True):
        with patch.object(settings,'g8_enabled',True),patch.object(settings,'g1_supervisor_enabled',g1),patch.object(settings,'g5_enabled',False):
            for kind in ('product','option','ingredient'):
                cat=IngredientCatalog() if kind=='ingredient' else OptionCatalog() if kind=='option' else Catalog()
                quote='이 상품에 향료가 들어 있어?' if kind=='ingredient' else '현재 만원 이하 립 옵션 찾아줘' if kind=='option' else '1만5천 원 이하 립 제품 찾아줘'
                plan={'intent':'detail','scope':'previous','ingredientLookup':True,'ingredientName':'향료'} if kind=='ingredient' else {'intent':'search','category':'lip','maxPriceKRW':10000,'optionSearch':True,'priceBasis':'current_offer'} if kind=='option' else {'intent':'search','category':'lip','maxPriceKRW':15000}
                plan['productRequirement']={'operation':'keep'}
                model=EntryModel('detail' if kind=='ingredient' else 'search',**plan)
                req=ChatRequest(message=quote,locale='ko',request_type='beauty_consultation',chat_context=context() if kind=='ingredient' else None)
                r=await asyncio.wait_for(ChatService(FakeGraph(),model,cat).answer(req),10)
                rows.append({'case':kind,'G1':g1,'G8':True,'parentCalls':model.parent_calls,'specialistModelCalls':model.calls,'optionToolCalls':len(cat.calls) if kind=='option' else 0,'ingredientToolCalls':len(cat.ingredient_calls) if kind=='ingredient' else 0,'products':[p.id for p in r.products],'optionPayload':r.option_search is not None,'ingredientPayload':bool(r.ingredient_results),'answer':r.answer,'summary':r.consultation.model_dump(mode='json',by_alias=True) if r.consultation else None})
                print('Completed',g1,kind,flush=True)
    (ROOT/'reports/g8/parent/stage6-investigation-product-flags.json').write_text(json.dumps({'mode':'real parent/product services; mock model/Catalog; zero paid or network calls','rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':asyncio.run(main())
