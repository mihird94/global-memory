"""Read-only convention audit and exact-snapshot fixture cleanup planning."""
from __future__ import annotations
import hashlib, json, re, sqlite3
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from memory_aliases import alias_inventory, canonicalize
from pollution_audit import run_pollution_audit
from reviewers import validate_reviewer_id

FIXTURE_AGENTS = {"agent_test", "agent_1", "dreamcycle-mock-provider"}
GENERIC_KEYS = {"k1", "k2", "temp_key", "fact_sem", "fact_op", "conflict_key", "legacy_key", "new_dream_fact"}

def snapshot_hash(items: Any) -> str:
    raw=json.dumps(items,sort_keys=True,separators=(",",":"),default=str)
    return "sha256:"+hashlib.sha256(raw.encode()).hexdigest()

def _classify(key: str, value: Any) -> tuple[str,str,bool,list[str]]:
    low=key.lower(); text=str(value).strip().lower(); blockers=[]
    if text in {"active","retired","done","blocked","complete","completed","unknown"}:
        return "opaque_status","medium",False,["missing rationale, scope, implications, evidence, and review horizon"]
    if any(x in low for x in ("policy","permission","safety","risk","account","preference")):
        return "user_preference_or_safety","high",False,["human review required","authoritative source required"]
    if any(x in low for x in ("procedure","workflow","command","path","schedule","version","status")):
        return "operational_or_procedure","medium",False,["source or revalidation evidence required"]
    if any(x in low for x in ("city","birthday","name","phone","address")):
        return "personal_reference","high",False,["identity/personal data requires human review"]
    ready = isinstance(value,(int,float,bool))
    if not ready: blockers=["legacy value has no verified provenance"]
    return "reference_fact" if ready else "unknown","low" if ready else "medium",ready,blockers

def migration_inventory(mem_root: Path) -> dict[str,Any]:
    root=Path(mem_root); path=root/"semantic"/"facts.json"
    facts=json.loads(path.read_text()) if path.exists() else {}
    aliases=alias_inventory(root); collision_keys={r["key"] for c in aliases["collisions"] for r in c["records"]}
    rows=[]
    for key,value in sorted(facts.items()):
        parsed=value
        if isinstance(value,str):
            try: parsed=json.loads(value)
            except Exception: pass
        if isinstance(parsed,dict) and parsed.get("schema_version")=="gms-context-record-v1": continue
        cls,risk,ready,blockers=_classify(key,value)
        if key in collision_keys: cls="duplicate_or_alias_candidate"; ready=False; blockers.append("canonical key collision requires review")
        rows.append({"legacy_key":key,"current_value":value,"proposed_key":canonicalize(key),
                     "classification":cls,"record_type":"fact","authority":"imported_legacy",
                     "verification":"unverified","rationale_required":risk in {"high","medium"},
                     "rationale_present":False,"risk":risk,"readiness":"ready" if ready else "blocked",
                     "recommended_operation":"add","blockers":blockers,"legacy_preserved":True})
    by_risk={x:sum(r["risk"]==x for r in rows) for x in ("high","medium","low")}
    by_readiness={x:sum(r["readiness"]==x for r in rows) for x in ("ready","blocked","staged","accepted")}
    return {"schema_version":"gms-migration-preview-v1","mode":"preview","total":len(rows),
            "by_risk":by_risk,"by_readiness":by_readiness,"rows":rows,"snapshot_hash":snapshot_hash(rows)}

