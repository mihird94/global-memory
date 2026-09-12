"""Append-only, optimistic-concurrency lifecycle engine for context records."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from reviewers import validate_reviewer_id

STATES = {"proposed", "accepted", "rejected", "deferred", "superseded", "archived"}
OPERATIONS = {"add", "reinforce", "merge", "supersede", "contradict", "noop", "archive", "restore"}
LEGAL = {
    "proposed": {"accepted", "rejected", "deferred"},
    "deferred": {"proposed", "rejected"},
    "accepted": {"superseded", "archived"},
    "superseded": {"archived"},
    "archived": {"accepted"},
    "rejected": set(),
}


def content_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS gms_context_records (
      record_id TEXT PRIMARY KEY, canonical_key TEXT NOT NULL, state TEXT NOT NULL,
      content_json TEXT NOT NULL, content_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS gms_lifecycle_audit (
      audit_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
      record_id TEXT NOT NULL, canonical_key TEXT NOT NULL, prior_state TEXT, next_state TEXT NOT NULL,
      operation TEXT NOT NULL, actor_id TEXT NOT NULL, actor_kind TEXT NOT NULL, rationale TEXT NOT NULL,
      original_hash TEXT, resulting_hash TEXT NOT NULL, effective_at TEXT, event_at TEXT,
      recorded_at TEXT NOT NULL, source_refs_json TEXT NOT NULL, related_ids_json TEXT NOT NULL
    );
    """)


def preview_transition(*, prior_state: str | None, next_state: str, operation: str,
                       rationale: str, expected_hash: str | None = None,
                       current_hash: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if next_state not in STATES: errors.append(f"unknown lifecycle state: {next_state}")
    if operation not in OPERATIONS: errors.append(f"unknown operation: {operation}")
    if prior_state is not None and next_state not in LEGAL.get(prior_state, set()):
        errors.append(f"illegal lifecycle transition: {prior_state} -> {next_state}")
    if len(str(rationale).strip()) < 10: errors.append("substantive rationale must be at least 10 characters")
    if expected_hash and current_hash and expected_hash != current_hash:
        errors.append("content changed since preview; refresh and try again")
    return {"valid": not errors, "prior_state": prior_state, "next_state": next_state,
            "operation": operation, "errors": errors}


def transition(db_path: Path, request: dict[str, Any], apply: bool = False) -> dict[str, Any]:
    """Preview by default; apply only with an explicit flag and registered caller identity upstream."""
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if apply:
            ensure_tables(conn)
        rid = str(request["record_id"])
        audit_exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_lifecycle_audit'").fetchone()
        records_exist=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_context_records'").fetchone()
        existing_audit = conn.execute("SELECT * FROM gms_lifecycle_audit WHERE request_id=?", (request["request_id"],)).fetchone() if audit_exists else None
        if existing_audit:
            return {"status": "idempotent", "applied": True, "audit": dict(existing_audit)}
        row = conn.execute("SELECT * FROM gms_context_records WHERE record_id=?", (rid,)).fetchone() if records_exist else None
        prior = row["state"] if row else None
        old_hash = row["content_hash"] if row else None
        check = preview_transition(prior_state=prior, next_state=request["next_state"],
                                   operation=request["operation"], rationale=request.get("rationale", ""),
                                   expected_hash=request.get("expected_hash"), current_hash=old_hash)
        valid_actor,_ = validate_reviewer_id(str(request.get("actor_id", "")), mem_root=db_path.parent)
        if apply and not valid_actor:
            check["errors"].append("actor identity is not registered")
            check["valid"] = False
        new_hash = content_hash(request.get("content", json.loads(row["content_json"]) if row else {}))
        result = {**check, "status": "preview", "applied": False, "record_id": rid,
                  "original_hash": old_hash, "resulting_hash": new_hash}
        if not apply or not check["valid"]: return result
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(request.get("content", json.loads(row["content_json"]) if row else {}), sort_keys=True)
        if row:
            conn.execute("UPDATE gms_context_records SET state=?,content_json=?,content_hash=?,version=version+1,updated_at=? WHERE record_id=?",
                         (request["next_state"], payload, new_hash, now, rid))
        else:
            conn.execute("INSERT INTO gms_context_records VALUES (?,?,?,?,?,1,?,?)",
                         (rid, request["canonical_key"], request["next_state"], payload, new_hash, now, now))
        conn.execute("""INSERT INTO gms_lifecycle_audit
          (request_id,record_id,canonical_key,prior_state,next_state,operation,actor_id,actor_kind,rationale,
           original_hash,resulting_hash,effective_at,event_at,recorded_at,source_refs_json,related_ids_json)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (request["request_id"],rid,request["canonical_key"],prior,request["next_state"],request["operation"],
           request["actor_id"],request["actor_kind"],request["rationale"],old_hash,new_hash,
           request.get("effective_at"),request.get("event_at"),now,json.dumps(request.get("source_refs",[])),
           json.dumps(request.get("related_ids",[]))))
        conn.commit()
        result.update(status="applied", applied=True)
        return result
    finally:
        conn.close()


def lifecycle_history(db_path: Path, record_id: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    try:
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_lifecycle_audit'").fetchone()
        if not exists: return []
        return [dict(r) for r in conn.execute("SELECT * FROM gms_lifecycle_audit WHERE record_id=? ORDER BY audit_id", (record_id,))]
    finally: conn.close()
