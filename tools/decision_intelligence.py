"""Decision Intelligence Service.

Manages, queries, and evaluates architectural, policy, and design decisions.
Preserves author/extractor separation, rationale, implications, and impact maps.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_aliases import canonicalize
from memory_authority import authority_label


def _extract_decisions_from_active_context(root: Path, project: str) -> list[dict[str, Any]]:
    decisions = []
    fp = root / "projects" / project / "activeContext.md"
    if not fp.exists():
        return decisions

    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
        sections = re.split(r"\n(?=## )", text)
        for sec in sections:
            if any(w in sec.lower() for w in ("decision", "constraint", "boundary", "rule")):
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", sec) if p.strip()]
                for idx, p in enumerate(paragraphs):
                    if len(p) > 20 and ("decision" in p.lower() or "constraint" in p.lower() or "never" in p.lower()):
                        d_id = f"dec_{project}_{idx}"
                        lines = [ln.strip() for ln in p.splitlines() if ln.strip() and not ln.strip().startswith("#")]
                        if not lines:
                            continue
                        stmt = lines[0].lstrip("- *").strip()
                        rationale = "\n".join(lines[1:]).strip() if len(lines) > 1 else "Preserve project constraints and operational safety"
                        decisions.append({
                            "decision_id": d_id,
                            "key": f"{project}.decision.{idx}",
                            "statement": stmt,
                            "rationale": rationale or "Defined in activeContext.md",
                            "implications": ["Governs active implementation and validation", "Must be observed by all collaborating agents"],
                            "scope": {"project": project, "level": "project"},
                            "alternatives": [],
                            "assumptions": ["Project boundaries remain active"],
                            "evidence": [{"ref": f"projects/{project}/activeContext.md", "type": "project_bank"}],
                            "author": "mihir",
                            "extractor": "system",
                            "authority": "source_document",
                            "authority_label": authority_label("source_document"),
                            "effective_time": "2026-09-08T00:00:00Z",
                            "review_condition": "When architectural goals change",
                            "lifecycle_status": "accepted",
                            "supersedes": [],
                            "superseded_by": None,
                            "affected_tasks": [],
                            "affected_artifacts": [f"projects/{project}/activeContext.md"],
                            "affected_entities": [project],
                        })
    except Exception:
        pass
    return decisions


def _extract_decisions_from_db(root: Path) -> list[dict[str, Any]]:
    decisions = []
    db = root / "gms_trust.sqlite"
    if not db.exists():
        return decisions

    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_claims'").fetchone():
            rows = conn.execute(
                "SELECT claim_id, memory_key, value, agent_id, status, created_at FROM gms_claims "
                "WHERE memory_key LIKE '%policy%' OR memory_key LIKE '%decision%' OR memory_key LIKE '%trust%'"
            ).fetchall()
            for r in rows:
                k = r["memory_key"]
                val = r["value"]
                status = r["status"]
                val_dict = {}
                if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
                    try:
                        val_dict = json.loads(val)
                    except Exception:
                        pass

                stmt = val_dict.get("statement") or str(val)
                rationale = val_dict.get("rationale") or "Recorded in claims ledger"
                implications = val_dict.get("implications") or ["Applies across global memory operations"]
                scope = val_dict.get("scope") or {"project": "global-memory"}

                decisions.append({
                    "decision_id": f"claim_dec_{r['claim_id']}",
                    "key": k,
                    "statement": stmt,
                    "rationale": rationale,
                    "implications": implications,
                    "scope": scope,
                    "alternatives": val_dict.get("alternatives", []),
                    "assumptions": val_dict.get("assumptions", []),
                    "evidence": val_dict.get("evidence", [{"ref": f"claim:{r['claim_id']}"}]),
                    "author": val_dict.get("provenance", {}).get("author", r["agent_id"]),
                    "extractor": val_dict.get("provenance", {}).get("extractor", "system"),
                    "authority": val_dict.get("authority", "imported_legacy"),
                    "authority_label": authority_label(val_dict.get("authority", "imported_legacy")),
                    "effective_time": r["created_at"],
                    "review_condition": "On protocol revision",
                    "lifecycle_status": "accepted" if status == "active" else status,
                    "supersedes": [],
                    "superseded_by": None if status == "active" else "superseded_claim",
                    "affected_tasks": [],
                    "affected_artifacts": [],
                    "affected_entities": ["global-memory"],
                })
        conn.close()
    except Exception:
        pass
    return decisions


def list_decisions(
    mem_root: Path,
    *,
    project: str = "",
    include_superseded: bool = False,
) -> dict[str, Any]:
    root = Path(mem_root)
    all_decisions: list[dict[str, Any]] = []

    if project:
        all_decisions.extend(_extract_decisions_from_active_context(root, project))
    else:
        # Scan all projects in projects/
        p_dir = root / "projects"
        if p_dir.exists():
            for p in p_dir.iterdir():
                if p.is_dir():
                    all_decisions.extend(_extract_decisions_from_active_context(root, p.name))

    all_decisions.extend(_extract_decisions_from_db(root))

    # Filter superseded if requested
    if not include_superseded:
        all_decisions = [d for d in all_decisions if d["lifecycle_status"] == "accepted" and not d.get("superseded_by")]

    # Quality check
    lacking_rationale = [d["decision_id"] for d in all_decisions if not d.get("rationale") or len(d.get("rationale", "")) < 10]
    lacking_evidence = [d["decision_id"] for d in all_decisions if not d.get("evidence")]

    return {
        "schema_version": "gms-decisions-inventory-v1",
        "project": project or "all",
        "total": len(all_decisions),
        "decisions": all_decisions,
        "quality": {
            "lacking_rationale_count": len(lacking_rationale),
            "lacking_rationale_ids": lacking_rationale,
            "lacking_evidence_count": len(lacking_evidence),
            "lacking_evidence_ids": lacking_evidence,
        },
    }


def get_decision(mem_root: Path, decision_id: str) -> dict[str, Any] | None:
    inv = list_decisions(mem_root, include_superseded=True)
    for d in inv.get("decisions", []):
        if d["decision_id"] == decision_id or d["key"] == decision_id:
            return d
    return None


def get_decision_impact(mem_root: Path, decision_id: str) -> dict[str, Any]:
    decision = get_decision(mem_root, decision_id)
    if not decision:
        return {"error": "DECISION_NOT_FOUND", "decision_id": decision_id}

    project = decision.get("scope", {}).get("project", "")
    affected_tasks = []
    affected_artifacts = list(decision.get("affected_artifacts", []))

    # Check active tasks in DB
    db = Path(mem_root) / "gms_trust.sqlite"
    if db.exists() and project:
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT task_id, title, status FROM gms_tasks WHERE project = ? AND status != 'completed'", (project,)).fetchall()
            affected_tasks = [dict(r) for r in rows]
            conn.close()
        except Exception:
            pass

    return {
        "schema_version": "gms-decision-impact-v1",
        "decision_id": decision_id,
        "key": decision.get("key"),
        "statement": decision.get("statement"),
        "rationale": decision.get("rationale"),
        "lifecycle_status": decision.get("lifecycle_status"),
        "supersession_consequence": {
            "risk_level": "high" if "security" in str(decision).lower() or "trust" in str(decision).lower() else "medium",
            "impact_summary": f"Superseding this decision invalidates behavioral constraints on {len(affected_tasks)} active tasks and {len(affected_artifacts)} artifacts.",
            "affected_tasks": affected_tasks,
            "affected_artifacts": affected_artifacts,
            "recommended_action": "Require explicit human operator review before committing replacement decision.",
        },
    }
