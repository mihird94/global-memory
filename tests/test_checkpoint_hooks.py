import json
import sqlite3

from gm.checkpoint import pending, save
from gm.checkpoint_hooks import codex_event


def test_codex_prompt_and_stop_are_deduplicated_without_storing_prompt(tmp_path, monkeypatch):
    import gm.index
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    payload = {"session_id": "session-1", "turn_id": "turn-1", "hook_event_name": "UserPromptSubmit", "prompt": "Remember my secret example preference"}
    output = codex_event(payload, surface="codex-cli", root=tmp_path)
    rows = pending(tmp_path, harness="codex", session="session-1")
    assert len(rows) == 1 and rows[0]["trigger"] == "explicit_request"
    assert rows[0]["id"] in json.dumps(output)
    codex_event({**payload, "hook_event_name": "Stop"}, surface="codex-cli", root=tmp_path)
    save(tmp_path, rows[0]["id"], content="An example preference", title="Example")
    codex_event({**payload, "hook_event_name": "Stop"}, surface="codex-cli", root=tmp_path)
    assert pending(tmp_path, harness="codex", session="session-1") == []
    with sqlite3.connect(tmp_path / ".gm/checkpoints.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM hook_deliveries").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 1
    assert b"secret example preference" not in (tmp_path / ".gm/checkpoints.sqlite3").read_bytes()


def test_codex_stop_without_turn_is_not_recorded_as_skip(tmp_path):
    assert codex_event({"session_id": "s1", "hook_event_name": "Stop"}, surface="codex-cli", root=tmp_path) == {}
    assert not (tmp_path / ".gm/checkpoints.sqlite3").exists()


def test_generated_codex_hook_runs_in_isolated_store(tmp_path):
    import subprocess
    import sys
    from gm.checkpoint_hooks import codex_config
    root = tmp_path / "pilot store"
    config = codex_config(surface="codex-cli", root=root, python=sys.executable)
    command = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    payload = {"session_id": "s1", "turn_id": "t1", "hook_event_name": "UserPromptSubmit", "prompt": "Remember this fact"}
    result = subprocess.run(command, shell=True, input=json.dumps(payload), text=True, capture_output=True, check=True)
    assert "checkpoint" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(pending(root, harness="codex", session="s1")) == 1


def test_antigravity_stop_requires_normal_completion_and_idle(tmp_path):
    from gm.checkpoint_hooks import antigravity_event
    common = {"conversationId": "c-1", "executionNum": 4, "lastUserInput": "Remember a synthetic preference"}
    for extra in ({"terminationReason": "error", "fullyIdle": True}, {"terminationReason": "model_stop", "fullyIdle": False}):
        assert antigravity_event({**common, **extra}, event="Stop", surface="antigravity-cli", root=tmp_path) == {"decision": "allow"}
    assert pending(tmp_path, harness="antigravity", session="c-1") == []
    normal = {**common, "terminationReason": "model_stop", "fullyIdle": True}
    for _ in range(2):
        antigravity_event(normal, event="Stop", surface="antigravity-cli", root=tmp_path)
    rows = pending(tmp_path, harness="antigravity", session="c-1")
    assert len(rows) == 1 and rows[0]["trigger"] == "explicit_request"


def test_observed_antigravity_cli_success_reason(tmp_path):
    from gm.checkpoint_hooks import antigravity_event
    payload = {"conversationId": "c-2", "executionNum": 0, "terminationReason": "NO_TOOL_CALL", "fullyIdle": True}
    antigravity_event(payload, event="Stop", surface="antigravity-cli", root=tmp_path)
    assert len(pending(tmp_path, harness="antigravity", session="c-2")) == 1


def test_clients_without_native_turn_id_keep_pending_and_dedupe_stop(tmp_path):
    from gm.checkpoint_hooks import standard_event
    for surface, harness, start, stop in (("claude-cli", "claude", "UserPromptSubmit", "Stop"), ("gemini-cli", "gemini", "BeforeAgent", "AfterAgent")):
        common = {"session_id": "session-" + harness}
        result = standard_event({**common, "hook_event_name": start, "prompt": "Remember this synthetic fact"}, surface=surface, root=tmp_path)
        rows = pending(tmp_path, harness=harness, session=common["session_id"])
        assert len(rows) == 1 and rows[0]["id"] in json.dumps(result)
        for retry in (False, True):
            standard_event({**common, "hook_event_name": stop, "stop_hook_active": retry}, surface=surface, root=tmp_path)
        assert len(pending(tmp_path, harness=harness, session=common["session_id"])) == 1


