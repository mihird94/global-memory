import json
import sqlite3
from pathlib import Path

from project_briefing import (
    generate_project_briefing,
    explain_project_briefing,
    build_resume_bundle,
)


def _setup_project_root(tmp_path: Path) -> Path:
    (tmp_path / "semantic").mkdir(parents=True, exist_ok=True)
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({
        "global_memory_sqlite_concurrency": "Use WAL mode and busy_timeout=5000",
        "car_stickers_status": "active",
    }))

    proj_dir = tmp_path / "projects" / "global-memory"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "projectBrief.md").write_text("# Project Brief\n\nBuild reliable multi-agent context engineering control plane.")
    (proj_dir / "activeContext.md").write_text(
        "## Active Constraints & Boundaries\n\n"
        "Decision: Never use a global agent trust score.\n\n"
        "Constraint: Never load local generative LLMs during daytime interactive navigation.\n\n"
        "## Verification & Acceptance\n\n"
        "- Full pytest test suite passing 100% green.\n"
        "- Clean JavaScript syntax across desktop views."
    )
    (proj_dir / "systemPatterns.md").write_text("## Core Patterns\n\nProcedure: Use WAL mode for all SQLite databases.")

    db = tmp_path / "gms_trust.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE gms_claims (claim_id INTEGER PRIMARY KEY, memory_key TEXT, value TEXT, agent_id TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO gms_claims VALUES (1, 'policy.trust_retired', 'Do not use global agent trust score in Mbrain.', 'Mihir', 'active', '2026-09-01')")

    conn.execute("CREATE TABLE gms_tasks (task_id TEXT PRIMARY KEY, project TEXT, title TEXT, objective TEXT, status TEXT, owner_agent TEXT, lease_expires_at TEXT, revision INTEGER, parent_task_id TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    conn.execute("INSERT INTO gms_tasks VALUES ('t_pass8', 'global-memory', 'Implement Pass 8 Project Intelligence', 'Deliver Project Briefing and Agent Continuity', 'in_progress', 'antigravity', '2026-09-10', 1, NULL, 'mihir', '2026-09-09', '2026-09-09', NULL)")

    conn.commit()
    conn.close()
    return tmp_path


def test_project_briefing_schema_completeness(tmp_path):
    root = _setup_project_root(tmp_path)
    briefing = generate_project_briefing(root, "global-memory", profile="standard")

    assert briefing["schema_version"] == "gms-project-briefing-v1"
    assert briefing["project_id"] == "global-memory"
    assert briefing["packet_hash"].startswith("sha256:")

    # Core required sections
    assert "statement" in briefing["goal"]
    assert isinstance(briefing["current_truth"], list)
    assert isinstance(briefing["active_work"], list)
    assert isinstance(briefing["binding_decisions"], list)
    assert isinstance(briefing["constraints"], list)
    assert isinstance(briefing["procedures"], list)
    assert isinstance(briefing["verification"], list)
    assert isinstance(briefing["next_action"], dict)
    assert isinstance(briefing["inclusion_manifest"], list)

    # Next action must identify active task
    assert "Resume active task: Implement Pass 8" in briefing["next_action"]["statement"]


def test_project_briefing_answers_ten_questions(tmp_path):
    root = _setup_project_root(tmp_path)
    briefing = generate_project_briefing(root, "global-memory", profile="standard")
    explained = explain_project_briefing(briefing)

    assert "q1_goal" in explained
    assert "q2_current_truth" in explained
    assert "q3_recent_changes" in explained
    assert "q4_active_work" in explained
    assert "q5_binding_decisions" in explained
    assert "q6_procedures" in explained
    assert "q7_evidence_summary" in explained
    assert "q8_contradictions_and_blockers" in explained
    assert "q9_next_action" in explained
    assert "q10_verification" in explained


def test_resume_bundle_and_no_dispatch(tmp_path):
    root = _setup_project_root(tmp_path)
    bundle = build_resume_bundle(root, "global-memory", target_format="antigravity")

    assert bundle["schema_version"] == "gms-task-resume-bundle-v1"
    assert bundle["target_format"] == "antigravity"
    assert bundle["dispatch_prohibited"] is True
    assert "Next Action Required" in bundle["prompt"]
    assert "Implement Pass 8" in bundle["prompt"]
    assert bundle["packet_hash"] == bundle["briefing"]["packet_hash"]


def test_packet_hash_is_deterministic(tmp_path):
    root = _setup_project_root(tmp_path)
    b1 = generate_project_briefing(root, "global-memory", profile="standard")
    b2 = generate_project_briefing(root, "global-memory", profile="standard")
    assert b1["packet_hash"] == b2["packet_hash"]


def test_missing_task_yields_graceful_next_action(tmp_path):
    root = _setup_project_root(tmp_path)
    # Clear tasks
    db = root / "gms_trust.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM gms_tasks")
    conn.commit()
    conn.close()

    briefing = generate_project_briefing(root, "global-memory", profile="standard")
    assert briefing["next_action"]["statement"] == "Next action unavailable"
    assert "missing_context" in briefing["next_action"]

def test_unrelated_collision_does_not_hijack_project_next_action(tmp_path):
    root = _setup_project_root(tmp_path)
    facts=json.loads((root/"semantic"/"facts.json").read_text())
    facts.update({"alphaos.swing.plugin_version":"2.0","alphaos_swing_plugin_version":"1.9"})
    (root/"semantic"/"facts.json").write_text(json.dumps(facts))
    briefing=generate_project_briefing(root,"global-memory",profile="standard")
    assert not any("alphaos" in str(x.get("key","")).lower() for x in briefing["blocking_issues"])
    assert "Implement Pass 8" in briefing["next_action"]["statement"]

def test_goal_prefers_overview_and_verification_is_recorded_not_live(tmp_path):
    root=_setup_project_root(tmp_path)
    (root/"projects"/"global-memory"/"projectBrief.md").write_text("# Title\n\n## Overview\nThe real operational goal is reliable agent continuity.\n\n## Notes\nOther")
    briefing=generate_project_briefing(root,"global-memory")
    assert briefing["goal"]["statement"]=="The real operational goal is reliable agent continuity."
    assert all(x["verification_state"]=="recorded_not_live" and not x["verified"] for x in briefing["verification"])

def test_dated_updates_are_history_not_current_truth(tmp_path):
    root = _setup_project_root(tmp_path)
    active = root / "projects" / "global-memory" / "activeContext.md"
    active.write_text(active.read_text() + "\n\n### Update (2026-09-01 10:00)\nOld implementation status that is no longer current truth.\n")
    briefing = generate_project_briefing(root, "global-memory")
    assert not any("Old implementation status" in str(x.get("statement", "")) for x in briefing["current_truth"])
    assert any("Old implementation status" in x["details"] for x in briefing["recent_changes"])
