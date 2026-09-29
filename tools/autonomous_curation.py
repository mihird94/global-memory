"""Evidence-gated system curation with reversible user contests."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import memory_mcp_server
import schemas
from memory_aliases import canonicalize


SYSTEM_REVIEWER = "system"


def assess_candidate(candidate: dict[str, Any], mem_root: Path) -> dict[str, Any]:
    """Return a deterministic, inspectable admission decision."""
    payload = candidate.get("payload") or {}
    evidence = payload.get("evidence") or []
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for item in evidence:
        valid, status, details = schemas.validate_source_reference(
            str(item.get("ref") or ""),
            excerpt_hash=item.get("excerpt_hash"),
            mem_root=mem_root,
        )
        if not valid:
            target = warnings if status == "hash_mismatch" else failures
            target.append({"ref": item.get("ref"), "status": status, "details": details})

    required = ["statement", "scope", "provenance", "evidence"]
    if candidate.get("record_type") in ("decision", "policy"):
        required += ["rationale", "implications"]
    missing = [field for field in required if not payload.get(field)]
    diff = candidate.get("diff") or {}
    authority = str(payload.get("authority") or "llm_inference")

    policy_text = " ".join(str(payload.get(field) or "") for field in ("statement", "rationale"))
    policy_text += " " + " ".join(str(x) for x in (payload.get("implications") or []))
    owner_superseded = any(phrase in policy_text.lower() for phrase in (
        "cannot be auto-promoted", "without local-first human review", "explicit manual approval",
    ))
    if owner_superseded:
        return {
            "decision": "reject", "eligible": False,
            "basis": "Rejected because the candidate's mandatory-human-review posture was superseded by the owner's system-decides policy.",
            "missing_fields": missing, "evidence_failures": failures, "evidence_warnings": warnings,
        }
    if missing or failures:
        return {
            "decision": "reject",
            "eligible": False,
            "basis": "Candidate failed the deterministic structure or source-integrity gate.",
            "missing_fields": missing,
            "evidence_failures": failures,
            "evidence_warnings": warnings,
        }

    operation = "supersede" if diff.get("has_existing") else "accept"
    return {
        "decision": operation,
        "eligible": True,
        "basis": (
            f"System accepted a schema-valid {candidate.get('record_type')} with {len(evidence)} "
            f"source-present evidence item(s); authority={authority}; integrity_warnings={len(warnings)}. "
            "The decision is contestable."
        ),
        "authority": authority,
        "evidence_count": len(evidence),
        "has_existing": bool(diff.get("has_existing")),
        "evidence_warnings": warnings,
    }


def curate_pending(mem_root: Path, *, apply: bool = False, limit: int = 100) -> dict[str, Any]:
    db_path = mem_root / "gms_trust.sqlite"
    pending = memory_mcp_server.get_context_candidates(
        status="proposed", limit=limit, db_path=db_path
    )
    outcomes: list[dict[str, Any]] = []
    for candidate in pending:
        original_key = candidate["canonical_key"]
        normalized_key = canonicalize(original_key)
        if apply and normalized_key != original_key:
            payload = dict(candidate.get("payload") or {})
            payload["key"] = normalized_key
            payload.setdefault("aliases", []).append(original_key)
            new_hash = schemas.compute_canonical_content_hash(payload)
            conn = memory_mcp_server.get_db_connection(db_path)
            conn.execute(
                "UPDATE gms_context_candidates SET canonical_key=?,payload_json=?,content_hash=?,updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
                (normalized_key, json.dumps(payload, sort_keys=True, ensure_ascii=False), new_hash, candidate["candidate_id"]),
            )
            conn.commit(); conn.close()
            candidate = memory_mcp_server.get_context_candidate_by_id(candidate["candidate_id"], db_path=db_path)
        assessment = assess_candidate(candidate, mem_root)
        outcome = {
            "candidate_id": candidate["candidate_id"],
            "canonical_key": candidate["canonical_key"],
            "record_type": candidate["record_type"],
            **assessment,
            "applied": False,
        }
        if apply:
            action = assessment["decision"]
            result = memory_mcp_server.review_context_candidate(
                candidate_id=candidate["candidate_id"],
                action=action,
                reviewer=SYSTEM_REVIEWER,
                rationale=assessment["basis"],
                expected_content_hash=candidate.get("content_hash"),
                db_path=db_path,
            )
            outcome["applied"] = result.get("status") in {"accepted", "merged", "rejected"}
            outcome["result"] = result
        outcomes.append(outcome)
    return {
        "status": "applied" if apply else "preview",
        "policy": "system-decides-user-may-contest-v1",
        "considered": len(outcomes),
        "accepted": sum(1 for x in outcomes if x["decision"] in {"accept", "supersede"}),
        "rejected": sum(1 for x in outcomes if x["decision"] == "reject"),
        "outcomes": outcomes,
    }


def contest_candidate(mem_root: Path, candidate_id: str, rationale: str, *, apply: bool = False) -> dict[str, Any]:
    """Contest a system decision and restore the immediately superseded truth."""
    clean_rationale = str(rationale).strip()
    if len(clean_rationale) < 10:
        return {"status": "error", "error": "Contest rationale must be at least 10 characters."}
    db_path = mem_root / "gms_trust.sqlite"
    candidate = memory_mcp_server.get_context_candidate_by_id(candidate_id, db_path=db_path)
    if not candidate:
        return {"status": "error", "error": f"Candidate '{candidate_id}' not found."}
    if candidate.get("reviewed_by") != SYSTEM_REVIEWER or candidate.get("review_status") not in {"accepted", "merged"}:
        return {"status": "error", "error": "Only a system-accepted candidate can be contested here."}

    conn = memory_mcp_server.get_db_connection(db_path)
    conn.row_factory = __import__("sqlite3").Row
    audit = conn.execute(
        "SELECT * FROM gms_review_audit WHERE candidate_id=? AND reviewer_id='system' "
        "ORDER BY audit_id DESC LIMIT 1", (candidate_id,)
    ).fetchone()
    if not audit:
        conn.close()
        return {"status": "error", "error": "System acceptance audit event is missing."}
    preview = {
        "status": "preview", "candidate_id": candidate_id,
        "canonical_key": candidate["canonical_key"],
        "remove_claim_id": audit["resulting_claim_id"],
        "restore_claim_id": audit["supersedes_claim_id"],
        "rationale": clean_rationale,
    }
    if not apply:
        conn.close()
        return preview

    now = datetime.now(UTC).isoformat()
    key = candidate["canonical_key"]
    if audit["resulting_claim_id"]:
        conn.execute("UPDATE gms_claims SET status='superseded', confidence=0.0 WHERE claim_id=?", (audit["resulting_claim_id"],))
    prior_value = None
    if audit["supersedes_claim_id"]:
        prior = conn.execute("SELECT value FROM gms_claims WHERE claim_id=?", (audit["supersedes_claim_id"],)).fetchone()
        if prior:
            prior_value = prior[0]
            conn.execute("UPDATE gms_claims SET status='active', confidence=1.0 WHERE claim_id=?", (audit["supersedes_claim_id"],))
    facts_path = mem_root / "semantic" / "facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else {}
    if prior_value is None:
        facts.pop(key, None)
    else:
        facts[key] = prior_value
    facts_path.write_text(json.dumps(facts, indent=2, sort_keys=True), encoding="utf-8")
    conn.execute(
        "UPDATE gms_context_candidates SET review_status='contested', review_rationale=?, reviewed_by='mihir', reviewed_at=?, updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
        (clean_rationale, now, candidate_id),
    )
    conn.execute(
        "INSERT INTO gms_review_audit (candidate_id,canonical_key,action,reviewer_id,review_rationale,original_content_hash,accepted_content_hash,supersedes_claim_id,resulting_claim_id,reviewed_at) VALUES (?,?, 'contest','mihir',?,?,NULL,?,?,?)",
        (candidate_id, key, clean_rationale, candidate.get("content_hash") or "", audit["resulting_claim_id"], audit["supersedes_claim_id"], now),
    )
    conn.commit()
    conn.close()

    extractor = candidate.get("extractor_agent")
    if extractor and str(extractor).lower() not in {"mihir", "system"}:
        try:
            memory_mcp_server.increment_agent_beta(str(extractor), 1.5)
        except Exception:
            pass

    return {**preview, "status": "contested", "restored": prior_value is not None}
