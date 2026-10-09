"""Research-only isolation, evidence validation and local HTTP boundaries."""
import copy
import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from review_test_helpers import model_responses, assessment_only
from agent import LLM, Policy, validate_packet
from app import handler
from pipeline import build_packet
from research import ResearchReviews, collect_context, validate_review
from runner import Application


def event(now):
    return {"id": "fixture-news", "symbol": "RAAPLUSDT", "title": "Test fixture: product availability",
            "url": "https://www.apple.com/newsroom/test-fixture/", "source_kind": "issuer",
            "published_at": now - 7200, "observed_at": now - 7000,
            "text": "Test fixture only. Products are available in stores. No sales or profit guidance is given.",
            "evidence_scope": "issuer RSS/Atom excerpt"}


def market(now):
    m = Mock()
    m.session.return_value = {"tradable": False, "reason": "Test fixture: session closed"}
    m.reference.return_value = {"price": 100.0, "bar_open_at": now - 7260, "bar_close_at": now - 7200}
    m.quote.return_value = {"bid": 101.0, "ask": 101.1, "bid_size": 100.0, "ask_size": 100.0,
                            "timestamp": now, "collected_at": now}
    return m


def assessment():
    def claim(text, ids): return {"text": text, "source_ids": ids}
    return {"event_classification": {"category": "product_or_service",
                "summary": "The fixture reports product availability.", "source_id": "issuer"},
            "business_impact": claim("The excerpt supplies no sales or profit guidance to quantify the impact.", ["issuer"]),
            "verdict": "insufficient_evidence",
            "thesis": claim("The excerpt does not establish a new earnings surprise.", ["issuer"]),
            "supporting_evidence": [claim("Product availability is reported.", ["issuer"])],
            "counterargument": claim("Availability alone does not demonstrate increased profit.", ["issuer"]),
            "priced_in_assessment": claim("The observed move cannot be attributed to this announcement alone.", ["price_change", "limits"]),
            "missing_information": ["Sales and margin impact", "Market expectations"],
            "invalidation": {"evidence_needed": "New quantified guidance with an independently sourced expectations comparison.",
                             "source_to_check": "The issuer's next financial release"}}


