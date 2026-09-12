import json
import sqlite3
from pathlib import Path

from context_retrieval_planner import retrieve, make_plan, LANES


def _setup_mock_memory(tmp_path: Path) -> Path:
    # 1. semantic/facts.json
    (tmp_path / "semantic").mkdir(parents=True, exist_ok=True)
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({
        "alphaos.swing.plugin_version": "2.0.1",
        "alphaos_swing_plugin_version": "1.9.0",
        "system.database.wal_mode": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;",
        "car_stickers_status": "active",
        "project.alpha.secret_key": "confidential_token",
    }))

    # 2. projects/alpha
    proj_dir = tmp_path / "projects" / "alpha"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "projectBrief.md").write_text("# Alpha Project Brief\n\nBuild high performance execution engine.")
    (proj_dir / "activeContext.md").write_text(
        "## Active Constraints & Boundaries\n\n"
        "Decision: Global agent trust score is strictly retired because it collapses orthogonal dimensions.\n\n"
        "Constraint: Never load local generative LLM during interactive desktop browsing."
    )
    (proj_dir / "systemPatterns.md").write_text(
        "## Core Architecture\n\n"
        "Procedure: SQLite Concurrency Protocol\n"
        "Always enable WAL mode and set busy_timeout=5000 before running concurrent writes."
    )
    (proj_dir / "progress.md").write_text(
        "## Milestone History\n\n"
        "Milestone: Completed Phase 1 baseline verification with zero test failures."
    )
    (proj_dir / "techContext.md").write_text(
        "## Tech Stack & Artifacts\n\n"
        "Artifact: tools/context_retrieval_planner.py implements 10-lane hybrid retrieval."
    )

    # 3. episodic/history
    hist_dir = tmp_path / "episodic" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    (hist_dir / "2026-09-08.md").write_text(
        "# Daily Notes 2026-09-08\n\n"
        "- Verified SQLite database concurrency under heavy parallel load.\n"
        "- Confirmed Dream Cycle schedule at 03:10 AM local time."
    )

    # 4. gms_trust.sqlite
    db = tmp_path / "gms_trust.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE gms_claims (claim_id INTEGER PRIMARY KEY, memory_key TEXT, value TEXT, agent_id TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO gms_claims VALUES (1, 'policy.trust_retired', 'Do not use global agent trust score in Mbrain.', 'Mihir', 'active', '2026-09-01')")
    conn.execute("INSERT INTO gms_claims VALUES (2, 'alphaos.swing.plugin_version', '0.2.0', 'Codex', 'superseded', '2026-08-01')")

    conn.execute("CREATE TABLE gms_tasks (task_id TEXT PRIMARY KEY, project TEXT, title TEXT, objective TEXT, status TEXT, owner_agent TEXT, lease_expires_at TEXT, revision INTEGER, parent_task_id TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    conn.execute("INSERT INTO gms_tasks VALUES ('t1', 'alpha', 'Build Hybrid Retrieval', 'Implement 10 real lanes', 'in_progress', 'antigravity', '2026-09-10', 1, NULL, 'mihir', '2026-09-09', '2026-09-09', NULL)")
    conn.execute("CREATE TABLE gms_task_checkpoints (checkpoint_id INTEGER PRIMARY KEY, task_id TEXT, revision INTEGER, agent_id TEXT, label TEXT, state_json TEXT, artifact_refs_json TEXT, claim_refs_json TEXT, episode_refs_json TEXT, created_at TEXT)")
    conn.execute("INSERT INTO gms_task_checkpoints VALUES (1, 't1', 1, 'antigravity', 'implementation', '{\"next_action\":\"run verification\",\"acceptance_criteria\":[\"all tests pass\"]}', '[\"tools/context_retrieval_planner.py\"]', '[]', '[]', '2026-09-09')")
    conn.execute("CREATE TABLE gms_handoffs (handoff_id INTEGER PRIMARY KEY, task_id TEXT, revision INTEGER, source_agent TEXT, target_agent TEXT, objective TEXT, completed_work TEXT, next_action TEXT, blockers TEXT, acceptance_criteria TEXT, context_json TEXT, artifact_refs_json TEXT, created_at TEXT, acknowledged_at TEXT)")
    conn.execute("INSERT INTO gms_handoffs VALUES (1, 't1', 1, 'antigravity', 'codex', 'Finish retrieval', 'Implemented task lane', 'Run verification', '', 'All tests pass', '{}', '[\"tools/context_retrieval_planner.py\"]', '2026-09-09', NULL)")

    conn.execute("CREATE TABLE gms_relationships (id INTEGER PRIMARY KEY, source_id TEXT, target_id TEXT, rel_type TEXT, weight REAL, summary TEXT, valid_from TEXT, valid_to TEXT)")
    conn.execute("INSERT INTO gms_relationships VALUES (1, 'Mbrain', 'SQLite', 'USES_DATABASE', 0.95, 'Mbrain persists state in gms_trust.sqlite', '2026-01-01', NULL)")
    conn.execute("INSERT INTO gms_relationships VALUES (2, 'Mbrain', 'DreamCycle', 'RUNS_NIGHTLY', 0.90, 'Mbrain runs nightly consolidation', '2026-01-01', NULL)")

    conn.commit()
    conn.close()
    return tmp_path


def test_10_lanes_declared_and_plan_generation(tmp_path):
    assert len(LANES) == 10
    plan = make_plan("Why was trust retired?", project="alpha")
    assert plan["intent"] == "decision"
    assert len(plan["lanes"]) == 10


def test_hybrid_retrieval_all_lanes_reporting(tmp_path):
    root = _setup_mock_memory(tmp_path)
    res = retrieve(root, "SQLite WAL mode concurrency procedure", project="alpha")

    items = res["items"]
    manifest = res["manifest"]
    lane_cands = manifest["lane_candidates"]
    latencies = res["lane_latencies_ms"]

    # Check that real lanes executed and reported non-negative latencies
    assert len(latencies) == 10
    assert all(lat >= 0.0 for lat in latencies.values())

    # Check BM25, procedures, exact, graph returned candidates
    assert lane_cands.get("bm25", 0) > 0
    assert lane_cands.get("procedures", 0) > 0

    # Ensure lanes_used only lists lanes with > 0 candidates
    assert all(lane_cands[lane] > 0 for lane in manifest["lanes_used"])

    # Ensure items have complete normalized contract
    for it in items:
        assert it["record_id"]
        assert it["key"]
        assert it["statement"]
        assert it["lane"] in LANES
        assert it["authority"]
        assert it["authority_label"]
        assert it["source_valid"] is True
        assert it["token_estimate"] > 0
        assert "rrf_score" in it


def test_conflict_and_collision_retrieval(tmp_path):
    root = _setup_mock_memory(tmp_path)
    res = retrieve(root, "alphaos swing plugin version", project="alpha")

    # The collision between alphaos.swing.plugin_version and alphaos_swing_plugin_version should be surfaced
    conflict_items = [it for it in res["items"] if it.get("contradiction_flag")]
    assert len(conflict_items) >= 1
    assert any("alphaos" in it["key"] for it in conflict_items)


def test_tasks_lane_retrieves_active_tasks(tmp_path):
    root = _setup_mock_memory(tmp_path)
    res = retrieve(root, "current work tasks", project="alpha")
    task_items = [it for it in res["items"] if it["lane"] == "tasks"]
    task_dict = json.loads(task_items[0]["statement"]) if isinstance(task_items[0]["statement"], str) else task_items[0]["statement"]
    assert task_dict["status"] == "in_progress"
    assert task_dict["latest_checkpoint"]["state"]["next_action"] == "run verification"
    assert task_dict["latest_handoff"]["acceptance_criteria"] == "All tests pass"


def test_graph_lane_retrieves_entity_triples(tmp_path):
    root = _setup_mock_memory(tmp_path)
    res = retrieve(root, "Mbrain SQLite database", project="alpha")
    graph_items = [it for it in res["items"] if it["lane"] == "graph"]
    assert len(graph_items) >= 1
    assert graph_items[0]["graph_path"] == ["Mbrain", "USES_DATABASE", "SQLite"]


def test_temporal_as_of_omission(tmp_path):
    root = _setup_mock_memory(tmp_path)
    # Query with as_of set to 2026-08-15 (before task t1 created on 2026-09-09)
    res = retrieve(root, "current work tasks", project="alpha", as_of="2026-08-15")
    task_items = [it for it in res["items"] if it["lane"] == "tasks"]
    assert len(task_items) == 0
    assert any("Created after as_of" in om.get("reason", "") for om in res["omission_manifest"])

def test_model_free_navigation_does_not_fake_vector_results(tmp_path):
    root=_setup_mock_memory(tmp_path)
    res=retrieve(root,"SQLite concurrency",project="alpha")
    assert res["manifest"]["lane_candidates"]["vector"]==0
    assert res["vector_backend"]["backend"]=="disabled_model_free"
    assert res["vector_backend"]["available"] is False


def test_legacy_facts_are_enveloped_and_structured_facts_are_preferred(tmp_path):
    root = _setup_mock_memory(tmp_path)
    facts_path = root / "semantic" / "facts.json"
    facts = json.loads(facts_path.read_text())
    facts["system.database.structured"] = {
        "decision": "Use SQLite WAL mode",
        "status": "accepted",
        "rationale": "Concurrent readers must not block the writer.",
        "provenance": {"agent": "system"},
    }
    facts_path.write_text(json.dumps(facts))

    legacy = retrieve(root, "car_stickers_status")
    legacy_item = next(item for item in legacy["items"] if item["key"] == "car_stickers_status")
    assert legacy_item["record_shape"] == "legacy_flat"
    assert legacy_item["verification"] == "unverified"
    assert legacy_item["requires_corroboration"] is True
    assert legacy_item["limitations"]
    assert legacy["manifest"]["legacy_items_requiring_corroboration"] >= 1

    structured = retrieve(root, "system.database.structured")
    structured_item = next(item for item in structured["items"] if item["key"] == "system.database.structured")
    assert structured_item["record_shape"] == "structured"
    assert structured_item["authority"] == "verified_system_output"
    assert structured_item["requires_corroboration"] is False


def test_retrieval_manifest_reports_source_diversity(tmp_path):
    root = _setup_mock_memory(tmp_path)
    res = retrieve(root, "alphaos swing plugin version system database")
    manifest = res["manifest"]
    assert "source_counts" in manifest
    assert 0 <= manifest["dominant_source_share"] <= 1
    assert isinstance(manifest["diversity_applied"], bool)
    assert isinstance(manifest["suppressed_redundant_hits"], int)
