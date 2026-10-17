"""Tests for GMS Pass 10: Live Context Integrity and Evaluation Honesty."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest

from dream_cycle import (
    _evaluate_provider_attempt,
    _redact_safe_message,
    write_dream_cycle_status,
)
from project_context_reconciliation import (
    build_project_context_reconciliation,
    apply_project_context_reconciliation,
)
from task_readiness import check_task_readiness
from context_retrieval_planner import retrieve
from project_briefing import generate_project_briefing
from resumption_eval import run_resumption_evaluation


@pytest.fixture
def temp_memory_root(tmp_path: Path):
    root = tmp_path / "memories"
    root.mkdir(parents=True, exist_ok=True)
    (root / "semantic").mkdir(parents=True, exist_ok=True)
    (root / "episodic").mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(parents=True, exist_ok=True)
    (root / "lessons").mkdir(parents=True, exist_ok=True)
    (root / "daily").mkdir(parents=True, exist_ok=True)

    db_path = root / "gms_trust.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            supersedes_claim_id INTEGER,
            review_status TEXT DEFAULT 'accepted'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_procedures (
            procedure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            "trigger" TEXT,
            action TEXT,
            context TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_relationships (
            relationship_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            target_id TEXT,
            predicate TEXT,
            confidence REAL DEFAULT 1.0,
            valid_from TEXT,
            valid_to TEXT,
            context TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_tasks (
            task_id TEXT PRIMARY KEY,
            project TEXT,
            title TEXT,
            status TEXT,
            owner TEXT,
            created_at TEXT,
            updated_at TEXT,
            blockers TEXT,
            acceptance_criteria TEXT,
            next_action TEXT,
            revision INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            task_id TEXT,
            project TEXT,
            summary TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_handoffs (
            handoff_id TEXT PRIMARY KEY,
            task_id TEXT,
            project TEXT,
            from_agent TEXT,
            to_agent TEXT,
            created_at TEXT,
            status TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gms_reconciliation_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT,
            actor TEXT,
            rationale TEXT,
            snapshot_hash TEXT,
            applied_at TEXT,
            diff_applied TEXT
        )
    """)
    conn.commit()
    conn.close()

    (root / "semantic" / "facts.json").write_text("{}", encoding="utf-8")
    return root


# ──────────────────────────────────────────────────────────────────────────────
# P0: Dream Cycle Attempt Diagnostics
# ──────────────────────────────────────────────────────────────────────────────

def test_dream_cycle_evaluate_provider_attempt_classifications(monkeypatch):
    import dream_cycle

    # 1. Unknown provider
    cands, att = _evaluate_provider_attempt("unknown_prov", "prompt", "ref", "hash")
    assert att["outcome"] == "unavailable"
    assert att["error_code"] == "UNKNOWN_PROVIDER"

    # 2. Unavailable: Antigravity binary not found
    monkeypatch.setattr(dream_cycle, "AGY_BIN", "/nonexistent/agy")
    cands, att = _evaluate_provider_attempt("antigravity", "prompt", "ref", "hash")
    assert att["outcome"] == "unavailable"
    assert att["error_code"] == "BINARY_NOT_FOUND"

    # 3. Success with mock tier fn
    mock_candidate = {
        "schema_version": "gms-context-record-v1",
        "record_type": "fact",
        "key": "test_fact_key",
        "statement": "Valid statement",
        "scope": {"project": "global-memory"},
        "provenance": {
            "extractor": "mock",
            "source_refs": ["ref"],
            "extracted_at": "2026-10-05T00:00:00Z",
            "prompt_version": "v1",
        },
        "evidence": [{"type": "source_document", "ref": "ref"}],
    }
    monkeypatch.setitem(dream_cycle.TIER_FNS, "mock_tier", lambda p: [mock_candidate])
    cands, att = _evaluate_provider_attempt("mock_tier", "prompt", "ref", "hash")
    assert att["outcome"] == "success"
    assert att["candidate_count"] == 1
    assert att["error_code"] is None

    # 4. Timeout
    def timeout_fn(p):
        import subprocess
        raise subprocess.TimeoutExpired(cmd="mock", timeout=10)
    monkeypatch.setitem(dream_cycle.TIER_FNS, "mock_tier", timeout_fn)
    cands, att = _evaluate_provider_attempt("mock_tier", "prompt", "ref", "hash")
    assert att["outcome"] == "timeout"
    assert att["error_code"] == "TIMEOUT"

    # 5. Invalid JSON output
    def bad_json_fn(p):
        import json
        raise json.JSONDecodeError("Unterminated string", "{", 1)
    monkeypatch.setitem(dream_cycle.TIER_FNS, "mock_tier", bad_json_fn)
    cands, att = _evaluate_provider_attempt("mock_tier", "prompt", "ref", "hash")
    assert att["outcome"] == "invalid_output"
    assert att["error_code"] == "INVALID_JSON"

    # 6. Schema rejected
    invalid_candidate = {"invalid": "missing_keys"}
    monkeypatch.setitem(dream_cycle.TIER_FNS, "mock_tier", lambda p: [invalid_candidate])
    cands, att = _evaluate_provider_attempt("mock_tier", "prompt", "ref", "hash")
    assert att["outcome"] == "schema_rejected"
    assert att["error_code"] == "SCHEMA_VALIDATION_FAILED"

    # 7. Empty candidates
    monkeypatch.setitem(dream_cycle.TIER_FNS, "mock_tier", lambda p: [])
    cands, att = _evaluate_provider_attempt("mock_tier", "prompt", "ref", "hash")
    assert att["outcome"] == "empty"
    assert att["error_code"] == "ZERO_CANDIDATES"


