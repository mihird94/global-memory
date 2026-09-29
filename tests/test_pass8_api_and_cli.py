"""Comprehensive Pass 8 Integration Tests for API & CLI.

Tests all Mbrain Pass 8 endpoints and memoryctl subcommands in isolated environments.
Ensures zero writes to live production memory, full schema conformance, and deterministic behavior.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

import memoryctl
from gms_desktop_api import GMSDesktopAPI
from memoryctl import main as memoryctl_main


@pytest.fixture
def isolated_pass8_env(tmp_path: Path, monkeypatch) -> Path:
    """Sets up an isolated test memory environment with project banks, decisions, tasks, and history."""
    mem_root = tmp_path / "memories"
    mem_root.mkdir(parents=True, exist_ok=True)

    # 1. Semantic facts with collision and opaque status
    semantic_dir = mem_root / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    facts_data = {
        "alphaos.swing.plugin_version": "2.0.0",
        "alphaos_swing_plugin_version": "1.9.0",
        "car_stickers_status": "active",
        "test-proj.current_truth": "Operating in normal regime",
    }
    (semantic_dir / "facts.json").write_text(json.dumps(facts_data, indent=2))

    # 2. Project bank
    proj_dir = mem_root / "projects" / "test-proj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "projectBrief.md").write_text(
        "# Test Project\n\n## Goal\nBuild reliable agent continuity.\n\n## Scope\nGlobal memory test suite."
    )
    (proj_dir / "activeContext.md").write_text(
        "# Active Context\n\n## Current Truth\nSystem is operating nominally.\n\n## Decisions\n- Decision DEC-001: Use SQLite WAL mode."
    )
    (proj_dir / "progress.md").write_text(
        "# Progress\n\n## Completed Work\n- Stage 0 complete.\n\n## Next Action\nPriority 1: Run integration test suite."
    )

    # 3. Episodic history
    hist_dir = mem_root / "episodic" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    (hist_dir / "2026-09-08.md").write_text(
        "- Event: Applied car stickers to fleet vehicles for conference.\n"
        "- Decision: Approved DEC-001 for SQLite WAL mode.\n"
    )

    # 4. SQLite tables
    db_path = mem_root / "gms_trust.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE gms_decisions (
            decision_id TEXT PRIMARY KEY,
            project TEXT,
            title TEXT,
            rationale TEXT,
            implications TEXT,
            status TEXT,
            superseded_by TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        INSERT INTO gms_decisions VALUES (
            'DEC-001', 'test-proj', 'Use SQLite WAL', 'Improves concurrency', 'Requires busy_timeout', 'binding', NULL, '2026-09-08T10:00:00Z'
        )
    """)

    cur.execute("""
        CREATE TABLE gms_tasks (
            task_id TEXT PRIMARY KEY,
            project TEXT,
            title TEXT,
            status TEXT,
            owner_agent TEXT,
            lease_expires_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        INSERT INTO gms_tasks VALUES (
            'TASK-101', 'test-proj', 'Run integration suite', 'in_progress', 'test-agent', '2026-09-08T23:59:59Z', '2026-09-08T09:00:00Z', '2026-09-08T09:30:00Z'
        )
    """)

    cur.execute("""
        CREATE TABLE gms_context_candidates (
            candidate_id TEXT PRIMARY KEY,
            canonical_key TEXT,
            content_hash TEXT,
            review_status TEXT,
            reviewed_by TEXT,
            created_at TEXT,
            payload_json TEXT
        )
    """)
    cand_payload = {
        "record_type": "decision",
        "statement": "Enforce zero daytime LLM inference",
        "scope": {"project": "test-proj"},
        "evidence": [{"ref": "episodic/history/2026-09-08.md#L2"}]
    }
    cur.execute("""
        INSERT INTO gms_context_candidates VALUES (
            'CAND-501', 'policy.zero_daytime_llm', 'hash501', 'proposed', NULL, '2026-09-08T11:00:00Z', ?
        )
    """, (json.dumps(cand_payload),))

    cur.execute("""
        CREATE TABLE gms_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_key TEXT,
            value TEXT,
            agent TEXT,
            status TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        INSERT INTO gms_claims VALUES (
            1, 'car_stickers_status', 'active', 'importer', 'active', '2026-09-08T08:00:00Z'
        )
    """)

    conn.commit()
    conn.close()

    # Monkeypatch GMS_ROOT, MEMORY_ROOT, and memoryctl.MEM_ROOT
    monkeypatch.setenv("GMS_ROOT", str(mem_root))
    monkeypatch.setenv("MEMORY_ROOT", str(mem_root))
    monkeypatch.setattr(memoryctl, "MEM_ROOT", mem_root)

    return mem_root