def convention_audit(mem_root: Path) -> dict[str,Any]:
    root=Path(mem_root); pollution=run_pollution_audit(mem_root=root)
    suspects=[]; db=root/"gms_trust.sqlite"
    if db.exists():
        conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
        try:
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_claims'").fetchone()
            if exists:
                for row in conn.execute("SELECT claim_id,memory_key,value,agent_id,status,created_at FROM gms_claims ORDER BY claim_id"):
                    if row["status"] == "archived_fixture": continue
                    agent=(row["agent_id"] or "").lower(); key=row["memory_key"] or ""; signals=[]
                    if agent in FIXTURE_AGENTS: signals.append("known fixture agent")
                    if key.lower() in GENERIC_KEYS or re.match(r"^(test|fact_|k\d+$|temp)",key,re.I): signals.append("generic test key")
                    if "mock" in agent: signals.append("mock provider name")
                    if not str(row["value"] or "").strip(): signals.append("empty semantic value")
                    if len(signals)>=2 or agent in FIXTURE_AGENTS:
                        suspects.append({"claim_id":row["claim_id"],"key":key,"agent":row["agent_id"],
                                         "status":row["status"],"signals":signals,
                                         "eligible_for_cleanup":agent in FIXTURE_AGENTS or len(signals)>=2})
        finally: conn.close()
    migration=migration_inventory(root); aliases=alias_inventory(root)
    candidates=0; structured_active=0; invalid_evidence=0; unresolved=0
    facts_path=root/"semantic"/"facts.json"
    if facts_path.exists():
        for value in json.loads(facts_path.read_text()).values():
            parsed=value
            if isinstance(value,str):
                try: parsed=json.loads(value)
                except Exception: pass
            if isinstance(parsed,dict) and parsed.get("schema_version")=="gms-context-record-v1": structured_active+=1
    if db.exists():
        conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_context_candidates'").fetchone():
                candidates=conn.execute("SELECT COUNT(*) FROM gms_context_candidates WHERE review_status IN ('proposed','deferred')").fetchone()[0]
                for row in conn.execute("SELECT payload_json FROM gms_context_candidates WHERE review_status IN ('proposed','deferred')"):
                    try:
                        payload=json.loads(row[0]); evidence=payload.get("evidence") or []
                        if not evidence or any(not e.get("ref") or not e.get("excerpt_hash") for e in evidence): invalid_evidence+=1
                    except Exception: invalid_evidence+=1
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_context_records'").fetchone():
                structured_active+=conn.execute("SELECT COUNT(*) FROM gms_context_records WHERE state='accepted'").fetchone()[0]
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_claims'").fetchone():
                unresolved=conn.execute("""SELECT COUNT(*) FROM (SELECT memory_key FROM gms_claims WHERE status='active' GROUP BY memory_key HAVING COUNT(DISTINCT value)>1)""").fetchone()[0]
        finally: conn.close()
    result={"schema_version":"gms-convention-audit-v1","structured_active_records":structured_active,
            "legacy_flat_records":migration["total"],"pending_ai_candidates":candidates,
            "invalid_or_missing_evidence":invalid_evidence,"stale_or_review_due":0,
            "unresolved_contradictions":unresolved,
            "suspected_fixtures":suspects,"suspected_fixture_count":len(suspects),
            "cleanup_eligible_count":sum(x["eligible_for_cleanup"] for x in suspects),
            "key_collisions":aliases["collisions"],"key_collision_count":aliases["collision_count"],
            "status_only_facts":pollution["convention_warnings"]["status_only_facts"],
            "migration":{"by_risk":migration["by_risk"],"by_readiness":migration["by_readiness"]}}
    result["snapshot_hash"]=snapshot_hash(result)
    return result

def cleanup_preview(mem_root: Path) -> dict[str,Any]:
    audit=convention_audit(mem_root)
    exact=[x for x in audit["suspected_fixtures"] if x["eligible_for_cleanup"]]
    return {"status":"dry_run","writes":0,"exact_claim_ids":[x["claim_id"] for x in exact],
            "items":exact,"expected_snapshot_hash":audit["snapshot_hash"],
            "message":"Preview only. Apply requires a registered reviewer, substantive rationale, and matching snapshot hash."}

