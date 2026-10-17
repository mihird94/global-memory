#!/usr/bin/env python3
"""
tests/test_eval_model_harvesting.py — Unit tests for the local model harvesting evaluation harness
and retrieval sufficiency heuristic edge cases.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import context_retrieval_planner
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
        mock_installed.return_value = (True, [eval_model_harvesting.BASELINE_MODEL, "qwen3-embedding:0.6b"])

        report = eval_model_harvesting.run_evaluation(run_live=False)
        self.assertTrue(report["ollama_online"])
        self.assertTrue(report["baseline"]["installed"])
        self.assertFalse(report["challenger"]["installed"])
        self.assertFalse(report["challenger"]["evaluated"])
        self.assertFalse(report["baseline"]["evaluated"])
        self.assertIn("Auto-download is prohibited", report["challenger"]["reason"])
        self.assertEqual(report["recommendation"]["decision"], "insufficient_evidence")
        self.assertEqual(report["contract_fixture_checks"]["schema_valid_rate"], 1.0)
        self.assertIn("non_llm_regex_baseline", report)

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

    @patch("urllib.request.urlopen", side_effect=OSError("Connection refused"))
    def test_unreachable_ps_does_not_report_verified_unloaded(self, _mock_urlopen):
        """When /api/ps is unreachable, verified_unloaded must be False, not inferred True from empty list."""
        unloaded, reachable, models = eval_model_harvesting._verify_unload_state("qwen2.5-coder:7b")
        self.assertFalse(reachable)
        self.assertEqual(models, [])
        self.assertFalse(unloaded)

    def test_gold_harvest_corpus_spec(self):
        """Verify the integrity and structure of GOLD_HARVEST_CORPUS."""
        from tests.fixtures.harvest_fixtures import GOLD_HARVEST_CORPUS
        self.assertGreaterEqual(len(GOLD_HARVEST_CORPUS), 3)
        for case in GOLD_HARVEST_CORPUS:
            self.assertIn("id", case)
            self.assertIn("excerpt", case)
            self.assertIn("expected_candidates", case)
            self.assertGreater(len(case["expected_candidates"]), 0)
            self.assertIn("prohibited_extracts", case)

    def test_candidate_proxy_rejects_key_only_and_statement_only_rationale(self):
        """Key regex without required semantic keywords must not match, and rationale keywords in statement alone must not count."""
        expected = [
            {
                "key_pattern": r"retire_global_trust",
                "expected_type": "decision",
                "required_keywords": ["retire", "trust"],
                "rationale_keywords": ["collapses", "certainty"],
            }
        ]
        # Case 1: Key matches regex, but statement has wrong semantics (missing required_keywords)
        wrong_semantics = [
            {
                "record_type": "decision",
                "key": "retire_global_trust",
                "statement": "Unrelated statement about apples and oranges.",
                "rationale": "A single score collapses reliability into false certainty.",
            }
        ]
        res1 = eval_model_harvesting.score_candidate_proxies(expected, wrong_semantics)
        self.assertEqual(res1["true_positives"], 0)

        # Case 2: Required keywords present, rationale keywords placed in statement instead of rationale
        stmt_only_rat = [
            {
                "record_type": "decision",
                "key": "retire_global_trust",
                "statement": "Retire global trust because it collapses reliability into false certainty.",
                "rationale": "We decided to make this change today for simplicity.",
            }
        ]
        res2 = eval_model_harvesting.score_candidate_proxies(expected, stmt_only_rat)
        self.assertEqual(res2["true_positives"], 1)
        self.assertEqual(res2["rationale_matches"], 0)

    def test_graph_triple_scoring_requires_object_and_1to1_assignment(self):
        """Graph scoring must check subject, predicate, AND object, and enforce 1-to-1 matching."""
        expected = [
            ("agent trust", "retired_in", "mbrain"),
            ("sqlite", "uses", "wal mode"),
        ]
        # Wrong object ('postgres' instead of 'mbrain') must NOT match
        wrong_obj = [("agent trust", "retired_in", "postgres")]
        s1 = eval_model_harvesting.score_graph_triples_1to1(expected, wrong_obj)
        self.assertEqual(s1["matched_count"], 0)
        self.assertEqual(s1["recall"], 0.0)
        self.assertEqual(s1["precision"], 0.0)

        # Duplicate expected target cannot be satisfied twice by a single extracted triple
        dup_expected = [
            ("sqlite", "uses", "wal mode"),
            ("sqlite", "uses", "wal mode"),
        ]
        single_extracted = [("sqlite", "uses", "wal mode")]
        s2 = eval_model_harvesting.score_graph_triples_1to1(dup_expected, single_extracted)
        self.assertEqual(s2["matched_count"], 1)
        self.assertEqual(s2["recall"], 0.5)
        self.assertEqual(s2["precision"], 1.0)

    @patch("eval_model_harvesting.unload_ollama_model")
    @patch("eval_model_harvesting.get_loaded_models")
    @patch("urllib.request.urlopen")
    def test_evaluate_gold_extraction_mocked(self, mock_urlopen, mock_loaded, mock_unload):
        """Evaluate gold extraction scoring and 6-stage isolated storage audit against controlled mock responses."""
        mock_unload.return_value = True
        mock_loaded.return_value = []

        mock_payload = {
            "response": json.dumps({
                "schema_version": "gms-context-harvest-v1",
                "candidates": [
                    {
                        "schema_version": "gms-context-record-v1",
                        "record_type": "decision",
                        "key": "retire_global_trust",
                        "statement": "Retire global agent trust in Mbrain",
                        "rationale": "A single score collapses reliability and certainty.",
                        "implications": ["Show separate provenance and disputes."],
                        "scope": {"project": "global-memory"},
                        "provenance": {
                            "extractor": "DreamCycle-test",
                            "source_refs": ["episodic/test.md"],
                            "extracted_at": "2026-10-17T08:00:00Z"
                        },
                        "evidence": [{"type": "source_document", "ref": "episodic/test.md"}]
                    },
                    {
                        "schema_version": "gms-context-record-v1",
                        "record_type": "procedure",
                        "key": "sqlite_wal_setup",
                        "trigger": "When opening SQLite",
                        "action": "Use WAL mode and busy_timeout=5000",
                        "constraints": ["Prevent database lockouts"],
                        "scope": {"project": "global-memory"},
                        "provenance": {
                            "extractor": "DreamCycle-test",
                            "source_refs": ["episodic/test.md"],
                            "extracted_at": "2026-10-17T08:00:00Z"
                        }
                    },
                    {
                        "schema_version": "gms-context-record-v1",
                        "record_type": "fact",
                        "key": "api_secret",
                        "statement": "Refreshed sk-live-99238481923849182391283912839128",
                        "scope": {"project": "global-memory"},
                        "provenance": {
                            "extractor": "DreamCycle-test",
                            "source_refs": ["episodic/test.md"],
                            "extracted_at": "2026-10-17T08:00:00Z"
                        }
                    }
                ]
            }),
            "prompt_eval_count": 120,
            "eval_count": 85,
            "done_reason": "stop",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = eval_model_harvesting.evaluate_gold_extraction("test-model", run_graph=False)
        self.assertEqual(res["model"], "test-model")
        self.assertGreaterEqual(res["candidate_recall"], 0.5)
        self.assertGreater(res["raw_model_prohibited_leaks"], 0)
        self.assertEqual(res["durable_storage_prohibited_leaks"], 0)
        self.assertEqual(res["storage_boundary_audit"]["persisted_disk_readback"]["leaks"], 0)
        self.assertEqual(res["storage_boundary_audit"]["retrieved_output"]["leaks"], 0)
        self.assertTrue(res["verified_unloaded"])

    def test_classify_evidence_preserves_framing_words_when_sole_subject(self):
        """When framing words ('snapshot', 'retrieval') are the sole content tokens, they must not be stripped."""
        unrelated_items = [
            {
                "key": "db.postgres_port",
                "statement": "Postgres listens on port 5432.",
                "source_valid": True,
                "lifecycle_status": "accepted",
                "freshness_state": "current",
            }
        ]
        # Query where 'snapshot' is the only substantive subject word
        status, _ = context_retrieval_planner._classify_evidence(
            unrelated_items,
            query_tokens=["what", "was", "the", "snapshot"],
            intent="fact",
            project="",
        )
        self.assertEqual(status, "insufficient")

        # Matching item for 'snapshot'
        matching_items = [
            {
                "key": "storage.snapshot",
                "statement": "The snapshot is stored in ~/memories/backups.",
                "source_valid": True,
                "lifecycle_status": "accepted",
                "freshness_state": "current",
            }
        ]
        status2, _ = context_retrieval_planner._classify_evidence(
            matching_items,
            query_tokens=["what", "was", "the", "snapshot"],
            intent="fact",
            project="",
        )
        self.assertEqual(status2, "supported")

    def test_storage_boundary_deduplicated_denominators_and_graph_controls(self):
        """Storage audit separates JSON/SQLite denominators from unique records, and graph boundary controls verify positive/negative triples."""
        controls = eval_model_harvesting.evaluate_graph_boundary_controls()
        pos = controls["positive_control"]
        neg = controls["negative_secret_leak_control"]

        # Positive control: 2 gold triples matched, 1 wrong-object distractor rejected as FP
        self.assertTrue(pos["schema_valid"])
        self.assertEqual(pos["matched_count"], 2)
        self.assertEqual(pos["false_positives"], 1)
        self.assertAlmostEqual(pos["precision"], 0.6667, places=4)
        self.assertEqual(pos["recall"], 1.0)

        # Negative secret-leak graph control: 1 prohibited secret in raw graph is blocked at admission and disk persistence
        self.assertTrue(neg["schema_valid"])
        self.assertEqual(neg["raw_graph_leaks"], 1)
        self.assertEqual(neg["raw_graph_denominator"], 2)
        self.assertEqual(neg["admitted_graph_leaks"], 0)
        self.assertEqual(neg["admitted_graph_denominator"], 1)
        self.assertEqual(neg["persisted_sqlite_relationships_leaks"], 0)
        self.assertEqual(neg["persisted_sqlite_relationships_denominator"], 1)

        # Verify deduplicated denominator vs representation rows on candidate persistence
        sample_cand = [{"key": "k1", "record_type": "fact", "statement": "Clean statement"}]
        audit = eval_model_harvesting.verify_isolated_storage_boundary(
            case_id="dedup_test",
            raw_cands=sample_cand,
            admitted_cands=sample_cand,
            raw_graph_rels=[],
            admitted_graph_rels=[],
            prohibited=["sk-live-secret"],
        )
        self.assertEqual(audit["audit_scope"], "surrogate_isolated_persistence_and_readback_audit")
        self.assertEqual(audit["persisted_facts_json_readback"]["denominator"], 1)
        self.assertEqual(audit["persisted_sqlite_candidates_readback"]["denominator"], 1)
        # Unique persisted records is 1 (not 2!), while representation_rows_checked is 2
        self.assertEqual(audit["persisted_disk_readback"]["denominator"], 1)
        self.assertEqual(audit["persisted_disk_readback"]["unique_candidate_records"], 1)
        self.assertEqual(audit["persisted_disk_readback"]["representation_rows_checked"], 2)


if __name__ == "__main__":
    unittest.main()

