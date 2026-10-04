#!/usr/bin/env python3
"""
tests/test_local_harvest.py — Comprehensive Local Harvest Verification Suite.

Validates:
1. Explicit Ollama preflight with all 6 states:
   - service_unavailable
   - model_unavailable
   - generate_endpoint_failure
   - malformed_candidate_json
   - timeout
   - successful_extraction
2. Bounded timing telemetry (model_load, generation, validation, staging_preview, unload, total).
3. Explicit model unload protocol and confirmation on success, error, and timeout paths.
4. Dry-run immutability (zero mutation to facts.json, gms_trust.sqlite, dream_cycle_status.json, journal.md).
5. Acceptance rule: provider:none cannot be reported as completed.
6. Desktop API status normalization and telemetry fields.
7. Separately gated live qwen3:8b smoke check (MBRAIN_LIVE_SMOKE=1).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib import error

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

import dream_cycle
import gms_desktop_api
import memory_mcp_server
import ollama_preflight


class TestLocalHarvestPreflight(unittest.TestCase):
    """Test explicit Ollama preflight classification and timing telemetry."""

    def _sample_valid_response(self) -> dict:
        return {
            "response": json.dumps({
                "schema_version": "gms-context-harvest-v1",
                "candidates": [
                    {
                        "schema_version": "gms-context-record-v1",
                        "record_type": "decision",
                        "key": "test_preflight_decision",
                        "statement": "Enforce strict preflight classification.",
                        "rationale": "Clear failure modes prevent silent extraction failures.",
                        "implications": ["Check all 6 preflight states before execution."],
                        "scope": {"project": "global-memory", "level": "system"},
                        "provenance": {
                            "extractor": "preflight-test",
                            "source_refs": ["episodic/history/2026-09-28.md"],
                            "source_hashes": ["sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
                            "extracted_at": "2026-09-28T20:00:00Z",
                            "prompt_version": "context-harvest-v1",
                        },
                        "evidence": [
                            {"type": "source_document", "ref": "episodic/history/2026-09-28.md", "excerpt_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
                        ],
                    }
                ],
            }),
            "load_duration": 1500000000,   # 1.5s in ns
            "eval_duration": 3200000000,   # 3.2s in ns
            "total_duration": 4800000000,
        }

    @patch("ollama_preflight.check_ollama_service")
    def test_state_service_unavailable(self, mock_svc):
        mock_svc.return_value = (False, "Connection refused")
        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b")
        self.assertEqual(res["state"], "service_unavailable")
        self.assertFalse(res["ok"])
        self.assertIn("Connection refused", res["error"])
        self.assertIn("total", res["duration_breakdown"])

    @patch("ollama_preflight.check_model_available")
    @patch("ollama_preflight.check_ollama_service")
    def test_state_model_unavailable(self, mock_svc, mock_model):
        mock_svc.return_value = (True, None)
        mock_model.return_value = (False, ["qwen3-embedding:0.6b"])
        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b")
        self.assertEqual(res["state"], "model_unavailable")
        self.assertFalse(res["ok"])
        self.assertIn("not installed", res["error"])
        self.assertIn("Prohibited from auto-downloading", res["error"])

    @patch("ollama_preflight.confirm_model_unload")
    @patch("urllib.request.urlopen")
    @patch("ollama_preflight.check_model_available")
    @patch("ollama_preflight.check_ollama_service")
    def test_state_generate_endpoint_failure(self, mock_svc, mock_model, mock_url, mock_unload):
        mock_svc.return_value = (True, None)
        mock_model.return_value = (True, ["qwen3:8b"])
        mock_url.side_effect = error.HTTPError("http://127.0.0.1:11434/api/generate", 500, "Internal Server Error", {}, None)
        mock_unload.return_value = {"requested": True, "command_sent": True, "confirmed": True, "active_models": []}

        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b")
        self.assertEqual(res["state"], "generate_endpoint_failure")
        self.assertFalse(res["ok"])
        # Unload must be requested and confirmed
        mock_unload.assert_called_once()
        self.assertTrue(res["unload_state"]["confirmed"])

    @patch("ollama_preflight.confirm_model_unload")
    @patch("urllib.request.urlopen")
    @patch("ollama_preflight.check_model_available")
    @patch("ollama_preflight.check_ollama_service")
    def test_state_timeout(self, mock_svc, mock_model, mock_url, mock_unload):
        mock_svc.return_value = (True, None)
        mock_model.return_value = (True, ["qwen3:8b"])
        mock_url.side_effect = socket.timeout("timed out")
        mock_unload.return_value = {"requested": True, "command_sent": True, "confirmed": True, "active_models": []}

        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b", timeout=5.0)
        self.assertEqual(res["state"], "timeout")
        self.assertFalse(res["ok"])
        self.assertIn("timed out", res["error"])
        mock_unload.assert_called_once()
        self.assertTrue(res["unload_state"]["confirmed"])

    @patch("ollama_preflight.confirm_model_unload")
    @patch("urllib.request.urlopen")
    @patch("ollama_preflight.check_model_available")
    @patch("ollama_preflight.check_ollama_service")
    def test_state_malformed_candidate_json(self, mock_svc, mock_model, mock_url, mock_unload):
        mock_svc.return_value = (True, None)
        mock_model.return_value = (True, ["qwen3:8b"])
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "response": "This is plain text with no JSON at all.",
            "load_duration": 1000000000,
            "eval_duration": 2000000000,
        }).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp
        mock_unload.return_value = {"requested": True, "command_sent": True, "confirmed": True, "active_models": []}

        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b")
        self.assertEqual(res["state"], "malformed_candidate_json")
        self.assertFalse(res["ok"])
        mock_unload.assert_called_once()

    @patch("ollama_preflight.confirm_model_unload")
    @patch("urllib.request.urlopen")
    @patch("ollama_preflight.check_model_available")
    @patch("ollama_preflight.check_ollama_service")
    def test_state_successful_extraction_and_telemetry(self, mock_svc, mock_model, mock_url, mock_unload):
        mock_svc.return_value = (True, None)
        mock_model.return_value = (True, ["qwen3:8b"])
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(self._sample_valid_response()).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp
        mock_unload.return_value = {"requested": True, "command_sent": True, "confirmed": True, "active_models": []}

        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b")
        self.assertEqual(res["state"], "successful_extraction")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["candidates"]), 1)
        self.assertEqual(res["candidates"][0]["key"], "test_preflight_decision")

        # Telemetry validation
        dur = res["duration_breakdown"]
        self.assertEqual(dur["model_load"], 1.5)
        self.assertEqual(dur["generation"], 3.2)
        self.assertGreaterEqual(dur["validation"], 0.0)
        self.assertGreaterEqual(dur["staging_preview"], 0.0)
        self.assertGreaterEqual(dur["unload"], 0.0)
        self.assertGreater(dur["total"], 0.0)

        # Unload confirmation
        self.assertTrue(res["unload_state"]["confirmed"])


class TestDryRunZeroMutation(unittest.TestCase):
    """Test that dry-run produces machine-readable reports without mutating live memory stores."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.old_dream_root = dream_cycle.MEM_ROOT
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_mcp_db = memory_mcp_server.DB_PATH
        dream_cycle.MEM_ROOT = self.mem_root
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.mem_root / "gms_trust.sqlite"


        # Seed sample note
        history_dir = self.mem_root / "episodic" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self.today_file = history_dir / f"{today}.md"
        self.today_file.write_text(f"# {today} Work Log\nConfigured WAL mode.\n", encoding="utf-8")

        # Seed facts.json and gms_trust.sqlite
        facts_dir = self.mem_root / "semantic"
        facts_dir.mkdir(parents=True, exist_ok=True)
        self.facts_path = facts_dir / "facts.json"
        self.facts_path.write_text(json.dumps({"existing_fact": "value"}), encoding="utf-8")

        self.db_path = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.init_db(self.db_path)

        self.status_file = self.mem_root / "logs" / "dream_cycle_status.json"

    def tearDown(self):
        dream_cycle.MEM_ROOT = self.old_dream_root
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_mcp_db
        self.temp_dir.cleanup()

    def _file_hash(self, path: Path) -> str:
        if not path.exists():
            return "absent"
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_dry_run_immutability_and_report_file(self):
        h_facts = self._file_hash(self.facts_path)
        h_db = self._file_hash(self.db_path)
        h_note = self._file_hash(self.today_file)

        report_out = self.mem_root / "test_report.json"

        mock_candidate = {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "test_immutability_decision",
            "statement": "Verify zero mutations.",
            "rationale": "Dry-run verification must leave live memory untouched.",
            "implications": ["Assert before and after hashes match."],
            "scope": {"project": "global-memory", "level": "system"},
            "provenance": {
                "extractor": "TestExtractor",
                "extracted_at": "2026-09-28T20:00:00Z",
                "source_refs": ["episodic/history/2026-09-28.md"],
                "source_hashes": ["sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
            },
            "evidence": [{"type": "source_document", "ref": "episodic/history/2026-09-28.md"}],
        }

        with patch("dream_cycle.extract_candidates_with_cascade", return_value=([mock_candidate], "ollama")), \
             patch("dream_cycle.confirm_ollama_unload", return_value={"requested": True, "command_sent": True, "confirmed": True, "active_models": []}):
            exit_code = dream_cycle.main(["--dry-run", "--report", str(report_out)])
            self.assertEqual(exit_code, 0)

        # 1. Assert zero files were mutated
        self.assertEqual(self._file_hash(self.facts_path), h_facts, "facts.json must not be mutated")
        self.assertEqual(self._file_hash(self.db_path), h_db, "gms_trust.sqlite must not be mutated")
        self.assertEqual(self._file_hash(self.today_file), h_note, "journal notes must not be mutated")
        self.assertFalse(self.status_file.exists(), "production dream_cycle_status.json must NOT be written in dry run")

        # 2. Assert machine-readable report was produced
        self.assertTrue(report_out.exists(), "Requested report file must exist")
        rep = json.loads(report_out.read_text(encoding="utf-8"))
        self.assertTrue(rep.get("dry_run"))
        self.assertEqual(rep.get("durable_writes"), 0)
        self.assertEqual(rep.get("provider"), "ollama")
        self.assertIn("test_immutability_decision", rep.get("candidates_would_stage", []))
        self.assertIn("duration_breakdown", rep)
        self.assertTrue(rep["model_unload"]["confirmed"])

    def test_provider_none_never_reported_as_completed(self):
        """When no provider succeeds or provider is none, status must be degraded, never completed."""
        report_out = self.mem_root / "failed_report.json"

        with patch("dream_cycle.extract_candidates_with_cascade", return_value=([], "none")), \
             patch("dream_cycle.confirm_ollama_unload", return_value={"requested": True, "command_sent": True, "confirmed": True, "active_models": []}):
            exit_code = dream_cycle.main(["--dry-run", "--report", str(report_out)])
            self.assertEqual(exit_code, 0)

        rep = json.loads(report_out.read_text(encoding="utf-8"))
        self.assertEqual(rep.get("provider"), "none")
        self.assertEqual(rep.get("status"), "degraded", "provider:none run MUST NOT be marked completed")
        self.assertIsNotNone(rep.get("degraded_reason"))


class TestDesktopApiAndUIContracts(unittest.TestCase):
    """Test desktop API status normalization and contract guarantees."""

    def setUp(self):
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_mcp_db = memory_mcp_server.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.logs_dir = self.mem_root / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.logs_dir / "dream_cycle_status.json"
        self.api = gms_desktop_api.GMSDesktopAPI(mem_root=self.mem_root)

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_mcp_db
        self.temp_dir.cleanup()

    def test_get_dream_cycle_status_defaults(self):
        st = self.api.get_dream_cycle_status()
        self.assertEqual(st["status"], "idle")
        self.assertEqual(st["configured_model"], "qwen3:8b")
        self.assertIn("duration_breakdown", st)
        self.assertIn("model_unload", st)

    def test_legacy_status_provider_none_normalized_to_degraded(self):
        # Seed a legacy status that claimed status=completed with provider=none
        legacy = {
            "timestamp": "2026-09-28 03:10:02",
            "status": "completed",
            "provider": "none",
            "facts_promoted": 0,
            "duration_seconds": 12.5,
        }
        self.status_file.write_text(json.dumps(legacy), encoding="utf-8")

        st = self.api.get_dream_cycle_status()
        self.assertEqual(st["status"], "degraded", "Desktop API must reject provider:none as completed")
        self.assertIn("provider: none", st["degraded_reason"])
        self.assertEqual(st["configured_model"], "qwen3:8b")
        self.assertIn("duration_breakdown", st)
        self.assertIn("model_unload", st)


class TestLiveSmokeCommandGated(unittest.TestCase):
    """Separately gated live smoke command test against live Ollama qwen3:8b."""

    @unittest.skipUnless(os.environ.get("MBRAIN_LIVE_SMOKE") == "1", "Gated live smoke: run with MBRAIN_LIVE_SMOKE=1")
    def test_live_qwen3_smoke_run(self):
        res = ollama_preflight.run_ollama_preflight(model_name="qwen3:8b", timeout=60.0)
        self.assertTrue(res["ok"], f"Live smoke check failed: state={res['state']}, error={res['error']}")
        self.assertEqual(res["state"], "successful_extraction")
        self.assertTrue(res["unload_state"]["confirmed"], "Model must be confirmed unloaded")
        self.assertGreater(len(res["candidates"]), 0)


if __name__ == "__main__":
    unittest.main()
