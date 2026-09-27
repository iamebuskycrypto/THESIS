import copy
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Engine, LLM, Policy, synthetic_decision, synthetic_packet


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(":memory:", "DEMO_STOCK", mode="synthetic")
        self.packet = synthetic_packet()

    def tearDown(self):
        self.engine.db.close()

    def execute(self, decision=None, packet=None):
        d = decision or synthetic_decision(self.packet, {}, Policy())
        return self.engine.step(packet or self.packet, lambda *_: d, now=1000.0)

    def test_fill_charges_fee_and_adverse_slippage(self):
        row = self.execute()
        self.assertEqual(row["status"], "paper_filled")
        self.assertGreater(row["fill"]["price"], self.packet["quote"]["ask"])
        self.assertAlmostEqual(row["after"]["cash"], 10000 - row["fill"]["notional"] - row["fill"]["fee"])
        self.assertLess(row["marked_equity"], 10000)

    def test_duplicate_is_idempotent_even_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.db")
            a = Engine(path, "DEMO_STOCK", mode="synthetic")
            a.step(self.packet, synthetic_decision, now=1000)
            first = a.state()
            a.db.close()
            b = Engine(path, "DEMO_STOCK", mode="synthetic")
            def must_not_run(*_):
                self.fail("Duplicate triggered a second decision")
            self.assertEqual(b.step(self.packet, must_not_run, now=1000)["status"], "duplicate")
            self.assertEqual(b.state(), first)
            self.assertEqual(len(b.export()), 1)
            b.db.close()

    def test_stale_quote_prevents_model_call(self):
        self.packet["quote"]["timestamp"] = 900
        result = self.engine.step(self.packet, lambda *_: self.fail("Model called on stale data"), now=1000)
        self.assertIn("Stale", result["reason"])
        self.assertEqual(self.engine.state()["quantity"], 0)

    def test_latency_can_expire_quote(self):
        clock = [1000.0]
        def slow_model(*args):
            clock[0] = 1030.0
            return synthetic_decision(*args)
        with patch("agent.time.time", side_effect=lambda: clock[0]):
            result = self.engine.step(self.packet, slow_model)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.engine.state()["quantity"], 0)

    def test_future_evidence_is_rejected(self):
        self.packet["evidence"][0]["observed_at"] = 1001
        self.assertIn("Future", self.execute()["reason"])

    def test_unknown_citation_is_rejected(self):
        decision = synthetic_decision(self.packet, {}, Policy())
        decision["source_ids"] = ["invented-source"]
        self.assertIn("Unknown evidence", self.execute(decision)["reason"])

    def test_risk_limit_cannot_be_overridden_by_model(self):
        decision = synthetic_decision(self.packet, {}, Policy())
        decision["target_weight"] = 0.8
        self.assertIn("Position cap", self.execute(decision)["reason"])

    def test_costs_can_eliminate_proposed_trade(self):
        decision = synthetic_decision(self.packet, {}, Policy())
        decision["expected_remaining_move_bps"] = 25
        self.assertIn("cost buffer", self.execute(decision)["reason"])

    def test_missing_liquidity_blocks_fills(self):
        self.packet["quote"]["ask_size"] = 1
        self.assertIn("liquidity", self.execute()["reason"])

    def test_nan_model_output_is_rejected(self):
        decision = synthetic_decision(self.packet, {}, Policy())
        decision["target_weight"] = math.nan
        self.assertIn("Non-finite", self.execute(decision)["reason"])

    def test_unrecognized_action_is_rejected(self):
        decision = synthetic_decision(self.packet, {}, Policy())
        decision["action"] = "withdraw"
        self.assertIn("Unsupported action", self.execute(decision)["reason"])

    def test_drawdown_blocks_new_exposure_but_permits_exit(self):
        self.execute()
        packet = copy.deepcopy(self.packet)
        packet.update(event_id="loss-event")
        packet["quote"].update(bid=50.0, ask=50.02)
        self.assertIn("Drawdown halt", self.execute(packet=packet)["reason"])
        packet["event_id"] = "exit-event"
        decision = synthetic_decision(packet, {}, Policy())
        decision.update(action="sell", target_weight=0.0)
        row = self.execute(decision, packet)
        self.assertEqual(row["status"], "paper_filled")
        self.assertLess(row["after"]["quantity"], 0.00011)

    def test_synthetic_and_observed_modes_cannot_mix(self):
        self.packet["evidence_mode"] = "observed"
        self.assertIn("mode", self.execute()["reason"])

    def test_provider_failure_does_not_trade(self):
        def failure(*_):
            raise RuntimeError("LLM call failed")
        row = self.engine.step(self.packet, failure, now=1000)
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(self.engine.state()["cash"], 10000)

    def test_edited_ledger_is_detected(self):
        self.execute()
        self.engine.db.execute("UPDATE ledger SET body=replace(body, '10000.0', '10001.0')")
        with self.assertRaisesRegex(ValueError, "hash chain"):
            self.engine.export()

    def test_closed_session_blocks_order(self):
        self.packet["session_tradable"] = False
        self.assertIn("Session", self.execute()["reason"])


class LLMConfigurationTests(unittest.TestCase):
    def test_online_provider_requires_https_and_key(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            LLM(endpoint="http://example.invalid/chat/completions", model="test", key="key")
        with self.assertRaisesRegex(ValueError, "API key"):
            LLM(endpoint="https://example.invalid/chat/completions", model="test", key="")
        with self.assertRaisesRegex(ValueError, "this computer"):
            LLM(endpoint="https://key@example.invalid/chat/completions", model="test", key="key")

    def test_loopback_model_can_connect_without_a_key(self):
        model = LLM(endpoint="http://127.0.0.1:11434/v1/chat/completions", model="local-model", key="")
        self.assertTrue(model.local)
        response = json.dumps({"choices": [{"message": {"content": "```json\n{\"status\":\"ready\"}\n```"}}]}).encode()
        with patch("agent.urllib.request.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = io.BytesIO(response)
            self.assertEqual(model._request({"model": "local-model"}), {"status": "ready"})
            request = open_url.call_args.args[0]
        self.assertNotIn("Authorization", dict(request.header_items()))


if __name__ == "__main__":
    unittest.main()
