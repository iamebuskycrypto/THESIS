"""Source copying tests; these do not measure real-model accuracy."""
import copy
import tempfile
import unittest
from unittest.mock import patch, Mock
from agent import LLM
from evidence_brief import build_brief, BRIEF_PROMPT
from evaluate import CASES, make_packet, new_record, run_case, render_html
import research
import review_steps
from runner import Application
from test_review_steps import record, selection


class SourceBriefTests(unittest.TestCase):
    def test_conditions_and_amounts_retained_even_when_not_highlighted(self):
        for spec in CASES:
            packet=make_packet(spec);before=copy.deepcopy(packet)
            chosen={'category':spec['expected_categories'][0], 'primary_source_id':'article_001', 'supporting_source_ids':[]}
            brief=build_brief(packet,chosen,research.EVENT_TYPES)
            eligible=review_steps.selection_input(packet,research.EVENT_TYPES)['evidence']
            self.assertEqual({x['id']:x['text'] for x in brief['passages']},{x['id']:x['text'] for x in eligible})
            self.assertEqual(packet,before)
            self.assertEqual(brief['highlight_ids'],['article_001'])
            self.assertEqual(brief['priced_in_status'],'not_determined')
            self.assertNotIn('business_impact',brief)
            if spec['id'] in ('04','08'):
                self.assertIn('article_001',brief['amount_source_ids'])
                for row in eligible:
                    self.assertIn(row['text'],[x['text'] for x in brief['passages']])
            if spec['id']=='08':
                self.assertNotIn('article_005',[x['id'] for x in brief['passages']])
                self.assertIn('article_005',[x['id'] for x in brief['excluded_passages']])

    def test_selector_cannot_inject_claim_text_or_select_quarantined_passages(self):
        packet=make_packet(CASES[7])
        selected={'category':'capital_or_management','primary_source_id':'article_001','supporting_source_ids':[]}
        for bad in ({**selected,'business_impact':'Funding is secured.'}, {**selected,'primary_source_id':'article_005'}):
            with self.assertRaises(ValueError):build_brief(packet,bad,research.EVENT_TYPES)

    def test_brief_recheck_preserves_context_and_both_records(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.market=Mock()
            app.model=LLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
            old=record();app.reviews.save(old)
            with patch.object(LLM,'_request',return_value=selection()),patch('research.collect_article') as fetch:
                first_id=app.reviews.recheck(old['id']);app.reviews.worker.join(3)
                first=app.reviews.get(first_id)
                second_id=app.reviews.recheck(first_id);app.reviews.worker.join(3)
            second=app.reviews.get(second_id)
            self.assertEqual(second['status'],'complete',second.get('error'))
            self.assertEqual(first,app.reviews.get(first_id))
            self.assertEqual(second['comparison_baseline']['brief'],first['brief'])
            self.assertEqual(second['context'],old['context'])
            self.assertEqual(app.market.mock_calls,[]);fetch.assert_not_called()

    def test_evaluator_uses_product_prompt_and_assembly(self):
        result=new_record(CASES[3])
        chosen={'category':'capital_or_management','primary_source_id':'article_001','supporting_source_ids':[]}
        model=research.ReviewLLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
        requests=[]
        def fake(model,payload,step):
            requests.append(payload)
            return chosen
        run_case(result,research,review_steps,model,lambda:None,request_fn=fake)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]['messages'][0]['content'],BRIEF_PROMPT)
        self.assertEqual(result['brief'],build_brief(result['packet'],chosen,research.EVENT_TYPES))
        self.assertTrue(all(x['passed'] for x in result['checks']))
        html=render_html({'cases':[result],'status':'finished','reviewer_version':research.REVIEWER_VERSION,'run_id':'unit-test'})
        self.assertIn('cannot be compared',html)
        self.assertNotIn('all three stages',html)
