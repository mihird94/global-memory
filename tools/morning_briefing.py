"""Morning Briefing Service.

Transforms nightly Dream Cycle consolidation into human- and agent-readable
project morning briefings answering what changed, what blocks, and what to do first.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_briefing import generate_project_briefing
from action_inbox import list_inbox_items


def generate_morning_briefing(
    mem_root: Path,
    project_id: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    root = Path(mem_root)
    briefing = generate_project_briefing(root, project_id, as_of=as_of, profile="standard")
    inbox = list_inbox_items(root, project=project_id)

    # Filter inbox items relevant to this project
    proj_inbox = [
        item for item in inbox.get("items", [])
        if item.get("affected_scope", {}).get("project") in (project_id, "global", None)
        or project_id in item.get("title", "")
    ]

    # Meaningful recent changes from briefing
    recent_changes = briefing.get("recent_changes", [])[:3]

    # Active tasks & blockers
    active_tasks = [t for t in briefing.get("active_work", []) if t.get("status") in ("in_progress", "blocked")]
    blockers = briefing.get("blocking_issues", [])

    # Decisions proposed or changed
    proposed_decisions = [
        it for it in briefing.get("candidates_awaiting_review", [])
        if "decision" in it.get("key", "").lower() or "policy" in it.get("key", "").lower()
    ]

    # Suggested first action
    next_act = briefing.get("next_action", {})

    # Human-readable summary lines
    summary_lines = [
        f"**Project**: {project_id}",
        f"**Objective**: {briefing.get('goal', {}).get('statement')}",
        f"**Suggested First Action**: {next_act.get('statement')}",
        f"**Active Blockers**: {len(blockers)} items requiring resolution",
        f"**Awaiting Review**: {len(briefing.get('candidates_awaiting_review', []))} candidates",
    ]
    if briefing.get("context_freshness_warning"):
        summary_lines.append(f"**Context Freshness Warning**: {briefing['context_freshness_warning']}")

    return {
        "schema_version": "gms-morning-briefing-v1",
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": "\n".join(summary_lines),
        "suggested_first_action": next_act,
        "blocking_issues": blockers,
        "active_tasks": active_tasks,
        "recent_changes": recent_changes,
        "decisions_proposed": proposed_decisions,
        "context_freshness_warning": briefing.get("context_freshness_warning"),
        "inbox_items_count": len(proj_inbox),
        "inbox_items": proj_inbox[:5],
        "packet_hash": briefing.get("packet_hash"),
    }


def list_morning_briefings(mem_root: Path) -> dict[str, Any]:
    root = Path(mem_root)
    proj_dir = root / "projects"
    briefings: list[dict[str, Any]] = []

    if proj_dir.exists():
        for p in sorted(proj_dir.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                try:
                    b = generate_morning_briefing(root, p.name)
                    briefings.append(b)
                except Exception:
                    pass

    return {
        "schema_version": "gms-morning-briefing-list-v1",
        "total_projects": len(briefings),
        "briefings": briefings,
    }
