"""Opt-in checkpoint ledger; canonical memories remain Markdown.

Saved receipts are produced only by the write path, never from a caller's ID.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from .store import ensure_layout, infer_kind_from_rel, now_iso
from .validation import normalize_project_slug

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
_TRIGGERS = {"explicit_request", "verified_fix", "decision", "milestone", "review"}


def _connect(path: Path, *, timeout: float = 10.0) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=timeout)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={int(max(timeout, 1.0) * 1000)}")
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
        return conn
    except Exception:
        conn.close()
        raise


def revision(root: Path, memory_id: str) -> dict:
    """Return the inspected canonical Markdown and its compare-and-write token."""
    from .store import markdown_revision, resolve_path

    base = root.resolve()
    filename = resolve_path(base, memory_id)
    if not filename.is_relative_to(base) or filename.relative_to(base).parts[0] not in ("notes", "projects", "journal"):
        raise ValueError("Choose a canonical Brain memory ID")
    raw = filename.read_text(encoding="utf-8")
    return {"memory_id": filename.relative_to(base).with_suffix("").as_posix(),
            "markdown": raw, "revision": markdown_revision(raw)}


def _identifier(value: str, name: str, *, optional: bool = False) -> str:
    if optional and not value:
        return value
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def observe(root: Path, *, surface: str, harness: str, session: str, turn: str,
            trigger: str, project: str = "") -> dict:
    """Record a delivered event once; never accept free-form transcript data."""
    for name, value in (("surface", surface), ("harness", harness),
                        ("session", session), ("turn", turn)):
        _identifier(value, name)
    _identifier(project, "project", optional=True)
    if project:
        project = normalize_project_slug(project)
        if not project:
            raise ValueError("invalid project")
    if trigger not in _TRIGGERS:
        raise ValueError("invalid trigger")
    identity = [surface, harness, session, turn, project, trigger]
    event_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    ensure_layout(root)
    with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=10)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
            surface TEXT NOT NULL, harness TEXT NOT NULL, session TEXT NOT NULL,
            turn TEXT NOT NULL, project TEXT NOT NULL, trigger TEXT NOT NULL,
            created_at TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT 'pending'
        )""")
        db.execute("""INSERT OR IGNORE INTO checkpoints
            (id,event_key,surface,harness,session,turn,project,trigger,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex, event_key, *identity, now_iso()))
        return dict(db.execute("SELECT id,surface,harness,session,turn,project,trigger,created_at,outcome FROM checkpoints WHERE event_key=?", (event_key,)).fetchone())


def save(root: Path, checkpoint_id: str, *, content: str, kind: str = "fact",
         title: str = "", project: str = "", headline: str = "", subject: str = "",
         predicate: str = "", source: str = "", author: str = "",
         expected_revision: str | None = None) -> dict:
    """Save a note with a durable operation marker and recover an interrupted save.

    Facts, decisions, lessons and project updates use revision-guarded writes.
    Journal entries use a per-entry marker so concurrent appends remain safe.
    """
    import fcntl
    from .index import index_single_item
    from .store import atomic_fact_value, load_item, markdown_revision, memory_write_lock, note_target, parse_frontmatter, save_memory, slugify, today_str
    from .validation import MemoryDraft

    if not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id):
        raise ValueError("invalid checkpoint id")
    draft = MemoryDraft(content=content, kind=kind, title=title, project=project,
                        headline=headline, subject=subject, predicate=predicate,
                        source=source, author=author)
    fields = draft.model_dump()
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    journal = draft.kind in ("journal", "episode")
    if journal:
        path = root / "journal" / f"{today_str()}.md"
    elif draft.kind == "project":
        slug = slugify(draft.project or draft.title, 48)
        path = root / "projects" / f"{slug}.md"
    else:
        path, note_title = note_target(root, draft)
    ensure_layout(root)
    if not (root / ".gm" / "checkpoints.sqlite3").exists():
        raise ValueError("unknown checkpoint")
    # This lock coordinates checkpoint operations. Canonical write locking and
    # expected_revision also protect against ordinary Brain writers.
    with (root / ".gm" / "checkpoint-write.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=10)) as db, db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoints'").fetchone():
                raise ValueError("unknown checkpoint")
            row = db.execute("SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,)).fetchone()
            if row is None:
                raise ValueError("unknown checkpoint")
            if row["outcome"] == "skipped":
                raise ValueError("checkpoint has already been skipped")
            if row["project"] and row["project"] != draft.project:
                raise ValueError("checkpoint project does not match draft")
            db.execute("""CREATE TABLE IF NOT EXISTS checkpoint_operations (
                checkpoint_id TEXT PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL,
                draft_hash TEXT NOT NULL, memory_id TEXT NOT NULL,
                baseline TEXT NOT NULL, saved INTEGER NOT NULL DEFAULT 0,
                indexed INTEGER NOT NULL DEFAULT 0, is_duplicate INTEGER NOT NULL DEFAULT 0
            )""")
            columns = {col[1] for col in db.execute("PRAGMA table_info(checkpoint_operations)")}
            if "is_duplicate" not in columns:
                db.execute("ALTER TABLE checkpoint_operations ADD COLUMN is_duplicate INTEGER NOT NULL DEFAULT 0")
            op = db.execute("SELECT * FROM checkpoint_operations WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
            if journal and op is not None and re.fullmatch(r"journal/[0-9]{4}-[0-9]{2}-[0-9]{2}", op["memory_id"]):
                path = root / (op["memory_id"] + ".md")
            memory_id = path.relative_to(root).as_posix()[:-3]
            if op is None:
                with memory_write_lock(root):
                    existing = path.read_text(encoding="utf-8") if path.exists() else ""
                    baseline = markdown_revision(existing)
                    old_meta, old_body = parse_frontmatter(existing)
                    duplicate = bool(draft.subject and old_meta.get("kind") == "fact"
                                     and old_meta.get("subject") == draft.subject
                                     and old_meta.get("predicate") == draft.predicate
                                     and (old_meta.get("project") or "") == draft.project
                                     and atomic_fact_value(old_body) == draft.content)
                    if path.exists() and not (duplicate or journal) and expected_revision != baseline:
                        raise FileExistsError("existing memory requires its current revision")
                    if expected_revision is not None and expected_revision != baseline:
                        raise FileExistsError("memory revision does not match")
                    db.execute("INSERT INTO checkpoint_operations (checkpoint_id,operation_id,draft_hash,memory_id,baseline,saved,indexed,is_duplicate) VALUES (?,?,?,?,?,?,?,?)",
                               (checkpoint_id, uuid.uuid4().hex, digest, memory_id, baseline,
                                int(duplicate), int(duplicate), int(duplicate)))
                    db.commit()
                op = db.execute("SELECT * FROM checkpoint_operations WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
            if op["draft_hash"] != digest or op["memory_id"] != memory_id:
                raise ValueError("checkpoint already has a different operation")
            raw = path.read_text(encoding="utf-8") if path.exists() else ""
            meta, body = parse_frontmatter(raw)
            marker = f"<!-- brain-checkpoint:{op['operation_id']} -->"
            if journal and marker in body:
                parts = body.split(marker)
                heading, _, value = parts[1].strip().partition("\n")
                suffix = (f" — {draft.title}" if draft.title else "") + (f" [{draft.project}]" if draft.project else "")
                if (len(parts) != 3 or not re.fullmatch(r"## [0-9]{2}:[0-9]{2}" + re.escape(suffix), heading)
                        or value.strip() != draft.content
                        or (meta.get("kind") or infer_kind_from_rel(memory_id)) != "journal"):
                    raise FileExistsError("checkpoint journal entry changed; refusing stale receipt")
                item = load_item(path, root)
            elif op["is_duplicate"]:
                if (markdown_revision(raw) != op["baseline"] or meta.get("kind") != "fact"
                        or meta.get("subject") != draft.subject or meta.get("predicate") != draft.predicate
                        or atomic_fact_value(body) != draft.content):
                    raise FileExistsError("duplicate memory changed; refusing stale receipt")
                item = load_item(path, root)
            elif meta.get("checkpoint_operation") == op["operation_id"]:
                if draft.kind == "project":
                    expected_body = draft.content if draft.content.startswith("# ") else f"# {draft.project or draft.title}\n\n{draft.content}"
                elif draft.subject:
                    expected_body = None
                else:
                    expected_body = draft.content if draft.content.startswith("# ") else f"# {note_title}\n\n{draft.content}"
                content_matches = (atomic_fact_value(body) == draft.content if draft.subject
                                   else body.strip() == expected_body.strip())
                expected_project = slug if draft.kind == "project" else draft.project
                if (not content_matches or meta.get("kind") != draft.kind
                        or (meta.get("project") or "") != expected_project
                        or (draft.subject and (meta.get("subject") != draft.subject
                                               or meta.get("predicate") != draft.predicate))):
                    raise FileExistsError("checkpoint memory changed; refusing stale receipt")
                item = load_item(path, root)
            elif op["saved"]:
                raise FileExistsError("saved memory changed; refusing stale retry")
            else:
                try:
                    item = save_memory(root, **fields, expected_revision=None if journal else op["baseline"],
                                       checkpoint_operation=op["operation_id"],
                                       checkpoint_journal_day=path.stem if journal else "")
                except FileExistsError:
                    cur_raw = path.read_text(encoding="utf-8") if path.exists() else ""
                    cur_meta, cur_body = parse_frontmatter(cur_raw)
                    our_write = (marker in cur_body) if journal else (cur_meta.get("checkpoint_operation") == op["operation_id"])
                    if not our_write:
                        db.execute("DELETE FROM checkpoint_operations WHERE checkpoint_id=? AND saved=0", (checkpoint_id,))
                        db.commit()
                    raise
            db.execute("CREATE TABLE IF NOT EXISTS checkpoint_outcomes (checkpoint_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)")
            db.execute("UPDATE checkpoint_operations SET saved=1 WHERE checkpoint_id=?", (checkpoint_id,))
            db.execute("UPDATE checkpoints SET outcome='saved' WHERE id=?", (checkpoint_id,))
            db.execute("INSERT OR IGNORE INTO checkpoint_outcomes VALUES (?,?)", (checkpoint_id, now_iso()))
            db.commit()
            if not op["indexed"]:
                index_single_item(root, item, background_embed=True)
                db.execute("UPDATE checkpoint_operations SET indexed=1 WHERE checkpoint_id=?", (checkpoint_id,))
                db.commit()
            return {"checkpoint_id": checkpoint_id, "outcome": "saved", "memory_id": item.id,
                    "deduplicated": bool(op["is_duplicate"]),
                    "surface": row["surface"], "harness": row["harness"], "session": row["session"],
                    "turn": row["turn"], "project": row["project"] or draft.project, "trigger": row["trigger"],
                    "created_at": row["created_at"], "updated_at": db.execute(
                        "SELECT updated_at FROM checkpoint_outcomes WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()[0]}


def pending(root: Path, *, harness: str, session: str) -> list[dict]:
    """Return pending observations for a session without creating a ledger."""
    _identifier(harness, "harness")
    _identifier(session, "session")
    path = root / ".gm" / "checkpoints.sqlite3"
    if not path.exists():
        return []
    with closing(_connect(path, timeout=10)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone():
            return []
        return [dict(row) for row in db.execute(
            "SELECT id,surface,harness,session,turn,project,trigger,created_at,outcome "
            "FROM checkpoints WHERE harness=? AND session=? AND outcome='pending' ORDER BY created_at,id",
            (harness, session))]


def skip(root: Path, checkpoint_id: str, reason: str) -> dict:
    """Close an observed checkpoint with an explicit bounded reason."""
    if not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id):
        raise ValueError("invalid checkpoint id")
    if reason not in {"no_durable_information", "unverified", "user_declined"}:
        raise ValueError("invalid skip reason")
    import fcntl
    ensure_layout(root)
    if not (root / ".gm" / "checkpoints.sqlite3").exists():
        raise ValueError("unknown checkpoint")
    with (root / ".gm" / "checkpoint-write.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=10)) as db, db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoints'").fetchone():
                raise ValueError("unknown checkpoint")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoint_skips (checkpoint_id TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL)")
            row = db.execute("SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,)).fetchone()
            if row is None:
                raise ValueError("unknown checkpoint")
            existing = db.execute("SELECT reason,created_at FROM checkpoint_skips WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
            if existing:
                if existing["reason"] != reason:
                    raise ValueError("checkpoint already skipped with a different reason")
            else:
                table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint_operations'").fetchone()
                if row["outcome"] != "pending" or (table and db.execute("SELECT 1 FROM checkpoint_operations WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()):
                    raise ValueError("checkpoint already has a write operation")
                updated_at = now_iso()
                db.execute("INSERT INTO checkpoint_skips VALUES (?,?,?)", (checkpoint_id, reason, updated_at))
                db.execute("UPDATE checkpoints SET outcome='skipped' WHERE id=?", (checkpoint_id,))
            return {"checkpoint_id": checkpoint_id, "outcome": "skipped", "reason": reason,
                    **{key: row[key] for key in ("surface", "harness", "session", "turn", "project", "trigger", "created_at")},
                    "updated_at": existing["created_at"] if existing else updated_at}


def record_delivery(root: Path, *, surface: str, harness: str, session: str,
                    turn: str, event: str) -> None:
    """Record a hook delivery independently of checkpoint review or saving."""
    for name, value in (("surface", surface), ("harness", harness), ("session", session), ("turn", turn), ("event", event)):
        _identifier(value, name)
    ensure_layout(root)
    key = hashlib.sha256(json.dumps([surface, harness, session, turn, event], separators=(",", ":")).encode()).hexdigest()
    with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=2)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS hook_deliveries (
            event_key TEXT PRIMARY KEY, surface TEXT NOT NULL, harness TEXT NOT NULL,
            session TEXT NOT NULL, turn TEXT NOT NULL, event TEXT NOT NULL, observed_at TEXT NOT NULL
        )""")
        db.execute("INSERT OR IGNORE INTO hook_deliveries VALUES (?,?,?,?,?,?,?)",
                   (key, surface, harness, session, turn, event, now_iso()))


