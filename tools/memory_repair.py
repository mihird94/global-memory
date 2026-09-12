"""Source-Grounded Memory Repair Service.

Provides a disciplined, evidence-backed workflow for repairing incomplete legacy
records (e.g., 'car_stickers_status = active') without hallucinating missing fields.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_authority import authority_label
from schemas import compute_excerpt_hash


def find_repair_evidence(mem_root: Path, legacy_key: str) -> dict[str, Any]:
    root = Path(mem_root)
    tokens = [t.lower() for t in re.split(r"[._-]+", legacy_key) if len(t) > 2 and t != "status"]
    evidence_matches: list[dict[str, Any]] = []

    # 1. Search episodic history files
    hist_dir = root / "episodic" / "history"
    if hist_dir.exists():
        for fp in sorted(hist_dir.glob("*.md"), reverse=True):
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                for idx, line in enumerate(lines, start=1):
                    line_lower = line.lower()
                    if tokens and all(t in line_lower for t in tokens):
                        excerpt = line.strip()
                        rel_path = f"episodic/history/{fp.name}"
                        ref = f"{rel_path}#L{idx}"
                        evidence_matches.append({
                            "ref": ref,
                            "file": rel_path,
                            "line": idx,
                            "excerpt": excerpt,
                            "excerpt_hash": f"sha256:{compute_excerpt_hash(excerpt)}",
                            "date": fp.stem,
                            "source_type": "episodic_history",
                        })
            except Exception:
                pass

    # 2. Search project banks
    proj_dir = root / "projects"
    if proj_dir.exists():
        for p in proj_dir.iterdir():
            if p.is_dir():
                for fn in ("activeContext.md", "progress.md", "projectBrief.md"):
                    fp = p / fn
                    if fp.exists():
                        try:
                            content = fp.read_text(encoding="utf-8", errors="replace")
                            lines = content.splitlines()
                            for idx, line in enumerate(lines, start=1):
                                if tokens and all(t in line.lower() for t in tokens):
                                    excerpt = line.strip()
                                    rel_path = f"projects/{p.name}/{fn}"
                                    ref = f"{rel_path}#L{idx}"
                                    evidence_matches.append({
                                        "ref": ref,
                                        "file": rel_path,
                                        "line": idx,
                                        "excerpt": excerpt,
                                        "excerpt_hash": f"sha256:{compute_excerpt_hash(excerpt)}",
                                        "date": None,
                                        "source_type": "project_bank",
                                    })
                        except Exception:
                            pass

    # 3. Search claims in SQLite
    db = root / "gms_trust.sqlite"
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_claims'").fetchone():
                rows = conn.execute("SELECT claim_id, memory_key, value, created_at FROM gms_claims").fetchall()
                for r in rows:
                    hay = f"{r['memory_key']} {str(r['value'])}".lower()
                    if tokens and all(t in hay for t in tokens):
                        evidence_matches.append({
                            "ref": f"claim:{r['claim_id']}",
                            "file": "sqlite:gms_claims",
                            "line": r["claim_id"],
                            "excerpt": f"Key: {r['memory_key']}, Value: {r['value']}",
                            "excerpt_hash": f"sha256:{compute_excerpt_hash(str(r['value']))}",
                            "date": r["created_at"],
                            "source_type": "claim_ledger",
                        })
            conn.close()
        except Exception:
            pass

    return {
        "schema_version": "gms-repair-evidence-v1",
        "legacy_key": legacy_key,
        "search_tokens": tokens,
        "evidence_count": len(evidence_matches),
        "evidence": evidence_matches,
    }


def analyze_missing_fields(mem_root: Path, legacy_key: str) -> dict[str, Any]:
    root = Path(mem_root)
    facts_path = root / "semantic" / "facts.json"
    legacy_val = None
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            legacy_val = facts.get(legacy_key)
        except Exception:
            pass

    ev_result = find_repair_evidence(root, legacy_key)
    evidence_items = ev_result.get("evidence", [])

    # Field analysis
    fields: dict[str, Any] = {
        "statement": {"status": "recovered_from_source" if legacy_val else "still_unknown", "value": str(legacy_val) if legacy_val else None},
        "rationale": {"status": "still_unknown", "value": None},
        "scope": {"status": "suggested_by_ai", "value": {"project": "global-memory", "domain": legacy_key.split("_")[0]}},
        "implications": {"status": "still_unknown", "value": []},
        "source": {"status": "recovered_from_source" if evidence_items else "still_unknown", "value": evidence_items[0]["ref"] if evidence_items else None},
        "effective_time": {"status": "recovered_from_source" if evidence_items and evidence_items[0].get("date") else "still_unknown", "value": evidence_items[0].get("date") if evidence_items else None},
        "review_horizon": {"status": "suggested_by_ai", "value": "90d"},
    }

    # If any evidence mentions reasons, check if rationale can be recovered
    for ev in evidence_items:
        ex = ev["excerpt"].lower()
        if "because" in ex or "due to" in ex or "ordered" in ex or "received" in ex or "applied" in ex:
            fields["rationale"] = {"status": "recovered_from_source", "value": ev["excerpt"]}
            break

    # If rationale is still unknown, generate clarifying questions
    user_questions = []
    if fields["rationale"]["status"] == "still_unknown":
        user_questions.append({
            "field": "rationale",
            "question": f"What was the purpose or context behind '{legacy_key} = {legacy_val}'?",
            "suggested_actions": ["Provide physical/operational context", "Mark as historical artifact or discard"],
        })
    if not evidence_items:
        user_questions.append({
            "field": "source",
            "question": f"No source files mention '{legacy_key}'. Where did this fact originate?",
            "suggested_actions": ["Cite specific file or chat", "Treat as unverified imported legacy"],
        })

    return {
        "schema_version": "gms-repair-analysis-v1",
        "legacy_key": legacy_key,
        "legacy_value": legacy_val,
        "evidence_found_count": len(evidence_items),
        "fields": fields,
        "questions_for_user": user_questions,
        "repair_readiness": "ready_with_questions" if user_questions else "ready_for_staging",
    }


def stage_repair_candidate(
    mem_root: Path,
    legacy_key: str,
    repaired_payload: dict[str, Any],
    *,
    actor: str = "mihir",
    rationale: str = "",
    apply: bool = False,
) -> dict[str, Any]:
    root = Path(mem_root)
    analysis = analyze_missing_fields(root, legacy_key)

    canonical_key = repaired_payload.get("key") or legacy_key.replace("_", ".")
    candidate_id = f"cand_repair_{canonical_key}_{hashlib.sha256(legacy_key.encode()).hexdigest()[:8]}"
    content_hash = hashlib.sha256(json.dumps(repaired_payload, sort_keys=True).encode("utf-8")).hexdigest()

    if not apply:
        return {
            "schema_version": "gms-repair-stage-v1",
            "status": "preview",
            "candidate_id": candidate_id,
            "canonical_key": canonical_key,
            "legacy_key": legacy_key,
            "content_hash": content_hash,
            "durable_writes": 0,
            "dry_run": True,
            "preview_payload": repaired_payload,
            "legacy_preserved": True,
        }

    # When apply=True, insert candidate into gms_context_candidates as proposed
    db = root / "gms_trust.sqlite"
    if db.exists():
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gms_context_candidates (
                candidate_id TEXT PRIMARY KEY,
                canonical_key TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'proposed',
                reviewed_by TEXT,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR REPLACE INTO gms_context_candidates
            (candidate_id, canonical_key, content_hash, review_status, reviewed_by, created_at, payload_json)
            VALUES (?, ?, ?, 'proposed', NULL, datetime('now'), ?)
        """, (candidate_id, canonical_key, content_hash, json.dumps(repaired_payload)))
        conn.commit()
        conn.close()

    return {
        "schema_version": "gms-repair-stage-v1",
        "status": "staged",
        "candidate_id": candidate_id,
        "canonical_key": canonical_key,
        "legacy_key": legacy_key,
        "content_hash": content_hash,
        "durable_writes": 1,
        "dry_run": False,
        "legacy_preserved": True,
        "note": "Legacy fact remains intact in facts.json until candidate is reviewed and accepted.",
    }


