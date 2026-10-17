"""Read-only Project Context Reconciliation Engine.

Calculates deterministic reconciliation previews comparing project bank state
against newer verified episodic history, tasks, handoffs, and unresolved conflicts.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from context_retrieval_planner import _effective_timestamp, _extract_effective_time
from memory_aliases import alias_inventory


REGISTERED_ACTORS = {"mihir", "antigravity", "codex", "gemini"}


def _parse_timestamp(text: str | None) -> float:
    return _effective_timestamp(text)


def extract_bank_effective_time(mem_root: Path, project_id: str) -> tuple[str | None, list[str]]:
    """Extract latest effective timestamp from the project bank files."""
    proj_dir = mem_root / "projects" / project_id
    if not proj_dir.exists():
        return None, []

    candidates: list[tuple[str, str]] = []  # (date_str, source_ref)

    # 1. activeContext.md
    active_fp = proj_dir / "activeContext.md"
    if active_fp.exists():
        try:
            content = active_fp.read_text(encoding="utf-8", errors="replace")
            # Look for headers like ### Update (2026-09-28 19:59) or similar
            updates = re.findall(r"###\s+Update\s*\(([^)]+)\)", content)
            for upd in updates:
                t = _extract_effective_time(upd)
                if t:
                    candidates.append((t, f"projects/{project_id}/activeContext.md#Update({upd})"))
            for line in content.splitlines():
                if line.startswith("#") or "updated" in line.lower() or "date" in line.lower():
                    t = _extract_effective_time(line)
                    if t:
                        candidates.append((t, f"projects/{project_id}/activeContext.md"))
        except Exception:
            pass

    # 2. projectBrief.md
    brief_fp = proj_dir / "projectBrief.md"
    if brief_fp.exists():
        try:
            content = brief_fp.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                t = _extract_effective_time(line)
                if t:
                    candidates.append((t, f"projects/{project_id}/projectBrief.md"))
        except Exception:
            pass

    # 3. progress.md
    prog_fp = proj_dir / "progress.md"
    if prog_fp.exists():
        try:
            content = prog_fp.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                t = _extract_effective_time(line)
                if t:
                    candidates.append((t, f"projects/{project_id}/progress.md"))
        except Exception:
            pass

    if not candidates:
        return None, []

    candidates.sort(key=lambda c: _parse_timestamp(c[0]), reverse=True)
    best_time, best_ref = candidates[0]
    all_refs = [ref for _, ref in candidates[:3]]
    return best_time, all_refs


def extract_latest_evidence_time(mem_root: Path, project_id: str) -> tuple[str | None, list[str]]:
    """Extract latest relevant evidence timestamp for this project from episodes, tasks, and claims."""
    evidence_candidates: list[tuple[str, str]] = []

    # Project terms for strict relevance matching
    proj_tokens = {x.lower() for x in re.findall(r"[a-z0-9]+", project_id) if len(x) > 2}
    if project_id == "global-memory":
        proj_tokens |= {"gms", "mbrain", "memoryctl", "global-memory"}
    elif project_id == "alphaos":
        proj_tokens |= {"alphaos", "swing", "robinhood"}
    elif project_id == "learning-os":
        proj_tokens |= {"learning-os", "learning", "anki", "quiz"}

    # 1. Episodic journal entries
    hist_dirs = [mem_root / "episodic" / "history", mem_root / "episodic"]
    for d in hist_dirs:
        if d.exists():
            for fp in sorted(d.glob("*.md"), reverse=True):
                if fp.is_dir():
                    continue
                try:
                    date_stem = fp.stem[:10]  # YYYY-MM-DD
                    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                    current_entry_time = date_stem
                    entry_has_project = False
                    for line in lines:
                        if line.startswith("### "):
                            # Check header time
                            m = re.search(r"\b(20\d{2}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2})?)\b", line)
                            current_entry_time = m.group(1).replace(" ", "T") if m else date_stem
                            entry_tokens = {x.lower() for x in re.findall(r"[a-z0-9]+", line)}
                            entry_has_project = bool(entry_tokens & proj_tokens)
                        else:
                            line_tokens = {x.lower() for x in re.findall(r"[a-z0-9]+", line)}
                            if line_tokens & proj_tokens:
                                entry_has_project = True

                        if entry_has_project:
                            evidence_candidates.append((current_entry_time, f"episodic/{fp.name}"))
                            entry_has_project = False
                except Exception:
                    pass

    # 2. SQLite tasks
    db_path = mem_root / "gms_trust.sqlite"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            # Check gms_tasks
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_tasks'").fetchone():
                rows = conn.execute(
                    "SELECT task_id, updated_at FROM gms_tasks WHERE project = ? ORDER BY updated_at DESC LIMIT 5",
                    (project_id,)
                ).fetchall()
                for r in rows:
                    if r["updated_at"]:
                        t = _extract_effective_time(r["updated_at"]) or str(r["updated_at"])[:10]
                        evidence_candidates.append((t, f"sqlite:gms_tasks:{r['task_id']}"))

            # Check gms_claims for project
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_claims'").fetchone():
                rows = conn.execute(
                    "SELECT claim_id, created_at, memory_key FROM gms_claims WHERE status='active' AND memory_key LIKE ? ORDER BY created_at DESC LIMIT 5",
                    (f"%{project_id}%",)
                ).fetchall()
                for r in rows:
                    if r["created_at"]:
                        t = _extract_effective_time(r["created_at"]) or str(r["created_at"])[:10]
                        evidence_candidates.append((t, f"sqlite:gms_claims:{r['claim_id']}"))
            conn.close()
        except Exception:
            pass

    if not evidence_candidates:
        return None, []

    evidence_candidates.sort(key=lambda c: _parse_timestamp(c[0]), reverse=True)
    best_time, best_ref = evidence_candidates[0]
    all_refs = list(dict.fromkeys([ref for _, ref in evidence_candidates[:5]]))
    return best_time, all_refs


def build_project_context_reconciliation(
    mem_root: Path,
    project_id: str,
) -> dict[str, Any]:
    """
    Build a deterministic, read-only project-context reconciliation preview.
    Does NOT mutate any file or database.
    """
    root = Path(mem_root)
    bank_effective_at, bank_refs = extract_bank_effective_time(root, project_id)
    latest_evidence_at, evidence_refs = extract_latest_evidence_time(root, project_id)

    gaps: list[dict[str, Any]] = []

    # Check active tasks, checkpoints, handoffs
    active_tasks = []
    db_path = root / "gms_trust.sqlite"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_tasks'").fetchone():
                rows = conn.execute(
                    "SELECT task_id, title, status FROM gms_tasks WHERE project = ? AND status != 'completed' ORDER BY updated_at DESC",
                    (project_id,)
                ).fetchall()
                active_tasks = [dict(r) for r in rows]
            conn.close()
        except Exception:
            pass

    if not active_tasks:
        gaps.append({
            "field": "active_work",
            "reason": "No active tasks, checkpoints, or handoffs found in task registry",
            "evidence_refs": ["sqlite:gms_tasks"],
        })

    # Check unresolved conflicts / collisions
    try:
        inv = alias_inventory(root)
        proj_collisions = [
            c for c in inv.get("collisions", [])
            if project_id.lower() in c.get("canonical_key", "").lower()
        ]
        if proj_collisions:
            gaps.append({
                "field": "unresolved_conflicts",
                "reason": f"Found {len(proj_collisions)} unresolved canonical-key collision(s)",
                "evidence_refs": [f"collision:{c.get('canonical_key')}" for c in proj_collisions[:3]],
            })
    except Exception:
        pass

    # Check bank existence and freshness
    if not bank_effective_at:
        freshness = "missing_active_context"
        gaps.append({
            "field": "project_bank",
            "reason": "Project memory bank has no recorded dated updates",
            "evidence_refs": [f"projects/{project_id}/activeContext.md"],
        })
    else:
        bank_ts = _parse_timestamp(bank_effective_at)
        ev_ts = _parse_timestamp(latest_evidence_at)
        if latest_evidence_at and ev_ts > bank_ts:
            freshness = "behind"
            gaps.append({
                "field": "project_bank_freshness",
                "reason": f"Project bank effective time ({bank_effective_at}) is behind latest verified evidence ({latest_evidence_at})",
                "evidence_refs": evidence_refs[:3],
            })
        else:
            freshness = "current"

    # Suggested update proposal (labeled as system synthesis)
    suggested_update: dict[str, Any] = {
        "derived_by": "system_synthesis",
        "proposal_notice": "This is a deterministic system proposal, not a verified claim of truth.",
        "project": project_id,
        "suggested_effective_at": latest_evidence_at or bank_effective_at,
        "recommended_actions": [],
    }
    if freshness == "behind":
        suggested_update["recommended_actions"].append(
            f"Review latest project timeline evidence ({latest_evidence_at}) and update activeContext.md"
        )
    if not active_tasks:
        suggested_update["recommended_actions"].append(
            "Create structured task and checkpoint before beginning agent work"
        )

    preview: dict[str, Any] = {
        "schema_version": "gms-project-context-reconciliation-v1",
        "project": project_id,
        "bank_effective_at": bank_effective_at,
        "latest_evidence_at": latest_evidence_at,
        "freshness": freshness,
        "gaps": gaps,
        "suggested_update": suggested_update,
        "apply_supported": False,
    }

    # Deterministic SHA-256 snapshot hash
    canonical_repr = json.dumps(preview, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    snapshot_hash = "sha256:" + hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
    preview["snapshot_hash"] = snapshot_hash

    return preview


def apply_project_context_reconciliation(
    mem_root: Path,
    project_id: str,
    *,
    actor: str,
    rationale: str,
    expected_snapshot_hash: str,
) -> dict[str, Any]:
    """
    Explicit apply path for project reconciliation.
    Guarded by: registered actor, substantive rationale (>=10 chars), and expected hash.
    Fails closed if any guard fails.
    """
    if actor not in REGISTERED_ACTORS:
        return {
            "status": "rejected",
            "reason": f"Actor '{actor}' is not a registered authorized actor ({sorted(REGISTERED_ACTORS)})",
            "applied": False,
        }

    if not rationale or len(rationale.strip()) < 10:
        return {
            "status": "rejected",
            "reason": "Rationale must be at least 10 substantive characters explaining the update",
            "applied": False,
        }

    preview = build_project_context_reconciliation(mem_root, project_id)
    if preview.get("snapshot_hash") != expected_snapshot_hash:
        return {
            "status": "rejected",
            "reason": "Optimistic concurrency conflict: expected snapshot hash does not match current state",
            "current_hash": preview.get("snapshot_hash"),
            "expected_hash": expected_snapshot_hash,
            "applied": False,
        }

    # If apply_supported is False, fail closed
    if not preview.get("apply_supported", False):
        return {
            "status": "rejected",
            "reason": "Automatic mutation of project banks is disabled (preview-only policy in GMS Pass 10)",
            "applied": False,
        }

    return {"status": "success", "applied": True}