def test_antigravity_reminder_keeps_one_checkpoint_across_model_callbacks(tmp_path):
    from gm.checkpoint_hooks import antigravity_event
    common = {"conversationId": "c-reminder", "lastUserInput": "Remember the synthetic color"}
    scope = {"surface": "antigravity-cli", "root": tmp_path, "reminder": True}
    start = {**common, "invocationNum": 0, "initialNumSteps": 1}
    stop = {**common, "executionNum": 0, "terminationReason": "NO_TOOL_CALL", "fullyIdle": True}
    assert antigravity_event(start, event="PreInvocation", **scope)["injectSteps"]
    assert antigravity_event(stop, event="Stop", **scope)["decision"] == "continue"
    assert antigravity_event(stop, event="Stop", **scope)["decision"] == "allow"
    assert antigravity_event({**start, "invocationNum": 1, "initialNumSteps": 4}, event="PreInvocation", **scope) == {}
    assert antigravity_event({**stop, "executionNum": 1}, event="Stop", **scope)["decision"] == "allow"
    rows = pending(tmp_path, harness="antigravity", session="c-reminder")
    assert len(rows) == 1 and rows[0]["turn"] == "trajectory-1"


def test_gemini_headless_wrapping_keeps_the_user_request(tmp_path):
    from gm.checkpoint_hooks import standard_event
    context = "<hook_context>[brain-checkpoint-startup]\nBrain summary\n[/brain-checkpoint-startup]</hook_context>"
    event = {"session_id": "s1", "hook_event_name": "BeforeAgent", "timestamp": "2026-11-26T00:00:00.000Z",
             "prompt": context + "\n\nRemember my synthetic preference."}
    scope = {"surface": "gemini-cli", "root": tmp_path}
    assert standard_event(event, **scope) == standard_event(event, **scope)
    rows = pending(tmp_path, harness="gemini", session="s1")
    assert len(rows) == 1 and rows[0]["trigger"] == "explicit_request"


def test_hook_store_failure_allows_turn_without_saved_receipt(tmp_path):
    import os
    import subprocess
    import sys

    bad_home = tmp_path / "unavailable"
    bad_home.write_text("not a directory")
    payload = {"session_id": "s1", "turn_id": "t1", "hook_event_name": "UserPromptSubmit",
               "prompt": "Remember this synthetic fact"}
    result = subprocess.run(
        [sys.executable, "-m", "gm.checkpoint_hooks", "--surface", "codex-cli"],
        input=json.dumps(payload), text=True, capture_output=True, check=True, timeout=3,
        env={**os.environ, "GM_CHECKPOINT_PILOT": "1", "GM_HOME": str(bad_home)},
    )
    assert json.loads(result.stdout) == {"systemMessage": "Brain checkpoint hook could not record this event."}
    assert bad_home.is_file()


def test_antigravity_stop_fallback_reminder_binds_next_preinvocation(tmp_path):
    from gm.checkpoint_hooks import antigravity_event
    scope = {"surface": "antigravity-cli", "root": tmp_path, "reminder": True}
    boot = antigravity_event({"conversationId": "c-fb", "source": "resume"}, event="SessionStart", surface="antigravity-cli", root=tmp_path)
    assert "injectSteps" in boot
    with sqlite3.connect(tmp_path / ".gm/checkpoints.sqlite3") as db:
        turns = db.execute("SELECT turn FROM hook_deliveries WHERE event='SessionStart' AND session='c-fb'").fetchall()
    assert turns == [("session-resume",)]

    stop1 = {"conversationId": "c-fb", "executionNum": 2, "lastUserInput": "Remember fallback color",
             "terminationReason": "NO_TOOL_CALL", "fullyIdle": True}
    assert antigravity_event(stop1, event="Stop", **scope)["decision"] == "continue"
    pre = {"conversationId": "c-fb", "invocationNum": 0, "initialNumSteps": 3, "lastUserInput": "Remember fallback color"}
    assert antigravity_event(pre, event="PreInvocation", **scope) == {}
    stop2 = {"conversationId": "c-fb", "executionNum": 3, "lastUserInput": "Remember fallback color",
             "terminationReason": "NO_TOOL_CALL", "fullyIdle": True}
    assert antigravity_event(stop2, event="Stop", **scope)["decision"] == "allow"
    rows = pending(tmp_path, harness="antigravity", session="c-fb")
    assert len(rows) == 1 and rows[0]["turn"] == "execution-2"
