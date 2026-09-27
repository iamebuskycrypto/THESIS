from review_test_helpers import passing_audit
"""Known-defect regressions. Successful AI responses below are hand-written mocks."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent import LLM, canonical
from research import EVENT_TYPES
from review_steps import (selection_input, selection_schema, validate_selection,
    assessment_input, assessment_schema, validate_assessment, check_text, assemble_review)
from runner import Application


def record():
    return json.loads((Path(__file__).with_name('fixtures')/'nvidia-review-052-quality.json').read_text())


def selection():
    # Intentionally omits the financial passage to exercise application retention.
    return {'category':'commercial_agreement','primary_source_id':'article_001',
            'supporting_source_ids':['article_002','article_017']}


def concise():
    def claim(text,ref): return {'text':text,'source_ids':[ref]}
    return {'verdict':'insufficient_evidence',
        'thesis':claim('The expanded collaboration does not establish an earnings surprise.','article_001'),
        'business_impact':claim('The convertible-bond investment commits capital; its future earnings contribution remains unknown.','article_004'),
        'counterargument':claim('Production deployment still requires extensive engineering and qualification.','article_017'),
        'priced_in_assessment':claim('The observed price change cannot establish news attribution or priced-in status.','price_change'),
        'missing_information':['Incremental earnings contribution','Convertible-bond maturity'],
        'invalidation':{'evidence_needed':'A quantified earnings contribution would change the assessment of commercial impact.',
                        'source_to_check':'Future issuer financial results'}}


class StageChecks(unittest.TestCase):
    def test_actual_unfinished_fields_fail_despite_the_old_complete_status(self):
        r=record();self.assertEqual(r['status'],'complete')
        for field,text in [('business_impact',r['model_response']['business_impact']['text']),
                           ('invalidation',r['model_response']['invalidation']['evidence_needed'])]:
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'unfinished'):
                check_text(text,field)
        focused=assessment_input(r['model_input'],selection())
        old={k:v for k,v in r['model_response'].items() if k not in ('event_classification','supporting_evidence')}
        with self.assertRaises(ValueError): validate_assessment(old,focused)

    def test_unprovided_expansion_is_rejected_even_with_a_finished_sentence(self):
        with self.assertRaisesRegex(ValueError,'acronym expansion'):
            check_text('Custom XPUs (eXascale Processors) could be developed.','claim','Custom XPUs may be developed.')
        check_text('A CPU (central processing unit) runs the task.','claim','A central processing unit runs a task.')
        with self.assertRaisesRegex(ValueError,'mixed-language'):
            check_text('The input describes 包装.','claim','The input describes packaging.')

    def test_completion_checks_do_not_append_punctuation_or_accept_dangling_phrases(self):
        for text in ('A claim ends with the','A claim ends with the.','A partial claim,','A trailing thought...'):
            with self.subTest(text=text),self.assertRaises(ValueError):check_text(text,'claim')
        check_text('The earnings contribution is unknown.','claim')
        # No grammar decoder field cap may force a half-sentence to look finished.
        focused=assessment_input(record()['model_input'],selection())
        self.assertNotIn('maxLength',json.dumps(assessment_schema(focused)))

    def test_amount_passage_is_retained_when_selector_omits_it(self):
        packet=record()['model_input'];before=copy.deepcopy(packet)
        inputs=selection_input(packet,EVENT_TYPES);selected=validate_selection(selection(),inputs)
        focused=assessment_input(packet,selected)
        self.assertEqual(focused['amount_source_ids'],['article_004'])
        self.assertEqual(focused['evidence'][0]['id'],'article_004')
        self.assertEqual(packet,before)
        result=assemble_review(validate_assessment(concise(),focused),selected,focused)
        amount=next(x for x in result['supporting_evidence'] if x['source_ids']==['article_004'])
        original=next(x['text'] for x in packet['evidence'] if x['id']=='article_004')
        self.assertEqual(amount['source_quote'],original)
        self.assertEqual(amount['selection_origin'],'amount_rule')
        self.assertNotIn('article_004',selected['supporting_source_ids'])
        self.assertLess(len(focused['evidence']),len(packet['evidence']))
        with self.assertRaisesRegex(ValueError,'disclosed amount'):
            bad=concise();bad['business_impact']['source_ids']=['article_001'];validate_assessment(bad,focused)

    def test_amount_detection_is_general_and_feed_fallback_remains_available(self):
        packet=copy.deepcopy(record()['model_input'])
        packet['evidence']=[{'id':'issuer','text':'An item costs €75. Revenue is undisclosed.'}, {'id':'limits','text':'Only an excerpt is provided.'}]
        inputs=selection_input(packet,EVENT_TYPES)
        self.assertEqual(selection_schema(inputs)['properties']['supporting_source_ids']['maxItems'],0)
        selected={'category':'product_or_service','primary_source_id':'issuer','supporting_source_ids':[]}
        focused=assessment_input(packet,validate_selection(selected,inputs))
        self.assertEqual(focused['amount_source_ids'],['issuer'])
        packet['evidence'][0]['text']='No monetary amount is disclosed.'
        self.assertEqual(assessment_input(packet,selected)['amount_source_ids'],[])

    def test_unknown_sources_and_extra_fields_do_not_become_repaired_selections(self):
        inputs=selection_input(record()['model_input'],EVENT_TYPES)
        for change in ({'primary_source_id':'invented'}, {'supporting_source_ids':['article_001']},
                       {'supporting_source_ids':['article_002','article_002']}, {'trade':'buy'}):
            value={**selection(),**change};before=copy.deepcopy(value)
            with self.assertRaises(ValueError):validate_selection(value,inputs)
            self.assertEqual(value,before)

    def test_specific_missing_terms_are_allowed_broad_financial_absence_is_rejected(self):
        focused=assessment_input(record()['model_input'],selection());good=concise()
        validate_assessment(good,focused)
        good['missing_information']=['Specific details on financial terms']
        with self.assertRaisesRegex(ValueError,'amount is disclosed'):validate_assessment(good,focused)
        good['missing_information']=['Financial terms: conversion price and maturity']
        validate_assessment(good,focused)


class StageLifecycle(unittest.TestCase):
    def run_case(self, responses):
        # Recheck keeps the actual observation fixed, without another web request.
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        app=Application(self.temp.name);app.market=Mock()
        app.model=LLM('http://127.0.0.1:11434/v1/chat/completions','qwen3:8b','')
        baseline=record();app.reviews.save(baseline)
        with patch.object(LLM,'_request',side_effect=responses) as call, patch('research.collect_article') as fetch:
            identifier=app.reviews.recheck(baseline['id']);app.reviews.worker.join(3)
        self.assertFalse(app.reviews.worker.is_alive())
        self.assertEqual(app.reviews.get(baseline['id']),baseline)
        self.assertEqual(app.market.mock_calls,[]);fetch.assert_not_called()
        self.assertFalse(app.busy);self.assertEqual(app.model.request_settings['max_tokens'],1024)
        self.assertTrue(app.cycle_lock.acquire(blocking=False));app.cycle_lock.release()
        return app.reviews.get(identifier),call

    def test_success_preserves_exact_selection_and_copies_without_additional_model_calls(self):
        result,call=self.run_case([selection()])
        self.assertEqual(result['status'],'complete',result.get('error'));self.assertEqual(call.call_count,1)
        self.assertEqual(result['model_response'],selection())
        self.assertEqual(result['evidence_selection'],selection())
        for step,args in zip(result['review_steps'],call.call_args_list):
            self.assertEqual(step['status'],'complete')
            sent=json.loads(args.args[0]['messages'][1]['content'])
            self.assertEqual(sent,step['input'])
            self.assertEqual(step['input_sha256'],hashlib.sha256(canonical(sent).encode()).hexdigest())
            self.assertEqual(step['request_settings']['response_format'],args.args[0]['response_format'])
        self.assertEqual(result['review_steps'][0]['model_response'],selection())
        self.assertEqual(result['quality_checks']['status'],'exact_copy_checked')
        self.assertIsNone(result['assessment'])
        self.assertNotIn('evidence_audit',result)
        self.assertTrue(result['brief']['passages'])

    def test_selection_failure_prevents_second_call_and_keeps_diagnostics(self):
        result,call=self.run_case([{**selection(),'primary_source_id':'invented'}])
        self.assertEqual(result['status'],'failed');self.assertEqual(call.call_count,1)
        self.assertEqual(result['failure_stage'],'selection');self.assertIsNone(result['assessment'])
        self.assertEqual(result['review_steps'][0]['status'],'failed')
        self.assertNotIn('quality_checks',result)

    def test_generated_claim_field_is_rejected_without_a_brief_or_retry(self):
        bad={**selection(), 'business_impact': 'Funding is secured.'}
        result,call=self.run_case([bad])
        self.assertEqual(result['status'],'failed');self.assertEqual(call.call_count,1)
        self.assertEqual(result['failure_stage'],'selection');self.assertIsNone(result['assessment'])
        self.assertIsNone(result['brief'])
        self.assertEqual(result['rejected_response']['parsed_json'],bad)
        self.assertNotIn('quality_checks',result)


class CitationContractRegression(unittest.TestCase):
    def actual_failure(self):
        path=Path(__file__).with_name('fixtures')/'nvidia-review-053-citation.json'
        return json.loads(path.read_text())

    def test_actual_rejected_response_stays_rejected_and_schema_excludes_its_citation(self):
        saved=self.actual_failure();inputs=saved['review_steps'][1]['input']
        response=saved['review_steps'][1]['rejected_response']['parsed_json'];before=copy.deepcopy(response)
        self.assertEqual(response['counterargument']['source_ids'],['limits'])
        schema=assessment_schema(inputs)
        permitted=schema['properties']['counterargument']['properties']['source_ids']['items']['enum']
        self.assertNotIn('limits',permitted);self.assertNotIn('quote',permitted)
        self.assertIn('article_004',permitted)
        with self.assertRaisesRegex(ValueError,'counterargument: cite the issuer'):
            validate_assessment(response,inputs)
        self.assertEqual(response,before)

    def test_every_schema_permitted_single_or_pair_citation_passes_the_same_field_policy(self):
        from itertools import combinations
        saved=self.actual_failure();inputs=saved['review_steps'][1]['input']
        # Controlled contract fixture: only the citation differs from the rejected
        # response. This is not a repaired production record or new model result.
        baseline=copy.deepcopy(saved['review_steps'][1]['rejected_response']['parsed_json'])
        baseline['counterargument']['source_ids']=['article_004']
        schema=assessment_schema(inputs)
        for field in ('thesis','business_impact','counterargument','priced_in_assessment'):
            refs=schema['properties'][field]['properties']['source_ids']
            for count in range(1,refs['maxItems']+1):
                for ids in combinations(refs['items']['enum'],count):
                    value=copy.deepcopy(baseline);value[field]['source_ids']=list(ids)
                    with self.subTest(field=field,ids=ids):
                        if field == 'business_impact' and inputs['amount_source_ids'] and not set(ids).intersection(inputs['amount_source_ids']):
                            with self.assertRaises(ValueError): validate_assessment(value,inputs)
                        else:
                            self.assertEqual(validate_assessment(value,inputs),value)
        self.assertEqual(saved,self.actual_failure())

    def test_excluded_counterargument_sources_are_rejected_even_mixed_with_an_article(self):
        saved=self.actual_failure();inputs=saved['review_steps'][1]['input']
        for refs in (['limits'],['quote'],['article_004','limits'],['article_004','quote']):
            value=copy.deepcopy(saved['review_steps'][1]['rejected_response']['parsed_json'])
            value['counterargument']['source_ids']=refs
            with self.subTest(refs=refs),self.assertRaisesRegex(ValueError,'counterargument: cite the issuer'):
                validate_assessment(value,inputs)

    def test_financial_phrasal_verb_endings_are_not_treated_as_truncation(self):
        saved=self.actual_failure();text=saved['review_steps'][1]['rejected_response']['parsed_json']['invalidation']['evidence_needed']
        self.assertTrue(text.endswith('priced in.'))
        check_text(text,'invalidation.evidence_needed')
        for sentence in ('These costs must be accounted for.', 'This is what the instrument is made of.', 'The rating is A.'):
            check_text(sentence,'claim')
        # The actual 0.5.2 cut-off is still rejected, including a punctuation-only repair.
        previous=record()['model_response']['invalidation']['evidence_needed']
        for sentence in (previous,previous+'.'):
            with self.assertRaises(ValueError):check_text(sentence,'invalidation.evidence_needed')
