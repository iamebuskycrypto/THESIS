"""Regressions from the user's real Qwen run on fictional inputs.

Changed successful answers in these tests are hand-written, not model results.
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent import LLM
from research import REVIEWER_VERSION
from review_steps import (ASSESSMENT_PROMPT, assessment_input, assessment_schema,
                          validate_assessment, validate_future_source)
from runner import Application
from test_review_coverage import saved, selected


FIXTURE = Path(__file__).with_name('fixtures') / 'fictional-evaluation-055.json'


def recorded():
    return json.loads(FIXTURE.read_text())


class FutureSourceTests(unittest.TestCase):
    def test_all_eight_observed_bad_future_sources_are_rejected_unchanged(self):
        baseline = recorded()
        for case in baseline['cases']:
            step = case['steps'][1]
            value = step['model_response']; before = copy.deepcopy(value)
            with self.subTest(case=case['id']), self.assertRaisesRegex(ValueError, 'invalidation.source_to_check'):
                validate_assessment(value, step['input'])
            self.assertEqual(value, before)
            self.assertEqual(step['status'], 'complete')  # the old result is preserved
        self.assertEqual(baseline, recorded())

    def test_passage_ids_including_cutoff_and_wrapped_forms_cannot_name_future_sources(self):
        inputs = recorded()['cases'][6]['steps'][1]['input']
        for value in ('article_002', '`article_001`', '[article_001]', 'Article 2',
                      'Check article_001 for updates', 'source_ids: issuer', 'issuer', 'limits'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalidation.source_to_check'):
                validate_future_source(value, inputs)

    def test_source_names_allow_named_publishers_and_unnamed_actor_roles(self):
        inputs = recorded()['cases'][0]['steps'][1]['input']
        for value in ("Vale Storage's next quarterly filing", "Delta Warehousing's published pilot results",
                      "The transport regulator's investigation decision", "Beacon Instruments' full company update",
                      "SEC orders", "Lumen Devices' campaign attribution study"):
            validate_future_source(value, inputs)

    def test_bare_urls_and_vague_placeholders_fail(self):
        inputs = recorded()['cases'][0]['steps'][1]['input']
        for value in ('https://invented.example/next-results', 'www.example.com future results',
                      'Reports', 'More information', 'Future reports', 'Additional data', 'Further evidence'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_future_source(value, inputs)

    def test_the_new_contract_is_on_the_same_fields_without_decoder_truncation(self):
        source = saved('nvidia'); inputs = assessment_input(source['model_input'], selected('nvidia'))
        schema = assessment_schema(inputs)
        properties = schema['properties']['invalidation']['properties']
        self.assertEqual(set(properties), {'evidence_needed', 'source_to_check'})
        self.assertIn('publisher', properties['source_to_check']['description'])
        self.assertNotIn('maxLength', json.dumps(schema))
        self.assertIn('A condition for one action is not a condition for a different action', ASSESSMENT_PROMPT)
        self.assertIn('a later increase alone is not proof', ASSESSMENT_PROMPT)

    def test_form_checks_are_not_a_semantic_score(self):
        step = recorded()['cases'][3]['steps'][1]
        response = copy.deepcopy(step['model_response'])
        response['invalidation']['source_to_check'] = "Vale Storage's next quarterly filing"
        # Its old condition/outcome conflation remains. Passing this validator
        # must not be called proof of improved reasoning.
        validate_assessment(response, step['input'])
        self.assertIn('construction permit', response['counterargument']['text'])

    def test_saved_recheck_never_requests_a_generated_followup_or_edits_original(self):
        baseline = saved('nvidia')
        bad = copy.deepcopy(baseline['model_response'])
        bad['invalidation']['source_to_check'] = 'article_001'
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory); app.market = Mock()
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            app.reviews.save(baseline)
            with patch.object(LLM, '_request', side_effect=[selected('nvidia'), bad]) as request, \
                 patch('research.collect_article') as collect:
                identifier = app.reviews.recheck(baseline['id']); app.reviews.worker.join(3)
            result = app.reviews.get(identifier)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['reviewer_version'], REVIEWER_VERSION)
            self.assertEqual(request.call_count, 1)
            self.assertIsNone(result.get('assessment'))
            self.assertNotIn('invalidation', result['brief'])
            self.assertNotIn('evidence_audit', result)
            self.assertEqual(app.reviews.get(baseline['id']), baseline)
            self.assertEqual(app.market.mock_calls, [])
            collect.assert_not_called()

    def test_bundled_evaluation_uses_identical_inputs_and_expected_labels(self):
        spec = importlib.util.spec_from_file_location('bundled_evaluate', Path(__file__).parents[1] / 'evaluate.py')
        evaluate = importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluate)
        self.assertEqual(evaluate.REVIEWER_VERSION, REVIEWER_VERSION)
        for case, original in zip(evaluate.CASES, recorded()['cases']):
            packet = evaluate.make_packet(case)
            step = original['steps'][1]
            new_rows = {x['id']: x for x in packet['evidence']}
            for row in step['input']['evidence']:
                self.assertEqual(row, new_rows[row['id']])
            self.assertEqual(case['expected_categories'], [original['steps'][0]['model_response']['category']])
            self.assertNotIn('expected_categories', packet)
            record = evaluate.new_record(case)
            record['steps'] = copy.deepcopy(original['steps'])
            record['status'] = 'failed'
            check = next(x for x in evaluate.mechanical_checks(record) if x['label'].startswith('Source brief'))
            self.assertFalse(check['passed'])


if __name__ == '__main__':
    unittest.main()
