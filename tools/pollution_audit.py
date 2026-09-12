#!/usr/bin/env python3
"""
tools/pollution_audit.py — Production Pollution Audit and Surgical Cleanup Utility.

Audits gms_context_candidates, gms_claims, and facts.json for test fixtures,
synthetic keys, and smoke-test leftovers. Enforces zero mutation on dry-run,
and records an append-only audit trail in gms_review_audit on --apply.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories"))
DEFAULT_DB_PATH = DEFAULT_MEM_ROOT / "gms_trust.sqlite"
DEFAULT_FACTS_PATH = DEFAULT_MEM_ROOT / "semantic" / "facts.json"

TEST_KEY_PATTERNS = [
    re.compile(r"^test[\._]", re.IGNORECASE),
    re.compile(r"^mcp_test", re.IGNORECASE),
    re.compile(r"^latest_key$", re.IGNORECASE),
]

KNOWN_POLLUTION_CANDIDATE_IDS = {
    "cand_mbrain.agent_trust_architecture_2bd8e5c4816f",
}

KNOWN_POLLUTION_CLAIM_IDS = {119}

TEST_REVIEWERS = {"tester", "human-test", "unrankedreviewer"}
SUSPICIOUS_FIXTURE_AGENTS = {"agent_test", "agent_1", "dreamcycle-mock-provider"}


def is_test_key(key: str) -> bool:
    if not key:
        return False
    return any(p.search(key) for p in TEST_KEY_PATTERNS)


def run_pollution_audit(db_path: Path | None = None, mem_root: Path | None = None) -> dict:
    root = mem_root or Path(os.environ.get("MEMORY_ROOT", DEFAULT_MEM_ROOT))
    db = db_path or (root / "gms_trust.sqlite")
    facts_file = root / "semantic" / "facts.json"

    findings = {
        "test_candidates": [],
        "test_claims": [],
        "test_facts": [],
        "total_pollutants": 0,
        "convention_warnings": {
            "suspicious_fixture_claims": [],
            "canonical_key_collisions": [],
            "flat_fact_count": 0,
            "status_only_facts": [],
        },
    }

    # 1. Inspect facts.json
    if facts_file.exists():
        try:
            facts_data = json.loads(facts_file.read_text(encoding="utf-8"))
            if isinstance(facts_data, dict):
                normalized_keys: dict[str, list[str]] = {}
                for k in sorted(facts_data.keys()):
                    value = facts_data[k]
                    normalized = re.sub(r"[^a-z0-9]+", ".", k.lower()).strip(".")
                    normalized_keys.setdefault(normalized, []).append(k)
                    parsed = value
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                        except Exception:
                            pass
                    if not (isinstance(parsed, dict) and parsed.get("schema_version") == "gms-context-record-v1"):
                        findings["convention_warnings"]["flat_fact_count"] += 1
                    if str(value).strip().lower() in {"active", "retired", "done", "blocked", "complete", "completed", "unknown"}:
                        findings["convention_warnings"]["status_only_facts"].append(k)
                    if is_test_key(k):
                        findings["test_facts"].append({"key": k, "value": str(facts_data[k])[:100]})
                findings["convention_warnings"]["canonical_key_collisions"] = [
                    keys for keys in normalized_keys.values() if len(keys) > 1
                ]
        except Exception:
            pass

    # 2. Inspect SQLite DB
    if db.exists():
        conn = sqlite3.connect(str(db), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            # Check gms_context_candidates
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_context_candidates'")
            if cursor.fetchone():
                cursor.execute(
                    "SELECT candidate_id, canonical_key, content_hash, review_status, reviewed_by, created_at FROM gms_context_candidates"
                )
                for row in cursor.fetchall():
                    cid = row["candidate_id"]
                    ckey = row["canonical_key"]
                    rev_by = (row["reviewed_by"] or "").lower()
                    if (
                        cid in KNOWN_POLLUTION_CANDIDATE_IDS
                        or is_test_key(ckey)
                        or rev_by in TEST_REVIEWERS
                    ):
                        findings["test_candidates"].append({
                            "candidate_id": cid,
                            "canonical_key": ckey,
                            "content_hash": row["content_hash"] or "",
                            "review_status": row["review_status"],
                            "reviewed_by": row["reviewed_by"],
                            "created_at": row["created_at"],
                        })

            # Check gms_claims
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_claims'")
            if cursor.fetchone():
                cursor.execute(
                    "SELECT claim_id, memory_key, value, agent_id, status, created_at FROM gms_claims"
                )
                for row in cursor.fetchall():
                    cid = row["claim_id"]
                    key = row["memory_key"]
                    agent = row["agent_id"] or ""
                    val = row["value"] or ""
                    # Claim #119 was created during pass 5 smoke testing with agent Mihir and key mbrain.agent_trust_architecture
                    is_smoke_claim = cid in KNOWN_POLLUTION_CLAIM_IDS
                    if is_test_key(key) or is_smoke_claim:
                        findings["test_claims"].append({
                            "claim_id": cid,
                            "key": key,
                            "value": val,
                            "agent": agent,
                            "status": row["status"],
                            "created_at": row["created_at"],
                        })
                    elif agent.lower() in SUSPICIOUS_FIXTURE_AGENTS and row["status"] != "archived_fixture":
                        findings["convention_warnings"]["suspicious_fixture_claims"].append({
                            "claim_id": cid,
                            "key": key,
                            "agent": agent,
                            "status": row["status"],
                        })
        finally:
            conn.close()

    findings["total_pollutants"] = (
        len(findings["test_candidates"])
        + len(findings["test_claims"])
        + len(findings["test_facts"])
    )
    return findings


def run_pollution_cleanup(
    apply: bool = False,
    db_path: Path | None = None,
    mem_root: Path | None = None,
    operator: str = "mihir",
) -> dict:
    audit = run_pollution_audit(db_path=db_path, mem_root=mem_root)
    if not apply:
        return {
            "status": "dry_run",
            "message": "Dry-run complete. Zero modifications performed.",
            "plan": audit,
        }

    import hashlib
    root = mem_root or Path(os.environ.get("MEMORY_ROOT", DEFAULT_MEM_ROOT))
    db = db_path or (root / "gms_trust.sqlite")
    facts_file = root / "semantic" / "facts.json"
    now_iso = datetime.now(timezone.utc).isoformat()

    deleted_summary = {
        "deleted_candidates": [c["candidate_id"] for c in audit["test_candidates"]],
        "deleted_claims": [c["claim_id"] for c in audit["test_claims"]],
        "deleted_facts": [f["key"] for f in audit["test_facts"]],
    }

    # 1. Clean facts.json
    if facts_file.exists() and audit["test_facts"]:
        try:
            facts_data = json.loads(facts_file.read_text(encoding="utf-8"))
            if isinstance(facts_data, dict):
                for f in audit["test_facts"]:
                    facts_data.pop(f["key"], None)
                facts_file.write_text(json.dumps(facts_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            return {"status": "error", "error": f"Failed to clean facts.json: {e}"}

    # 2. Clean SQLite DB
    if db.exists() and (audit["test_candidates"] or audit["test_claims"]):
        conn = sqlite3.connect(str(db), timeout=10.0)
        try:
            cursor = conn.cursor()
            # Ensure gms_review_audit table exists
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gms_review_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    review_rationale TEXT NOT NULL,
                    original_content_hash TEXT NOT NULL,
                    accepted_content_hash TEXT,
                    supersedes_claim_id INTEGER,
                    resulting_claim_id INTEGER,
                    reviewed_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Delete candidates
            for cand in audit["test_candidates"]:
                cursor.execute(
                    "DELETE FROM gms_context_candidates WHERE candidate_id = ?",
                    (cand["candidate_id"],),
                )
                c_hash = cand.get("content_hash") or "unknown"
                cursor.execute(
                    """
                    INSERT INTO gms_review_audit (
                        candidate_id, canonical_key, action, reviewer_id, review_rationale,
                        original_content_hash, accepted_content_hash, supersedes_claim_id,
                        resulting_claim_id, reviewed_at
                    ) VALUES (?, ?, 'pollution_cleanup', ?, ?, ?, NULL, NULL, NULL, ?)
                    """,
                    (
                        cand["candidate_id"],
                        cand["canonical_key"],
                        operator,
                        f"Automated cleanup of test/smoke artifact {cand['candidate_id']}",
                        c_hash,
                        now_iso,
                    ),
                )

            # Delete claims
            for claim in audit["test_claims"]:
                cursor.execute(
                    "DELETE FROM gms_claims WHERE claim_id = ?",
                    (claim["claim_id"],),
                )
                cl_hash = hashlib.sha256(str(claim.get("value", "")).encode("utf-8")).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO gms_review_audit (
                        candidate_id, canonical_key, action, reviewer_id, review_rationale,
                        original_content_hash, accepted_content_hash, supersedes_claim_id,
                        resulting_claim_id, reviewed_at
                    ) VALUES (?, ?, 'pollution_cleanup', ?, ?, ?, NULL, ?, NULL, ?)
                    """,
                    (
                        f"claim:{claim['claim_id']}",
                        claim["key"],
                        operator,
                        f"Automated cleanup of test claim #{claim['claim_id']} ({claim['key']})",
                        cl_hash,
                        claim["claim_id"],
                        now_iso,
                    ),
                )

            polluted_keys = {f["key"] for f in audit["test_facts"]} | {c["key"] for c in audit["test_claims"]}
            for key in polluted_keys:
                cursor.execute("DELETE FROM gms_fact_provenance WHERE fact_key = ?", (key,))

            conn.commit()
        finally:
            conn.close()

    return {
        "status": "applied",
        "message": f"Successfully cleaned {len(deleted_summary['deleted_candidates'])} candidates, {len(deleted_summary['deleted_claims'])} claims, and {len(deleted_summary['deleted_facts'])} facts.",
        "deleted": deleted_summary,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit and clean test pollution in GMS memory files.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Perform read-only audit without mutation (default)")
    parser.add_argument("--apply", action="store_true", help="Apply cleanup and record audit trail")
    parser.add_argument("--db-path", type=Path, default=None, help="Custom path to gms_trust.sqlite")
    parser.add_argument("--mem-root", type=Path, default=None, help="Custom memory root directory")
    args = parser.parse_args()

    if args.apply:
        result = run_pollution_cleanup(apply=True, db_path=args.db_path, mem_root=args.mem_root)
    else:
        result = run_pollution_audit(db_path=args.db_path, mem_root=args.mem_root)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
