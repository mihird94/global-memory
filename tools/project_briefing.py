"""Mbrain Project Briefing Engine and Agent Resumption Service.

Implements the canonical gms-project-briefing-v1 schema answering the 10
operational context questions for human operators and collaborating agents.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from context_retrieval_planner import retrieve
from memory_aliases import alias_inventory, canonicalize
from memory_authority import authority_label

PROFILE_BUDGETS = {"small": 900, "standard": 2400, "deep": 6000}


def _extract_project_goal(root: Path, project_id: str) -> dict[str, Any]:
    brief_file = root / "projects" / project_id / "projectBrief.md"
    if brief_file.exists():
        try:
            content = brief_file.read_text(encoding="utf-8", errors="replace")
            overview = re.search(r"^## Overview\s*\n(.*?)(?=^## |\Z)", content, re.MULTILINE | re.DOTALL)
            if overview and overview.group(1).strip():
                return {"statement": overview.group(1).strip(), "source_refs": [f"projects/{project_id}/projectBrief.md#Overview"]}
            # First paragraph containing prose rather than only headings.
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
            for p in paragraphs:
                if not p.startswith("#") and len(p.split()) >= 5:
                    return {"statement": p, "source_refs": [f"projects/{project_id}/projectBrief.md"]}
            if paragraphs:
                return {"statement": paragraphs[0].lstrip("#").strip(), "source_refs": [f"projects/{project_id}/projectBrief.md"]}
        except Exception:
            pass
    return {"statement": "Project goal unavailable", "source_refs": [],
            "missing_context": ["projectBrief.md Overview or explicit goal"]}


def _extract_project_verification(root: Path, project_id: str) -> list[dict[str, Any]]:
    items = []
    active_file = root / "projects" / project_id / "activeContext.md"
    if active_file.exists():
        try:
            text = active_file.read_text(encoding="utf-8", errors="replace")
            # The project bank is evidence of a recorded verification, not a
            # live test execution. Prefer the newest statements and never turn
            # words such as "green" into current proof.
            lines=[line.strip("- *").strip() for line in text.splitlines()
                   if line.strip() and not line.lstrip().startswith("#") and any(w in line.lower() for w in
                   ("test", "pytest", "javascript", "diff check", "verification", "benchmark"))]
            seen=set()
            for line in reversed(lines):
                normalized=re.sub(r"\s+"," ",line)
                if normalized in seen: continue
                seen.add(normalized)
                items.append({"criterion_id":f"recorded_{len(items)+1}","statement":line,
                    "source":f"projects/{project_id}/activeContext.md","verified":False,
                    "verification_state":"recorded_not_live","requires_revalidation":True})
                if len(items)>=8: break
        except Exception:
            pass
    return items


def _extract_project_recent_changes(root: Path, project_id: str, limit: int = 5) -> list[dict[str, Any]]:
    changes = []
    active_file = root / "projects" / project_id / "activeContext.md"
    if active_file.exists():
        try:
            text = active_file.read_text(encoding="utf-8", errors="replace")
            updates = re.findall(r"### Update \(([^)]+)\)\n(.*?)(?=\n### Update|\Z)", text, re.DOTALL)
            for date_str, body in reversed(updates[-limit:]):
                first_line = body.strip().splitlines()[0] if body.strip() else ""
                changes.append({
                    "timestamp": date_str,
                    "summary": first_line[:140],
                    "details": body.strip()[:400],
                    "source": f"projects/{project_id}/activeContext.md",
                })
        except Exception:
            pass
    return changes


def _infer_next_action(active_tasks: list[dict[str, Any]], blocking_issues: list[dict[str, Any]], project_id: str) -> dict[str, Any]:
    # If there are blocking issues, the first action must be addressing blockers
    if blocking_issues:
        first_blocker = blocking_issues[0]
        return {
            "statement": f"Resolve blocking issue: {first_blocker.get('title') or first_blocker.get('statement') or 'Collision / Blocker'}",
            "rationale": first_blocker.get("warning") or first_blocker.get("inclusion_reason") or "Active operational conflict blocks safe continuation",
            "acceptance_criteria": [
                "Investigate competing claims / collision in Action Inbox",
                "Adjudicate collision or provide explicit user resolution",
                "Re-run verification test suite",
            ],
            "source_type": "blocking_issue",
        }

    # If there is an in_progress task
    in_prog = [t for t in active_tasks if t.get("status") == "in_progress"]
    if in_prog:
        curr = in_prog[0]
        return {
            "statement": f"Resume active task: {curr.get('title', 'Ongoing task')}",
            "rationale": curr.get("objective", "Task currently claimed and in progress"),
            "acceptance_criteria": [
                f"Complete remaining objectives for task {curr.get('task_id')}",
                "Run test suite and verify no regressions",
                "Record task checkpoint and structured handoff package",
            ],
            "task_id": curr.get("task_id"),
            "source_type": "active_task",
        }

    # If tasks are empty or all completed
    return {
        "statement": "Next action unavailable",
        "rationale": "No active tasks, checkpoints, handoffs, or blocking issues found in project memory bank.",
        "acceptance_criteria": [
            "Check project backlog in projectBrief.md or activeContext.md",
            "Initialize new task using memoryctl task-create",
        ],
        "missing_context": ["active_task", "handoff_package"],
        "source_type": "missing",
    }


def generate_project_briefing(
    mem_root: Path,
    project_id: str,
    *,
    as_of: str | None = None,
    profile: str = "standard",
) -> dict[str, Any]:
    root = Path(mem_root)
    profile = profile.lower()
    budget = PROFILE_BUDGETS.get(profile, 2400)

    retrieval = retrieve(
        root,
        query=f"{project_id} current truth decisions constraints procedures tasks",
        project=project_id,
        as_of=as_of,
        token_budget=budget,
    )

    retrieved_items = retrieval.get("items", [])
    omitted = retrieval.get("omission_manifest", [])

    # Categorize items into briefing sections
    goal = _extract_project_goal(root, project_id)
    current_truth: list[dict[str, Any]] = []
    active_work: list[dict[str, Any]] = []
    binding_decisions: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    procedures: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    open_questions: list[dict[str, Any]] = []
    awaiting_review: list[dict[str, Any]] = []

    # Filter out proposed AI candidates from current truth
    for it in retrieved_items:
        lane = it.get("lane")
        status = it.get("lifecycle_status", "accepted")

        # Proposed candidates never enter current_truth
        if status == "proposed" or it.get("authority") == "llm_inference" and not it.get("reviewed_by"):
            awaiting_review.append(it)
            continue

        if it.get("contradiction_flag") or it.get("warning") in ("unresolved canonical-key collision", "superseded record"):
            blocking_issues.append(it)
        elif lane == "tasks":
            active_work.append(it)
        elif lane == "decisions":
            stmt = it.get("statement", "")
            if "constraint" in stmt.lower() or "never" in stmt.lower() or "boundary" in stmt.lower():
                constraints.append(it)
            else:
                binding_decisions.append(it)
        elif lane == "procedures":
            procedures.append(it)
        elif lane == "artifacts":
            artifacts.append(it)
        elif lane in ("exact", "bm25", "vector", "verified_facts"):
            # Dated project-bank updates are historical evidence. They belong
            # in recent_changes/timeline and must never be promoted to present
            # truth merely because lexical retrieval ranked them highly.
            statement = str(it.get("statement") or "").lstrip()
            if lane == "bm25" and re.match(r"^###\s+Update\s*\(", statement, re.IGNORECASE):
                continue
            # Mark stale facts
            if it.get("freshness_state") == "stale":
                it["stale_warning"] = "Stale operational truth; requires revalidation before driving action"
            current_truth.append(it)

    # Active tasks from DB directly if not captured in lane
    db = root / "gms_trust.sqlite"
    direct_tasks = []
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_tasks'").fetchone():
                rows = conn.execute(
                    "SELECT * FROM gms_tasks WHERE project = ? AND status != 'completed' ORDER BY updated_at DESC",
                    (project_id,)
                ).fetchall()
                direct_tasks = [dict(r) for r in rows]
            conn.close()
        except Exception:
            pass

    # Merge direct tasks into active_work if not present
    existing_tids = {it.get("key") for it in active_work}
    for dt in direct_tasks:
        if str(dt.get("task_id")) not in existing_tids:
            active_work.append({
                "record_id": f"task:{dt.get('task_id')}",
                "key": str(dt.get("task_id")),
                "statement": dt,
                "lane": "tasks",
                "authority": "verified_system_output",
                "authority_label": "System verified",
                "lifecycle_status": "accepted",
                "source": f"task:{dt.get('task_id')}",
                "source_valid": True,
                "token_estimate": 40,
                "status": dt.get("status"),
                "title": dt.get("title"),
            })

    # Collision check for blocking issues
    try:
        inv = alias_inventory(root)
        for col in inv.get("collisions", []):
            can_k = col.get("canonical_key", "")
            key_terms=set(re.findall(r"[a-z0-9]+",can_k.lower()))
            project_terms=set(re.findall(r"[a-z0-9]+",project_id.lower()))
            if not project_id or key_terms & project_terms:
                if not any(b.get("key") == can_k for b in blocking_issues):
                    blocking_issues.append({
                        "record_id": f"collision:{can_k}",
                        "key": can_k,
                        "title": f"Canonical Key Collision: {can_k}",
                        "statement": f"Unresolved collision between: {', '.join([r['key'] for r in col.get('records', [])])}",
                        "warning": "unresolved canonical-key collision",
                        "contradiction_flag": True,
                        "lane": "conflicts",
                        "authority": "verified_system_output",
                        "authority_label": "System verified",
                        "source": f"collision:{can_k}",
                        "source_valid": True,
                    })
    except Exception:
        pass

    recent_changes = _extract_project_recent_changes(root, project_id)
    verification = _extract_project_verification(root, project_id)

    # Proposed records are review context only. Load them directly because the
    # normal retrieval planner intentionally excludes candidates.
    if db.exists():
        try:
            conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_context_candidates'").fetchone()
            if exists:
                cols={r[1] for r in conn.execute("PRAGMA table_info(gms_context_candidates)")}
                if "payload_json" in cols:
                    rows=conn.execute("SELECT * FROM gms_context_candidates WHERE review_status IN ('proposed','deferred') ORDER BY created_at DESC").fetchall()
                    for row in rows:
                        try: payload=json.loads(row["payload_json"] or "{}")
                        except Exception: payload={}
                        scope=payload.get("scope") or {}; scoped_project=str(scope.get("project") or "")
                        if scoped_project and scoped_project != project_id: continue
                        key=str(row["canonical_key"] if "canonical_key" in cols else payload.get("key", ""))
                        # Unscoped candidates must at least mention the project.
                        if not scoped_project and project_id.lower() not in (key+" "+json.dumps(payload)).lower(): continue
                        awaiting_review.append({"candidate_id":row["candidate_id"],"key":key,
                            "record_type":payload.get("record_type"),"statement":payload.get("statement"),
                            "lifecycle_status":row["review_status"],"authority":payload.get("authority","llm_inference"),
                            "authority_label":authority_label(payload.get("authority","llm_inference")),
                            "source":"gms_context_candidates","source_valid":bool(payload.get("evidence")),
                            "proposed_operation":payload.get("proposed_operation")})
            conn.close()
        except Exception: pass
    next_action = _infer_next_action(direct_tasks or [it.get("statement") for it in active_work if isinstance(it.get("statement"), dict)], blocking_issues, project_id)

    # Inclusions
    inclusion_manifest = [
        {"record_id": it.get("record_id"), "key": it.get("key"), "lane": it.get("lane"), "authority": it.get("authority")}
        for it in (current_truth + active_work + binding_decisions + constraints + procedures + blocking_issues)
    ]

    briefing = {
        "schema_version": "gms-project-briefing-v1",
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "profile": profile,
        "goal": goal,
        "current_truth": current_truth,
        "active_work": active_work,
        "binding_decisions": binding_decisions,
        "constraints": constraints,
        "procedures": procedures,
        "recent_changes": recent_changes,
        "blocking_issues": blocking_issues,
        "open_questions": open_questions,
        "artifacts": artifacts,
        "verification": verification,
        "next_action": next_action,
        "candidates_awaiting_review": awaiting_review,
        "inclusion_manifest": inclusion_manifest,
        "omission_manifest": omitted,
    }

    # Deterministic hash of content excluding variable runtime timestamps
    hashable = {k: v for k, v in briefing.items() if k not in ("generated_at", "packet_hash")}
    canonical_repr = json.dumps(hashable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    briefing["packet_hash"] = "sha256:" + hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()

    return briefing


def explain_project_briefing(briefing: dict[str, Any]) -> dict[str, Any]:
    """Provides high-level human/agent answers to the 10 operational questions."""
    goal = briefing.get("goal", {}).get("statement", "Unspecified")
    next_action = briefing.get("next_action", {}).get("statement", "Unavailable")
    blockers_count = len(briefing.get("blocking_issues", []))
    decisions_count = len(briefing.get("binding_decisions", []))
    active_work_count = len(briefing.get("active_work", []))
    truth_count = len(briefing.get("current_truth", []))

    return {
        "schema_version": "gms-project-briefing-explanation-v1",
        "project_id": briefing.get("project_id"),
        "q1_goal": goal,
        "q2_current_truth": f"{truth_count} verified semantic facts and active context records",
        "q3_recent_changes": f"{len(briefing.get('recent_changes', []))} logged changes in memory bank",
        "q4_active_work": f"{active_work_count} tasks in progress or pending",
        "q5_binding_decisions": f"{decisions_count} active architectural/policy decisions governing next action",
        "q6_procedures": f"{len(briefing.get('procedures', []))} operational procedures and runbooks",
        "q7_evidence_summary": f"{len(briefing.get('inclusion_manifest', []))} source-disclosed references included",
        "q8_contradictions_and_blockers": f"{blockers_count} blocking issues / collisions requiring attention",
        "q9_next_action": next_action,
        "q10_verification": f"{len(briefing.get('verification', []))} verification criteria defined",
        "packet_hash": briefing.get("packet_hash"),
    }


def build_resume_bundle(
    mem_root: Path,
    project_id: str,
    *,
    target_format: str = "antigravity",
    as_of: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Generates a complete resumption bundle tailored for a specific agent runtime."""
    briefing = generate_project_briefing(mem_root, project_id, as_of=as_of, profile="standard")
    target_format = target_format.lower()

    # Distinguish verified truth from proposed context
    verified_truth_lines = []
    for it in briefing.get("current_truth", [])[:8]:
        verified_truth_lines.append(f"- **{it.get('key')}**: {it.get('statement')} (Authority: {it.get('authority_label')}, Source: {it.get('source')})")

    decisions_lines = []
    for it in briefing.get("binding_decisions", [])[:6]:
        decisions_lines.append(f"- **{it.get('key')}**: {it.get('statement')}")

    constraints_lines = []
    for it in briefing.get("constraints", [])[:6]:
        constraints_lines.append(f"- **{it.get('key')}**: {it.get('statement')}")

    blockers_lines = []
    for it in briefing.get("blocking_issues", []):
        blockers_lines.append(f"- ⚠️ **{it.get('title') or it.get('key')}**: {it.get('statement')} (Warning: {it.get('warning', 'Blocker')})")

    next_act = briefing.get("next_action", {})
    criteria = next_act.get("acceptance_criteria", [])

    prompt_body = f"""# Project Resumption Context — {project_id}

## Goal
{briefing.get('goal', {}).get('statement', 'Project execution')}

## Next Action Required (START HERE)
**Action**: {next_act.get('statement')}
**Rationale**: {next_act.get('rationale')}
**Acceptance Criteria**:
{chr(10).join([f"- [ ] {c}" for c in criteria]) if criteria else "- [ ] Verify completion"}

## Blocking Issues & Contradictions (ATTENTION)
{chr(10).join(blockers_lines) if blockers_lines else "None currently blocking."}

## Binding Decisions & Policies
{chr(10).join(decisions_lines) if decisions_lines else "None explicitly recorded."}

## Active Constraints & Safety Boundaries
{chr(10).join(constraints_lines) if constraints_lines else "Follow global memory conventions v1."}

## Verified Current Truth
{chr(10).join(verified_truth_lines) if verified_truth_lines else "Refer to semantic memory bank."}

## Context Packet Verification
- **Packet Hash**: `{briefing.get('packet_hash')}`
- **Items Included**: {len(briefing.get('inclusion_manifest', []))}
- **Items Omitted**: {len(briefing.get('omission_manifest', []))}
"""

    return {
        "schema_version": "gms-task-resume-bundle-v1",
        "project_id": project_id,
        "task_id": task_id,
        "target_format": target_format,
        "packet_hash": briefing.get("packet_hash"),
        "briefing": briefing,
        "prompt": prompt_body.strip(),
        "next_action": next_act,
        "dispatch_prohibited": True,  # Non-negotiable boundary: user must choose where to dispatch
    }