def test_dream_cycle_sensitive_text_redaction():
    leak_text = "Failed with token Bearer sk-ant-api03-1234567890abcdef and password=SuperSecretPassword123"
    redacted = _redact_safe_message(leak_text)
    assert "sk-ant" not in redacted
    assert "SuperSecretPassword123" not in redacted
    assert "[REDACTED]" in redacted


def test_dream_cycle_dry_run_preserves_production_status(temp_memory_root: Path, monkeypatch):
    import dream_cycle
    monkeypatch.setattr(dream_cycle, "MEM_ROOT", temp_memory_root)

    status_file = temp_memory_root / "logs" / "dream_cycle_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    prod_status = {
        "status": "degraded",
        "configured_model": "qwen3:8b",
        "provider": "none",
        "provider_attempts": [
            {
                "provider": "ollama",
                "model": "qwen3:8b",
                "outcome": "unavailable",
                "duration_seconds": 0.5,
                "candidate_count": 0,
                "error_code": "UNAVAILABLE",
                "safe_message": "Service unavailable",
            }
        ],
    }
    status_file.write_text(json.dumps(prod_status), encoding="utf-8")

    # Attempt to write a dry run status
    dry_run_status = {
        "status": "completed",
        "dry_run": True,
        "durable_writes": 0,
        "provider": "mock",
    }
    dream_cycle.write_dream_cycle_status(dry_run_status)

    # The production status file on disk must not have been overwritten with dry run state
    on_disk = json.loads(status_file.read_text(encoding="utf-8"))
    assert on_disk["provider_attempts"][0]["error_code"] == "UNAVAILABLE"
    assert on_disk["status"] == "degraded"


def test_harvest_status_cli_and_desktop_api_agree_on_attempts(temp_memory_root: Path, monkeypatch, capsys):
    """The CLI and Desktop API expose the same safe persisted attempt summary."""
    from gms_desktop_api import GMSDesktopAPI
    import memoryctl
    import memory_mcp_server
    import gms_inspect

    attempts = [{
        "provider": "ollama",
        "model": "qwen3:8b",
        "outcome": "unavailable",
        "duration_seconds": 0.2,
        "candidate_count": 0,
        "error_code": "SERVICE_UNAVAILABLE",
        "safe_message": "Ollama service unreachable",
    }]
    logs = temp_memory_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "dream_cycle_status.json").write_text(json.dumps({
        "status": "degraded",
        "provider": "none",
        "configured_model": "qwen3:8b",
        "provider_attempts": attempts,
    }), encoding="utf-8")

    # Avoid the constructor here: it deliberately repoints process-global MCP
    # paths for the desktop process, which would leak into the legacy suite.
    api = object.__new__(GMSDesktopAPI)
    api.mem_root = temp_memory_root
    api.db_path = temp_memory_root / "gms_trust.sqlite"
    api.get_effective_launchd_schedule = lambda: "Unavailable"
    api_status = api.get_harvest_status()
    assert api_status["provider_attempts"] == attempts

    # The real CLI constructs GMSDesktopAPI, whose process-wide compatibility
    # behavior repoints these collaborators. Register their original values
    # with monkeypatch so this integration assertion cannot leak into the
    # older unittest fixture suite that follows it.
    monkeypatch.setattr(memory_mcp_server, "MEM_ROOT", memory_mcp_server.MEM_ROOT)
    monkeypatch.setattr(memory_mcp_server, "DB_PATH", memory_mcp_server.DB_PATH)
    monkeypatch.setattr(gms_inspect, "MEM_ROOT", gms_inspect.MEM_ROOT)
    monkeypatch.setattr(gms_inspect, "DB_PATH", gms_inspect.DB_PATH)
    monkeypatch.setattr(memoryctl, "MEM_ROOT", temp_memory_root)
    assert memoryctl.cmd_harvest_status(SimpleNamespace(diagnose=True)) == 0
    cli_status = json.loads(capsys.readouterr().out)
    assert cli_status["provider_attempts"] == attempts


