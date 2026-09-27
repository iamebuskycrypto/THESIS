"""Real-input regression fixture; all new model outputs here are controlled mocks."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from review_test_helpers import model_responses, assessment_only
from agent import LLM, canonical
from research import build_review_input, validate_review
from runner import Application

FIXTURE = Path(__file__).with_name('fixtures') / 'apple-review-04.json'


def baseline():
    return json.loads(FIXTURE.read_text())


def expected_shape(selected=False):
    """Hand-written example for contract tests, not a generated Qwen assessment."""
    def claim(text, refs=('issuer',)):
        return {'text': text, 'source_ids': list(refs)}
    result = {
        'event_classification': {'category': 'promotion_or_showcase',
            'summary': 'Apple describes a photography exhibition showcasing the iPhone camera.',
            'source_quote': 'A new photography exhibition'},
        'business_impact': claim('A showcase could support product awareness; the excerpt supplies no quantified sales or margin impact.'),
        'verdict': 'no_clear_edge',
        'thesis': claim('The exhibition excerpt does not establish a new business surprise or remaining edge.'),
        'supporting_evidence': [claim('The excerpt describes an exhibition showcasing the camera system.')],
        'counterargument': claim('The excerpt could omit commercial evidence connecting awareness to purchases.'),
        'priced_in_assessment': claim('The measured move cannot establish attribution or priced-in status.', ('price_change', 'limits')),
        'missing_information': ['Quantified commercial impact', 'An independent expectations comparison'],
        'invalidation': {'evidence_needed': 'New quantified sales or margin guidance paired with a dated expectations comparison.',
                         'source_to_check': 'Issuer financial releases and the underlying analyst research'}
    }

    if selected:
        result['event_classification'].pop('source_quote')
        result['event_classification']['source_id'] = 'issuer'
    return result


class SpecificityTests(unittest.TestCase):
    def inputs(self):
        row = baseline()
        return build_review_input(row['event'], row['context'], 'saved_context', 1789900000)

    def test_exact_quote_and_issuer_citations_are_checked(self):
        evidence = self.inputs()['evidence']
        self.assertEqual(validate_review(expected_shape(), evidence), expected_shape())
        for quotation in ['Apple raises its sales outlook.', 'new photography ... exhibition']:
            bad = expected_shape(); bad['event_classification']['source_quote'] = quotation
            with self.assertRaisesRegex(ValueError, 'not in the issuer'):
                validate_review(bad, evidence)
        for field in ('business_impact', 'thesis', 'counterargument'):
            bad = expected_shape(); bad[field]['source_ids'] = ['price_change']
            with self.assertRaisesRegex(ValueError, 'issuer excerpt'):
                validate_review(bad, evidence)
        bad = expected_shape(); bad['supporting_evidence'][0]['source_ids'] = ['quote']
        with self.assertRaisesRegex(ValueError, 'issuer excerpt'):
            validate_review(bad, evidence)

    def test_quote_whitespace_is_tolerated_without_rewriting_source(self):
        row = expected_shape(); row['event_classification']['source_quote'] = 'A new\nphotography exhibition'
        self.assertEqual(validate_review(row, self.inputs()['evidence']), row)

    def test_old_generic_shape_and_unprovided_operational_citation_fail(self):
        with self.assertRaises(ValueError): validate_review(baseline()['assessment'], self.inputs()['evidence'])
        bad = expected_shape(); bad['invalidation'] = 'Clearer correlation'
        with self.assertRaisesRegex(ValueError, 'new evidence'):
            validate_review(bad, self.inputs()['evidence'])
        bad = expected_shape(); bad['priced_in_assessment']['source_ids'] = ['entry_context']
        with self.assertRaisesRegex(ValueError, 'unknown'):
            validate_review(bad, self.inputs()['evidence'])

    def test_analysis_inputs_preserve_prices_and_exclude_execution_status(self):
        row = baseline(); original = copy.deepcopy(row)
        payload = build_review_input(row['event'], row['context'], 'saved_context', 1789900000)
        self.assertEqual(row, original)
        self.assertEqual(payload['market_captured_at'], row['context']['captured_at'])
        self.assertEqual(payload['published_at'], row['event']['published_at'])
        for key in ('issuer', 'quote', 'reference', 'price_change'):
            self.assertEqual(next(r for r in payload['evidence'] if r['id'] == key),
                             next(r for r in row['context']['evidence'] if r['id'] == key))
        self.assertNotIn('weekend', json.dumps(payload))
        self.assertNotIn('entry_context', json.dumps(payload))

    def test_saved_review_uses_no_market_calls_and_preserves_original_record(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            app.market = Mock()
            source = baseline(); app.reviews.save(source)
            with app.reviews.connect() as db:
                before = db.execute('SELECT body FROM reviews WHERE id=?', (source['id'],)).fetchone()[0]
            with patch.object(LLM, '_request', side_effect=model_responses(expected_shape(selected=True))) as request:
                new_id = app.reviews.recheck(source['id'])
                app.reviews.worker.join(3)
                self.assertFalse(app.reviews.worker.is_alive())
            row = app.reviews.get(new_id)
            self.assertEqual(row['status'], 'complete', row.get('error'))
            self.assertEqual(row['input_mode'], 'saved_context')
            self.assertEqual(row['context'], source['context'])
            self.assertEqual(row['event'], source['event'])
            self.assertEqual(row['comparison_baseline']['assessment'], source['assessment'])
            self.assertEqual(row['comparison_baseline']['reviewer_version'], 'original-0.4')
            self.assertNotEqual(row['id'], source['id'])
            self.assertEqual(app.market.mock_calls, [])
            payload = json.loads(request.call_args_list[0].args[0]['messages'][1]['content'])
            self.assertEqual(payload, row['review_steps'][0]['input'])
            self.assertEqual(row['review_steps'][0]['input_sha256'], hashlib.sha256(canonical(payload).encode()).hexdigest())
            with app.reviews.connect() as db:
                after = db.execute('SELECT body FROM reviews WHERE id=?', (source['id'],)).fetchone()[0]
            self.assertEqual(before, after)

    def test_failed_comparison_keeps_original_and_does_not_supply_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            source = baseline(); app.reviews.save(source)
            with patch.object(LLM, '_request', side_effect=RuntimeError('Test timeout')):
                new_id = app.reviews.recheck(source['id']); app.reviews.worker.join(3)
            result = app.reviews.get(new_id)
            self.assertEqual(result['status'], 'failed')
            self.assertIsNone(result['assessment'])
            self.assertEqual(app.reviews.get(source['id']), source)
            with self.assertRaisesRegex(ValueError, 'completed review'):
                app.reviews.recheck(new_id)