def test_desktop_api_pass8_endpoints(isolated_pass8_env: Path):
    api = GMSDesktopAPI(mem_root=isolated_pass8_env)

    # 1. Project Briefing
    briefing = api.get_project_briefing("test-proj")
    assert briefing["schema_version"] == "gms-project-briefing-v1"
    assert briefing["project_id"] == "test-proj"
    assert "packet_hash" in briefing
    assert "goal" in briefing
    assert "current_truth" in briefing
    assert "binding_decisions" in briefing
    assert "constraints" in briefing
    assert "active_work" in briefing
    assert "blocking_issues" in briefing
    assert "recent_changes" in briefing
    assert "next_action" in briefing

    # 2. Explain Briefing
    explanation = api.explain_project_briefing("test-proj")
    assert explanation["schema_version"] == "gms-project-briefing-explanation-v1"
    assert "q1_goal" in explanation

    # 3. Project Timeline
    timeline = api.get_project_timeline("test-proj")
    assert timeline["schema_version"] == "gms-timeline-stream-v1"
    assert isinstance(timeline.get("events"), list)

    # 4. Resume Bundle Generation
    bundle = api.get_resume_bundle("test-proj", target_format="antigravity")
    assert bundle["schema_version"] == "gms-task-resume-bundle-v1"
    assert bundle["target_format"] == "antigravity"
    assert bundle["dispatch_prohibited"] is True
    assert "Project Resumption Context" in bundle["prompt"]

    # 5. Decisions & Impact
    decisions = api.get_decisions(project="test-proj")
    assert decisions["schema_version"] == "gms-decisions-inventory-v1"
    assert len(decisions["decisions"]) >= 1

    dec_id = decisions["decisions"][0]["decision_id"]
    dec_detail = api.get_decision(dec_id)
    assert dec_detail["decision_id"] == dec_id

    dec_impact = api.get_decision_impact(dec_id)
    assert dec_impact["schema_version"] == "gms-decision-impact-v1"
    assert dec_impact["decision_id"] == dec_id

    # 6. Action Inbox & Preview
    inbox = api.get_action_inbox(project="test-proj")
    assert inbox["schema_version"] == "gms-action-inbox-v1"
    assert inbox["total_items"] >= 1

    inbox_item = inbox["items"][0]
    preview = api.preview_inbox_action(inbox_item["inbox_id"])
    assert preview["schema_version"] == "gms-inbox-preview-v1"
    assert preview["durable_writes"] == 0
    assert preview["dry_run"] is True

    # 7. Memory Repair
    ev = api.get_repair_evidence("car_stickers_status")
    assert ev["schema_version"] == "gms-repair-evidence-v1"
    assert ev["evidence_count"] >= 1

    analysis = api.analyze_repair_record("car_stickers_status")
    assert analysis["schema_version"] == "gms-repair-analysis-v1"
    assert analysis["fields"]["statement"]["status"] == "recovered_from_source"

    staged = api.stage_repair_record(
        "car_stickers_status",
        payload={"statement": "active", "rationale": "Applied to fleet"},
        apply=False,
        actor="mihir",
    )
    assert staged["durable_writes"] == 0
    assert staged["legacy_preserved"] is True

    # 8. Morning Briefing
    morning = api.get_morning_briefing("test-proj")
    assert morning["schema_version"] == "gms-morning-briefing-v1"
    assert "summary" in morning
    assert "suggested_first_action" in morning
    assert "blocking_issues" in morning

    # 9. Resumption Evaluation
    eval_res = api.get_resumption_evaluation()
    assert eval_res["schema_version"] == "gms-resumption-eval-report-v1"
    assert "overall_pass_rate" in eval_res
    assert eval_res["total_scenarios"] == 10
    assert eval_res["agent_continuation_trial"]["passed"] is False
    assert eval_res["agent_continuation_trial"]["status"] == "not_run"
    assert eval_res["agent_continuation_trial"]["bundle_contract_valid"] is True


def test_memoryctl_pass8_subcommands(isolated_pass8_env: Path, monkeypatch, capsys):
    def run_cli(*args):
        monkeypatch.setattr(sys, "argv", ["memoryctl", *args])
        exit_code = memoryctl_main()
        captured = capsys.readouterr()
        return exit_code, captured.out, captured.err

    # 1. project-briefing get
    code, out, _ = run_cli("project-briefing", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-project-briefing-v1"
    assert data["project_id"] == "test-proj"

    # 2. project-briefing explain
    code, out, _ = run_cli("project-briefing", "explain", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-project-briefing-explanation-v1"

    # 3. project-timeline list
    code, out, _ = run_cli("project-timeline", "list", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-timeline-stream-v1"

    # 4. task-resume build
    code, out, _ = run_cli("task-resume", "build", "--project", "test-proj", "--format", "antigravity")
    assert code == 0
    assert "Project Resumption Context" in out
    assert "Next Action Required" in out

    # 5. task-resume verify
    code, out, _ = run_cli("task-resume", "verify", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data.get("status") == "verified"

    # 6. decision list
    code, out, _ = run_cli("decision", "list", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-decisions-inventory-v1"
    assert len(data["decisions"]) >= 1
    cli_dec_id = data["decisions"][0]["decision_id"]

    # 7. decision impact
    code, out, _ = run_cli("decision", "impact", "--project", "test-proj", "--decision-id", cli_dec_id)
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-decision-impact-v1"
    assert data["decision_id"] == cli_dec_id

    # 8. action-inbox list
    code, out, _ = run_cli("action-inbox", "list", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-action-inbox-v1"
    assert data["total_items"] >= 1

    # 9. memory-repair analyze
    code, out, _ = run_cli("memory-repair", "analyze", "--key", "car_stickers_status")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-repair-analysis-v1"
    assert data["legacy_key"] == "car_stickers_status"

    # 10. morning-briefing get
    code, out, _ = run_cli("morning-briefing", "get", "--project", "test-proj")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-morning-briefing-v1"

    # 11. eval-resumption run
    code, out, _ = run_cli("eval-resumption", "run")
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == "gms-resumption-eval-report-v1"