# ──────────────────────────────────────────────────────────────────────────────
# P0: Project Context Freshness & Reconciliation
# ──────────────────────────────────────────────────────────────────────────────

def test_project_context_reconciliation_behind_and_missing_task(temp_memory_root: Path):
    proj_dir = temp_memory_root / "projects" / "myproj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "activeContext.md").write_text("""# Active Context
Last updated: 2026-09-01T10:00:00Z

## Next Action
Implement v1 architecture.
""", encoding="utf-8")

    # Newer episode at 2026-10-01
    (temp_memory_root / "episodic" / "2026-10-01_deploy.md").write_text("""# Episode 2026-10-01
Project: myproj
Successfully deployed v2.0 milestone to staging.
""", encoding="utf-8")

    preview = build_project_context_reconciliation(temp_memory_root, "myproj")
    assert preview["freshness"] == "behind"
    assert preview["latest_evidence_at"] >= "2026-10-01"
    assert any(g["field"] in ("project_bank_freshness", "timeline") for g in preview["gaps"])
    assert any(g["field"] == "active_work" for g in preview["gaps"])
    assert preview["apply_supported"] is False
    assert preview["snapshot_hash"].startswith("sha256:")


def test_project_context_reconciliation_irrelevant_project_episode(temp_memory_root: Path):
    proj_dir = temp_memory_root / "projects" / "myproj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "activeContext.md").write_text("""# Active Context
Last updated: 2026-10-02T10:00:00Z
""", encoding="utf-8")

    # Newer episode for another project
    (temp_memory_root / "episodic" / "2026-10-04_other.md").write_text("""# Episode
Project: other-proj
Work on something else.
""", encoding="utf-8")

    preview = build_project_context_reconciliation(temp_memory_root, "myproj")
    # Should not be behind because the other episode does not mention myproj
    assert preview["freshness"] != "behind"


def test_project_context_reconciliation_current_is_deterministic_and_read_only(temp_memory_root: Path):
    proj_dir = temp_memory_root / "projects" / "myproj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "activeContext.md").write_text(
        "# Active Context\nLast updated: 2026-10-04T10:00:00Z\n",
        encoding="utf-8",
    )
    (temp_memory_root / "episodic" / "2026-10-04_myproj.md").write_text(
        "# Episode\nProject: myproj\nCompleted verified milestone.\n",
        encoding="utf-8",
    )

    before = (temp_memory_root / "gms_trust.sqlite").read_bytes()
    first = build_project_context_reconciliation(temp_memory_root, "myproj")
    second = build_project_context_reconciliation(temp_memory_root, "myproj")
    after = (temp_memory_root / "gms_trust.sqlite").read_bytes()

    assert first == second
    assert first["freshness"] == "current"
    assert before == after


def test_project_context_apply_guards(temp_memory_root: Path):
    proj_dir = temp_memory_root / "projects" / "myproj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "activeContext.md").write_text("""# Active Context
Last updated: 2026-09-01
""", encoding="utf-8")

    preview = build_project_context_reconciliation(temp_memory_root, "myproj")
    correct_hash = preview["snapshot_hash"]

    # Reject unknown actor
    res = apply_project_context_reconciliation(
        temp_memory_root, "myproj",
        actor="unknown_agent",
        rationale="Detailed valid rationale for applying reconciliation",
        expected_snapshot_hash=correct_hash,
    )
    assert res["applied"] is False
    assert "not a registered" in res["reason"]

    # Reject short rationale
    res = apply_project_context_reconciliation(
        temp_memory_root, "myproj",
        actor="mihir",
        rationale="too short",
        expected_snapshot_hash=correct_hash,
    )
    assert res["applied"] is False
    assert "substantive characters" in res["reason"]

    # Reject stale snapshot hash
    res = apply_project_context_reconciliation(
        temp_memory_root, "myproj",
        actor="mihir",
        rationale="Detailed valid rationale for applying reconciliation",
        expected_snapshot_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert res["applied"] is False
    assert "snapshot hash" in res["reason"].lower() or "optimistic concurrency" in res["reason"].lower()


# ──────────────────────────────────────────────────────────────────────────────
# P1: Current-Context Ranking & Historical Retrieval
# ──────────────────────────────────────────────────────────────────────────────

def test_context_ranking_effective_recency_boost_and_historical_isolation(temp_memory_root: Path):
    proj_dir = temp_memory_root / "projects" / "global-memory"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "activeContext.md").write_text("""# Active Context
