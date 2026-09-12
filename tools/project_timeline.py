"""Unified Project Timeline Service.

Normalizes multi-source events (user instructions, project bank updates,
task lifecycle transitions, decisions, benchmark observations, contradictions,
nightly consolidation, memory repairs) into a single inspectable timeline stream.
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


def _generate_event_id(prefix: str, content: str, timestamp: str) -> str:
    raw = f"{prefix}:{content}:{timestamp}"
    return "evt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14]


def get_project_timeline(
    mem_root: Path,
    project_id: str,
    *,
    event_type: str | None = None,
    agent: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    root = Path(mem_root)
    events: list[dict[str, Any]] = []

    # 1. Project Bank Updates from activeContext.md
    active_path = root / "projects" / project_id / "activeContext.md"
    if active_path.exists():
        try:
            text = active_path.read_text(encoding="utf-8", errors="replace")
            updates = re.findall(r"### Update \(([^)]+)\)\n(.*?)(?=\n### Update|\Z)", text, re.DOTALL)
            for date_str, body in updates:
                first_line = body.strip().splitlines()[0] if body.strip() else "Project update"
                evt_id = _generate_event_id("proj", first_line, date_str)
                events.append({
                    "event_id": evt_id,
                    "event_type": "project_bank_change",
                    "project_id": project_id,
                    "event_time": date_str,
                    "effective_time": date_str,
                    "recorded_time": date_str,
                    "title": first_line[:90],
                    "summary": body.strip()[:300],
                    "producer": "agent",
                    "authority": "source_document",
                    "authority_label": authority_label("source_document"),
                    "source_refs": [f"projects/{project_id}/activeContext.md"],
                    "related_records": [],
                    "resulting_state": "updated",
                    "actionable_context_changed": True,
                })
        except Exception:
            pass

    # 2. Tasks & Task Checkpoints from SQLite
    db = root / "gms_trust.sqlite"
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            # Check gms_tasks
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_tasks'").fetchone():
                rows = conn.execute(
                    "SELECT task_id, title, objective, status, owner_agent, created_by, created_at, updated_at "
                    "FROM gms_tasks WHERE project = ? ORDER BY updated_at DESC LIMIT 50",
                    (project_id,)
                ).fetchall()
                for r in rows:
                    evt_id = _generate_event_id("task", str(r["task_id"]), r["updated_at"] or r["created_at"])
                    events.append({
                        "event_id": evt_id,
                        "event_type": "task",
                        "project_id": project_id,
                        "event_time": r["updated_at"] or r["created_at"],
                        "effective_time": r["updated_at"] or r["created_at"],
                        "recorded_time": r["created_at"],
                        "title": f"Task '{r['title']}': status {r['status']}",
                        "summary": r["objective"] or f"Task owned by {r['owner_agent']}",
                        "producer": r["owner_agent"] or r["created_by"] or "agent",
                        "authority": "verified_system_output",
                        "authority_label": authority_label("verified_system_output"),
                        "source_refs": [f"task:{r['task_id']}"],
                        "related_records": [f"task:{r['task_id']}"],
                        "resulting_state": r["status"],
                        "actionable_context_changed": r["status"] in ("in_progress", "completed", "blocked"),
                    })
            # Check gms_review_audit
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_review_audit'").fetchone():
                rows = conn.execute(
                    "SELECT audit_id, candidate_id, action, reviewer_id, review_rationale, timestamp "
                    "FROM gms_review_audit ORDER BY audit_id DESC LIMIT 30"
                ).fetchall()
                for r in rows:
                    evt_id = _generate_event_id("review", str(r["candidate_id"]), r["timestamp"])
                    events.append({
                        "event_id": evt_id,
                        "event_type": "candidate",
                        "project_id": project_id,
                        "event_time": r["timestamp"],
                        "effective_time": r["timestamp"],
                        "recorded_time": r["timestamp"],
                        "title": f"Candidate Review: {r['action'].upper()} on {r['candidate_id']}",
                        "summary": r["review_rationale"][:300],
                        "producer": r["reviewer_id"],
                        "authority": "user_instruction" if r["reviewer_id"].lower() == "mihir" else "verified_system_output",
                        "authority_label": authority_label("user_instruction" if r["reviewer_id"].lower() == "mihir" else "verified_system_output"),
                        "source_refs": [f"audit:{r['audit_id']}"],
                        "related_records": [r["candidate_id"]],
                        "resulting_state": r["action"],
                        "actionable_context_changed": r["action"] in ("accept", "merge", "supersede"),
                    })
            conn.close()
        except Exception:
            pass

    # 3. Nightly Consolidation Status
    status_file = root / "logs" / "dream_cycle_status.json"
    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text(encoding="utf-8"))
            ts = status_data.get("timestamp", "")
            evt_id = _generate_event_id("consolidation", "nightly", ts)
            events.append({
                "event_id": evt_id,
                "event_type": "consolidation",
                "project_id": project_id,
                "event_time": ts,
                "effective_time": ts,
                "recorded_time": ts,
                "title": f"Nightly Consolidation ({status_data.get('status', 'completed')})",
                "summary": f"Staged {status_data.get('candidates_staged', 0)} candidates, promoted {status_data.get('facts_promoted', 0)} facts in {status_data.get('duration_seconds', 0)}s",
                "producer": f"DreamCycle-{status_data.get('provider', 'local')}",
                "authority": "verified_system_output",
                "authority_label": authority_label("verified_system_output"),
                "source_refs": ["logs/dream_cycle_status.json"],
                "related_records": [],
                "resulting_state": status_data.get("status", "completed"),
                "actionable_context_changed": status_data.get("candidates_staged", 0) > 0,
            })
        except Exception:
            pass

    # Apply filters
    if event_type:
        events = [e for e in events if e["event_type"] == event_type]
    if agent:
        events = [e for e in events if agent.lower() in e["producer"].lower()]

    # Sort descending by event_time
    events.sort(key=lambda e: str(e["event_time"]), reverse=True)

    # Group low-value repeated telemetry
    grouped_events: list[dict[str, Any]] = []
    prev_key = None
    repeat_count = 0

    for e in events:
        key = (e["event_type"], e["producer"], e["resulting_state"])
        if key == prev_key and e["event_type"] in ("observation", "consolidation"):
            repeat_count += 1
            grouped_events[-1]["repeat_count"] = repeat_count
            grouped_events[-1]["title"] = f"{e['title']} (x{repeat_count + 1})"
        else:
            prev_key = key
            repeat_count = 0
            e["repeat_count"] = 0
            grouped_events.append(e)

    return {
        "schema_version": "gms-timeline-stream-v1",
        "project_id": project_id,
        "total_events": len(grouped_events),
        "events": grouped_events[:limit],
    }
