"""Implementation regressions with explicit mocked model outputs, not AI scores."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from agent import LLM
from evaluate import CASES, make_packet
from evidence_brief import build_brief
from research import EVENT_TYPES
from research_reasoning import make_input, schema, validate, entry_context
from runner import Application
from app import handler
from check_reasoning import run_case
import check_reasoning


def answer():
    def claim(text, *refs):
        return {'text': text, 'source_ids': list(refs)}
    return {'change': claim('Vale signed an agreement for convertible financing for a proposed factory.', 'article_001'),
            'business_effect': {'channel': 'financing_or_capital', 'status': 'conditional',
                **claim('The financing could fund construction, but closing requires investor approval and construction requires a permit.', 'article_001', 'article_003')},
            'limitation': claim('The funds have not been established as received, and factory construction remains conditional.', 'article_003'),
            'research_action': 'investigate_further',
            'action_reason': claim('Financing creates a concrete development to follow, with unresolved closing and permitting milestones.', 'article_001', 'article_003'),
            'next_check': {'observation': 'Confirmation of financing completion would resolve the closing uncertainty, while the construction permit must be checked separately.',
                'source_to_check': 'Vale quarterly filing on financing completion and permit progress.', 'source_ids': ['article_003', 'article_004']}}


def brief_record():
    packet = make_packet(CASES[3])
    chosen = {'category': 'capital_or_management', 'primary_source_id': 'article_001', 'supporting_source_ids': ['article_003']}
    brief = build_brief(packet, chosen, EVENT_TYPES)
    return {'id': 'a'*32, 'status': 'complete', 'reviewer_version': 'source-brief-061',
        'started_at': 1000, 'model': 'qwen3:8b', 'model_seconds': 2.0, 'brief': brief,
        'event': {'id': 'fictional-source', 'title': packet['announcement_title'], 'symbol': 'RAAPLUSDT',
                  'published_at': 100, 'observed_at': 200, 'url': 'https://example.invalid/fictional'},
        'context': {'captured_at': 1000, 'evidence': packet['evidence'], 'limitations': ['Fictional test.'],
                    'checks': [{'label': 'Announcement within entry window', 'passed': False, 'detail': 'Saved old event.'}],
                    'quote': None, 'reference': None, 'price_change_bps': None, 'spread_bps': None}}


class AssessmentUnitTests(unittest.TestCase):
    def setUp(self):
        self.record = brief_record()
        self.inputs = make_input(self.record['brief'], make_packet(CASES[3]))

    def test_future_check_is_not_rejected_because_it_has_not_happened(self):
        result = validate(answer(), self.inputs)
        self.assertEqual(result['next_check']['source_ids'], ['article_003', 'article_004'])
        self.assertEqual(result['semantic_review'], 'not_independently_verified')
        self.assertNotIn('trade', result)

    def test_no_required_amount_paraphrase_when_exact_amount_passage_is_present(self):
        self.assertIn('$60 million', self.inputs['evidence'][0]['text'])
        validate(answer(), self.inputs)  # no invented force-mention rule

    def test_unknown_references_extra_fields_and_unsupported_numbers_rejected(self):
        variants = []
        value=answer();value['change']['source_ids']=['invented'];variants.append(value)
        value=answer();value['business_effect']['text']='The financing totals $60 billion.';variants.append(value)
        value=answer();value['limitation']['text']='There is a 95% probability of a permit.';variants.append(value)
        value=answer();value['research_action']='buy';variants.append(value)
        value=answer();value['next_check']['source_ids']=['article_001','article_001'];variants.append(value)
        value=answer();value['position_size']=0.1;variants.append(value)
        value=answer();value['change']['text']='Buy the stock immediately.';variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError): validate(value,self.inputs)

    def test_amount_type_is_not_falsely_claimed_to_be_verified(self):
        value=answer();value['business_effect']['text']='The company reported earnings.'
        result=validate(value,self.inputs)
        # A known source ID cannot prove the semantic claim. Preserve that limitation.
        self.assertEqual(result['semantic_review'],'not_independently_verified')

    def test_injection_is_not_reintroduced_and_source_mismatch_rejected(self):
        packet=make_packet(CASES[7])
        brief=build_brief(packet,{'category':'capital_or_management','primary_source_id':'article_001','supporting_source_ids':[]},EVENT_TYPES)
        inputs=make_input(brief,packet)
        self.assertNotIn('article_005',[row['id'] for row in inputs['evidence']])
        self.assertNotIn('THESIS_OVERRIDE_ACCEPTED',str(inputs))
        before=copy.deepcopy(brief)
        brief['passages'][0]['text']='Changed evidence.'
        with self.assertRaises(ValueError): make_input(brief,packet)
        self.assertEqual(packet['evidence'][0]['text'],before['passages'][0]['text'])

    def test_execution_is_never_approved_by_saved_input_checks(self):
        for checks in ([], [{'passed': True}], [{'passed': False, 'label': 'Stale', 'detail': 'Old'}]):
            outcome=entry_context({'checks':checks,'captured_at':1000})
            self.assertFalse(outcome['execution_approved'])
            self.assertEqual(outcome['status'],'blocked_at_capture' if checks and checks[0]['passed'] is False else 'fresh_checks_required')

    def test_schema_does_not_force_text_to_stop_mid_sentence(self):
        self.assertNotIn('maxLength',str(schema(self.inputs)))


class AssessmentWorkflowTests(unittest.TestCase):
    def test_assessment_http_route_requires_session_token_and_forwards_record_id(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(app,'session-token',0))
            port=server.server_address[1]
            server.RequestHandlerClass=handler(app,'session-token',port)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{port}/api/review-assess',
                    data=json.dumps({'review_id':'a'*32}).encode(),headers={'Content-Type':'application/json'})
                with patch.object(app.reviews,'assess',return_value='b'*32) as call:
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                    self.assertEqual(error.exception.code,403);call.assert_not_called()
                    request.add_header('X-Thesis-Token','session-token')
                    with urllib.request.urlopen(request) as response:body=json.load(response)
                    self.assertEqual(body,{'ok':True,'review_id':'b'*32})
                    call.assert_called_once_with('a'*32)
            finally:
                server.shutdown();server.server_close();thread.join()

    def run_assessment(self, response=None, error=None):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.market=Mock()
            app.model=LLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
            original=brief_record();app.reviews.save(original)
            for symbol in ('RAAPLUSDT','RNVDAUSDT'):
                for kind in ('agent','benchmark'):
                    engine=app.engine(symbol,kind);engine.db.close()
            before={path.name:path.read_bytes() for path in app.root.glob('v02-*.db')}
            with patch.object(LLM,'_request',return_value=response,side_effect=error) as call, patch('research.collect_article') as article, patch.object(app,'engine',side_effect=AssertionError('Research cannot touch paper ledgers')):
                new_id=app.reviews.assess(original['id']);app.reviews.worker.join(3)
            result=app.reviews.get(new_id)
            self.assertNotEqual(new_id,original['id'])
            self.assertEqual(app.reviews.get(original['id']),original)
            self.assertEqual(result['context'],original['context'])
            self.assertEqual(result['brief'],original['brief'])
            self.assertEqual(before,{path.name:path.read_bytes() for path in app.root.glob('v02-*.db')})
            self.assertEqual(app.market.mock_calls,[]);article.assert_not_called()
            self.assertEqual(call.call_count,1)
            self.assertFalse(app.busy);self.assertIsNone(app.reviews.active)
            self.assertTrue(app.cycle_lock.acquire(False));app.cycle_lock.release()
            return result

    def test_one_call_new_saved_record_original_and_paper_ledgers_unchanged(self):
        result=self.run_assessment(answer())
        self.assertEqual(result['status'],'complete',result.get('error'))
        self.assertEqual(result['interpretation']['research_action'],'investigate_further')
        self.assertEqual(result['source_brief_provenance']['model_seconds'],2.0)
        self.assertFalse(result['entry_readiness']['execution_approved'])
        self.assertEqual(result['review_steps'][0]['name'],'interpretation')

    def test_bad_output_keeps_failed_answer_and_original_brief_without_retry(self):
        result=self.run_assessment({'bad':'response'})
        self.assertEqual(result['status'],'failed')
        self.assertIsNone(result['interpretation'])
        self.assertEqual(result['rejected_response']['parsed_json'],{'bad':'response'})
        self.assertEqual(result['failure_stage'],'interpretation')

    def test_timeout_does_not_erase_brief_or_leak_lock(self):
        result=self.run_assessment(error=RuntimeError('Local model timed out.'))
        self.assertEqual(result['status'],'failed')
        self.assertIn('timed out',result['error'])

    def test_incomplete_review_or_busy_application_rejected_before_call(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);source=brief_record();source['status']='failed';app.reviews.save(source)
            with self.assertRaisesRegex(ValueError,'completed'):app.reviews.assess(source['id'])
            source['status']='complete';app.reviews.save(source)
            app.cycle_lock.acquire()
            try:
                with self.assertRaisesRegex(ValueError,'running'):app.reviews.assess(source['id'])
            finally:app.cycle_lock.release()


class LocalCheckTests(unittest.TestCase):
    def test_two_case_mode_keeps_failures_in_denominator_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            def recorded_failure(spec, model):
                return run_case(spec,model,Mock(return_value={'invalid':'response'}))
            with patch.object(check_reasoning,'model_metadata',return_value={'name':'qwen3:8b'}), \
                 patch.object(check_reasoning,'run_case',side_effect=recorded_failure) as call, \
                 contextlib.redirect_stdout(io.StringIO()) as stdout:
                code=check_reasoning.main(['--condition-check','--output-dir',directory])
            self.assertEqual(code,1)
            self.assertEqual(call.call_count,2)
            report=json.loads(next(Path(directory).glob('*/report.json')).read_text())
            self.assertEqual(report['planned_case_ids'],['04','09'])
            self.assertEqual(report['planned_cases'],2)
            self.assertEqual(report['mechanical_completions'],0)
            self.assertEqual(len(report['cases']),2)
            self.assertIn('0/2 completed the format',stdout.getvalue())
            self.assertEqual(len(list(Path(directory).glob('*.zip'))),1)

    def test_opposite_dependency_probe_reaches_model_intact_without_human_rubric(self):
        spec=check_reasoning.PERMIT_FINANCING_CASE
        model=LLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
        record=run_case(spec,model,Mock(return_value={'invalid':'response'}))
        inputs=json.loads(record['request']['messages'][1]['content'])
        self.assertEqual([row['text'] for row in inputs['evidence']],spec['passages'])
        for question in spec['human_review_focus']:
            self.assertNotIn(question,str(record['request']))

    def test_harness_preserves_failure_and_rubric_is_not_sent_to_model(self):
        model=LLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
        request=Mock(return_value={'not':'valid'})
        record=run_case(CASES[3],model,request)
        self.assertEqual(record['status'],'failed')
        self.assertEqual(record['parsed_response'],{'not':'valid'})
        self.assertEqual(request.call_count,1)
        self.assertEqual(record['human_review'],'pending')
        self.assertNotIn(CASES[3]['human_review_focus'][0],str(record['request']))

    def test_harness_uses_product_validation_and_never_claims_semantic_pass(self):
        model=LLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
        record=run_case(CASES[3],model,Mock(return_value=answer()))
        self.assertEqual(record['status'],'structure_and_references_checked',record['error'])
        self.assertEqual(record['human_review'],'pending')
        self.assertEqual(record['interpretation']['semantic_review'],'not_independently_verified')
