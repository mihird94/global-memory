"""Local inter-agent communication protocol for agents sharing a Brain home."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .store import now_iso
from .validation import normalize_project_slug

THREAD_KINDS = {
    "assignment": "Assignment",
    "request": "Request",
    "discussion": "Discussion",
    "broadcast": "Broadcast",
}

MESSAGE_KINDS = {
    "message": "Message",
    "brief": "Brief",
    "question": "Question",
    "answer": "Answer",
    "proposal": "Proposal",
    "decision": "Decision",
    "handoff": "Handoff",
    "status": "Status",
    "ack": "Ack",
}

PRIORITIES = {
    "low": "Low",
    "normal": "Normal",
    "high": "High",
    "urgent": "Urgent",
}
_PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}

AGENT_STATES = {
    "active": "Active",
    "idle": "Idle",
    "busy": "Busy",
    "offline": "Offline",
}

STATES = {
    "assigned": "Assigned",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "in_review": "In review",
    "done": "Done",
    "cancelled": "Cancelled",
    "open": "Open",
    "resolved": "Resolved",
    "declined": "Declined",
    "closed": "Closed",
}

INITIAL_STATUS = {
    "assignment": "assigned",
    "request": "open",
    "discussion": "open",
    "broadcast": "open",
}

TRANSITIONS_BY_KIND: dict[str, dict[str, dict[str, tuple[str, str, bool]]]] = {
    "assignment": {
        "assigned": {
            "in_progress": ("assignee", "Start work", False),
            "cancelled": ("supervisor", "Cancel", True),
        },
        "in_progress": {
            "blocked": ("assignee", "Flag blocker", True),
            "in_review": ("assignee", "Submit for review", True),
            "cancelled": ("supervisor", "Cancel", True),
        },
        "blocked": {
            "in_progress": ("assignee", "Resume work", False),
            "cancelled": ("supervisor", "Cancel", True),
        },
        "in_review": {
            "in_progress": ("supervisor", "Request changes", True),
            "done": ("supervisor", "Mark done", False),
        },
        "done": {},
        "cancelled": {},
    },
    "request": {
        "open": {
            "in_progress": ("recipient", "Accept", False),
            "resolved": ("any", "Resolve", True),
            "declined": ("recipient", "Decline", True),
        },
        "in_progress": {
            "blocked": ("recipient", "Flag blocker", True),
            "resolved": ("any", "Resolve", True),
            "declined": ("recipient", "Decline", True),
        },
        "blocked": {
            "in_progress": ("recipient", "Resume", False),
            "resolved": ("any", "Resolve", True),
            "declined": ("recipient", "Decline", True),
        },
        "resolved": {
            "open": ("any", "Reopen", True),
        },
        "declined": {
            "open": ("initiator", "Reopen", True),
        },
    },
    "discussion": {
        "open": {
            "resolved": ("any", "Resolve", False),
            "closed": ("any", "Close", False),
        },
        "resolved": {
            "open": ("any", "Reopen", True),
        },
        "closed": {
            "open": ("any", "Reopen", True),
        },
    },
    "broadcast": {
        "open": {
            "closed": ("initiator", "Close", False),
        },
        "closed": {},
    },
}

TRANSITIONS = TRANSITIONS_BY_KIND["assignment"]

_ATTENTION_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "assignment": {
        "assigned": {"in_progress"},
        "blocked": {"in_progress"},
        "in_review": {"in_progress", "done"},
    },
    "request": {
        "open": {"in_progress", "resolved"},
        "in_progress": {"resolved"},
        "blocked": {"in_progress", "resolved"},
    },
}

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'discussion',
    title TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'normal',
    created_by TEXT NOT NULL,
    supervisor TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_participants (
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    actor TEXT NOT NULL COLLATE NOCASE,
    role TEXT NOT NULL DEFAULT 'participant',
    joined_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, actor)
);
CREATE INDEX IF NOT EXISTS idx_tp_actor ON thread_participants(actor, thread_id);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'message',
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    reply_to INTEGER REFERENCES messages(id),
    to_actors TEXT NOT NULL DEFAULT '[]',
    refs TEXT NOT NULL DEFAULT '[]',
    payload TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_idemp
    ON messages(thread_id, author COLLATE NOCASE, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS read_cursors (
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    actor TEXT NOT NULL COLLATE NOCASE,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    acked_id INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, actor)
);
CREATE TABLE IF NOT EXISTS agent_presence (
    actor TEXT PRIMARY KEY COLLATE NOCASE,
    harness TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    summary TEXT NOT NULL DEFAULT '',
    capabilities TEXT NOT NULL DEFAULT '[]',
    last_seen_at TEXT NOT NULL
);
"""

THREAD_SELECT = """
    SELECT t.*,
           coalesce((SELECT max(m.id) FROM messages m WHERE m.thread_id = t.id), 0) AS revision,
           (SELECT count(*) FROM messages m WHERE m.thread_id = t.id) AS message_count
    FROM threads t
"""


