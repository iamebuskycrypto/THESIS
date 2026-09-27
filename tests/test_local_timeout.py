"""Regression checks for the local Ollama transport and evaluation boundaries."""
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from agent import Engine, LLM, synthetic_packet, synthetic_decision
from runner import Application


def response(content, reason="stop"):
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": reason,
        "message": {"content": json.dumps(content)}}]}).encode())


class LocalTransportTests(unittest.TestCase):
    def setUp(self):
        self.model = LLM("http://127.0.0.1:11434/v1/chat/completions", "qwen3:8b", "")

    def test_local_qwen_request_is_bounded_and_thinking_disabled(self):
        payload = {"model": "qwen3:8b", "messages": [], "temperature": 0}
        with patch("agent.urllib.request.urlopen", return_value=response({"status": "ready"})) as request:
            self.assertEqual(self.model._request(payload), {"status": "ready"})
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertEqual(body["max_tokens"], 1024)
        self.assertEqual(request.call_args.kwargs["timeout"], 180)
        self.assertNotIn("reasoning_effort", payload)

    def test_other_providers_do_not_receive_qwen_settings(self):
        model = LLM("https://example.invalid/v1/chat/completions", "other-model", "test-key")
        with patch("agent.urllib.request.urlopen", return_value=response({"status": "ready"})) as request:
            model._request({"messages": []})
        body = json.loads(request.call_args.args[0].data)
        self.assertNotIn("reasoning_effort", body)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(request.call_args.kwargs["timeout"], 45)

    def test_truncated_valid_json_is_rejected(self):
        with patch("agent.urllib.request.urlopen", return_value=response({"action": "hold"}, "length")):
            with self.assertRaisesRegex(RuntimeError, "output limit"):
                self.model._request({"messages": []})

    def test_timeout_is_actionable_without_request_data(self):
        for error in (TimeoutError("secret"), urllib.error.URLError(TimeoutError("secret"))):
            with self.subTest(error=type(error).__name__), patch("agent.urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "timed out after 180 seconds") as caught:
                    self.model._request({"messages": []})
                self.assertNotIn("secret", str(caught.exception))

    def test_http_error_hides_response_body(self):
        error = urllib.error.HTTPError(self.model.endpoint, 400, "secret", {}, io.BytesIO(b"secret"))
        with patch("agent.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400") as caught:
                self.model._request({"messages": []})
        self.assertNotIn("secret", str(caught.exception))

    def test_slow_model_still_requires_fresh_execution_quote(self):
        for refreshed, expected in ((False, "blocked"), (True, "paper_filled")):
            clock = [1000.0]
            packet = synthetic_packet(1000)
            def slow_request(*args, **kwargs):
                clock[0] = 1100.0
                return response(synthetic_decision(packet, {}, None))
            engine = Engine(":memory:", "DEMO_STOCK", mode="synthetic")
            try:
                with patch("agent.time.time", side_effect=lambda: clock[0]), patch("agent.urllib.request.urlopen", side_effect=slow_request):
                    result = engine.step(packet, self.model,
                        refresh_quote=(lambda: {**packet["quote"], "timestamp": clock[0]}) if refreshed else None)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["decision_request_settings"]["reasoning_effort"], "none")
            finally:
                engine.db.close()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = Application(self.directory.name)
        self.model = LLM("http://127.0.0.1:11434/v1/chat/completions", "qwen3:8b", "")
        self.app.check_profile(self.model, save=True)
        self.path = Path(self.directory.name) / "run-profile.json"
        self.original = json.loads(self.path.read_text())

    def tearDown(self):
        self.directory.cleanup()

    def legacy(self):
        legacy = copy.deepcopy(self.original)
        legacy.pop("request_settings")
        self.path.write_text(json.dumps(legacy))
        return legacy

    def test_legacy_monitoring_only_run_migrates_with_archive(self):
        legacy = self.legacy()
        engine = self.app.engine("RAAPLUSDT")
        engine.db.close()
        self.app.check_profile(self.model, save=True)
        self.assertEqual(json.loads(self.path.read_text()), self.original)
        archive = self.path.with_name("run-profile-before-local-fix.json")
        self.assertEqual(json.loads(archive.read_text()), legacy)

    def test_legacy_run_with_any_decision_record_cannot_migrate(self):
        legacy = self.legacy()
        engine = self.app.engine("RAAPLUSDT")
        engine.db.execute("INSERT INTO ledger VALUES (1, 'record', '{}', 'test')")
        engine.db.close()
        with self.assertRaisesRegex(ValueError, "another model"):
            self.app.check_profile(self.model, save=True)
        self.assertEqual(json.loads(self.path.read_text()), legacy)

    def test_changed_generation_settings_cannot_be_mixed(self):
        profile = copy.deepcopy(self.original)
        profile["request_settings"]["reasoning_effort"] = "high"
        self.path.write_text(json.dumps(profile))
        with self.assertRaises(ValueError):
            self.app.check_profile(self.model, save=True)