### Update 2026-09-09
Architecture decisions for v2.1.0 rollout and storage indexing.

### Update 2026-10-04
Architecture decisions for Pass 8 and Pass 9 context retrieval integrity.
""", encoding="utf-8")

    # Current context query: Oct 4 update should win over Sep 9
    pkt_current = retrieve(
        temp_memory_root,
        query="current global-memory architecture decisions and updates",
        project="global-memory",
    )
    assert len(pkt_current["items"]) > 0
    top_item = pkt_current["items"][0]
    assert "2026-10-04" in top_item["statement"] or "Pass 8" in top_item["statement"]
    assert pkt_current["manifest"]["recency_boost_applied"] is True

    # Historical query: as_of="2026-09-15": Oct 4 update must be omitted
    pkt_hist = retrieve(
        temp_memory_root,
        query="global-memory architecture decisions as of 2026-09-15",
        project="global-memory",
        as_of="2026-09-15",
    )
    assert pkt_hist["manifest"]["recency_boost_applied"] is False
    for it in pkt_hist["items"]:
        assert "2026-10-04" not in it.get("statement", "")


def test_context_ranking_missing_active_task_reported(temp_memory_root: Path):
    pkt = retrieve(
        temp_memory_root,
        query="resume active task and next action",
        project="global-memory",
    )
    assert pkt["manifest"]["active_task_continuity"] is False
    assert pkt["manifest"]["task_continuity_status"] == "missing_active_task"
    assert "No active task" in pkt["manifest"]["next_action_fallback"]


def test_project_briefing_excludes_unaffined_legacy_current_truth(temp_memory_root: Path):
    """Generic legacy retrieval matches must not pollute a project's briefing."""
    project_dir = temp_memory_root / "projects" / "global-memory"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "projectBrief.md").write_text(
        "# Global Memory\n\n## Overview\nA local context engineering system.\n",
        encoding="utf-8",
    )
    (temp_memory_root / "semantic" / "facts.json").write_text(json.dumps({
        # This mimics the real failure: generic query words score, while the
        # source/key do not establish any global-memory relationship.
        "test_proj.lesson.keyerror_missing_cfg": "Current truth status for a fixture-only test project.",
        # A legacy record with an explicit Mbrain identifier remains eligible.
        "mbrain.runtime.status": "Current Mbrain runtime context is local-first.",
    }), encoding="utf-8")

    briefing = generate_project_briefing(temp_memory_root, "global-memory", profile="condensed")
    truth_keys = {item["key"] for item in briefing["current_truth"]}
    assert "test_proj.lesson.keyerror_missing_cfg" not in truth_keys
    assert "mbrain.runtime.status" in truth_keys


# ──────────────────────────────────────────────────────────────────────────────
# P1: Decision-Useful Evaluation Reporting
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# P2: Task Readiness & Resumption Quality Gate
# ──────────────────────────────────────────────────────────────────────────────

def test_task_readiness_check_read_only_and_gate_closed(temp_memory_root: Path):
    # Check readiness when no active task exists
    readiness = check_task_readiness(temp_memory_root, project="global-memory")
    assert readiness["ready"] is False
    assert readiness["quality_gate_eligible"] is False
    assert readiness["active_task"] is None

    # Verify that check_task_readiness did NOT mutate the database
    conn = sqlite3.connect(temp_memory_root / "gms_trust.sqlite")
    task_count = conn.execute("SELECT count(*) FROM gms_tasks").fetchone()[0]
    conn.close()
    assert task_count == 0

    # Resumption evaluation on empty tasks must report not_evaluable for task continuity
    eval_res = run_resumption_evaluation(temp_memory_root)
    assert eval_res["quality_gate_passed"] is False
    scen_5 = next((s for s in eval_res["scenario_results"] if s["scenario_id"] == "scen_5"), None)
    if scen_5:
        assert scen_5["status"] == "not_evaluable"