def _normalize_actors(actors: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if actors is None:
        return []
    raw_list = [actors] if isinstance(actors, str) else list(actors)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_list:
        for part in str(item).split(","):
            cleaned = " ".join(part.strip().split())
            if not cleaned or len(cleaned) > 500:
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                out.append(cleaned)
    return out


def _normalize_refs(refs: list[str] | tuple[str, ...] | None) -> list[str]:
    if not refs:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in refs:
        cleaned = str(item).strip()
        if not cleaned:
            continue
        if len(cleaned) > 500:
            raise ValueError("Each reference must be at most 500 characters.")
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    if len(out) > 50:
        raise ValueError("Attach at most 50 references per message.")
    return out


def _serialize_json_obj(obj: dict[str, Any] | None, *, label: str, max_bytes: int = 65_536) -> str | None:
    if obj is None:
        return None
    if not isinstance(obj, dict):
        raise ValueError(f"{label} must be a JSON object.")
    encoded = json.dumps(obj, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} must be at most {max_bytes:,} bytes.")
    return encoded


class ThreadDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)

    kind: str = "discussion"
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=250_000)
    author: str = Field(min_length=1, max_length=500)
    supervisor: str = Field(default="", max_length=500)
    assignee: str = Field(default="", max_length=500)
    to: list[str] = Field(default_factory=list)
    project: str = ""
    channel: str = ""
    priority: str = "normal"
    refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    idempotency_key: str = Field(default="", max_length=200)

    @field_validator("kind")
    @classmethod
    def check_kind(cls, value: str) -> str:
        k = value.lower()
        if k not in THREAD_KINDS:
            raise ValueError("Choose thread kind assignment, request, discussion, or broadcast.")
        return k

    @field_validator("priority")
    @classmethod
    def check_priority(cls, value: str) -> str:
        p = (value or "normal").lower()
        if p not in PRIORITIES:
            raise ValueError("Choose priority low, normal, high, or urgent.")
        return p

    @field_validator("project")
    @classmethod
    def check_project(cls, value: str) -> str:
        return normalize_project_slug(value) if value.strip() else ""

    @field_validator("channel")
    @classmethod
    def check_channel(cls, value: str) -> str:
        return normalize_project_slug(value) if value.strip() else ""

    @model_validator(mode="after")
    def check_kind_fields(self) -> "ThreadDraft":
        if self.kind == "assignment":
            if not self.supervisor or not self.assignee:
                raise ValueError("Assignments require both a supervisor and an assignee.")
            if not self.body:
                raise ValueError("Assignments require a brief.")
        elif self.kind == "request":
            if not self.body:
                raise ValueError("Requests require a message.")
            if not self.to:
                raise ValueError("Requests require at least one recipient (--to).")
        elif self.kind == "broadcast":
            if not self.body:
                raise ValueError("Broadcasts require a message.")
        return self


class AssignmentDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)

    title: str = Field(min_length=1, max_length=500)
    brief: str = Field(min_length=1, max_length=250_000)
    supervisor: str = Field(min_length=1, max_length=500)
    assignee: str = Field(min_length=1, max_length=500)
    project: str = ""
    priority: str = "normal"

    @field_validator("project")
    @classmethod
    def check_project(cls, value: str) -> str:
        return normalize_project_slug(value) if value.strip() else ""

    @field_validator("priority")
    @classmethod
    def check_priority(cls, value: str) -> str:
        p = (value or "normal").lower()
        if p not in PRIORITIES:
            raise ValueError("Choose priority low, normal, high, or urgent.")
        return p


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
            conn.execute("PRAGMA busy_timeout=5000")
            for attempt in range(8):
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if ("locked" not in msg and "busy" not in msg) or attempt == 7:
                        raise
                    time.sleep(0.05 * (attempt + 1))
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < 2:
                self._migrate_to_v2(conn)
            return conn
        except Exception:
            conn.close()
            raise

    def _migrate_to_v2(self, conn: sqlite3.Connection) -> None:
        try:
            # executescript commits any existing transaction; include BEGIN in the
            # script so the version check and migration retain the write lock.
            conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA_V2)
            if conn.execute("PRAGMA user_version").fetchone()[0] >= 2:
                conn.commit()
                return
            has_legacy = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assignments'"
            ).fetchone()
            if has_legacy is not None:
                has_posts = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_posts'"
                ).fetchone()
                rows = conn.execute("SELECT * FROM assignments ORDER BY id").fetchall()
                for row in rows:
                    first_ts = row["updated_at"]
                    if has_posts is not None:
                        ts_row = conn.execute(
                            "SELECT min(created_at) AS first_ts FROM board_posts WHERE assignment_id = ?",
                            (row["id"],),
                        ).fetchone()
                        if ts_row and ts_row["first_ts"]:
                            first_ts = ts_row["first_ts"]
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO threads(
                            id, kind, title, project, channel, priority,
                            created_by, supervisor, assignee, status, metadata, created_at, updated_at
                        ) VALUES (?, 'assignment', ?, ?, '', 'normal', ?, ?, ?, ?, '{}', ?, ?)
                        """,
                        (
                            row["id"],
                            row["title"],
                            row["project"],
                            row["supervisor"],
                            row["supervisor"],
                            row["assignee"],
                            row["status"],
                            first_ts,
                            row["updated_at"],
                        ),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO thread_participants(thread_id, actor, role, joined_at) VALUES (?, ?, 'supervisor', ?)",
                        (row["id"], row["supervisor"], first_ts),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO thread_participants(thread_id, actor, role, joined_at) VALUES (?, ?, 'assignee', ?)",
                        (row["id"], row["assignee"], first_ts),
                    )
                if has_posts is not None:
                    first_ids = {
                        r["assignment_id"]: r["first_id"]
                        for r in conn.execute(
                            "SELECT assignment_id, min(id) AS first_id FROM board_posts GROUP BY assignment_id"
                        ).fetchall()
                    }
                    posts = conn.execute("SELECT * FROM board_posts ORDER BY id").fetchall()
                    for post in posts:
                        if post["id"] == first_ids.get(post["assignment_id"]):
                            mkind = "brief"
                        elif post["status"]:
                            mkind = "status"
                        else:
                            mkind = "message"
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO messages(
                                id, thread_id, author, kind, body, status, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                post["id"],
                                post["assignment_id"],
                                post["author"],
                                mkind,
                                post["message"],
                                post["status"],
                                post["created_at"],
                            ),
                        )
                    conn.execute("DROP TABLE board_posts")
                conn.execute("DROP TABLE assignments")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _thread(self, conn: sqlite3.Connection, thread_id: int) -> dict[str, Any]:
        if type(thread_id) is not int or not 1 <= thread_id <= 2**63 - 1:
            raise ValueError("Use the thread number shown on the board.")
        row = conn.execute(f"{THREAD_SELECT} WHERE t.id = ?", (thread_id,)).fetchone()
        if row is None:
            raise ValueError(f"Thread #{thread_id} was not found. Check the Agent Board for its number.")
        return self._format_thread(conn, row)

    def _format_thread(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["metadata"] = json.loads(data.get("metadata") or "{}")
        except Exception:
            data["metadata"] = {}
        parts = conn.execute(
            "SELECT actor, role, joined_at FROM thread_participants WHERE thread_id = ? ORDER BY rowid",
            (data["id"],),
        ).fetchall()
        data["participants"] = [p["actor"] for p in parts]
        data["participant_roles"] = [dict(p) for p in parts]
        return data

    def _format_message(self, row: sqlite3.Row) -> dict[str, Any]:
        to_actors = json.loads(row["to_actors"] or "[]")
        refs = json.loads(row["refs"] or "[]")
        payload = json.loads(row["payload"]) if row["payload"] else None
        return {
            "id": row["id"],
            "thread_id": row["thread_id"],
            "author": row["author"],
            "kind": row["kind"],
            "message": row["body"],
            "status": row["status"],
            "reply_to": row["reply_to"],
            "to": to_actors,
            "refs": refs,
            "payload": payload,
            "created_at": row["created_at"],
        }

    def _actions_for(self, conn: sqlite3.Connection, thread: dict[str, Any]) -> list[dict[str, Any]]:
        kind = thread["kind"]
        status = thread["status"]
        transitions = TRANSITIONS_BY_KIND.get(kind, {}).get(status, {})
        actions: list[dict[str, Any]] = []
        recipients = [
            p["actor"]
            for p in thread.get("participant_roles", [])
            if p["role"] == "recipient"
        ]
        for target, (role, label, needs_message) in transitions.items():
            if role == "supervisor":
                actors = [thread["supervisor"]] if thread["supervisor"] else []
                actor_display = thread["supervisor"]
            elif role == "assignee":
                actors = [thread["assignee"]] if thread["assignee"] else []
                actor_display = thread["assignee"]
            elif role == "initiator":
                actors = [thread["created_by"]]
                actor_display = thread["created_by"]
            elif role == "recipient":
                actors = recipients or ["*"]
                actor_display = ", ".join(recipients) if recipients else "*"
            else:
                actors = ["*"]
                actor_display = "*"
            actions.append(
                {
                    "status": target,
                    "role": role,
                    "actor": actor_display,
                    "actors": actors,
                    "label": label,
                    "needs_message": needs_message,
                }
            )
        return actions

    def _authorize_transition(
        self, conn: sqlite3.Connection, thread: dict[str, Any], author: str, role: str
    ) -> None:
        if role == "supervisor":
            if author.casefold() != thread["supervisor"].casefold():
                raise ValueError(f"{thread['supervisor']} can make this status change as the supervisor.")
        elif role == "assignee":
            if author.casefold() != thread["assignee"].casefold():
                raise ValueError(f"{thread['assignee']} can make this status change as the assignee.")
        elif role == "initiator":
            if author.casefold() != thread["created_by"].casefold():
                raise ValueError(f"{thread['created_by']} can make this status change as the initiator.")
        elif role == "recipient":
            recipients = [
                p["actor"].casefold()
                for p in thread.get("participant_roles", [])
                if p["role"] == "recipient"
            ]
            if "*" in recipients:
                if author.casefold() == thread["created_by"].casefold():
                    raise ValueError("A recipient other than the initiator can make this status change.")
            elif author.casefold() not in recipients:
                expected = ", ".join(
                    p["actor"] for p in thread.get("participant_roles", []) if p["role"] == "recipient"
                )
                raise ValueError(f"Only a recipient ({expected}) can make this status change.")
        # role == "any" permits any non-empty actor

    def _ensure_participant(
        self, conn: sqlite3.Connection, thread_id: int, actor: str, role: str, stamp: str
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO thread_participants(thread_id, actor, role, joined_at) VALUES (?, ?, ?, ?)",
            (thread_id, actor, role, stamp),
        )

    def open_thread(
        self,
        *,
        kind: str = "discussion",
        title: str,
        body: str = "",
        author: str,
        to: list[str] | tuple[str, ...] | str | None = None,
        supervisor: str = "",
        assignee: str = "",
        project: str = "",
        channel: str = "",
        priority: str = "normal",
        refs: list[str] | tuple[str, ...] | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        to_list = _normalize_actors(to)
        if kind.strip().lower() == "broadcast" and not to_list:
            to_list = ["*"]
        refs_list = _normalize_refs(refs)
        payload_json = _serialize_json_obj(payload, label="Payload")
        meta_json = _serialize_json_obj(metadata, label="Metadata") or "{}"

        sup = supervisor.strip() or (author.strip() if kind.strip().lower() == "assignment" else "")
        asg = assignee.strip() or (to_list[0] if kind.strip().lower() == "assignment" and to_list else "")

        draft = ThreadDraft(
            kind=kind,
            title=title,
            body=body,
            author=author,
            supervisor=sup,
            assignee=asg,
            to=to_list,
            project=project,
            channel=channel,
            priority=priority,
            refs=refs_list,
            payload=payload,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        initial_status = INITIAL_STATUS[draft.kind]
        first_msg_kind = "brief" if draft.kind == "assignment" else ("handoff" if draft.kind == "request" else "message")
        stamp = now_iso()

        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if draft.idempotency_key:
                existing = conn.execute(
                    """
                    SELECT t.id, t.kind, t.status, m.id AS post_id
                    FROM messages m JOIN threads t ON t.id = m.thread_id
                    WHERE m.author = ? COLLATE NOCASE
                      AND m.idempotency_key = ?
                      AND m.id = (SELECT min(m2.id) FROM messages m2 WHERE m2.thread_id = m.thread_id)
                    ORDER BY m.id DESC LIMIT 1
                    """,
                    (draft.author, draft.idempotency_key),
                ).fetchone()
                if existing is not None:
                    return {
                        "id": existing["id"],
                        "post_id": existing["post_id"],
                        "kind": existing["kind"],
                        "status": existing["status"],
                        "deduplicated": True,
                    }

            cursor = conn.execute(
                """
                INSERT INTO threads(
                    kind, title, project, channel, priority,
                    created_by, supervisor, assignee, status, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.kind,
                    draft.title,
                    draft.project,
                    draft.channel,
                    draft.priority,
                    draft.author,
                    draft.supervisor,
                    draft.assignee,
                    initial_status,
                    meta_json,
                    stamp,
                    stamp,
                ),
            )
            thread_id = int(cursor.lastrowid)

            if draft.kind == "assignment":
                self._ensure_participant(conn, thread_id, draft.supervisor, "supervisor", stamp)
                self._ensure_participant(conn, thread_id, draft.assignee, "assignee", stamp)
                msg_to = [draft.assignee]
            else:
                self._ensure_participant(conn, thread_id, draft.author, "initiator", stamp)
                for target in draft.to:
                    self._ensure_participant(conn, thread_id, target, "recipient", stamp)
                msg_to = draft.to

            m_cursor = conn.execute(
                """
                INSERT INTO messages(
                    thread_id, author, kind, body, status, to_actors, refs, payload, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    draft.author,
                    first_msg_kind,
                    draft.body,
                    initial_status if draft.kind == "assignment" else "",
                    json.dumps(msg_to),
                    json.dumps(draft.refs),
                    payload_json,
                    draft.idempotency_key or None,
                    stamp,
                ),
            )
            post_id = int(m_cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO read_cursors(thread_id, actor, last_read_id, acked_id, updated_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(thread_id, actor) DO UPDATE SET
                    last_read_id = max(last_read_id, excluded.last_read_id),
                    updated_at = excluded.updated_at
                """,
                (thread_id, draft.author, post_id, stamp),
            )

        return {"id": thread_id, "post_id": post_id, "kind": draft.kind, "status": initial_status}

    def assign(
        self,
        *,
        title: str,
        brief: str,
        supervisor: str,
        assignee: str,
        project: str = "",
        priority: str = "normal",
    ) -> dict[str, Any]:
        draft = AssignmentDraft(
            title=title,
            brief=brief,
            supervisor=supervisor,
            assignee=assignee,
            project=project,
            priority=priority,
        )
        res = self.open_thread(
            kind="assignment",
            title=draft.title,
            body=draft.brief,
            author=draft.supervisor,
            supervisor=draft.supervisor,
            assignee=draft.assignee,
            project=draft.project,
            priority=draft.priority,
        )
        return {"id": res["id"], "status": res["status"]}

    def _list_in_conn(
        self,
        conn: sqlite3.Connection,
        *,
        actor: str = "",
        status: str = "",
        project: str = "",
        kind: str = "",
        channel: str = "",
        since_rev: int = 0,
        include_broadcasts: bool = False,
        limit: int = 200,
    ) -> dict[str, Any]:
        actor = actor.strip()
        status = status.strip()
        kind = kind.strip().lower()
        channel = normalize_project_slug(channel) if channel.strip() else ""
        project = normalize_project_slug(project) if project.strip() else ""

        if status and status not in STATES:
            raise ValueError(f"Unknown status '{status}'.")
        if kind and kind not in THREAD_KINDS:
            raise ValueError("Choose kind assignment, request, discussion, or broadcast.")

        where: list[str] = []
        values: list[Any] = []
        if actor:
            if include_broadcasts:
                where.append(
                    "EXISTS (SELECT 1 FROM thread_participants tp WHERE tp.thread_id = t.id AND (tp.actor = ? COLLATE NOCASE OR tp.actor = '*'))"
                )
            else:
                where.append(
                    "EXISTS (SELECT 1 FROM thread_participants tp WHERE tp.thread_id = t.id AND tp.actor = ? COLLATE NOCASE)"
                )
            values.append(actor)
        if status:
            where.append("t.status = ?")
            values.append(status)
        if kind:
            where.append("t.kind = ?")
            values.append(kind)
        if channel:
            where.append("lower(t.channel) = lower(?)")
            values.append(channel)
        if project:
            where.append("lower(t.project) = lower(?)")
            values.append(project)
        if since_rev > 0:
            where.append("coalesce((SELECT max(m.id) FROM messages m WHERE m.thread_id = t.id), 0) > ?")
            values.append(int(since_rev))

        condition = f" WHERE {' AND '.join(where)}" if where else ""
        limit_val = max(1, min(int(limit), 500))
        rows = conn.execute(
            f"{THREAD_SELECT}{condition} ORDER BY revision DESC, t.id DESC LIMIT ?",
            [*values, limit_val],
        ).fetchall()
        threads = [self._format_thread(conn, row) for row in rows]
        if actor:
            for thread in threads:
                cursor = conn.execute(
                    "SELECT last_read_id, acked_id FROM read_cursors WHERE thread_id = ? AND actor = ? COLLATE NOCASE",
                    (thread["id"], actor),
                ).fetchone()
                last_read = cursor["last_read_id"] if cursor else 0
                thread["unread_count"] = conn.execute(
                    "SELECT count(*) FROM messages WHERE thread_id = ? AND id > ? AND author != ? COLLATE NOCASE",
                    (thread["id"], last_read, actor),
                ).fetchone()[0]
        revision = conn.execute("SELECT coalesce(max(id), 0) FROM messages").fetchone()[0]
        return {"threads": threads, "assignments": threads, "revision": revision}

    def list(
        self,
        *,
        actor: str = "",
        status: str = "",
        project: str = "",
        kind: str = "",
        channel: str = "",
        since_rev: int = 0,
        include_broadcasts: bool = False,
        limit: int = 200,
    ) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            return self._list_in_conn(
                conn,
                actor=actor,
                status=status,
                project=project,
                kind=kind,
                channel=channel,
                since_rev=since_rev,
                include_broadcasts=include_broadcasts,
                limit=limit,
            )

    def read(
        self,
        thread_id: int,
        *,
        actor: str = "",
        since_post_id: int = 0,
        mark_read: bool = False,
    ) -> dict[str, Any]:
        actor = actor.strip()
        with closing(self._connect()) as conn:
            if actor and mark_read:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute("BEGIN")
            thread = self._thread(conn, thread_id)

            posts_rows = conn.execute(
                "SELECT * FROM messages WHERE thread_id = ? AND id > ? ORDER BY id",
                (thread_id, int(since_post_id)),
            ).fetchall()
            posts = [self._format_message(row) for row in posts_rows]
            if actor and mark_read:
                latest_id = thread["revision"]
                if latest_id > 0:
                    stamp = now_iso()
                    conn.execute(
                        """
                        INSERT INTO read_cursors(thread_id, actor, last_read_id, acked_id, updated_at)
                        VALUES (?, ?, ?, 0, ?)
                        ON CONFLICT(thread_id, actor) DO UPDATE SET
                            last_read_id = max(last_read_id, excluded.last_read_id),
                            updated_at = excluded.updated_at
                        """,
                        (thread_id, actor, latest_id, stamp),
                    )
                conn.commit()
            cursors = {
                r["actor"].casefold(): {"last_read_id": r["last_read_id"], "acked_id": r["acked_id"], "updated_at": r["updated_at"]}
                for r in conn.execute(
                    "SELECT actor, last_read_id, acked_id, updated_at FROM read_cursors WHERE thread_id = ?",
                    (thread_id,),
                ).fetchall()
            }
            for p in thread["participant_roles"]:
                c = cursors.get(p["actor"].casefold())
                p["last_read_id"] = c["last_read_id"] if c else 0
                p["acked_id"] = c["acked_id"] if c else 0
            thread["posts"] = posts
            thread["actions"] = self._actions_for(conn, thread)
            return thread

    def post(
        self,
        thread_id: int,
        *,
        author: str,
        message: str = "",
        status: str = "",
        kind: str = "",
        reply_to: int | None = None,
        to: list[str] | tuple[str, ...] | str | None = None,
        refs: list[str] | tuple[str, ...] | None = None,
        payload: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        author = author.strip()
        message = message.strip()
        status = status.strip()
        kind = kind.strip().lower()
        idempotency_key = idempotency_key.strip()
        to_list = _normalize_actors(to)
        refs_list = _normalize_refs(refs)
        payload_json = _serialize_json_obj(payload, label="Payload")

        if not author:
            raise ValueError("Enter the harness or session posting this update.")
        if len(author) > 500:
            raise ValueError("Author must be at most 500 characters.")
        if len(message) > 250_000:
            raise ValueError("Message must be at most 250,000 characters.")
        if len(idempotency_key) > 200:
            raise ValueError("Idempotency key must be at most 200 characters.")
        if kind and kind not in MESSAGE_KINDS:
            raise ValueError(f"Unknown message kind '{kind}'.")
        msg_kind = kind or ("status" if status and not message else "message")
        if not (message or status or payload_json is not None or refs_list or msg_kind == "ack"):
            raise ValueError("Enter a message, payload, reference, or select a status change.")
        stamp = now_iso()

        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            thread = self._thread(conn, thread_id)

            cursor_row = conn.execute(
                "SELECT last_read_id FROM read_cursors WHERE thread_id = ? AND actor = ? COLLATE NOCASE",
                (thread_id, author),
            ).fetchone()
            previous_read = cursor_row["last_read_id"] if cursor_row else 0
            has_unread = conn.execute(
                "SELECT 1 FROM messages WHERE thread_id = ? AND id > ? AND author != ? COLLATE NOCASE LIMIT 1",
                (thread_id, previous_read, author),
            ).fetchone() is not None

            if idempotency_key:
                existing = conn.execute(
                    "SELECT id, status FROM messages WHERE thread_id = ? AND author = ? COLLATE NOCASE AND idempotency_key = ?",
                    (thread_id, author, idempotency_key),
                ).fetchone()
                if existing is not None:
                    return {
                        "id": thread_id,
                        "post_id": existing["id"],
                        "status": thread["status"],
                        "deduplicated": True,
                    }

            if expected_revision is not None and thread["revision"] != expected_revision:
                raise ValueError(
                    f"Thread #{thread_id} changed (expected revision {expected_revision}, current {thread['revision']}). Read the latest messages before posting."
                )

            if reply_to is not None:
                if type(reply_to) is not int or reply_to < 1:
                    raise ValueError("reply_to must be a valid message ID.")
                parent = conn.execute(
                    "SELECT id FROM messages WHERE id = ? AND thread_id = ?",
                    (reply_to, thread_id),
                ).fetchone()
                if parent is None:
                    raise ValueError(f"Message #{reply_to} was not found in thread #{thread_id}.")

            if status:
                action = TRANSITIONS_BY_KIND.get(thread["kind"], {}).get(thread["status"], {}).get(status)
                if action is None:
                    raise ValueError(
                        f"Thread #{thread_id} is {STATES[thread['status']].lower()}. Read the thread for available status changes."
                    )
                role, label, needs_message = action
                self._authorize_transition(conn, thread, author, role)
                if needs_message and not message:
                    raise ValueError(f"Add a message explaining the update before selecting {label.lower()}.")

            self._ensure_participant(conn, thread_id, author, "participant", stamp)
            for target in to_list:
                self._ensure_participant(conn, thread_id, target, "participant", stamp)

            post_cursor = conn.execute(
                """
                INSERT INTO messages(
                    thread_id, author, kind, body, status, reply_to, to_actors, refs, payload, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    author,
                    msg_kind,
                    message,
                    status,
                    reply_to,
                    json.dumps(to_list),
                    json.dumps(refs_list),
                    payload_json,
                    idempotency_key or None,
                    stamp,
                ),
            )
            post_id = int(post_cursor.lastrowid)
            current_status = status or thread["status"]
            conn.execute(
                "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
                (current_status, stamp, thread_id),
            )
            ack_target = post_id if msg_kind == "ack" else 0
            # Posting is not proof that earlier messages from others were read.
            read_target = post_id if not has_unread or msg_kind == "ack" else previous_read
            conn.execute(
                """
                INSERT INTO read_cursors(thread_id, actor, last_read_id, acked_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, actor) DO UPDATE SET
                    last_read_id = max(last_read_id, excluded.last_read_id),
                    acked_id = max(acked_id, excluded.acked_id),
                    updated_at = excluded.updated_at
                """,
                (thread_id, author, read_target, ack_target, stamp),
            )

        return {"id": thread_id, "post_id": post_id, "kind": msg_kind, "status": current_status}

    def ack(
        self,
        thread_id: int,
        *,
        actor: str,
        up_to_post_id: int | None = None,
        message: str = "",
        post_ack: bool = False,
    ) -> dict[str, Any]:
        actor = actor.strip()
        message = message.strip()
        if not actor:
            raise ValueError("Enter the harness or session acknowledging this thread.")
        stamp = now_iso()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            thread = self._thread(conn, thread_id)
            target_id = thread["revision"] if up_to_post_id is None else int(up_to_post_id)
            if up_to_post_id is not None:
                found = conn.execute(
                    "SELECT id FROM messages WHERE id = ? AND thread_id = ?",
                    (target_id, thread_id),
                ).fetchone()
                if found is None:
                    raise ValueError(f"Message #{target_id} was not found in thread #{thread_id}.")
            self._ensure_participant(conn, thread_id, actor, "participant", stamp)

            ack_post_id = 0
            if post_ack or message:
                cur = conn.execute(
                    """
                    INSERT INTO messages(thread_id, author, kind, body, status, created_at)
                    VALUES (?, ?, 'ack', ?, '', ?)
                    """,
                    (thread_id, actor, message, stamp),
                )
                ack_post_id = int(cur.lastrowid)
                target_id = max(target_id, ack_post_id)
                conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (stamp, thread_id))

            conn.execute(
                """
                INSERT INTO read_cursors(thread_id, actor, last_read_id, acked_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, actor) DO UPDATE SET
                    last_read_id = max(last_read_id, excluded.last_read_id),
                    acked_id = max(acked_id, excluded.acked_id),
                    updated_at = excluded.updated_at
                """,
                (thread_id, actor, target_id, target_id, stamp),
            )
        return {"id": thread_id, "acked_id": target_id, "post_id": ack_post_id, "status": thread["status"]}

    def inbox(
        self,
        actor: str,
        *,
        project: str = "",
        kind: str = "",
        unread_only: bool = True,
        since_rev: int = 0,
    ) -> dict[str, Any]:
        actor = actor.strip()
        if not actor:
            raise ValueError("Specify an actor (--for) to check inbox.")
        items: list[dict[str, Any]] = []
        unread_total = 0
        attention_total = 0

        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            listed = self._list_in_conn(
                conn,
                actor=actor,
                project=project,
                kind=kind,
                since_rev=since_rev,
                include_broadcasts=True,
            )
            for thread in listed["threads"]:
                tid = thread["id"]
                cursor = conn.execute(
                    "SELECT last_read_id, acked_id FROM read_cursors WHERE thread_id = ? AND actor = ? COLLATE NOCASE",
                    (tid, actor),
                ).fetchone()
                last_read = cursor["last_read_id"] if cursor else 0
                acked_id = cursor["acked_id"] if cursor else 0

                unread_rows = conn.execute(
                    "SELECT * FROM messages WHERE thread_id = ? AND id > ? AND author != ? COLLATE NOCASE ORDER BY id",
                    (tid, last_read, actor),
                ).fetchall()
                unread_count = len(unread_rows)
                latest_row = conn.execute(
                    "SELECT * FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 1",
                    (tid,),
                ).fetchone()
                latest_msg = self._format_message(latest_row) if latest_row else None

                reasons: list[str] = []
                actor_cf = actor.casefold()
                for ur in unread_rows:
                    to_list = [x.casefold() for x in json.loads(ur["to_actors"] or "[]")]
                    if actor_cf in to_list or "*" in to_list:
                        reasons.append("direct_mention")
                    if ur["kind"] in ("question", "handoff"):
                        reasons.append(ur["kind"])

                expected_next = _ATTENTION_TRANSITIONS.get(thread["kind"], {}).get(thread["status"], set())
                for act in self._actions_for(conn, thread):
                    if act["status"] in expected_next and act["role"] in ("supervisor", "assignee", "initiator", "recipient"):
                        if actor_cf in [a.casefold() for a in act["actors"]] or (
                            "*" in act["actors"] and actor_cf != thread["created_by"].casefold()
                        ):
                            reasons.append(f"action:{act['status']}")
                            break

                if (
                    thread["kind"] == "broadcast"
                    and thread["status"] == "open"
                    and acked_id < thread["revision"]
                    and thread["created_by"].casefold() != actor_cf
                ):
                    reasons.append("unacked_broadcast")

                dedup_reasons = list(dict.fromkeys(reasons))
                needs_attention = bool(dedup_reasons)
                if unread_only and unread_count == 0 and not needs_attention:
                    continue

                unread_total += unread_count
                if needs_attention:
                    attention_total += 1

                entry = {
                    **thread,
                    "unread_count": unread_count,
                    "last_read_id": last_read,
                    "acked_id": acked_id,
                    "needs_attention": needs_attention,
                    "attention_reasons": dedup_reasons,
                    "latest_message": latest_msg,
                }
                items.append(entry)

        items.sort(
            key=lambda t: (
                1 if t["needs_attention"] else 0,
                _PRIORITY_RANK.get(t["priority"], 1),
                t["revision"],
            ),
            reverse=True,
        )
        return {
            "actor": actor,
            "threads": items,
            "unread_total": unread_total,
            "attention_total": attention_total,
            "revision": listed["revision"],
        }

    def wait(
        self,
        *,
        actor: str = "",
        thread_id: int | None = None,
        since_rev: int = 0,
        timeout: float = 30.0,
        poll_interval: float = 0.2,
    ) -> dict[str, Any]:
        actor = actor.strip()
        timeout = max(0.0, min(float(timeout), 60.0))
        poll_interval = max(0.05, min(float(poll_interval), 2.0))
        deadline = time.monotonic() + timeout

        with closing(self._connect()) as conn:
            while True:
                conn.execute("BEGIN")
                try:
                    if thread_id is not None:
                        thread = self._thread(conn, thread_id)
                        rev = thread["revision"]
                        if rev > since_rev:
                            posts = [
                                self._format_message(r)
                                for r in conn.execute(
                                    "SELECT * FROM messages WHERE thread_id = ? AND id > ? ORDER BY id",
                                    (thread_id, int(since_rev)),
                                ).fetchall()
                            ]
                            return {"timed_out": False, "revision": rev, "threads": [{**thread, "posts": posts}]}
                    else:
                        listed = self._list_in_conn(conn, actor=actor, since_rev=since_rev, include_broadcasts=bool(actor))
                        rev = listed["revision"]
                        if listed["threads"] and rev > since_rev:
                            return {"timed_out": False, "revision": rev, "threads": listed["threads"]}
                finally:
                    conn.rollback()

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"timed_out": True, "revision": rev, "threads": []}
                time.sleep(min(poll_interval, remaining))

    def heartbeat(
        self,
        *,
        actor: str,
        harness: str = "",
        project: str = "",
        status: str = "active",
        summary: str = "",
        capabilities: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        actor = actor.strip()
        harness = harness.strip()
        project = normalize_project_slug(project) if project.strip() else ""
        status = (status or "active").strip().lower()
        summary = " ".join(summary.split())[:500]
        if not actor:
            raise ValueError("Specify an actor identity (--as) to register.")
        if len(actor) > 500:
            raise ValueError("Actor must be at most 500 characters.")
        if status not in AGENT_STATES:
            raise ValueError("Choose status active, idle, busy, or offline.")
        caps = _normalize_actors(capabilities)
        stamp = now_iso()

        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                INSERT INTO agent_presence(actor, harness, project, status, summary, capabilities, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(actor) DO UPDATE SET
                    harness = CASE WHEN excluded.harness <> '' THEN excluded.harness ELSE agent_presence.harness END,
                    project = CASE WHEN excluded.project <> '' THEN excluded.project ELSE agent_presence.project END,
                    status = excluded.status,
                    summary = CASE WHEN excluded.summary <> '' THEN excluded.summary ELSE agent_presence.summary END,
                    capabilities = CASE WHEN excluded.capabilities <> '[]' THEN excluded.capabilities ELSE agent_presence.capabilities END,
                    last_seen_at = excluded.last_seen_at
                RETURNING *
                """,
                (actor, harness, project, status, summary, json.dumps(caps), stamp),
            ).fetchone()
        result = dict(row)
        result["capabilities"] = json.loads(result.get("capabilities") or "[]")
        return result

    def agents(
        self,
        *,
        project: str = "",
        active_within_minutes: int = 60,
        include_offline: bool = False,
    ) -> dict[str, Any]:
        project = normalize_project_slug(project) if project.strip() else ""
        where: list[str] = []
        values: list[Any] = []
        if project:
            where.append("lower(project) = lower(?)")
            values.append(project)
        if not include_offline:
            where.append("status <> 'offline'")
        if active_within_minutes > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=int(active_within_minutes))).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            where.append("last_seen_at >= ?")
            values.append(cutoff)
        condition = f" WHERE {' AND '.join(where)}" if where else ""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                f"SELECT * FROM agent_presence{condition} ORDER BY last_seen_at DESC, actor ASC",
                values,
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item.get("capabilities") or "[]")
            items.append(item)
        return {"agents": items}