def archive_opaque_fact(mem_root: Path, key: str, *, actor: str, rationale: str, apply: bool=False) -> dict[str,Any]:
    """Remove an unsupported opaque fact from current truth while preserving ledger history."""
    root=Path(mem_root); facts_path=root/"semantic"/"facts.json"
    facts=json.loads(facts_path.read_text()) if facts_path.exists() else {}
    if key not in facts: return {"status":"error","error":"fact not found"}
    evidence=find_repair_evidence(root,key)
    preview={"status":"preview","key":key,"value":facts[key],"evidence_count":evidence["evidence_count"],"recoverable":True}
    if len(rationale.strip())<10: return {**preview,"status":"error","error":"substantive rationale required"}
    if not apply: return preview
    prior=facts.pop(key); facts_path.write_text(json.dumps(facts,indent=2,sort_keys=True),encoding="utf-8")
    db=root/"gms_trust.sqlite"; conn=sqlite3.connect(db); now=datetime.now(timezone.utc).isoformat()
    rows=conn.execute("SELECT claim_id FROM gms_claims WHERE memory_key=? AND status='active'",(key,)).fetchall()
    conn.execute("UPDATE gms_claims SET status='archived_opaque',confidence=0.0 WHERE memory_key=? AND status='active'",(key,))
    for (claim_id,) in rows:
        conn.execute("""INSERT INTO gms_review_audit(candidate_id,canonical_key,action,reviewer_id,review_rationale,original_content_hash,accepted_content_hash,supersedes_claim_id,resulting_claim_id,reviewed_at)
          VALUES(?,?, 'archive_opaque',?,?,?,NULL,?,NULL,?)""",
          (f"claim:{claim_id}",key,actor,rationale,hashlib.sha256(str(prior).encode()).hexdigest(),claim_id,now))
    conn.commit(); conn.close(); return {**preview,"status":"archived","claims_archived":len(rows)}
