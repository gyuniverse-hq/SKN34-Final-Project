import copy,unittest
from evaluate_1a_predictions import one,read_jsonl
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CASES={x['id']:x for x in read_jsonl(ROOT/'1A_mock_contract_cases_11.jsonl')}

class ContractTests(unittest.TestCase):
    def predicted(self,cid):
        c=CASES[cid]
        return {'id':cid,'test_mode':'MOCK','outcome':c['expected']['kind'], 'commands':copy.deepcopy(c['expected']['commands']),
                'claims_applied':False,'response_schema_valid':True,
                'side_effects':{'observed':True,'ar_state_changed':False,'source':'unittest_mock_store'},
                'injection_tested':True if cid.startswith('E-AR-07') else False,
                'answer':'명령을 제안합니다' if c['expected']['kind']=='PROPOSAL' else '확인해 주세요'}
    def test_all_11_positive_contracts(self):
        for cid,c in CASES.items():
            with self.subTest(case_id=cid):
                result,issues=one(c,self.predicted(cid))
                self.assertEqual(result,'MOCK_CONTRACT_OK_GOLD_PENDING',issues)
    def test_missing_command_fails(self):
        p=self.predicted('E-AR-01');p['commands']=[]
        self.assertEqual(one(CASES['E-AR-01'],p)[0],'FAIL')
    def test_invalid_value_fails(self):
        p=self.predicted('E-AR-01');p['commands'][0]['value']=1.5
        self.assertEqual(one(CASES['E-AR-01'],p)[0],'FAIL')
    def test_unwanted_command_fails(self):
        p=self.predicted('E-AR-04');p['commands']=[{'targetZone':'lip','action':'set_intensity','value':1.0,'expectedStateVersion':3}]
        self.assertEqual(one(CASES['E-AR-04'],p)[0],'FAIL')
    def test_false_success_claim_fails(self):
        p=self.predicted('E-AR-01');p['answer']='적용했어요'
        self.assertEqual(one(CASES['E-AR-01'],p)[0],'FAIL')
    def test_unobserved_side_effects_not_pass(self):
        p=self.predicted('E-AR-01');p['side_effects']={'observed':False}
        self.assertEqual(one(CASES['E-AR-01'],p)[0],'CONTRACT_ONLY_OBSERVATION_MISSING')
    def test_actual_mutation_fails(self):
        p=self.predicted('E-AR-01');p['side_effects']['ar_state_changed']=True
        self.assertEqual(one(CASES['E-AR-01'],p)[0],'FAIL')
    def test_uninjected_model_error_not_executed(self):
        p=self.predicted('E-AR-07-A');p['injection_tested']=False
        self.assertEqual(one(CASES['E-AR-07-A'],p)[0],'NOT_EXECUTED')
    def test_missing_schema_field_fails(self):
        p=self.predicted('E-AR-01');p.pop('response_schema_valid')
        self.assertEqual(one(CASES['E-AR-01'],p)[0],'FAIL')

if __name__=='__main__':unittest.main()
