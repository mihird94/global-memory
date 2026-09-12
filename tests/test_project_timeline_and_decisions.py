import json
import sqlite3
from pathlib import Path

from project_timeline import get_project_timeline
from decision_intelligence import list_decisions, get_decision, get_decision_impact


def _setup_test_env(tmp_path: Path) -> Path:
    proj_dir = tmp_path / "projects" / "test_proj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "activeContext.md").write_text(
        "## Decisions & Constraints\n\n"
        "Decision: Use WAL mode on all SQLite connections.\n"
        "Rationale: Prevent database write locks during concurrent multi-agent access.\n\n"
        "### Update (2026-09-08 10:00)\n"
        "Implemented initial SQLite WAL connection pool."
    )

    db = tmp_path / "gms_trust.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE gms_claims (claim_id INTEGER PRIMARY KEY, memory_key TEXT, value TEXT, agent_id TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO gms_claims VALUES (1, 'policy.sqlite_wal', 'Enable WAL mode', 'Mihir', 'active', '2026-09-08')")

    conn.execute("CREATE TABLE gms_tasks (task_id TEXT PRIMARY KEY, project TEXT, title TEXT, objective TEXT, status TEXT, owner_agent TEXT, lease_expires_at TEXT, revision INTEGER, parent_task_id TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    conn.execute("INSERT INTO gms_tasks VALUES ('task_1', 'test_proj', 'Migrate DB', 'Apply WAL mode', 'in_progress', 'antigravity', '2026-09-10', 1, NULL, 'mihir', '2026-09-08', '2026-09-08', NULL)")

    conn.execute("CREATE TABLE gms_review_audit (audit_id INTEGER PRIMARY KEY, candidate_id TEXT, action TEXT, reviewer_id TEXT, review_rationale TEXT, original_content_hash TEXT, final_content_hash TEXT, timestamp TEXT)")
    conn.execute("INSERT INTO gms_review_audit VALUES (1, 'cand_1', 'accept', 'mihir', 'Substantive rationale for approving candidate', 'h1', 'h2', '2026-09-08 12:00:00')")

    conn.commit()
    conn.close()
    return tmp_path


def test_project_timeline_normalization_and_events(tmp_path):
    root = _setup_test_env(tmp_path)
    timeline = get_project_timeline(root, "test_proj")

    assert timeline["schema_version"] == "gms-timeline-stream-v1"
    assert timeline["project_id"] == "test_proj"
    assert timeline["total_events"] >= 3

    event_types = {e["event_type"] for e in timeline["events"]}
    assert "project_bank_change" in event_types
    assert "task" in event_types
    assert "candidate" in event_types

    # Ensure all events have stable IDs and complete timestamps
    for e in timeline["events"]:
        assert e["event_id"].startswith("evt_")
        assert e["event_time"]
        assert e["effective_time"]
        assert e["producer"]
        assert e["authority"]


def test_decision_intelligence_listing_and_impact(tmp_path):
    root = _setup_test_env(tmp_path)
    inv = list_decisions(root, project="test_proj")

    assert inv["schema_version"] == "gms-decisions-inventory-v1"
    assert inv["total"] >= 1

    dec = inv["decisions"][0]
    assert dec["decision_id"]
    assert "WAL mode" in dec["statement"]
    assert dec["rationale"]

    # Test get_decision_impact
    impact = get_decision_impact(root, dec["decision_id"])
    assert impact["schema_version"] == "gms-decision-impact-v1"
    assert "supersession_consequence" in impact
    assert len(impact["supersession_consequence"]["affected_tasks"]) >= 1
    assert impact["supersession_consequence"]["affected_tasks"][0]["task_id"] == "task_1"
