import copy
import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent import Engine, Policy, synthetic_decision, synthetic_packet
from pipeline import SOURCES, parse_feed, resolve_session
from runner import Application, EventStore, mechanical_demo


class FeedTests(unittest.TestCase):
    def test_atom_feed_preserves_source_and_time(self):
        raw = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Example release</title><link href="https://www.apple.com/newsroom/example/"/><published>2026-09-16T10:00:00Z</published><summary>&lt;b&gt;Example statement&lt;/b&gt;</summary></entry></feed>'''
        now = datetime.fromisoformat("2026-09-16T10:01:00+00:00").timestamp()
        events = parse_feed(raw, SOURCES["RAAPLUSDT"], "RAAPLUSDT", now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["observed_at"], now)
        self.assertNotIn("<b>", events[0]["text"])
        self.assertEqual(events[0]["source_kind"], "issuer")

    def test_foreign_link_and_future_release_are_excluded(self):
        raw = b'''<rss><channel><item><title>Bad link</title><link>https://www.apple.com.attacker.invalid/news</link><pubDate>Wed, 16 Sep 2026 10:00:00 GMT</pubDate></item><item><title>Future event</title><link>https://www.apple.com/newsroom/future/</link><pubDate>Thu, 17 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
        now = datetime.fromisoformat("2026-09-16T10:01:00+00:00").timestamp()
        self.assertEqual(parse_feed(raw, SOURCES["RAAPLUSDT"], "RAAPLUSDT", now), [])

    def test_xml_entities_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY a "payload">]><rss/>', SOURCES["RAAPLUSDT"], "RAAPLUSDT", time.time())

    def test_first_observation_is_not_overwritten_by_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(directory)
            event = {"id": "same", "published_at": 10, "observed_at": 11}
            store.add([event])
            store.add([{**event, "observed_at": 50}])
            self.assertEqual(store.events()[0]["observed_at"], 11)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 11, tzinfo=ZoneInfo("America/New_York")).timestamp()
        self.stock = {"tradingPeriod": ["regular"], "weekendTradable": "yes"}
        self.calendar = {"specificConfig": [], "regularConfig": ["SATURDAY", "SUNDAY"]}
        self.sessions = {"daylightType": "dst", "stateList": [{"state": "regular", "startTime": "09:30", "endTime": "16:00"}]}

    def test_supported_session(self):
        self.assertTrue(resolve_session(self.stock, self.calendar, self.sessions, self.now)["tradable"])

    def test_daylight_conflict_blocks_trading(self):
        self.sessions["daylightType"] = "standard"
        self.assertFalse(resolve_session(self.stock, self.calendar, self.sessions, self.now)["tradable"])

    def test_holiday_blocks_trading(self):
        self.calendar["specificConfig"] = [{"startTime": "2026-09-16 09:00", "endTime": "2026-09-16 20:00"}]
        self.assertFalse(resolve_session(self.stock, self.calendar, self.sessions, self.now)["tradable"])

    def test_full_day_coverage_resolves_offset_without_hiding_conflict(self):
        self.stock["tradingPeriod"] = ["pre_market", "regular", "after_hours", "overnight"]
        self.sessions = {"daylightType": "standard", "stateList": [
            {"state": "pre_market", "startTime": "04:00", "endTime": "09:30"},
            {"state": "regular", "startTime": "09:30", "endTime": "16:00"},
            {"state": "after_hours", "startTime": "16:00", "endTime": "20:00"},
            {"state": "overnight", "startTime": "20:00", "endTime": "04:00"}]}
        result = resolve_session(self.stock, self.calendar, self.sessions, self.now)
        self.assertTrue(result["tradable"])
        self.assertIn("metadata_warning", result)
        self.calendar["specificConfig"] = [{"startTime": "2026-09-16 09:00", "endTime": "2026-09-16 20:00"}]
        self.assertFalse(resolve_session(self.stock, self.calendar, self.sessions, self.now)["tradable"])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(":memory:", "DEMO_STOCK", mode="synthetic")

    def tearDown(self):
        self.engine.db.close()

    def test_quote_refresh_handles_latency_without_using_old_price(self):
        clock = [1000.0]
        packet = synthetic_packet(1000)
        def model(*args):
            clock[0] = 1020.0
            return synthetic_decision(*args)
        def quote():
            return {**packet["quote"], "timestamp": 1020.0}
        with patch("agent.time.time", side_effect=lambda: clock[0]):
            row = self.engine.step(packet, model, refresh_quote=quote)
        self.assertEqual(row["status"], "paper_filled")
        self.assertEqual(row["execution_packet"]["quote"]["timestamp"], 1020)

    def test_material_price_drift_rejects_old_thesis(self):
        packet = synthetic_packet()
        row = self.engine.step(packet, synthetic_decision, now=1000,
                               refresh_quote=lambda: {**packet["quote"], "bid": 105.0, "ask": 105.1})
        self.assertEqual(row["status"], "blocked")
        self.assertIn("tolerance", row["reason"])
        self.assertEqual(row["execution_packet"]["quote"]["bid"], 105)

    def test_holding_expiry_exits_without_an_llm_call(self):
        self.engine.step(synthetic_packet(), synthetic_decision, now=1000)
        packet = synthetic_packet(4700)
        packet["event_id"] = "monitor-expiry"
        row = self.engine.monitor(packet, now=4700)
        self.assertEqual(row["status"], "paper_filled")
        self.assertEqual(row["fill"]["side"], "sell")
        self.assertEqual(self.engine.state()["quantity"], 0)

    def test_stale_quotes_cannot_mark_portfolio(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            self.engine.mark(synthetic_packet()["quote"], now=2000)

    def test_demo_includes_all_six_distinct_outcomes(self):
        rows = mechanical_demo()["scenarios"]
        self.assertEqual([r["result"]["status"] for r in rows], ["paper_filled", "held", "blocked", "blocked", "blocked", "paper_filled"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = Application(self.directory.name)
        self.now = time.time()
        packet = synthetic_packet(self.now)
        self.event = {**packet["evidence"][0], "id": "test-event", "symbol": "RAAPLUSDT", "title": "Test event"}
        instrument = {**packet["instrument"], "symbol": "RAAPLUSDT"}
        quote = {**packet["quote"], "collected_at": self.now}
        self.market = {"RAAPLUSDT": {"symbol": "RAAPLUSDT", "instrument": instrument, "quote": quote, "session": {"tradable": True}}}
        class Model:
            model, endpoint = "TEST-DOUBLE-NOT-A-REAL-MODEL", "https://example.invalid/chat/completions"
            def __call__(self, packet, state, policy):
                return {**synthetic_decision(packet, state, policy), "source_ids": [packet["evidence"][0]["id"]]}
        self.app.model = Model()
        self.app.store.add([self.event])

    def tearDown(self):
        self.directory.cleanup()

    def test_complete_pipeline_and_comparison_with_explicit_test_double(self):
        with patch.object(self.app, "observe", return_value=self.market), \
             patch.object(self.app.market, "reference", return_value={"price": 99.5, "bar_close_at": self.now - 60}), \
             patch.object(self.app.market, "quote", return_value=self.market["RAAPLUSDT"]["quote"]):
            self.assertEqual(self.app.run_once(), 1)
            self.assertEqual(self.app.run_once(), 0)
        agent = self.app.ledger("RAAPLUSDT")
        baseline = self.app.ledger("RAAPLUSDT", "benchmark")
        self.assertEqual(agent["summary"]["fills"], 1)
        self.assertEqual(baseline["summary"]["decisions"], 1)
        self.assertIn("TEST-DOUBLE", agent["records"][0]["decision_provider"])

    def test_model_change_cannot_silently_contaminate_a_run(self):
        self.app.check_profile(self.app.model, save=True)
        self.app.model.model = "another-model"
        with self.assertRaisesRegex(ValueError, "another model"):
            self.app.check_profile(self.app.model)

    def test_no_model_prevents_paper_cycle(self):
        self.app.model = None
        with self.assertRaisesRegex(ValueError, "Connect an AI"):
            self.app.run_once()

    def test_old_news_is_not_presented_as_a_new_trade(self):
        self.app.policy = Policy(max_event_age_seconds=1)
        with patch.object(self.app, "observe", return_value=self.market):
            self.assertEqual(self.app.run_once(), 0)


if __name__ == "__main__":
    unittest.main()