def apply_fixture_cleanup(mem_root: Path, *, actor: str, rationale: str,
                          expected_hash: str, apply: bool = False) -> dict[str, Any]:
    """Archive only the exact high-signal fixture claims from a matching preview."""
    root = Path(mem_root); preview = cleanup_preview(root); errors=[]
    valid_actor, normalized = validate_reviewer_id(actor, mem_root=root)
    if not valid_actor: errors.append("registered actor identity is required")
    if len(rationale.strip()) < 10: errors.append("substantive rationale must be at least 10 characters")
    if expected_hash != preview["expected_snapshot_hash"]: errors.append("cleanup snapshot changed")
    result={"status":"preview","writes":0,"claim_ids":preview["exact_claim_ids"],"errors":errors,"recoverable":True}
    if not apply or errors: return result
    db=root/"gms_trust.sqlite"; conn=sqlite3.connect(db); now=datetime.now(timezone.utc).isoformat()
    try:
        for item in preview["items"]:
            conn.execute("UPDATE gms_claims SET status='archived_fixture', confidence=0.0 WHERE claim_id=?",(item["claim_id"],))
            conn.execute("""INSERT INTO gms_review_audit
              (candidate_id,canonical_key,action,reviewer_id,review_rationale,original_content_hash,
               accepted_content_hash,supersedes_claim_id,resulting_claim_id,reviewed_at)
              VALUES (?,?, 'archive_fixture',?,?,?,NULL,?,NULL,?)""",
              (f"claim:{item['claim_id']}",item["key"],normalized,rationale,
               snapshot_hash(item),item["claim_id"],now))
        conn.commit()
        result.update(status="applied",writes=len(preview["items"]))
        return result
    finally: conn.close()

def stage_migration(mem_root:Path, keys:list[str], *, actor:str, rationale:str, expected_hash:str, apply:bool=False)->dict[str,Any]:
    inventory=migration_inventory(mem_root); selected=[r for r in inventory["rows"] if r["legacy_key"] in set(keys)]
    errors=[]
    if expected_hash != inventory["snapshot_hash"]: errors.append("migration snapshot changed")
    if len(rationale.strip())<10: errors.append("substantive rationale must be at least 10 characters")
    actor_valid,_=validate_reviewer_id(actor,mem_root=Path(mem_root))
    if not actor_valid: errors.append("registered actor identity is required")
    result={"status":"preview","writes":0,"selected":selected,"legacy_preserved":True,"accepted":0,"errors":errors}
    if not apply or errors: return result
    db=Path(mem_root)/"gms_trust.sqlite"; conn=sqlite3.connect(db)
    try:
        conn.executescript("""CREATE TABLE IF NOT EXISTS gms_migration_staging(
          legacy_key TEXT PRIMARY KEY, preview_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'staged', actor_id TEXT NOT NULL, rationale TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);""")
        now=datetime.now(timezone.utc).isoformat()
        for row in selected:
            conn.execute("INSERT OR IGNORE INTO gms_migration_staging VALUES (?,?,?,'staged',?,?,?,?)",
                         (row["legacy_key"],json.dumps(row,sort_keys=True),expected_hash,actor,rationale,now,now))
        conn.commit(); result.update(status="staged",writes=conn.total_changes,staged=conn.total_changes)
        return result
    finally: conn.close()

def rollback_migration(mem_root:Path, keys:list[str], *, actor:str, rationale:str, apply:bool=False)->dict[str,Any]:
    actor_valid,_=validate_reviewer_id(actor,mem_root=Path(mem_root))
    if len(rationale.strip())<10 or not actor_valid: return {"status":"error","errors":["registered actor and substantive rationale required"],"writes":0}
    db=Path(mem_root)/"gms_trust.sqlite"; rows=[]
    if db.exists():
        conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
        try:
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_migration_staging'").fetchone()
            if exists and keys:
                marks=",".join("?" for _ in keys); rows=[dict(r) for r in conn.execute(f"SELECT * FROM gms_migration_staging WHERE legacy_key IN ({marks}) AND state='staged'",keys)]
            if apply and rows:
                now=datetime.now(timezone.utc).isoformat()
                for row in rows: conn.execute("UPDATE gms_migration_staging SET state='rolled_back',actor_id=?,rationale=?,updated_at=? WHERE legacy_key=?",(actor,rationale,now,row["legacy_key"]))
                conn.commit()
        finally: conn.close()
    return {"status":"rolled_back" if apply else "preview","writes":len(rows) if apply else 0,"items":rows,"legacy_restored":True}
