"""Read-only task readiness and continuity validator.

Checks whether a suitable real task, checkpoint, and handoff exist for
cross-agent resumption evaluation without mutating durable memory or
manufacturing fictitious tasks.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def check_task_readiness(
    mem_root: Path,
    project: str = "global-memory",
) -> dict[str, Any]:
    """Read-only inspection of project task continuity in gms_trust.sqlite.

    Guarantees zero durable writes or mutations to ~/memories.
    """
    root = Path(mem_root)
    db_path = root / "gms_trust.sqlite"

    base_report: dict[str, Any] = {
        "schema_version": "gms-task-readiness-v1",
        "project": project,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ready": False,
        "quality_gate_eligible": False,
        "active_task": None,
        "latest_checkpoint": None,
        "latest_handoff": None,
        "read_only": True,
        "message": "No task database found.",
    }

    if not db_path.exists():
        return base_report

    try:
        # Open in URI read-only mode to prevent any incidental lock/mutation
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row

        # Check table existence
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "gms_tasks" not in tables:
            conn.close()
            base_report["message"] = "Table gms_tasks not present in database."
            return base_report

        # Find active or handed-off task for the project
        task_row = conn.execute(
            """
            SELECT task_id, project, title, objective, status, owner_agent, revision,
                   lease_expires_at, created_at, updated_at
            FROM gms_tasks
            WHERE project = ? AND status IN ('in_progress', 'handed_off', 'blocked')
            ORDER BY revision DESC, updated_at DESC
            LIMIT 1
            """,
            (project,),
        ).fetchone()

        if not task_row:
            conn.close()
            base_report["message"] = (
                f"No active or handed-off task found for project '{project}'. "
                "Quality gate correctly remains closed."
            )
            return base_report

        task_dict = dict(task_row)
        task_id = task_dict["task_id"]
        base_report["active_task"] = task_dict

        # Check for checkpoint
        chk_row = None
        if "gms_task_checkpoints" in tables:
            chk_row = conn.execute(
                """
                SELECT checkpoint_id, task_id, revision, agent_id, label, state_json,
                       artifact_refs_json, created_at
                FROM gms_task_checkpoints
                WHERE task_id = ?
                ORDER BY revision DESC, checkpoint_id DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()

        if chk_row:
            chk_dict = dict(chk_row)
            try:
                chk_dict["state"] = json.loads(chk_dict.pop("state_json") or "{}")
            except Exception:
                chk_dict["state"] = {}
            try:
                chk_dict["artifact_refs"] = json.loads(chk_dict.pop("artifact_refs_json") or "[]")
            except Exception:
                chk_dict["artifact_refs"] = []
            base_report["latest_checkpoint"] = chk_dict

        # Check for handoff
        ho_row = None
        if "gms_handoffs" in tables:
            ho_row = conn.execute(
                """
                SELECT handoff_id, task_id, revision, source_agent, target_agent,
                       objective, completed_work, next_action, blockers, acceptance_criteria,
                       artifact_refs_json, created_at, acknowledged_at
                FROM gms_handoffs
                WHERE task_id = ?
                ORDER BY revision DESC, handoff_id DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()

        if ho_row:
            ho_dict = dict(ho_row)
            try:
                ho_dict["artifact_refs"] = json.loads(ho_dict.pop("artifact_refs_json") or "[]")
            except Exception:
                ho_dict["artifact_refs"] = []
            base_report["latest_handoff"] = ho_dict

        conn.close()

        has_active = bool(task_dict)
        has_checkpoint = bool(chk_row)
        has_handoff = bool(ho_row)

        if has_active and has_checkpoint and has_handoff:
            base_report["ready"] = True
            base_report["quality_gate_eligible"] = True
            base_report["message"] = (
                f"Task continuity verified for '{project}' (task={task_id}, "
                f"revision={task_dict['revision']}). Resumption gate eligible."
            )
        else:
            missing = []
            if not has_checkpoint:
                missing.append("checkpoint")
            if not has_handoff:
                missing.append("handoff")
            base_report["message"] = (
                f"Incomplete task continuity for '{project}': missing {', '.join(missing)}. "
                "Quality gate remains closed."
            )

        return base_report

    except Exception as exc:
        base_report["message"] = f"Read-only check error: {str(exc)[:120]}"
        return base_report
