"""Transport, isolation and validation tests with mocked answers; no model accuracy claims."""
import copy
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer

from app import handler
from runner import Application
from research_groq import GroqResearch, NoRedirect, ENDPOINT
import research_grounding as grounding
from test_research_reasoning import brief_record, answer

KEY = 'gsk_fake_test_secret_no_real_credentials'


def grounded_answer():
    value = answer()
    known = {r['id']: r['text'] for r in brief_record()['brief']['passages']}
    value['source_excerpt'] = {'source_id': 'article_001', 'quote': known['article_001']}
    value['conditions'] = [
        {'source_id': 'article_003', 'quote': 'Closing is subject to investor approval',
         'outcome_span': 'Closing', 'condition_span': 'investor approval', 'condition_status': 'pending'},
        {'source_id': 'article_003', 'quote': 'the factory still requires a construction permit.',
         'outcome_span': 'the factory', 'condition_span': 'construction permit', 'condition_status': 'pending'}]
    return value


def inputs():
    record = brief_record()
    return grounding.make_input(record['brief'], {'evidence': record['context']['evidence'],
        'input_mode': 'fictional_evaluation', 'announcement_title': record['event']['title']})


def completion(value=None, finish='stop'):
    return {'model': 'openai/gpt-oss-120b', 'id': 'test', 'usage': {'total_tokens': 100},
            'choices': [{'finish_reason': finish, 'message': {'role': 'assistant',
                'content': json.dumps(grounded_answer() if value is None else value),
                'reasoning': 'PRIVATE THOUGHT SHOULD NOT BE SAVED'}}]}


class Response:
    def __init__(self, data): self.data=json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,n): return self.data[:n]


class Opener:
    def __init__(self, data=None, error=None): self.data=data;self.error=error;self.calls=[]
    def open(self, req, timeout):
        self.calls.append(req)
        assert req.full_url==ENDPOINT
        assert req.get_header('Authorization')=='Bearer '+KEY
        assert timeout==90
        if self.error: raise self.error
        return Response(self.data or completion())


def request(client):
    return {'messages': [{'role':'system','content':grounding.PROMPT},{'role':'user','content':json.dumps(inputs())}],
            'response_format': client.response_format(grounding.schema(inputs()), 'test')}


class GroundingTests(unittest.TestCase):
    def test_short_source_names_are_valid_labels_not_explanations(self):
        for name in ('Apple Newsroom', 'Quarterly filing', 'Newsroom', 'Investor relations'):
            with self.subTest(name=name):
                value=grounded_answer();value['next_check']['source_to_check']=name
                result=grounding.validate(value,inputs())
                self.assertEqual(result['next_check']['source_to_check'],name)
                self.assertEqual(result['semantic_review'],'not_independently_verified')

    def test_source_label_fix_preserves_other_rejections(self):
        variants=[]
        for text in ('', ' ', '123', 'N/A', 'Unknown', 'Newsroom...', 'Form 99-Z'):
            value=grounded_answer();value['next_check']['source_to_check']=text;variants.append(value)
        value=grounded_answer();value['next_check']['source_to_check']='Apple Newsroom'
        value['next_check']['source_ids']=['invented'];variants.append(value)
        for field in ('change','limitation','action_reason'):
            value=grounded_answer();value[field]['text']='Too short';variants.append(value)
        value=grounded_answer();value['next_check']['observation']='Too short';variants.append(value)
        for value in variants:
            with self.subTest(value=value),self.assertRaises(grounding.EvidenceError):
                grounding.validate(value,inputs())

    def test_valid_mappings_are_explicitly_unverified(self):
        result=grounding.validate(grounded_answer(),inputs())
        self.assertEqual(result['presentation_status'],'ai_draft')
        self.assertEqual(result['semantic_review'],'not_independently_verified')
        self.assertEqual(result['conditions'][0]['outcome_span'],'Closing')
        self.assertFalse(grounding.entry_context({'checks':[]})['execution_approved'])

    def test_reports_all_errors_without_repair(self):
        draft=grounded_answer();before=copy.deepcopy(draft)
        draft['conditions'][0]['quote']='Closing requires the construction permit.'
        draft['business_effect']['text']='The financing is worth $900 billion.'
        draft['next_check']['source_ids']=['invented']
        with self.assertRaises(grounding.EvidenceError) as e:grounding.validate(draft,inputs())
        self.assertEqual(len(e.exception.issues),3)
        self.assertNotEqual(draft,before)
        self.assertIn('$900 billion',draft['business_effect']['text'])

    def test_duplicate_links_fake_spans_invalid_status_and_extra_fields_fail(self):
        variants=[]
        v=grounded_answer();v['conditions']*=2;variants.append(v)
        v=grounded_answer();v['conditions'][0]['condition_span']='permit';variants.append(v)
        v=grounded_answer();v['conditions'][0]['condition_status']='verified';variants.append(v)
        v=grounded_answer();v['source_excerpt']['quote']='An invented source quotation.';variants.append(v)
        v=grounded_answer();v['change']['source_ids']=['article_001']*2;variants.append(v)
        v=grounded_answer();v['position']=1;variants.append(v)
        for v in variants:
            with self.subTest(v=v),self.assertRaises(grounding.EvidenceError):grounding.validate(v,inputs())

    def test_exact_words_do_not_prove_a_link(self):
        # Deliberately wrong dependency can still copy existing words. Do not certify it.
        v=grounded_answer();v['conditions'][0].update(
            quote=inputs()['evidence'][2]['text'],condition_span='construction permit')
        result=grounding.validate(v,inputs())
        self.assertEqual(result['semantic_review'],'not_independently_verified')
        self.assertEqual(result['presentation_status'],'ai_draft')


