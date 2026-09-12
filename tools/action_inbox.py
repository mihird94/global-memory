"""Action Inbox Service.

Ranks operational and memory items by explicit consequence rules:
1. Blocking contradiction affecting active work
2. Human decision required for an active task
3. Invalid or missing evidence on actionable context
4. Stale operational fact used by an active workflow
5. Broken task handoff or expired lease
6. Proposed decision/policy awaiting review
7. Alias collision affecting retrieved truth
8. Opaque status record needing repair
9. Lower-impact candidate review
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_aliases import alias_inventory, canonicalize
from memory_authority import authority_label
from memory_lifecycle import transition

INBOX_CATEGORIES = [
    ("blocking_contradiction", 1, "Blocking Contradiction"),
    ("human_decision_required", 2, "Required Human Decision"),
    ("invalid_missing_evidence", 3, "Evidence Failure"),
    ("stale_operational_fact", 4, "Stale Operational Truth"),
    ("broken_task_handoff", 5, "Broken Task Handoff / Expired Lease"),
    ("proposed_decision", 6, "Proposed Decision / Policy"),
    ("alias_collision", 7, "Canonical Key Collision"),
    ("opaque_status", 8, "Opaque Memory Repair"),
    ("candidate_review", 9, "Context Candidate Review"),
]


def list_inbox_items(mem_root: Path, *, project: str = "") -> dict[str, Any]:
    root = Path(mem_root)
    items: list[dict[str, Any]] = []

    # 1. Check alias collisions (Severity 7 or 1 if project matching)
    try:
        inv = alias_inventory(root)
        for col in inv.get("collisions", []):
            can_k = col.get("canonical_key", "")
            recs = col.get("records", [])
            is_active_proj = project and project in can_k
            cat = "blocking_contradiction" if is_active_proj else "alias_collision"
            sev = 1 if is_active_proj else 7
            content_sig = hashlib.sha256(json.dumps(col, sort_keys=True).encode("utf-8")).hexdigest()
            items.append({
                "inbox_id": f"inbox_col_{can_k}",
                "category": cat,
                "severity": sev,
                "title": f"Key Collision: {can_k}",
                "description": f"Multiple competing legacy keys: {', '.join([r['key'] for r in recs])}",
                "consequence": "Retrieval may return conflicting values or ambiguity for downstream agents.",
                "affected_scope": {"canonical_key": can_k, "project": project or "global"},
                "evidence": [{"source": "semantic/facts.json", "detail": f"{len(recs)} conflicting representations"}],
                "action_impact": {
                    "on_accept": "Consolidates to single canonical key via contradict/merge candidate.",
                    "on_reject": "Preserves split keys, risking retrieval ambiguity.",
                    "on_defer": "Postpones adjudication until next maintenance cycle.",
                },
                "reversible": True,
                "content_hash": content_sig,
                "target_type": "collision",
                "target_id": can_k,
                "raw_data": col,
            })
    except Exception:
        pass

    # 2. Check candidates in SQLite (Severity 6 for decisions/policies, Severity 9 for others)
    db = root / "gms_trust.sqlite"
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_context_candidates'").fetchone():
                rows = conn.execute(
                    "SELECT candidate_id, canonical_key, content_hash, review_status, payload_json, created_at "
                    "FROM gms_context_candidates WHERE review_status = 'proposed' ORDER BY created_at DESC"
                ).fetchall()
                for r in rows:
                    cid = r["candidate_id"]
                    ckey = r["canonical_key"]
                    payload = {}
                    try:
                        payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
                    except Exception:
                        pass

                    rec_type = payload.get("record_type", "fact")
                    is_decision = rec_type in ("decision", "policy") or "decision" in ckey.lower() or "policy" in ckey.lower()
                    cat = "proposed_decision" if is_decision else "candidate_review"
                    sev = 6 if is_decision else 9

                    items.append({
                        "inbox_id": f"inbox_cand_{cid}",
                        "category": cat,
                        "severity": sev,
                        "title": f"Proposed {rec_type.capitalize()}: {ckey}",
                        "description": payload.get("statement", f"Harvest candidate {cid}"),
                        "consequence": "Decisions and policies cannot be auto-promoted without human verification." if is_decision else "Context candidate pending inclusion in active memory.",
                        "affected_scope": payload.get("scope", {"key": ckey}),
                        "evidence": payload.get("evidence", [{"ref": f"candidate:{cid}"}]),
                        "action_impact": {
                            "on_accept": f"Promotes {ckey} into active memory with full audit provenance.",
                            "on_reject": "Discards candidate from context packet consideration.",
                            "on_defer": "Keeps candidate staged for future review.",
                        },
                        "reversible": True,
                        "content_hash": r["content_hash"] or hashlib.sha256(r["payload_json"].encode("utf-8")).hexdigest(),
                        "target_type": "candidate",
                        "target_id": cid,
                        "raw_data": payload,
                    })
            # 3. Check tasks for broken handoffs or expired leases (Severity 5)
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_tasks'").fetchone():
                now_iso = datetime.now(timezone.utc).isoformat()
                task_rows = conn.execute(
                    "SELECT task_id, project, title, status, owner_agent, lease_expires_at, updated_at "
                    "FROM gms_tasks WHERE status = 'in_progress'"
                ).fetchall()
                for tr in task_rows:
                    if tr["lease_expires_at"] and tr["lease_expires_at"] < now_iso[:10]:
                        items.append({
                            "inbox_id": f"inbox_lease_{tr['task_id']}",
                            "category": "broken_task_handoff",
                            "severity": 5,
                            "title": f"Expired Task Lease: {tr['title']}",
                            "description": f"Task {tr['task_id']} held by {tr['owner_agent']} expired on {tr['lease_expires_at']}.",
                            "consequence": "Parallel agents cannot claim work; potential abandoned task state.",
                            "affected_scope": {"task_id": tr["task_id"], "project": tr["project"]},
                            "evidence": [{"source": f"task:{tr['task_id']}", "detail": f"Lease expired {tr['lease_expires_at']}"}],
                            "action_impact": {
                                "on_accept": "Reclaims or resets task lease.",
                                "on_reject": "Leaves task blocked in current lease.",
                            },
                            "reversible": True,
                            "content_hash": hashlib.sha256(str(tr['task_id']).encode("utf-8")).hexdigest(),
                            "target_type": "task",
                            "target_id": tr["task_id"],
                            "raw_data": dict(tr),
                        })
            conn.close()
        except Exception:
            pass

    # 4. Check opaque status records (Severity 8)
    facts_path = root / "semantic" / "facts.json"
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            for k, v in facts.items():
                if "status" in k and isinstance(v, str) and v.lower() in ("active", "done", "pending", "retired", "true", "false"):
                    items.append({
                        "inbox_id": f"inbox_opaque_{k}",
                        "category": "opaque_status",
                        "severity": 8,
                        "title": f"Opaque Status Fact: {k}",
                        "description": f"'{k}' is stored as bare status '{v}' without rationale or scope.",
                        "consequence": "Future agents cannot determine why this status exists or when it expires.",
                        "affected_scope": {"key": k},
                        "evidence": [{"source": f"semantic/facts.json#{k}", "value": v}],
                        "action_impact": {
                            "on_repair": "Discovers source context and stages structured replacement.",
                            "on_defer": "Retains legacy flat string.",
                        },
                        "reversible": True,
                        "content_hash": hashlib.sha256(f"{k}:{v}".encode("utf-8")).hexdigest(),
                        "target_type": "opaque_status",
                        "target_id": k,
                        "raw_data": {"key": k, "value": v},
                    })
        except Exception:
            pass

    # Sort by consequence severity ascending (1 is highest priority), then inbox_id
    items.sort(key=lambda x: (x["severity"], x["inbox_id"]))

    return {
        "schema_version": "gms-action-inbox-v1",
        "total_items": len(items),
        "items": items,
        "categories": {cat[0]: len([i for i in items if i["category"] == cat[0]]) for cat in INBOX_CATEGORIES},
    }


def preview_inbox_action(
    mem_root: Path,
    inbox_id: str,
    action: str = "accept",
    *,
    project: str = "",
    reviewer: str = "mihir",
    rationale: str = "",
) -> dict[str, Any]:
    """Generates a zero-write preview of what would change if an inbox action is executed."""
    root = Path(mem_root)
    inv = list_inbox_items(root)
    item = next((i for i in inv.get("items", []) if i["inbox_id"] == inbox_id), None)
    if not item:
        return {"error": "ITEM_NOT_FOUND", "inbox_id": inbox_id}

    return {
        "schema_version": "gms-inbox-preview-v1",
        "inbox_id": inbox_id,
        "action": action,
        "reviewer": reviewer,
        "rationale": rationale,
        "target_type": item["target_type"],
        "target_id": item["target_id"],
        "expected_hash": item["content_hash"],
        "consequence_summary": item["action_impact"].get(f"on_{action}", f"Executes {action} on {item['target_id']}"),
        "reversible": item["reversible"],
        "durable_writes": 0,
        "dry_run": True,
    }
