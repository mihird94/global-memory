import hashlib
import json
import tempfile
from pathlib import Path

import autonomous_curation
import memory_mcp_server
from memory_convention_audit import apply_fixture_cleanup, cleanup_preview
from memoryctl import _structured_graph_triples


def _stage(root: Path, key: str = "project.policy") -> str:
    source = root / "episodic" / "history" / "2026-09-10.md"
    source.parent.mkdir(parents=True)
    source.write_text("A verified policy decision with enough source context.\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    candidate = {
        "schema_version": "gms-context-record-v1", "record_type": "policy", "key": key,
        "statement": "Use evidence-gated autonomous memory admission.",
        "rationale": "Useful context should be available without creating a manual review bottleneck.",
        "implications": ["The owner can contest and restore the prior value."],
        "scope": {"project": "global-memory", "level": "system"},
        "authority": "user_instruction", "verification": "verified",
        "provenance": {"source_refs": ["episodic/history/2026-09-10.md"], "source_hashes": [f"sha256:{digest}"], "extractor": "system", "extracted_at": "2026-09-10T00:00:00Z"},
        "evidence": [{"ref": "episodic/history/2026-09-10.md", "excerpt_hash": f"sha256:{digest}", "type": "user_instruction"}],
        "review": {"requires_human": False, "status": "proposed"},
    }
    result = memory_mcp_server.stage_context_candidate(candidate, db_path=root / "gms_trust.sqlite")
    return result["candidate_id"]


def test_system_curates_valid_candidate_and_keeps_audit():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory_mcp_server.init_db(root / "gms_trust.sqlite")
        cid = _stage(root)
        result = autonomous_curation.curate_pending(root, apply=True)
        assert result["accepted"] == 1
        candidate = memory_mcp_server.get_context_candidate_by_id(cid, db_path=root / "gms_trust.sqlite")
        assert candidate["review_status"] == "accepted"
        assert candidate["reviewed_by"] == "system"
        assert len(memory_mcp_server.get_review_audit_history(cid, db_path=root / "gms_trust.sqlite")) == 1


def test_owner_contest_removes_new_truth_and_is_audited():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory_mcp_server.init_db(root / "gms_trust.sqlite")
        cid = _stage(root)
        autonomous_curation.curate_pending(root, apply=True)
        result = autonomous_curation.contest_candidate(root, cid, "This policy does not reflect my intended workflow.", apply=True)
        assert result["status"] == "contested"
        facts = json.loads((root / "semantic" / "facts.json").read_text())
        assert "project.policy" not in facts
        candidate = memory_mcp_server.get_context_candidate_by_id(cid, db_path=root / "gms_trust.sqlite")
        assert candidate["review_status"] == "contested"
        history = memory_mcp_server.get_review_audit_history(cid, db_path=root / "gms_trust.sqlite")
        assert [item["action"] for item in history] == ["contest", "accept"]


def test_missing_source_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory_mcp_server.init_db(root / "gms_trust.sqlite")
        cid = _stage(root)
        (root / "episodic" / "history" / "2026-09-10.md").unlink()
        preview = autonomous_curation.curate_pending(root, apply=False)
        assert preview["outcomes"][0]["decision"] == "reject"
        assert preview["outcomes"][0]["evidence_failures"]


def test_fixture_cleanup_archives_exact_snapshot_and_is_recoverable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db = root / "gms_trust.sqlite"
        memory_mcp_server.init_db(db)
        conn = memory_mcp_server.get_db_connection(db)
        conn.execute("INSERT INTO gms_claims(memory_kind,memory_key,value,agent_id,status) VALUES('semantic','k1','fixture','agent_test','active')")
        conn.commit(); conn.close()
        preview = cleanup_preview(root)
        result = apply_fixture_cleanup(root, actor="system", rationale="Archive exact high-signal fixture records.", expected_hash=preview["expected_snapshot_hash"], apply=True)
        assert result["status"] == "applied" and result["recoverable"] is True
        conn = memory_mcp_server.get_db_connection(db)
        assert conn.execute("SELECT status FROM gms_claims WHERE memory_key='k1'").fetchone()[0] == "archived_fixture"
        conn.close()


def test_structured_records_create_explanatory_graph_edges():
    triples = _structured_graph_triples("gms.policy", {
        "schema_version": "gms-context-record-v1", "record_type": "policy",
        "scope": {"project": "global-memory", "applies_to": ["dream-cycle"]},
        "implications": ["Candidates become current truth"],
        "evidence": [{"ref": "history.md#L1"}],
    })
    predicates = {predicate for _, predicate, _ in triples}
    assert {"is_a", "scoped_to", "applies_to", "implies", "supported_by"} <= predicates
    assert "configured_as" not in predicates
