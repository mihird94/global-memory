from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gm.board import Board
from gm.cli import main
from gm.desktop import Desktop


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