class ClientTests(unittest.TestCase):
    def test_one_request_schema_headers_no_reasoning_and_cooldown(self):
        opener=Opener(); clock=[100.0]
        client=GroqResearch(KEY,opener=opener,clock=lambda:clock[0])
        answer=client._request(request(client))
        self.assertEqual(answer,grounded_answer())
        payload=json.loads(opener.calls[0].data)
        self.assertTrue(payload['response_format']['json_schema']['strict'])
        self.assertFalse(payload['include_reasoning'])
        self.assertNotIn(KEY,json.dumps(client.request_settings)+json.dumps(client.snapshot()))
        self.assertNotIn('PRIVATE THOUGHT',str(client.last_response_metadata))
        with self.assertRaisesRegex(ValueError,'60 seconds'):client._request(request(client))
        self.assertEqual(len(opener.calls),1)
        clock[0]+=61;self.assertEqual(client.cooldown_seconds(),0)

    def test_http_errors_never_retry_or_leak_credentials(self):
        for code in (400,401,403,404,429,503):
            err=urllib.error.HTTPError(ENDPOINT,code,'test',{'Retry-After':'120'},io.BytesIO(KEY.encode()))
            opener=Opener(error=err);client=GroqResearch(KEY,opener=opener)
            with self.assertRaises(ValueError) as e:client._request(request(client))
            self.assertNotIn(KEY,str(e.exception));self.assertEqual(len(opener.calls),1)
            if code==429:self.assertGreaterEqual(client.cooldown_seconds(),119)

    def test_truncation_refusal_tool_calls_timeout_and_redirect(self):
        values=[completion(finish='length')]
        for field,val in [('refusal','no'),('tool_calls',[{}]),('content','<think>private</think>')]:
            obj=completion();obj['choices'][0]['message'][field]=val;values.append(obj)
        for value in values:
            client=GroqResearch(KEY,opener=Opener(value))
            with self.assertRaises(ValueError):client._request(request(client))
        client=GroqResearch(KEY,opener=Opener(error=TimeoutError(KEY)))
        with self.assertRaises(ValueError) as e:client._request(request(client))
        self.assertNotIn(KEY,str(e.exception))
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,302,'',{},'https://example.org')


class IntegrationTests(unittest.TestCase):
    def test_saved_brief_uses_groq_without_touching_paper_model_or_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp);paper=Mock();app.model=paper
            original=brief_record();app.reviews.save(original)
            for name in ('v02-agent-RAAPLUSDT.db','run-profile.json'):(Path(tmp)/name).write_bytes(b'unchanged fixture')
            draft=grounded_answer();draft['next_check']['source_to_check']='Quarterly filing'
            opener=Opener(completion(draft))
            with patch('research.GroqResearch',side_effect=lambda key:GroqResearch(key,opener=opener)):
                app.reviews.configure_groq(KEY)
            with patch.object(app,'engine',side_effect=AssertionError('no paper access')),patch('research.collect_article',side_effect=AssertionError('no retrieval')):
                new_id=app.reviews.assess(original['id']);app.reviews.worker.join(3)
            record=app.reviews.get(new_id)
            self.assertEqual(record['status'],'complete',record['error'])
            self.assertEqual(record['interpretation']['presentation_status'],'ai_draft')
            self.assertEqual(app.reviews.get(original['id']),original)
            self.assertIs(app.model,paper);self.assertEqual(paper.mock_calls,[])
            self.assertEqual(len(opener.calls),1)
            self.assertIn('source_excerpt',json.loads(opener.calls[0].data)['response_format']['json_schema']['schema']['properties'])
            self.assertFalse(record['entry_readiness']['execution_approved'])
            self.assertEqual(record['assessment_profile'],grounding.VERSION)
            self.assertNotIn(KEY,json.dumps(record)+json.dumps(app.reviews.snapshot()))
            self.assertNotIn('PRIVATE THOUGHT',json.dumps(record))
            self.assertFalse(app.busy)
            before=len(app.reviews.snapshot()['records'])
            with self.assertRaisesRegex(ValueError,'seconds'):app.reviews.assess(original['id'])
            self.assertEqual(len(app.reviews.snapshot()['records']),before)
            for name in ('v02-agent-RAAPLUSDT.db','run-profile.json'):self.assertEqual((Path(tmp)/name).read_bytes(),b'unchanged fixture')

    def test_failed_new_schema_keeps_source_and_all_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp);original=brief_record();app.reviews.save(original)
            value=grounded_answer();value['source_excerpt']['quote']='Fabricated exact quote.'
            value['change']['source_ids']=['invented']
            app.reviews.groq=GroqResearch(KEY,opener=Opener(completion(value)))
            new_id=app.reviews.assess(original['id']);app.reviews.worker.join(3)
            record=app.reviews.get(new_id)
            self.assertEqual(record['status'],'failed')
            self.assertIsNone(record['interpretation'])
            self.assertEqual(len(record['review_steps'][0]['validation_issues']),2)
            self.assertEqual(record['brief'],original['brief'])
            self.assertFalse(app.busy)

    def test_session_route_requires_token_and_never_returns_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp);server=ThreadingHTTPServer(('127.0.0.1',0),handler(app,'token',0))
            port=server.server_address[1];server.RequestHandlerClass=handler(app,'token',port)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                req=urllib.request.Request(f'http://127.0.0.1:{port}/api/research-groq',data=json.dumps({'key':KEY}).encode(),headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
                self.assertEqual(e.exception.code,403);self.assertIsNone(app.reviews.groq)
                req.add_header('X-Thesis-Token','token')
                with urllib.request.urlopen(req) as response:body=response.read()
                self.assertNotIn(KEY.encode(),body)
                self.assertTrue(app.reviews.snapshot()['connection']['configured'])
                self.assertFalse(app.reviews.snapshot()['connection']['connection_tested'])
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
