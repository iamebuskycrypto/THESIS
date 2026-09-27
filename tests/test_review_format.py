"""Review-only schema transport and diagnostics; no real model outputs claimed."""
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from review_test_helpers import model_responses, assessment_only
from agent import LLM
from research import rejected_output, review_response_format, validate_review
from runner import Application
from test_review_specificity import baseline, expected_shape


def envelope(value):
    return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
        'message': {'content': json.dumps(value)}}]}).encode())


class FormatTests(unittest.TestCase):
    def test_schema_reaches_actual_adapter_and_settings_match_without_changing_paper_model(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            original_settings = copy.deepcopy(app.model.request_settings)
            source = baseline(); app.reviews.save(source)
            with patch('agent.urllib.request.urlopen', side_effect=[envelope(x) for x in model_responses(expected_shape(selected=True))]) as send:
                identifier = app.reviews.recheck(source['id']); app.reviews.worker.join(3)
            result = app.reviews.get(identifier)
            self.assertEqual(result['status'], 'complete', result.get('error'))
            request = json.loads(send.call_args_list[0].args[0].data)
            fmt = request['response_format']
            self.assertEqual(fmt['type'], 'json_schema')
            schema = fmt['json_schema']['schema']
            self.assertEqual(set(schema['required']), {'category','primary_source_id','supporting_source_ids'})
            self.assertFalse(schema['additionalProperties'])
            self.assertNotIn('entry_context', schema['properties']['primary_source_id']['enum'])
            self.assertNotIn('business_impact', schema['properties'])
            self.assertEqual(request['reasoning_effort'], 'none')
            self.assertEqual(request['max_tokens'], 3072)
            self.assertEqual(result['request_settings']['max_tokens'], 3072)
            self.assertEqual(app.model.request_settings['max_tokens'], 1024)
            self.assertEqual(send.call_args.kwargs['timeout'], 180)
            self.assertEqual(result['review_steps'][0]['request_settings']['response_format'], fmt)
            self.assertEqual(app.model.request_settings, original_settings)
            self.assertEqual(app.model.request_settings['response_format'], {'type': 'json_object'})
            self.assertEqual(send.call_count, 1)

    def test_claim_errors_identify_the_field_and_do_not_repair_or_invent_references(self):
        evidence = baseline()['context']['evidence']
        for field in ('business_impact', 'thesis', 'counterargument', 'priced_in_assessment'):
            for bad in ({'text': 'No references'}, {'text': 'Extra key', 'source_ids': ['issuer'], 'label': 'extra'}):
                response = expected_shape(); response[field] = bad
                original = copy.deepcopy(response)
                with self.assertRaisesRegex(ValueError, '^' + field + ': expected an object'):
                    validate_review(response, evidence)
                self.assertEqual(response, original)
        response = expected_shape(); response['supporting_evidence'] = [{'text': 'No references'}]
        with self.assertRaisesRegex(ValueError, r'^supporting_evidence\[0\]'):
            validate_review(response, evidence)

    def test_rejected_output_is_saved_with_failure_and_original_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            source = baseline(); app.reviews.save(source)
            bad = model_responses(expected_shape(selected=True))[0]; bad['primary_source_id'] = 'invented'
            with patch.object(LLM, '_request', side_effect=[bad]):
                identifier = app.reviews.recheck(source['id']); app.reviews.worker.join(3)
            row = app.reviews.get(identifier)
            self.assertEqual(row['status'], 'failed')
            self.assertIsNone(row['assessment'])
            self.assertIn('primary passage is unknown', row['error'])
            self.assertEqual(row['failure_stage'], 'selection')
            self.assertEqual(row['rejected_response'], {'truncated': False, 'parsed_json': bad})
            self.assertEqual(app.reviews.get(source['id']), source)

    def test_provider_error_does_not_downgrade_or_retry_and_keeps_body_private(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            source = baseline(); app.reviews.save(source)
            error = urllib.error.HTTPError(app.model.endpoint, 400, 'private-provider-message', {}, io.BytesIO(b'private-provider-body'))
            with patch('agent.urllib.request.urlopen', side_effect=error) as send:
                identifier = app.reviews.recheck(source['id']); app.reviews.worker.join(3)
            row = app.reviews.get(identifier)
            self.assertEqual(row['status'], 'failed')
            self.assertIn('HTTP 400', row['error'])
            self.assertNotIn('rejected_response', row)
            self.assertNotIn('private-provider', json.dumps(row))
            send.assert_called_once()

    def test_unrelated_providers_keep_previous_json_mode(self):
        for endpoint, key in [('https://example.invalid/v1/chat/completions', 'test-key'),
                              ('http://127.0.0.1:9999/v1/chat/completions', '')]:
            model = LLM(endpoint, 'other-model', key)
            self.assertEqual(review_response_format(model, baseline()['context']['evidence']), {'type': 'json_object'})

    def test_diagnostics_are_bounded_and_nonstandard_json_cannot_break_saving(self):
        huge = rejected_output({'text': 'x' * 40000})
        self.assertTrue(huge['truncated'])
        self.assertLessEqual(len(huge['preview']), 4000)
        self.assertEqual(len(huge['sha256']), 64)
        nonstandard = rejected_output({'number': float('nan')})
        self.assertIn('unavailable', nonstandard)
        json.dumps(nonstandard, allow_nan=False)

class ResearchBudgetRegressionTests(unittest.TestCase):
    def test_article_request_uses_larger_budget_and_preserves_paper_profile(self):
        from pathlib import Path
        from test_issuer_article import article, event, output
        from test_research import market
        import time
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            app.market = market(time.time())
            e = event(); app.store.add([e]); app.check_profile(app.model, save=True)
            profile = Path(directory) / 'run-profile.json'
            before = profile.read_bytes()
            with patch('research.collect_article', return_value=article()), patch('agent.urllib.request.urlopen', side_effect=[envelope(x) for x in model_responses(output(selected=True))]) as send:
                identifier = app.reviews.start(e['id']); app.reviews.worker.join(3)
            row = app.reviews.get(identifier)
            self.assertEqual(row['status'], 'complete', row.get('error'))
            request = json.loads(send.call_args_list[0].args[0].data)
            self.assertEqual(request['max_tokens'], 3072)
            self.assertEqual(row['request_settings']['max_tokens'], request['max_tokens'])
            self.assertEqual(request['reasoning_effort'], 'none')
            self.assertEqual(send.call_args.kwargs['timeout'], 180)
            self.assertLessEqual(request['response_format']['json_schema']['schema']['properties']['supporting_source_ids']['maxItems'], 2)
            self.assertEqual(profile.read_bytes(), before)
            self.assertEqual(app.model.request_settings['max_tokens'], 1024)
            self.assertNotIn('review_budget_version', app.model.request_settings)
            self.assertEqual(send.call_count, 1)

    def test_cut_off_response_is_still_rejected_without_automatic_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            source = baseline(); app.reviews.save(source)
            # Even syntactically valid JSON is rejected if the provider reports cutoff.
            body = {'choices': [{'finish_reason': 'length', 'message': {'content': json.dumps(expected_shape())}}]}
            with patch('agent.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())) as send:
                identifier = app.reviews.recheck(source['id']); app.reviews.worker.join(3)
            row = app.reviews.get(identifier)
            self.assertEqual(row['status'], 'failed')
            self.assertIsNone(row['assessment'])
            self.assertIn('output limit', row['error'])
            self.assertEqual(app.reviews.get(source['id']), source)
            self.assertFalse(app.busy)
            self.assertEqual(row['request_settings']['max_tokens'], 3072)
            send.assert_called_once()

class SelectedPassageRegressionTests(unittest.TestCase):
    """Actual rejected output and hand-written contract fixtures, not quality tests."""
    def actual_failure(self):
        from pathlib import Path
        path = Path(__file__).with_name('fixtures') / 'nvidia-review-051-failed.json'
        return json.loads(path.read_text())

    def selected_fixture(self):
        # Hand-written to test copying. This is NOT a generated Qwen assessment.
        value = expected_shape(selected=True)
        value['event_classification'] = {'category': 'commercial_agreement',
            'summary': 'The issuer describes an expanded computing collaboration.',
            'source_id': 'article_001'}
        value['business_impact'] = {'text': 'The issuer reports a convertible-bond investment; this does not establish future earnings.', 'source_ids': ['article_004']}
        value['thesis'] = {'text': 'An announced investment is distinct from an earnings surprise.', 'source_ids': ['article_004']}
        value['counterargument'] = {'text': 'Production deployment requires engineering and qualification.', 'source_ids': ['article_017']}
        value['supporting_evidence'] = [{'text': 'The disclosed amount is an investment in convertible bonds.', 'source_ids': ['article_004']}]
        value['missing_information'] = ['Incremental earnings contribution']
        value['invalidation'] = {'evidence_needed': 'A quantified earnings contribution would help evaluate the business impact.', 'source_to_check': 'Issuer financial results'}
        return value

    def test_actual_paraphrase_and_wrong_citations_are_not_silently_accepted(self):
        record = self.actual_failure()
        value = record['rejected_response']['parsed_json']; evidence = record['model_input']['evidence']
        with self.assertRaisesRegex(ValueError, 'not in the issuer evidence'):
            validate_review(value, evidence)
        with self.assertRaisesRegex(ValueError, 'source_id'):
            validate_review(value, evidence, selected_passages=True)
        bad = copy.deepcopy(value)
        bad['event_classification']['source_quote'] = evidence[1]['text']
        with self.assertRaisesRegex(ValueError, r'supporting_evidence\[0\].source_quote'):
            validate_review(bad, evidence)

    def test_selected_text_is_copied_exactly_and_raw_model_response_is_untouched(self):
        evidence = self.actual_failure()['model_input']['evidence']
        original = copy.deepcopy(evidence); value = self.selected_fixture(); before = copy.deepcopy(value)
        result = validate_review(value, evidence, selected_passages=True)
        by_id = {row['id']: row['text'] for row in evidence}
        self.assertEqual(value, before); self.assertEqual(evidence, original)
        self.assertEqual(result['event_classification']['source_quote'], by_id['article_001'])
        self.assertEqual(result['supporting_evidence'][0]['source_quote'], by_id['article_004'])
        self.assertEqual(result['supporting_evidence'][0]['source_quote_origin'], 'saved_evidence')
        self.assertIn('$3.5 billion in convertible bonds', result['supporting_evidence'][0]['source_quote'])

    def test_unknown_or_nonbusiness_selection_and_extra_quotes_fail_closed(self):
        evidence = self.actual_failure()['model_input']['evidence']
        for source_id in ('article_999', 'price_change', 'limits', '', ['article_001']):
            bad = self.selected_fixture(); bad['event_classification']['source_id'] = source_id
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                validate_review(bad, evidence, selected_passages=True)
        for ids in (['article_999'], ['quote'], [], ['article_001', 'article_004'], ['article_004', 'article_004']):
            bad = self.selected_fixture(); bad['supporting_evidence'][0]['source_ids'] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_review(bad, evidence, selected_passages=True)
        for target in ('event_classification', 'supporting_evidence'):
            bad = self.selected_fixture(); obj = bad[target][0] if target == 'supporting_evidence' else bad[target]
            obj['source_quote'] = 'Changed numbers or invented source text'
            with self.assertRaises(ValueError): validate_review(bad, evidence, selected_passages=True)
        bad = self.selected_fixture(); bad['supporting_evidence'] = []
        with self.assertRaisesRegex(ValueError, 'at least one'):
            validate_review(bad, evidence, selected_passages=True)

    def test_complete_selected_paragraph_is_preserved_including_qualifiers(self):
        evidence = copy.deepcopy(self.actual_failure()['model_input']['evidence'])
        text = 'A long source passage with qualifiers. ' * 30 + 'This is not revenue, profit or a guaranteed return.'
        next(row for row in evidence if row['id'] == 'article_004')['text'] = text
        result = validate_review(self.selected_fixture(), evidence, selected_passages=True)
        self.assertEqual(result['supporting_evidence'][0]['source_quote'], text)
        model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
        schema = review_response_format(model, evidence)['json_schema']['schema']
        self.assertNotIn('source_quote', json.dumps(schema))
        ids = schema['properties']['event_classification']['properties']['source_id']['enum']
        self.assertIn('article_004', ids); self.assertNotIn('price_change', ids)

    def test_application_saves_model_selection_separately_and_preserves_failed_record(self):
        from test_issuer_article import article, event, output
        from test_research import market
        import time
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory); e = event(); app.store.add([e]); app.market = market(time.time())
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            failed = self.actual_failure(); failed['started_at'] = time.time() - 600
            app.reviews.save(failed); raw = output(selected=True)
            with patch('research.collect_article', return_value=article()), patch.object(LLM, '_request', side_effect=model_responses(raw)):
                identifier = app.reviews.start(e['id']); app.reviews.worker.join(3)
            result = app.reviews.get(identifier)
            self.assertEqual(result['status'], 'complete', result.get('error'))
            self.assertEqual(result['model_response'], model_responses(raw)[0])
            self.assertEqual(result['quotation_method'], 'server_copied_source_passages')
            self.assertNotIn('source_quote', raw['event_classification'])
            self.assertIsNone(result['assessment'])
            originals={x['id']:x['text'] for x in result['model_input']['evidence']}
            self.assertTrue(all(originals[x['id']]==x['text'] for x in result['brief']['passages']))
            self.assertEqual(app.reviews.get(failed['id']), failed)
            self.assertEqual(app.model.request_settings['max_tokens'], 1024)
            self.assertFalse(app.busy)
