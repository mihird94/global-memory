"""A local assignment and status log for agents sharing a Brain home."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import now_iso
from .validation import normalize_project_slug

STATES = {
    "assigned": "Assigned",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "in_review": "In review",
    "done": "Done",
}
TRANSITIONS = {
    "assigned": {"in_progress": ("assignee", "Start work", False)},
    "in_progress": {
        "blocked": ("assignee", "Flag blocker", True),
        "in_review": ("assignee", "Submit for review", True),
    },
    "blocked": {"in_progress": ("assignee", "Resume work", False)},
    "in_review": {
        "in_progress": ("supervisor", "Request changes", True),
        "done": ("supervisor", "Mark done", False),
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    supervisor TEXT NOT NULL,
    assignee TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS board_posts (
    id INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id),
    author TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS board_posts_assignment ON board_posts(assignment_id, id);
"""
ASSIGNMENT_SELECT = """
    SELECT a.*, (SELECT max(p.id) FROM board_posts p WHERE p.assignment_id = a.id) AS revision
    FROM assignments a
"""


class AssignmentDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)

    title: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    supervisor: str = Field(min_length=1)
    assignee: str = Field(min_length=1)
    project: str = ""

    @field_validator("project")
    @classmethod
    def check_project(cls, value: str) -> str:
        return normalize_project_slug(value) if value.strip() else ""


class Board:
    def __init__(self, root: Path) -> None:
        self.path = root / ".gm" / "board.sqlite"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        conn = sqlite3.connect(self.path, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA)
            return conn
        except Exception:
            conn.close()
            raise

    def list(self, *, actor: str = "", status: str = "", project: str = "") -> dict[str, Any]:
        actor, status = actor.strip(), status.strip()
        project = normalize_project_slug(project) if project.strip() else ""
        if status and status not in STATES:
            raise ValueError("Choose assigned, in_progress, blocked, in_review, or done.")
        where: list[str] = []
        values: list[str] = []
        if actor:
            where.append("(lower(a.assignee) = lower(?) OR lower(a.supervisor) = lower(?))")
            values.extend((actor, actor))
        if status:
            where.append("a.status = ?")
            values.append(status)
        if project:
            where.append("lower(a.project) = lower(?)")
            values.append(project)
        condition = f" WHERE {' AND '.join(where)}" if where else ""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute(f"{ASSIGNMENT_SELECT}{condition} ORDER BY revision DESC", values).fetchall()
            revision = conn.execute("SELECT coalesce(max(id), 0) FROM board_posts").fetchone()[0]
        return {"assignments": [dict(row) for row in rows], "revision": revision}

    def _assignment(self, conn: sqlite3.Connection, assignment_id: int) -> dict[str, Any]:
        if type(assignment_id) is not int or not 1 <= assignment_id <= 2**63 - 1:
            raise ValueError("Use the assignment number shown on the board.")
        row = conn.execute(f"{ASSIGNMENT_SELECT} WHERE a.id = ?", (assignment_id,)).fetchone()
        if row is None:
            raise ValueError(f"Assignment #{assignment_id} was not found. Check the Agent Board for its number.")
        return dict(row)

    def read(self, assignment_id: int) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            assignment = self._assignment(conn, assignment_id)
            posts = conn.execute(
                "SELECT id, author, message, status, created_at FROM board_posts WHERE assignment_id = ? ORDER BY id",
                (assignment_id,),
            ).fetchall()
        assignment["posts"] = [dict(row) for row in posts]
        assignment["actions"] = [
            {"status": target, "actor": assignment[role], "label": label, "needs_message": needs_message}
            for target, (role, label, needs_message) in TRANSITIONS.get(assignment["status"], {}).items()
        ]
        return assignment

    def assign(self, *, title: str, brief: str, supervisor: str, assignee: str, project: str = "") -> dict[str, Any]:
        draft = AssignmentDraft(title=title, brief=brief, supervisor=supervisor, assignee=assignee, project=project)
        stamp = now_iso()
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO assignments(title, project, supervisor, assignee, status, updated_at) VALUES (?, ?, ?, ?, 'assigned', ?)",
                (draft.title, draft.project, draft.supervisor, draft.assignee, stamp),
            )
            assignment_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO board_posts(assignment_id, author, message, status, created_at) VALUES (?, ?, ?, 'assigned', ?)",
                (assignment_id, draft.supervisor, draft.brief, stamp),
            )
        return {"id": assignment_id, "status": "assigned"}

    def post(self, assignment_id: int, *, author: str, message: str = "", status: str = "") -> dict[str, Any]:
        author, message, status = author.strip(), message.strip(), status.strip()
        if not author:
            raise ValueError("Enter the harness or session posting this update.")
        if not (message or status):
            raise ValueError("Enter a message or select a status change.")
        stamp = now_iso()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            assignment = self._assignment(conn, assignment_id)
            if status:
                action = TRANSITIONS.get(assignment["status"], {}).get(status)
                if action is None:
                    raise ValueError(f"Assignment #{assignment_id} is {STATES[assignment['status']].lower()}. Read the thread for available status changes.")
                role, label, needs_message = action
                if author.casefold() != assignment[role].casefold():
                    raise ValueError(f"{assignment[role]} can make this status change as the {role}.")
                if needs_message and not message:
                    raise ValueError(f"Add a message explaining the update before selecting {label.lower()}.")
            post = conn.execute(
                "INSERT INTO board_posts(assignment_id, author, message, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (assignment_id, author, message, status, stamp),
            )
            current_status = status or assignment["status"]
            conn.execute("UPDATE assignments SET status = ?, updated_at = ? WHERE id = ?",
                         (current_status, stamp, assignment_id))
        return {"id": assignment_id, "post_id": post.lastrowid, "status": current_status}
