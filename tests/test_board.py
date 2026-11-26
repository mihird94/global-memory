from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gm.board import Board
from gm.cli import main
from gm.desktop import Desktop
from gm.index import build_context
from gm.mcp_server import brain_board


def test_supervisor_and_implementer_share_the_assignment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = ["--home", str(tmp_path), "board"]
    assert main([*cli, "assign", "Verify the change", "--brief", "Include test evidence.",
                 "--by", "codex/review", "--to", "antigravity/build", "--json"]) == 0
    assignment = json.loads(capsys.readouterr().out)
    task = assignment["id"]
    desktop = Desktop(tmp_path)
    listed = desktop.request("board_list", {"actor": "antigravity/build"})
    assert [row["id"] for row in listed["assignments"]] == [task]
    assert desktop.request("board_read", {"id": task})["posts"][0]["message"] == "Include test evidence."

    base = {"id": task, "author": "antigravity/build"}
    desktop.request("board_post", {**base, "status": "in_progress"})
    with pytest.raises(ValueError, match="Add a message"):
        desktop.request("board_post", {**base, "status": "blocked"})
    desktop.request("board_post", {**base, "status": "blocked", "message": "Waiting for a fixture."})
    desktop.request("board_post", {**base, "status": "in_progress"})
    desktop.request("board_post", {**base, "status": "in_review", "message": "Regression suite passed."})
    with pytest.raises(ValueError, match="as the supervisor"):
        desktop.request("board_post", {**base, "status": "done"})
    assert main([*cli, "post", str(task), "Include the slow case.", "--by", "codex/review", "--status", "in_progress"]) == 0
    desktop.request("board_post", {**base, "status": "in_review", "message": "Slow case passed too."})
    assert main([*cli, "post", str(task), "--by", "codex/review", "--status", "done"]) == 0
    thread = desktop.request("board_read", {"id": task})
    assert [entry["status"] for entry in thread["posts"]] == [
        "assigned", "in_progress", "blocked", "in_progress", "in_review", "in_progress", "in_review", "done",
    ]
    assert not thread["actions"]
    assert desktop.browse({"refresh": True})["total"] == 0


def test_concurrent_sessions_can_post_without_losing_updates(tmp_path: Path) -> None:
    board = Board(tmp_path)
    new = board.assign(title="Concurrent review", brief="Record the results.", supervisor="lead", assignee="builder")
    original = board.list()["revision"]

    def post(index: int) -> None:
        Board(tmp_path).post(new["id"], author=f"session-{index % 2}", message=f"Update {index}")

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(post, range(12)))
    thread = board.read(new["id"])
    assert {entry["message"] for entry in thread["posts"][1:]} == {f"Update {i}" for i in range(12)}
    assert board.list(actor="builder")["revision"] > original


def test_board_normalizes_project_slugs(tmp_path: Path) -> None:
    board = Board(tmp_path)
    created = board.assign(
        title="Check roadmap",
        brief="Verify active study path.",
        supervisor="codex",
        assignee="antigravity",
        project="learning_os",
    )
    listed = board.list(project="learning-os")
    assert [row["id"] for row in listed["assignments"]] == [created["id"]]
    assert listed["assignments"][0]["project"] == "learning-os"


