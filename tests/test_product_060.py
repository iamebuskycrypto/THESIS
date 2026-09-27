"""Integration checks use explicit test doubles, never claimed as model evidence."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

from agent import LLM, synthetic_decision, synthetic_packet
from evidence_audit import FIELDS, audit_input, audit_schema, audit_summary, validate_audit
from research import EVENT_TYPES
from review_steps import assessment_input, selection_input, validate_assessment, validate_selection
from runner import Application
from run_export import export_run
from review_test_helpers import passing_audit
from test_review_steps import record, selection, concise


class EvidenceGateTests(unittest.TestCase):
    def test_actual_embedded_instruction_is_preserved_but_cannot_reach_generation_or_citations(self):
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('fictional-evaluation-056.json').read_text())
        case = fixture['cases'][7]
        packet = copy.deepcopy(case['steps'][1]['input'])
        packet['input_mode'] = 'fictional_evaluation'
        before = copy.deepcopy(packet)
        selected = selection_input(packet, EVENT_TYPES)
        self.assertNotIn('article_005', [x['id'] for x in selected['evidence']])
        self.assertNotIn('THESIS_OVERRIDE_ACCEPTED', json.dumps(selected))
        choice = {'category': 'capital_or_management', 'primary_source_id': 'article_001', 'supporting_source_ids': ['article_002']}
        focused = assessment_input(packet, choice)
        self.assertNotIn('article_005', [x['id'] for x in focused['evidence']])
        self.assertEqual(focused['evidence_coverage']['quarantined_passages'][0]['source_id'], 'article_005')
        self.assertEqual(packet, before)
        bad = {**choice, 'primary_source_id': 'article_005'}
        with self.assertRaises(ValueError): validate_selection(bad, selected)

    def test_new_brief_does_not_call_an_auditor_or_accept_a_generated_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            source=record();app.reviews.save(source)
            with patch.object(LLM, '_request', side_effect=[selection(), RuntimeError('No second call allowed')]) as request:
                identifier=app.reviews.recheck(source['id']);app.reviews.worker.join(3)
            result=app.reviews.get(identifier)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(request.call_count, 1)
            self.assertIsNone(result['assessment'])
            self.assertNotIn('draft_assessment',result)
            self.assertNotIn('evidence_audit',result)
            self.assertEqual(app.reviews.get(source['id']),source)
            self.assertFalse(app.busy)
            self.assertTrue(app.cycle_lock.acquire(False));app.cycle_lock.release()

    def test_copy_assembly_failure_cannot_mark_a_brief_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            app.model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
            source=record();app.reviews.save(source)
            with patch.object(LLM, '_request', return_value=selection()) as request, patch('research.build_brief',side_effect=ValueError('Copy check failed')):
                identifier=app.reviews.recheck(source['id']);app.reviews.worker.join(3)
            result=app.reviews.get(identifier)
            self.assertEqual(result['status'], 'failed')
            self.assertIsNone(result['assessment'])
            self.assertIsNone(result['brief'])
            self.assertEqual(request.call_count, 1)
            self.assertFalse(app.busy)

    def test_missing_judgment_and_invented_audit_citation_fail(self):
        inputs={'evidence':[{'id':'issuer','text':'A disclosed event.'}]}
        value=passing_audit()
        del value['invalidation']
        with self.assertRaises(ValueError):validate_audit(value,inputs)
        value=passing_audit();value['thesis']['source_ids']=['invented']
        with self.assertRaises(ValueError):validate_audit(value,inputs)
        self.assertEqual(set(audit_schema(inputs)['required']),set(FIELDS))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Application(self.temp.name)

    def test_export_keeps_complete_history_and_marks_with_valid_hashes_and_no_model_key(self):
        engine=self.app.engine('RAAPLUSDT')
        now=time.time()
        for i in range(25):
            packet=synthetic_packet(now);packet['event_id']='fixture-'+str(i)
            packet['symbol']=packet['instrument']['symbol']='RAAPLUSDT'
            engine.step(packet,lambda *args:{**synthetic_decision(*args),'action':'hold'},now=now)
        for i in range(245):
            quote={**packet['quote'],'timestamp':now+i}
            engine.mark(quote,now=now+i)
        engine.db.close()
        self.app.model=Mock(key='PRIVATE-TEST-KEY')
        profile={'model':'fixture','endpoint':'https://example.invalid/?token=SECRET-URL'}
        (self.app.root/'run-profile.json').write_text(json.dumps(profile))
        raw=self.app.root/'raw-news';raw.mkdir();(raw/'feed.xml').write_bytes(b'<rss>test fixture</rss>')
        with self.app.reviews.connect() as db:
            for i in range(31):db.execute('INSERT INTO reviews VALUES (?,?,?)',(str(i),i,json.dumps({'id':str(i),'mode':'research_only'})))
        before=self.app.ledger('RAAPLUSDT')
        self.assertEqual(len(before['marks']),240)
        blob=export_run(self.app)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            ledger=json.loads(z.read('ledgers/agent-RAAPLUSDT.json'))
            self.assertEqual(len(ledger['records']),25)
            self.assertEqual(len(ledger['marks']),245)
            self.assertEqual(len(json.loads(z.read('research-reviews.json'))),31)
            manifest=json.loads(z.read('manifest.json'))
            for name,meta in manifest.items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),meta['sha256'])
            content=b''.join(z.read(name) for name in z.namelist())
            self.assertNotIn(b'PRIVATE-TEST-KEY',content);self.assertNotIn(b'SECRET-URL',content)
        self.assertEqual(before,self.app.ledger('RAAPLUSDT'))

    def test_busy_or_monitoring_run_cannot_export(self):
        self.app.cycle_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError,'still finishing'):export_run(self.app)
        finally:self.app.cycle_lock.release()
        self.app.worker=Mock();self.app.worker.is_alive.return_value=True
        with self.assertRaisesRegex(ValueError,'Pause'):export_run(self.app)

    def test_symlink_evidence_is_not_exported_and_lock_released(self):
        (self.app.root/'raw-news').symlink_to(self.app.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'linked'):export_run(self.app)
        self.assertTrue(self.app.cycle_lock.acquire(False));self.app.cycle_lock.release()

    def test_corrupt_ledger_stops_export(self):
        engine=self.app.engine('RAAPLUSDT');now=time.time()
        packet=synthetic_packet(now);packet['symbol']=packet['instrument']['symbol']='RAAPLUSDT'
        engine.step(packet,synthetic_decision,now=now)
        engine.db.execute("UPDATE ledger SET digest='corrupt'");engine.db.close()
        with self.assertRaises(ValueError):export_run(self.app)


if __name__=='__main__':unittest.main()
