from review_test_helpers import passing_audit
"""Regressions from real saved inputs; changed outputs below are hand-written mocks."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent import LLM
from research import EVENT_TYPES
from review_steps import (selection_input, selection_schema, validate_selection,
                          assessment_input, assessment_schema, validate_assessment, assemble_review)
from runner import Application


def saved(company):
    return json.loads((Path(__file__).with_name('fixtures') /
                       (company + '-review-054-complete.json')).read_text())


def selected(company):
    # A test choice, not a new Qwen output. The new schema excludes the old
    # NVIDIA heading and offers the substantive platform passage instead.
    value = copy.deepcopy(saved(company)['evidence_selection'])
    if company == 'nvidia':
        value['supporting_source_ids'] = ['article_004', 'article_002']
    return value


class CoverageRegressions(unittest.TestCase):
    def test_actual_nvidia_blind_spot_is_available_even_when_not_highlighted(self):
        old = saved('nvidia'); before = copy.deepcopy(old)
        self.assertNotIn('article_007', [x['id'] for x in old['review_steps'][1]['input']['evidence']])
        packet = old['model_input']
        inputs = assessment_input(packet, selected('nvidia'))
        rows = {x['id']: x for x in inputs['evidence']}
        for original in packet['evidence']:
            if original['id'].startswith('article_'):
                self.assertEqual(rows[original['id']]['text'], original['text'])
        self.assertIn('RTX Spark', rows['article_007']['text'])
        self.assertIn('extensive chip-to-rack engineering', rows['article_017']['text'])
        self.assertIn('article_007', assessment_schema(inputs)['properties']['thesis']['properties']['source_ids']['items']['enum'])
        self.assertEqual(old, before)

    def test_heading_and_partial_passage_are_excluded_from_both_citation_schemas(self):
        packet = saved('nvidia')['model_input']
        first = selection_input(packet, EVENT_TYPES)
        ids = selection_schema(first)['properties']['primary_source_id']['enum']
        self.assertNotIn('article_005', ids)
        self.assertNotIn('article_013', ids)
        self.assertNotIn('article_022', ids)
        inputs = assessment_input(packet, selected('nvidia'))
        schema = assessment_schema(inputs)
        for field in ('thesis', 'business_impact', 'counterargument', 'priced_in_assessment'):
            for source in ('article_005', 'article_013', 'article_022'):
                self.assertNotIn(source, schema['properties'][field]['properties']['source_ids']['items']['enum'])
        self.assertTrue(next(x for x in inputs['evidence'] if x['id'] == 'article_022')['partial_paragraph'])
        with self.assertRaises(ValueError):
            validate_selection(saved('nvidia')['evidence_selection'], first)
        bad = copy.deepcopy(saved('nvidia')['model_response'])
        bad['counterargument']['source_ids'] = ['article_005']
        with self.assertRaises(ValueError):
            validate_assessment(bad, inputs)

    def test_apple_exhibition_context_survives_a_product_feature_highlight(self):
        old = saved('apple'); packet = old['model_input']
        first = selection_input(packet, EVENT_TYPES)
        choice = validate_selection(old['evidence_selection'], first)
        self.assertEqual(choice['category'], 'promotion_or_showcase')
        self.assertNotIn('article_001', [x['id'] for x in old['review_steps'][1]['input']['evidence']])
        inputs = assessment_input(packet, choice)
        rows = {x['id']: x for x in inputs['evidence']}
        self.assertIn('new photography exhibition', rows['article_001']['text'])
        self.assertEqual(inputs['amount_source_ids'], [])
        self.assertNotIn('article_014', inputs['evidence_coverage']['citation_source_ids'])
        self.assertEqual(len(inputs['evidence_coverage']['article_source_ids']), 14)

    def test_assessment_does_not_expand_the_saved_article_budget_or_edit_market_rows(self):
        for company in ('apple', 'nvidia'):
            with self.subTest(company=company):
                packet = saved(company)['model_input']; before = copy.deepcopy(packet)
                inputs = assessment_input(packet, selected(company))
                text = [x['text'] for x in inputs['evidence'] if x['id'].startswith('article_')]
                self.assertLessEqual(sum(map(len, text)), 5000)
                for key in ('quote', 'reference', 'price_change', 'limits'):
                    self.assertEqual(next(x['text'] for x in inputs['evidence'] if x['id'] == key),
                                     next(x['text'] for x in packet['evidence'] if x['id'] == key))
                self.assertEqual(packet, before)

    def test_newly_cited_passage_is_copied_with_accurate_provenance(self):
        packet = saved('nvidia')['model_input']; choice = selected('nvidia')
        inputs = assessment_input(packet, choice)
        response = copy.deepcopy(saved('nvidia')['model_response'])
        response['counterargument'] = {'text': 'Production deployment requires extensive engineering and qualification.',
                                       'source_ids': ['article_017']}
        before = copy.deepcopy(response)
        result = assemble_review(validate_assessment(response, inputs), choice, inputs)
        row = next(x for x in result['supporting_evidence'] if x['source_ids'] == ['article_017'])
        self.assertEqual(row['selection_origin'], 'assessment_citation')
        self.assertEqual(row['source_quote'], next(x['text'] for x in packet['evidence'] if x['id'] == 'article_017'))
        self.assertEqual(response, before)

    def test_fallback_and_missing_evidence_fail_without_an_empty_schema(self):
        packet = copy.deepcopy(saved('apple')['model_input'])
        packet['evidence'] = [{'id': 'issuer', 'text': 'The issuer announced an exhibition.'},
                              {'id': 'article_001', 'text': 'A cut-off paragraph', 'partial_paragraph': True},
                              {'id': 'limits', 'text': 'Partial evidence.'}]
        inputs = selection_input(packet, EVENT_TYPES)
        self.assertEqual([x['id'] for x in inputs['evidence']], ['issuer'])
        choice = {'category': 'promotion_or_showcase', 'primary_source_id': 'issuer', 'supporting_source_ids': []}
        focused = assessment_input(packet, validate_selection(choice, inputs))
        self.assertEqual(focused['evidence_coverage']['citation_source_ids'], ['issuer'])
        packet['evidence'] = packet['evidence'][1:]
        with self.assertRaisesRegex(ValueError, 'no usable issuer'):
            selection_input(packet, EVENT_TYPES)

    def test_saved_input_recheck_preserves_original_and_records_exact_new_coverage(self):
        baseline = saved('nvidia')
        response = copy.deepcopy(baseline['model_response'])
        response['counterargument'] = {'text': 'Production deployment requires extensive engineering and qualification.',
                                       'source_ids': ['article_017']}
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory); app.market = Mock()
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            app.reviews.save(baseline)
            with patch.object(LLM, '_request', side_effect=[selected('nvidia'), response, passing_audit('article_001')]) as call, \
                 patch('research.collect_article') as fetch:
                identifier = app.reviews.recheck(baseline['id']); app.reviews.worker.join(3)
            self.assertFalse(app.reviews.worker.is_alive())
            result = app.reviews.get(identifier)
            self.assertEqual(result['status'], 'complete', result.get('error'))
            self.assertEqual(call.call_count, 1)
            self.assertEqual({r['id']:r['text'] for r in result['brief']['passages']}, {r['id']:r['text'] for r in result['review_steps'][0]['input']['evidence']})
            self.assertEqual(result['context'], baseline['context'])
            self.assertEqual(app.reviews.get(baseline['id']), baseline)
            self.assertEqual(app.market.mock_calls, []); fetch.assert_not_called()
            self.assertEqual(app.model.request_settings['max_tokens'], 1024)
            self.assertFalse(app.busy)