def test_migrates_v0_board_sqlite_in_place(tmp_path: Path) -> None:
    db_path = tmp_path / ".gm" / "board.sqlite"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE assignments (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '',
            supervisor TEXT NOT NULL,
            assignee TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE board_posts (
            id INTEGER PRIMARY KEY,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            author TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        INSERT INTO assignments VALUES (7, 'Legacy task', 'my-proj', 'codex', 'claude', 'in_progress', '2026-01-02T00:00:00Z');
        INSERT INTO board_posts VALUES (10, 7, 'codex', 'Initial brief', 'assigned', '2026-01-01T00:00:00Z');
        INSERT INTO board_posts VALUES (11, 7, 'claude', 'Started work', 'in_progress', '2026-01-02T00:00:00Z');
        INSERT INTO board_posts VALUES (12, 7, 'claude', 'Plain note', '', '2026-01-02T01:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    board = Board(tmp_path)
    thread = board.read(7)
    assert thread["kind"] == "assignment"
    assert thread["revision"] == 12
    assert [p["kind"] for p in thread["posts"]] == ["brief", "status", "message"]
    assert [p["id"] for p in thread["posts"]] == [10, 11, 12]
    assert set(thread["participants"]) == {"codex", "claude"}

    with sqlite3.connect(db_path) as check:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 2


def test_discussion_request_broadcast_and_inbox(tmp_path: Path) -> None:
    board = Board(tmp_path)

    disc = board.open_thread(
        kind="discussion",
        title="Sync protocol design",
        body="Should we use monotonic revisions?",
        author="codex",
        to=["claude", "gemini"],
        channel="architecture_rfc",
        priority="high",
        refs=["memory:dec-sync-1"],
        payload={"options": ["monotonic_rev", "etag"]},
    )
    assert disc["kind"] == "discussion"
    assert disc["status"] == "open"

    reply = board.post(
        disc["id"],
        author="claude",
        kind="answer",
        message="Monotonic revisions are simpler.",
        reply_to=disc["post_id"],
        to=["codex"],
        refs=["gm/board.py:1"],
    )
    assert reply["kind"] == "answer"

    # Cross-thread reply_to is rejected
    req = board.open_thread(
        kind="request",
        title="Review schema",
        body="Please review the SQLite migration.",
        author="codex",
        to=["antigravity"],
    )
    with pytest.raises(ValueError, match="not found in thread"):
        board.post(req["id"], author="antigravity", message="Wrong thread", reply_to=disc["post_id"])

    # Only recipient can accept/decline request
    with pytest.raises(ValueError, match="Only a recipient"):
        board.post(req["id"], author="codex", status="in_progress")
    board.post(req["id"], author="antigravity", status="in_progress")
    board.post(req["id"], author="antigravity", status="resolved", message="Looks solid.")

    # Broadcast reaches everyone's inbox until acked
    bcast = board.open_thread(
        kind="broadcast",
        title="Index schema bumped",
        body="All sessions should reload context.",
        author="codex",
    )
    inbox_gemini = board.inbox("gemini")
    assert {t["id"] for t in inbox_gemini["threads"]} == {disc["id"], bcast["id"]}
    bcast_entry = next(t for t in inbox_gemini["threads"] if t["id"] == bcast["id"])
    assert "unacked_broadcast" in bcast_entry["attention_reasons"]

    board.ack(bcast["id"], actor="gemini", message="Noted", post_ack=True)
    board.read(disc["id"], actor="gemini", mark_read=True)
    assert board.inbox("gemini")["threads"] == []


def test_concurrency_expected_revision_idempotency_and_wait(tmp_path: Path) -> None:
    board = Board(tmp_path)
    t = board.open_thread(kind="discussion", title="Locking", body="Start", author="agent-a", to=["agent-b"])
    rev1 = t["post_id"]

    # Idempotency deduplicates retries
    p1 = board.post(t["id"], author="agent-a", message="Check once", idempotency_key="retry-1")
    p2 = board.post(t["id"], author="agent-a", message="Check once", idempotency_key="retry-1")
    assert p1["post_id"] == p2["post_id"]
    assert p2.get("deduplicated") is True

    # expected_revision rejects stale writes
    with pytest.raises(ValueError, match="changed"):
        board.post(t["id"], author="agent-b", message="Stale", expected_revision=rev1)
    board.post(t["id"], author="agent-b", message="Fresh", expected_revision=p1["post_id"])

    # wait() wakes when another thread posts
    current_rev = board.list()["revision"]
    timed_out = board.wait(actor="agent-a", since_rev=current_rev, timeout=0.05)
    assert timed_out["timed_out"] is True

    def delayed_post() -> None:
        time.sleep(0.15)
        Board(tmp_path).post(t["id"], author="agent-b", message="Wake up!")

    worker = threading.Thread(target=delayed_post)
    worker.start()
    woke = board.wait(actor="agent-a", since_rev=current_rev, timeout=2.0)
    worker.join()
    assert woke["timed_out"] is False
    assert woke["revision"] > current_rev


def test_presence_cli_mcp_desktop_and_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GM_HOME", str(tmp_path))
    cli = ["--home", str(tmp_path), "board"]

    assert main([*cli, "register", "--as", "codex/main", "--harness", "codex", "--project", "gm",
                 "--status", "active", "--summary", "Reviewing protocol", "--capabilities", "review,test", "--json"]) == 0
    reg = json.loads(capsys.readouterr().out)
    assert reg["actor"] == "codex/main"

    assert main([*cli, "open", "API check", "--by", "codex/main", "--kind", "request",
                 "--to", "pi/build", "--body", "Check CLI flags", "--channel", "cli", "--json"]) == 0
    opened = json.loads(capsys.readouterr().out)

    assert main([*cli, "inbox", "--for", "pi/build", "--json"]) == 0
    inbox = json.loads(capsys.readouterr().out)
    assert len(inbox["threads"]) == 1

    # MCP brain_board tool works end-to-end
    mcp_res = json.loads(brain_board(action="post", thread_id=opened["id"], actor="pi/build",
                                     message="Flags look good.", message_kind="answer", status="resolved"))
    assert mcp_res["status"] == "resolved"

    who_res = json.loads(brain_board(action="who"))
    assert [a["actor"] for a in who_res["agents"]] == ["codex/main"]

    # Desktop RPC endpoints
    desktop = Desktop(tmp_path)
    open_d = desktop.request("board_open", {
        "kind": "discussion",
        "title": "Desktop thread",
        "author": "codex/main",
        "to": "pi/build",
        "body": "Active topic",
    })
    assert desktop.request("board_inbox", {"actor": "pi/build"})["unread_total"] >= 1
    desktop.request("board_ack", {"id": open_d["id"], "actor": "pi/build"})
    assert desktop.request("board_agents", {})["agents"][0]["actor"] == "codex/main"

    # build_context surfaces active board threads
    ctx = build_context(tmp_path)
    assert "Active Board Threads" in ctx
    assert "Desktop thread" in ctx


def test_review_regressions(tmp_path: Path) -> None:
    board = Board(tmp_path)

    # 1. Supervisor is not nagged on their own newly assigned or in_progress task
    task = board.assign(title="Build feature", brief="Implement it.", supervisor="lead", assignee="worker")
    assert board.inbox("lead")["threads"] == []
    board.post(task["id"], author="worker", status="in_progress")
    board.read(task["id"], actor="lead", mark_read=True)
    assert board.inbox("lead")["threads"] == []
    # Supervisor IS nagged once submitted for review
    board.post(task["id"], author="worker", status="in_review", message="Ready for review")
    lead_inbox = board.inbox("lead")
    assert len(lead_inbox["threads"]) == 1
    assert any(r.startswith("action:") for r in lead_inbox["threads"][0]["attention_reasons"])

    # 2. Broadcaster is not nagged on their own open broadcast
    bcast = board.open_thread(kind="broadcast", title="Heads up", body="Maintenance soon.", author="lead")
    assert not any(t["id"] == bcast["id"] for t in board.inbox("lead")["threads"])

    # 3. Empty-body discussion advances revision >= 1
    before_rev = board.list()["revision"]
    empty_disc = board.open_thread(kind="discussion", title="Quick sync", author="lead", to=["worker"])
    assert empty_disc["post_id"] > before_rev
    assert board.list()["revision"] > before_rev

    # 4. post(..., kind="ack") works with empty message and updates acked_id
    ack_post = board.post(bcast["id"], author="worker", kind="ack")
    assert ack_post["kind"] == "ack"
    thread_state = board.read(bcast["id"])
    worker_role = next(p for p in thread_state["participant_roles"] if p["actor"] == "worker")
    assert worker_role["acked_id"] >= ack_post["post_id"]

    # 5. read(mark_read=True) immediately reflects updated last_read_id in response
    read_after = board.read(empty_disc["id"], actor="worker", mark_read=True)
    worker_disc = next(p for p in read_after["participant_roles"] if p["actor"] == "worker")
    assert worker_disc["last_read_id"] == empty_disc["post_id"]

    # 6. heartbeat() returns merged stored fields on status-only updates
    board.heartbeat(actor="codex", harness="codex", project="gm", summary="Reviewing", capabilities=["review"])
    updated_hb = board.heartbeat(actor="codex", status="busy")
    assert updated_hb["harness"] == "codex"
    assert updated_hb["project"] == "gm"
    assert updated_hb["summary"] == "Reviewing"
    assert updated_hb["capabilities"] == ["review"]
    assert updated_hb["status"] == "busy"

    # 7. open_thread() idempotency returns stored thread kind
    first = board.open_thread(kind="request", title="Check", body="Body", author="lead", to=["worker"], idempotency_key="open-1")
    dup = board.open_thread(kind="discussion", title="Check", body="Body", author="lead", to=["worker"], idempotency_key="open-1")
    assert dup["deduplicated"] is True
    assert dup["id"] == first["id"]
    assert dup["kind"] == "request"

    # 8. Desktop board_post rejects boolean reply_to
    desktop = Desktop(tmp_path)
    with pytest.raises(ValueError, match="reply_to"):
        desktop.request("board_post", {"id": empty_disc["id"], "author": "worker", "message": "hi", "reply_to": True})



def test_post_does_not_hide_unread_handoff(tmp_path: Path) -> None:
    board = Board(tmp_path)
    thread = board.open_thread(kind="request", title="Review", body="Please review", author="pi", to=["codex"])
    board.post(thread["id"], author="codex", message="Will take a look")
    inbox = board.inbox("codex")
    assert inbox["threads"][0]["unread_count"] == 1
    assert "handoff" in inbox["threads"][0]["attention_reasons"]
    board.read(thread["id"], actor="codex", mark_read=True)
    assert board.inbox("codex", unread_only=False)["threads"][0]["unread_count"] == 0


def test_mcp_board_read_ack_and_presence_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_HOME", str(tmp_path))
    board = Board(tmp_path)
    thread = board.open_thread(kind="discussion", title="Cross interface", body="First", author="alice", to=["bob"])
    second = board.post(thread["id"], author="alice", message="Second")
    result = json.loads(brain_board(action="read", thread_id=thread["id"], since_post_id=thread["post_id"]))
    assert [p["id"] for p in result["posts"]] == [second["post_id"]]
    json.loads(brain_board(action="ack", thread_id=thread["id"], actor="bob", up_to_post_id=thread["post_id"]))
    inbox = json.loads(brain_board(action="inbox", actor="bob", unread_only=False))
    assert inbox["threads"][0]["unread_count"] == 1
    json.loads(brain_board(action="register", actor="bob", harness="codex", status="offline"))
    who = json.loads(brain_board(action="who", include_offline=True))
    assert who["agents"][0]["harness"] == "codex"


def test_concurrent_first_connections_migrate_legacy_once(tmp_path: Path) -> None:
    path = tmp_path / '.gm' / 'board.sqlite'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript('''
          CREATE TABLE assignments (id INTEGER PRIMARY KEY, title TEXT NOT NULL, project TEXT NOT NULL DEFAULT '', supervisor TEXT NOT NULL, assignee TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE board_posts (id INTEGER PRIMARY KEY, assignment_id INTEGER NOT NULL REFERENCES assignments(id), author TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
          INSERT INTO assignments VALUES (1, 'Legacy', '', 'a', 'b', 'assigned', '2026-01-01T00:00:00Z');
          INSERT INTO board_posts VALUES (1, 1, 'a', 'Brief', 'assigned', '2026-01-01T00:00:00Z');
        ''')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: Board(tmp_path).read(1), range(4)))
    assert all(row['posts'][0]['message'] == 'Brief' for row in results)
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 1


def test_legacy_migration_rolls_back_schema_on_failure(tmp_path: Path) -> None:
    path = tmp_path / '.gm' / 'board.sqlite'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript('''
          CREATE TABLE assignments (id INTEGER PRIMARY KEY, title TEXT NOT NULL, project TEXT NOT NULL DEFAULT '', supervisor TEXT NOT NULL, assignee TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE board_posts (id INTEGER PRIMARY KEY, assignment_id INTEGER NOT NULL, author TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
          INSERT INTO board_posts VALUES (1, 999, 'a', 'Orphan', '', '2026-01-01T00:00:00Z');
        ''')
    with pytest.raises(sqlite3.IntegrityError):
        Board(tmp_path).list()
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 0
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'assignments' in tables and 'board_posts' in tables
        assert 'threads' not in tables and 'messages' not in tables


def test_open_thread_idempotency_does_not_collide_with_reply_key(tmp_path: Path) -> None:
    board = Board(tmp_path)
    t1 = board.open_thread(kind="discussion", title="Thread One", body="Init", author="lead", to=["worker"])
    board.post(t1["id"], author="lead", message="Reply with shared key", idempotency_key="step-1")

    t2 = board.open_thread(kind="discussion", title="Thread Two", body="Fresh", author="lead", to=["worker"], idempotency_key="step-1")
    assert t2["id"] != t1["id"]
    assert "deduplicated" not in t2

    t2_dup = board.open_thread(kind="discussion", title="Thread Two", body="Fresh", author="lead", to=["worker"], idempotency_key="step-1")
    assert t2_dup["deduplicated"] is True
    assert t2_dup["id"] == t2["id"]
