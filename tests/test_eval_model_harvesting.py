#!/usr/bin/env python3
"""
tests/test_eval_model_harvesting.py — Unit tests for the local model harvesting evaluation harness.
"""

import unittest
from unittest.mock import MagicMock, patch

import eval_model_harvesting


class TestEvalModelHarvesting(unittest.TestCase):
    def test_evaluate_fixtures_corpus_metrics(self):
        """Corpus evaluation verifies 100% schema validity on valid fixtures and 0 unsafe promotions."""
        metrics = eval_model_harvesting.evaluate_fixtures_corpus()
        self.assertGreaterEqual(metrics["total_fixtures"], 10)
        self.assertEqual(metrics["decision_unsafe_promotions"], 0)
        self.assertEqual(metrics["schema_valid_rate"], 1.0)
        self.assertEqual(metrics["unsupported_inference_rate"], 0.0)

    @patch("eval_model_harvesting.check_ollama_installed_models")
    def test_challenger_absence_never_auto_downloads(self, mock_installed):
        """When challenger qwen3.5:9b is not installed, it is reported without auto-download."""
        mock_installed.return_value = (True, ["qwen3:8b", "qwen3-embedding:0.6b"])

        report = eval_model_harvesting.run_evaluation(run_live=False)
        self.assertTrue(report["ollama_online"])
        self.assertTrue(report["baseline"]["installed"])
        self.assertFalse(report["challenger"]["installed"])
        self.assertFalse(report["challenger"]["evaluated"])
        self.assertFalse(report["baseline"]["evaluated"])
        self.assertIn("Auto-download is prohibited", report["challenger"]["reason"])
        self.assertEqual(report["recommendation"]["decision"], "insufficient_evidence")
        self.assertEqual(report["contract_fixture_checks"]["schema_valid_rate"], 1.0)

    @patch("eval_model_harvesting.check_ollama_installed_models")
    def test_ollama_offline_graceful_fallback(self, mock_installed):
        """When Ollama is offline, evaluation completes with fixtures corpus and offline status."""
        mock_installed.return_value = (False, [])

        report = eval_model_harvesting.run_evaluation(run_live=False)
        self.assertFalse(report["ollama_online"])
        self.assertFalse(report["baseline"]["evaluated"])
        self.assertEqual(report["contract_fixture_checks"]["decision_unsafe_promotions"], 0)
        self.assertEqual(report["recommendation"]["decision"], "insufficient_evidence")

    @patch("urllib.request.urlopen")
    def test_model_unload_protocol(self, mock_urlopen):
        """Unload sends keep_alive: 0 to /api/generate."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success = eval_model_harvesting.unload_ollama_model("qwen3:8b")
        self.assertTrue(success)
        self.assertTrue(mock_urlopen.called)
        req_arg = mock_urlopen.call_args[0][0]
        self.assertIn("/api/generate", req_arg.full_url)
        self.assertIn(b'"keep_alive": 0', req_arg.data)


if __name__ == "__main__":
    unittest.main()
