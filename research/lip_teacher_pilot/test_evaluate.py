import unittest
from evaluate import COLS, matched, score, spearman, validate, ordering

class PilotTests(unittest.TestCase):
    def test_score_na_and_unknown(self):
        c=dict.fromkeys(COLS,1)
        c.update(q3_2='na',q3_3='na',q3_4='na',q3_5=0)
        self.assertEqual(score(c)['total'],4.5)
        c['q1_1']='unknown'
        self.assertIsNone(score(c)['total'])
    def test_tied_rank_and_constant(self):
        self.assertAlmostEqual(spearman([1,1,3,4],[8,8,6,5]),-1)
        self.assertIsNone(spearman([1,1,1],[1,2,3]))
    def test_matched_comparisons_use_identical_consensus(self):
        # Only R5 is judged: R1/R4 agree0; other pairs disagree.
        row={'raters':{r:{'checks':dict.fromkeys(COLS,v)} for r,v in [('R1',0),('R4',0),('R5',1)]},
             'prediction':{'checks':dict.fromkeys(COLS,0)}}
        result=matched([row])
        self.assertEqual(result['binary_trials'],25)
        self.assertEqual(result['teacher_macro'],1)
        self.assertEqual(result['human_macro'],0)
        row['prediction']['checks']=dict.fromkeys(COLS,'unknown')
        self.assertEqual(matched([row])['teacher_macro'],0)
    def test_strict_order_rejects_ties(self):
        rows=[{'kind':k,'predicted_total':v} for k,v in [('sticker',1),('render',3),('real',5)]]
        self.assertTrue(ordering(rows)['passes'])
        rows[1]['predicted_total']=5
        self.assertFalse(ordering(rows)['passes'])
    def test_validation_no_na_on_glossy_or_bool(self):
        manifest=[{'alias':f'T{i:02d}','finish':'glossy'} for i in range(1,17)]
        p={'rubric_version':'lip-rubric-v2','predictions':[{'alias':r['alias'],'checks':dict.fromkeys(COLS,1),'overall':4,'reason':'visible texture'} for r in manifest]}
        self.assertEqual(len(validate(p,manifest)),16)
        p['predictions'][0]['checks']['q3_2']='na'
        with self.assertRaises(ValueError):validate(p,manifest)
        p['predictions'][0]['checks']['q3_2']=True
        with self.assertRaises(ValueError):validate(p,manifest)
if __name__=='__main__':unittest.main()