class ContextTests(unittest.TestCase):
    def test_old_news_closed_session_is_reviewable_but_not_tradeable(self):
        now = time.time()
        e, m = event(now), market(now)
        original = copy.deepcopy(e)
        ctx = collect_context(e, m, Policy(), now_fn=lambda: now)
        self.assertEqual(e, original)
        self.assertAlmostEqual(ctx["price_change_bps"], 105.0)
        self.assertFalse(ctx["checks"][0]["passed"])
        self.assertFalse(ctx["session"]["tradable"])
        packet = build_packet(e, {"quote": m.quote(), "instrument": {
            "symbol": e["symbol"], "status": "online", "is_reality": True,
            "quantity_precision": 4, "min_notional": 1}}, {"tradable": True}, m.reference())
        with self.assertRaisesRegex(ValueError, "Stale evidence"):
            validate_packet(packet, now, Policy(), "observed")

    def test_no_reference_means_no_invented_price_change(self):
        now = time.time(); m = market(now)
        m.reference.return_value = None
        ctx = collect_context(event(now), m, Policy(), now_fn=lambda: now)
        self.assertIsNone(ctx["price_change_bps"])
        self.assertEqual(next(r for r in ctx["evidence"] if r["id"] == "reference")["kind"], "missing")

    def test_future_or_remote_reference_is_discarded(self):
        now = time.time()
        for closed in (now, now - 9000):
            m = market(now)
            m.reference.return_value = {"price": 100, "bar_open_at": closed - 60, "bar_close_at": closed}
            ctx = collect_context(event(now), m, Policy(), now_fn=lambda: now)
            self.assertIsNone(ctx["reference"])
            self.assertIsNone(ctx["price_change_bps"])

    def test_failed_feeds_are_explicit_and_do_not_expose_response_secrets(self):
        now = time.time(); m = market(now)
        for call in (m.quote, m.reference, m.session): call.side_effect = RuntimeError("private-provider-response")
        ctx = collect_context(event(now), m, Policy(), now_fn=lambda: now)
        self.assertIsNone(ctx["quote"])
        self.assertIsNone(ctx["price_change_bps"])
        self.assertFalse(ctx["session"]["available"])
        self.assertNotIn("private-provider-response", json.dumps(ctx))

    def test_bad_quote_and_foreign_issuer_are_not_accepted(self):
        now = time.time(); m = market(now)
        m.quote.return_value["bid"] = float("nan")
        ctx = collect_context(event(now), m, Policy(), now_fn=lambda: now)
        self.assertIsNone(ctx["quote"])
        with self.assertRaises(ValueError):
            collect_context({**event(now), "url": "https://apple.com.attacker.invalid/"}, m, Policy())


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.now = time.time()
        self.app.store.add([event(self.now)])
        self.app.market = market(self.now)
        self.app.model = LLM("http://127.0.0.1:11434/v1/chat/completions", "qwen3:8b", "")

    def tearDown(self):
        if self.app.reviews.worker: self.app.reviews.worker.join(3)
        self.temp.cleanup()

    def finish(self):
        self.app.reviews.worker.join(3)
        self.assertFalse(self.app.reviews.worker.is_alive())
        return self.app.reviews.snapshot()["records"][0]

    def test_actual_adapter_path_leaves_existing_paper_data_unchanged(self):
        self.app.check_profile(self.app.model, save=True)
        for symbol in ("RAAPLUSDT", "RNVDAUSDT"):
            for kind in ("agent", "benchmark"):
                engine = self.app.engine(symbol, kind)
                engine.mark(self.app.market.quote())
                engine.db.close()
        root = Path(self.temp.name)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
        with patch.object(LLM, "_request", side_effect=model_responses(assessment())) as call:
            review_id = self.app.reviews.start("fixture-news")
            row = self.finish()
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["mode"], "research_only")
        self.assertEqual(row["event"]["published_at"], self.now - 7200)
        user = json.loads(call.call_args.args[0]["messages"][1]["content"])
        self.assertEqual(user, row["review_steps"][0]["input"])
        self.assertEqual(self.app.reviews.get(review_id)["model_response"], model_responses(assessment())[0])
        restored = ResearchReviews(root / "research-reviews", self.app)
        self.assertEqual(restored.get(review_id)["status"], "complete")
        self.assertFalse(self.app.busy)
        self.assertTrue(self.app.cycle_lock.acquire(blocking=False))
        self.app.cycle_lock.release()

    def test_unknown_citation_is_rejected_and_failure_is_saved(self):
        bad = assessment(); bad["event_classification"]["source_id"] = "imaginary-consensus-feed"
        with patch.object(LLM, "_request", side_effect=model_responses(bad)):
            self.app.reviews.start("fixture-news")
            row = self.finish()
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["assessment"])
        self.assertIn("unknown", row["error"])

    def test_model_failure_does_not_generate_a_scripted_result(self):
        with patch.object(LLM, "_request", side_effect=RuntimeError("LLM request timed out after 180 seconds")):
            self.app.reviews.start("fixture-news")
            row = self.finish()
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["assessment"])
        self.assertIn("180", row["error"])
        self.assertFalse(self.app.busy)

    def test_cannot_interrupt_monitoring_or_overlap_other_work(self):
        self.app.worker = Mock(); self.app.worker.is_alive.return_value = True
        with self.assertRaisesRegex(ValueError, "Pause the paper run"):
            self.app.reviews.start("fixture-news")
        self.app.worker = None
        self.app.cycle_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "running"):
                self.app.reviews.start("fixture-news")
        finally: self.app.cycle_lock.release()
        self.app.busy = True
        with self.assertRaisesRegex(ValueError, "Wait"):
            self.app.start()

    def test_unknown_event_rejected_but_source_reader_needs_no_model(self):
        with self.assertRaises(ValueError): self.app.reviews.start("unknown")
        self.app.model = None
        with patch('research.collect_article', return_value={'status':'unavailable','reason':'Fixture'}):
            review_id = self.app.reviews.start("fixture-news")
            self.app.reviews.worker.join(5)
        row = self.app.reviews.get(review_id)
        self.assertEqual(row['status'], 'complete')
        self.assertEqual(row['model_calls'], 0)
        self.assertEqual(row['brief']['category_origin'], 'not_classified')
        self.assertIsNone(row['assessment'])
        self.assertEqual(row['brief']['passages'][0]['text'], event(self.now)['text'])
        with self.assertRaisesRegex(ValueError, 'AI explanations need a model'):
            self.app.reviews.assess(review_id)

    def test_interrupted_work_does_not_appear_successful_after_restart(self):
        row = {"id": "a" * 32, "started_at": self.now, "status": "running"}
        self.app.reviews.save(row)
        self.assertEqual(self.app.reviews.get(row["id"])["status"], "interrupted")

    def test_schema_rejects_extra_trading_fields(self):
        result = {**assessment(), "action": "buy"}
        with self.assertRaises(ValueError): validate_review(result, [{"id": "issuer"}])

    def test_http_requires_token_and_serves_real_review_assets(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.app, "test-token", 0))
        port = server.server_address[1]
        server.RequestHandlerClass = handler(self.app, "test-token", port)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            req = urllib.request.Request(base + "/api/review", data=b'{"event_id":"fixture-news"}',
                                         headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
            for path, content_type in (("/research.js", "text/javascript"), ("/research.css", "text/css")):
                with urllib.request.urlopen(base + path) as response:
                    self.assertIn(content_type, response.headers["Content-Type"])
                    self.assertGreater(len(response.read()), 100)
            with patch.object(LLM, "_request", side_effect=model_responses(assessment())):
                req.add_header("X-Thesis-Token", "test-token")
                with urllib.request.urlopen(req) as response: result = json.load(response)
                self.finish()
            with urllib.request.urlopen(base + "/api/review?id=" + result["review_id"]) as response:
                self.assertEqual(json.load(response)["status"], "complete")
            again = urllib.request.Request(base + "/api/review-again",
                data=json.dumps({"review_id": result["review_id"]}).encode(),
                headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(again)
            self.assertEqual(error.exception.code, 403)
            again.add_header("X-Thesis-Token", "test-token")
            with patch.object(LLM, "_request", side_effect=model_responses(assessment())):
                with urllib.request.urlopen(again) as response: repeated = json.load(response)
                self.finish()
            with urllib.request.urlopen(base + "/api/review?id=" + repeated["review_id"]) as response:
                saved = json.load(response)
            self.assertEqual(saved["status"], "complete")
            self.assertEqual(saved["comparison_baseline"]["id"], result["review_id"])
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
