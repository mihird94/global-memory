import json
import sqlite3
from pathlib import Path

from context_packet import build_context_packet
from context_retrieval_planner import retrieve
from memory_aliases import alias_inventory, canonicalize
from memory_authority import validate_authority
from memory_convention_audit import cleanup_preview, convention_audit, migration_inventory, stage_migration, rollback_migration
from memory_lifecycle import lifecycle_history, transition
from consolidation_policy import classify_candidate
from gms_desktop_api import GMSDesktopAPI


def make_root(tmp_path: Path) -> Path:
    (tmp_path / "semantic").mkdir()
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({
        "alphaos.swing.plugin_version": "2.0",
        "alphaos_swing_plugin_version": "1.9",
        "server_url": "https://prod",
        "server_url@staging": "https://staging",
        "car_stickers_status": "active",
        "answer": 42,
    }))
    conn=sqlite3.connect(tmp_path/"gms_trust.sqlite")
    conn.execute("CREATE TABLE gms_claims (claim_id INTEGER PRIMARY KEY,memory_key TEXT,value TEXT,agent_id TEXT,status TEXT,created_at TEXT)")
    conn.execute("INSERT INTO gms_claims VALUES (1,'temp_key','x','agent_test','active','2026-01-01')")
    conn.execute("CREATE TABLE gms_context_candidates (candidate_id TEXT,canonical_key TEXT,content_hash TEXT,review_status TEXT,reviewed_by TEXT,created_at TEXT,payload_json TEXT)")
    conn.execute("INSERT INTO gms_context_candidates VALUES ('c1','project.item','h','proposed',NULL,'2026-01-01','{}')")
    conn.commit(); conn.close(); return tmp_path


def request(rid="r1", request_id="req1", next_state="proposed", operation="add", expected_hash=None):
    return {"request_id":request_id,"record_id":rid,"canonical_key":"project.item","next_state":next_state,
            "operation":operation,"actor_id":"codex","actor_kind":"verified_agent",
            "rationale":"Evidence-backed lifecycle test transition","content":{"statement":"value"},
            "expected_hash":expected_hash,"source_refs":["test#1"]}


def test_lifecycle_is_audited_idempotent_and_fail_closed(tmp_path):
    db=tmp_path/"db.sqlite"
    first=transition(db,request(),apply=True)
    assert first["applied"] and first["status"]=="applied"
    repeated=transition(db,request(),apply=True)
    assert repeated["status"]=="idempotent"
    illegal=transition(db,request(request_id="req2",next_state="archived",operation="archive"),apply=False)
    assert not illegal["valid"] and "illegal lifecycle transition" in illegal["errors"][0]
    assert len(lifecycle_history(db,"r1"))==1


def test_lifecycle_optimistic_hash_and_archive_restore(tmp_path):
    db=tmp_path/"db.sqlite"; created=transition(db,request(),apply=True)
    accepted=transition(db,request(request_id="r2",next_state="accepted",operation="add",expected_hash="sha256:wrong"),apply=True)
    assert not accepted["applied"] and "content changed" in accepted["errors"][0]
    ok=transition(db,request(request_id="r3",next_state="accepted",operation="add",expected_hash=created["resulting_hash"]),apply=True)
    assert ok["applied"]
    archived=transition(db,request(request_id="r4",next_state="archived",operation="archive",expected_hash=ok["resulting_hash"]),apply=True)
    assert archived["applied"]
    restored=transition(db,request(request_id="r5",next_state="accepted",operation="restore",expected_hash=archived["resulting_hash"]),apply=True)
    assert restored["applied"]


def test_authority_roles_are_not_conflated():
    bad=validate_authority({"authority":"llm_inference","record_type":"policy","provenance":{"author":"mihir","extractor":"codex"},"review":{"status":"accepted"}})
    assert not bad["valid"] and bad["requires_human_review"]
    good=validate_authority({"authority":"source_document","record_type":"fact","provenance":{"author":"document owner","extractor":"codex"},"evidence":[{"ref":"doc#x"}]})
    assert good["valid"] and good["label"]=="Document extracted"


def test_migration_and_fixture_preview_never_write(tmp_path):
    root=make_root(tmp_path); before=(root/"gms_trust.sqlite").read_bytes()
    inventory=migration_inventory(root)
    assert inventory["total"]==6 and inventory["by_risk"]["medium"]>=1
    car=next(x for x in inventory["rows"] if x["legacy_key"]=="car_stickers_status")
    assert car["classification"]=="opaque_status" and car["readiness"]=="blocked"
    audit=convention_audit(root); preview=cleanup_preview(root)
    assert audit["suspected_fixture_count"]==1 and preview["writes"]==0
    assert (root/"gms_trust.sqlite").read_bytes()==before


def test_alias_collisions_do_not_collapse_environment(tmp_path):
    root=make_root(tmp_path); result=alias_inventory(root)
    assert result["collision_count"]==1
    assert result["collisions"][0]["proposal"]=="contradict"
    assert canonicalize("server_url") != canonicalize("server_url@staging")

def test_migration_staging_never_accepts_and_can_rollback(tmp_path):
    root=make_root(tmp_path); inv=migration_inventory(root); key=inv["rows"][0]["legacy_key"]
    preview=stage_migration(root,[key],actor="codex",rationale="Reviewable staged migration only",expected_hash=inv["snapshot_hash"])
    assert preview["writes"]==0 and preview["accepted"]==0
    staged=stage_migration(root,[key],actor="codex",rationale="Reviewable staged migration only",expected_hash=inv["snapshot_hash"],apply=True)
    assert staged["status"]=="staged" and staged["accepted"]==0
    rolled=rollback_migration(root,[key],actor="codex",rationale="Restore untouched legacy staging",apply=True)
    assert rolled["status"]=="rolled_back" and rolled["legacy_restored"]


def test_retrieval_and_packets_are_explainable_and_deterministic(tmp_path):
    root=make_root(tmp_path)
    result=retrieve(root,"alphaos.swing.plugin_version",token_budget=200)
    assert result["items"] and all(x["inclusion_reason"] and x["authority_label"] for x in result["items"])
    assert result["manifest"]["proposed_included"] is False
    small=build_context_packet(root,"alphaos plugin version",profile="small")
    again=build_context_packet(root,"alphaos plugin version",profile="small")
    deep=build_context_packet(root,"alphaos plugin version",profile="deep")
    assert small["packet_hash"]==again["packet_hash"]
    assert small["retrieval_plan"]["token_budget"] < deep["retrieval_plan"]["token_budget"]

def test_nightly_operation_classification_preserves_conflicts():
    base={"project.mode":"old"}
    conflict=classify_candidate({"key":"project_mode","statement":"new"},base)
    reinforce=classify_candidate({"key":"project.mode","statement":"old","evidence":[{"ref":"x"}]},base)
    assert conflict["operation"]=="contradict" and not conflict["automatic_promotion"]
    assert reinforce["operation"]=="reinforce"

def test_versioned_desktop_interfaces_share_the_same_engines(tmp_path):
    root=make_root(tmp_path); api=GMSDesktopAPI(mem_root=root)
    assert api.get_memory_quality()["legacy_flat_records"]==6
    assert api.get_aliases()["collision_count"]==1
    assert api.get_retrieval_plan({"query":"server_url","token_budget":100})["plan"]["schema_version"]=="gms-retrieval-plan-v1"
    assert api.get_context_packet_v1({"query":"server_url","profile":"small"})["schema_version"]=="gms-context-packet-v1"