def has_turn(root: Path, *, surface: str, harness: str, session: str, turn: str) -> bool:
    for name, value in (("surface", surface), ("harness", harness), ("session", session), ("turn", turn)):
        _identifier(value, name)
    path = root / ".gm" / "checkpoints.sqlite3"
    if not path.exists():
        return False
    with closing(_connect(path, timeout=2)) as db:
        found = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone()
        return bool(found and db.execute("SELECT 1 FROM checkpoints WHERE surface=? AND harness=? AND session=? AND turn=? LIMIT 1", (surface, harness, session, turn)).fetchone())


def session_turn(root: Path, *, surface: str, harness: str, session: str,
                 begin: bool = False, native_id: str = "") -> str:
    """Track a locally assigned turn for clients that omit a turn identifier.

    A prompt hook starts a turn; stop retries reuse it. The caller must not
    infer a turn when no prompt was observed.
    """
    for name, value in (("surface", surface), ("harness", harness), ("session", session)):
        _identifier(value, name)
    if native_id:
        _identifier(native_id, "turn")
    if not begin and not (root / ".gm" / "checkpoints.sqlite3").exists():
        return ""
    ensure_layout(root)
    with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=2)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS checkpoint_session_turns (
            surface TEXT NOT NULL, harness TEXT NOT NULL, session TEXT NOT NULL,
            turn TEXT NOT NULL, PRIMARY KEY(surface,harness,session))""")
        if begin:
            turn = native_id or uuid.uuid4().hex
            db.execute("INSERT INTO checkpoint_session_turns VALUES (?,?,?,?) ON CONFLICT(surface,harness,session) DO UPDATE SET turn=excluded.turn",
                       (surface, harness, session, turn))
            return turn
        row = db.execute("SELECT turn FROM checkpoint_session_turns WHERE surface=? AND harness=? AND session=?",
                         (surface, harness, session)).fetchone()
        return row[0] if row else ""


def claim_reminder(root: Path, checkpoint_id: str) -> bool:
    """Atomically claim the single reminder allowed for an open explicit request."""
    with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=2)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS checkpoint_reminders (
            checkpoint_id TEXT PRIMARY KEY, requested_at TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'requested')""")
        result = db.execute("""INSERT OR IGNORE INTO checkpoint_reminders (checkpoint_id, requested_at)
            SELECT id,? FROM checkpoints WHERE id=? AND outcome='pending' AND trigger='explicit_request'""",
            (now_iso(), checkpoint_id))
        return result.rowcount == 1


def reminder_callback(root: Path, *, surface: str, harness: str, session: str, turn: str,
                      start: bool) -> bool:
    """Keep callbacks created by the reminder attached to the original checkpoint."""
    if not turn:
        return False
    with closing(_connect(root / ".gm" / "checkpoints.sqlite3", timeout=2)) as db, db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_reminders'").fetchone():
            return False
        row = db.execute("""SELECT c.id,r.phase FROM checkpoints c JOIN checkpoint_reminders r ON r.checkpoint_id=c.id
            WHERE c.surface=? AND c.harness=? AND c.session=? AND c.turn=? AND r.phase!='finished'""",
            (surface, harness, session, turn)).fetchone()
        if row is None:
            return False
        if start and row[1] == 'requested':
            db.execute("UPDATE checkpoint_reminders SET phase='running' WHERE checkpoint_id=?", (row[0],))
        elif not start and row[1] == 'running':
            db.execute("UPDATE checkpoint_reminders SET phase='finished' WHERE checkpoint_id=?", (row[0],))
        return True
