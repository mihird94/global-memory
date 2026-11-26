"""Opt-in, fail-open client hooks for the checkpoint pilot.

Hook payloads are never persisted. Only explicit event identifiers and bounded
metadata enter the ledger. Unsupported or absent identities remain unobserved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys

from .checkpoint import observe, pending, record_delivery
from .store import gm_home

_REMEMBER = re.compile(r"^\s*(?:please\s+)?(?:remember|memorize|store (?:this|that|the following) (?:in|to) (?:brain|memory)|save (?:this|that|the following) (?:in|to) (?:brain|memory))\b", re.I)
_GEMINI_CONTEXT_END = "[/brain-checkpoint-startup]"
_START_SOURCES = {"startup", "resume", "compact", "clear", "fork", "new", "reload"}


def boot_turn(payload: dict) -> str:
    reason = payload.get("source")
    return f"session-{reason}" if isinstance(reason, str) and reason in _START_SOURCES else "session"


def codex_config(*, surface: str, root, python: str = sys.executable) -> dict:
    """Produce opt-in hooks.json content without changing client configuration."""
    if surface not in ("codex-cli", "codex-desktop"):
        raise ValueError("invalid Codex surface")
    command = shlex.join(["env", "GM_CHECKPOINT_PILOT=1", f"GM_HOME={root}", python,
                          "-m", "gm.checkpoint_hooks", "--surface", surface])
    handler = {"type": "command", "command": command, "timeout": 2}
    return {"hooks": {event: [{"hooks": [handler.copy()]}] for event in
                      ("SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "PostCompact", "Interrupt")}}


def antigravity_config(*, surface: str, root, python: str = sys.executable, reminder: bool = False) -> dict:
    if surface not in ("antigravity-cli", "antigravity-desktop", "antigravity-ide"):
        raise ValueError("invalid Antigravity surface")
    def handler(event: str) -> dict:
        args = ["env", "GM_CHECKPOINT_PILOT=1", f"GM_HOME={root}", python,
                "-m", "gm.checkpoint_hooks", "--surface", surface, "--event", event]
        if reminder:
            args.append("--reminder")
        command = shlex.join(args)
        return {"type": "command", "command": command, "timeout": 3}
    return {"brain-checkpoint-pilot": {event: [handler(event)] for event in ("SessionStart", "PreInvocation", "Stop")}}


def antigravity_event(payload: dict, *, event: str, surface: str, root, reminder: bool = False) -> dict:
    """Observe Antigravity, with an optional reminder after a verified idle stop."""
    from .checkpoint import claim_reminder, has_turn, reminder_callback, session_turn
    if surface not in ("antigravity-cli", "antigravity-desktop", "antigravity-ide"):
        raise ValueError("invalid Antigravity surface")
    session = payload.get("conversationId", "")
    if not session or event not in ("SessionStart", "PreInvocation", "Stop"):
        return {}
    if event == "SessionStart":
        record_delivery(root, surface=surface, harness="antigravity", session=session, turn=boot_turn(payload), event=event)
        from .index import build_context
        paths = payload.get("workspacePaths", [])
        cwd = paths[0] if isinstance(paths, list) and paths and isinstance(paths[0], str) else ""
        context = build_context(root, cwd=cwd, compact=True)
        entries = pending(root, harness="antigravity", session=session)
        if entries:
            context += "\nPending checkpoint IDs: " + ", ".join(item["id"] for item in entries)
        return {"injectSteps": [{"systemMessage": {"systemMessage": context}}]}
    if event == "PreInvocation":
        scope = dict(surface=surface, harness="antigravity", session=session)
        current = session_turn(root, **scope)
        if reminder and reminder_callback(root, **scope, turn=current, start=True):
            record_delivery(root, **scope, turn=current, event="ReminderInvocation")
            return {}
        initial_steps = payload.get("initialNumSteps")
        # CLI 1.5.16 supplies the initial trajectory length and resets the
        # invocation counter for each execution. Inject once at its first call.
        if payload.get("invocationNum") != 0 or type(initial_steps) is not int or initial_steps < 0:
            return {}
        turn = session_turn(root, **scope, begin=True, native_id=f"trajectory-{initial_steps}")
        record_delivery(root, **scope, turn=turn, event=event)
        explicit = bool(_REMEMBER.search(str(payload.get("lastUserInput", ""))))
        output = review_context(root, **scope, turn=turn, event=event, explicit=explicit)
        if output:
            return {"injectSteps": [{"systemMessage": {"systemMessage":
                    output["hookSpecificOutput"]["additionalContext"]}}]}
        return {}
    execution = payload.get("executionNum")
    if not isinstance(execution, int) or isinstance(execution, bool) or execution < 0:
        return {"decision": "allow"}
    tracked_turn = session_turn(root, surface=surface, harness="antigravity", session=session)
    turn = tracked_turn or f"execution-{execution}"
    record_delivery(root, surface=surface, harness="antigravity", session=session, turn=turn, event=event)
    if reminder and reminder_callback(root, surface=surface, harness="antigravity", session=session, turn=turn, start=False):
        return {"decision": "allow"}
    # An error, cancellation, or running background work isn't a normal completion.
    # CLI 1.5.16 reports NO_TOOL_CALL for a successful final answer; the
    # published schema also describes model_stop on other surfaces.
    if payload.get("terminationReason") in {"model_stop", "NO_TOOL_CALL"} and payload.get("fullyIdle") is True:
        trigger = "explicit_request" if _REMEMBER.search(str(payload.get("lastUserInput", ""))) else "review"
        if not has_turn(root, surface=surface, harness="antigravity", session=session, turn=turn):
            observe(root, surface=surface, harness="antigravity", session=session, turn=turn, trigger=trigger)
        if reminder:
            for item in pending(root, harness="antigravity", session=session):
                if item["turn"] == turn and item["surface"] == surface and claim_reminder(root, item["id"]):
                    if not tracked_turn:
                        session_turn(root, surface=surface, harness="antigravity", session=session, begin=True, native_id=turn)
                    return {"decision": "continue", "reason":
                            f"Resolve explicit Brain checkpoint {item['id']} using the configured pilot tool. "
                            "If it is unavailable, finish and leave the checkpoint pending."}
    return {"decision": "allow"}


def standard_config(*, surface: str, root, python: str = sys.executable) -> dict:
    if surface not in ("claude-cli", "gemini-cli"):
        raise ValueError("invalid client surface")
    events = (("SessionStart", "UserPromptSubmit", "Stop", "PreCompact") if surface == "claude-cli"
              else ("SessionStart", "BeforeAgent", "AfterAgent", "PreCompress"))
    command = shlex.join(["env", "GM_CHECKPOINT_PILOT=1", f"GM_HOME={root}", python,
                          "-m", "gm.checkpoint_hooks", "--surface", surface])
    timeout = 3000 if surface == "gemini-cli" else 3
    return {"hooks": {event: [{"hooks": [{"type": "command", "command": command, "timeout": timeout}]}]
                      for event in events}}


def standard_event(payload: dict, *, surface: str, root, reminder: bool = False) -> dict:
    """Observe Claude/Gemini events where the client does not expose turn IDs."""
    from .checkpoint import claim_reminder, has_turn, reminder_callback, session_turn
    if surface not in ("claude-cli", "gemini-cli", "pi-cli"):
        raise ValueError("invalid client surface")
    harness = surface.split("-")[0]
    event, session = payload.get("hook_event_name", ""), payload.get("session_id", "")
    boot, start_event, end_event = {
        "claude": ("SessionStart", "UserPromptSubmit", "Stop"),
        "gemini": ("SessionStart", "BeforeAgent", "AfterAgent"),
        "pi": ("session_start", "before_agent_start", "agent_before_settle"),
    }[harness]
    if not session or event not in (boot, start_event, end_event, "PreCompact", "PreCompress",
                                    "session_before_compact", "agent_settled"):
        return {}
    if event == boot:
        record_delivery(root, surface=surface, harness=harness, session=session, turn=boot_turn(payload), event=event)
        from .index import build_context
        context = build_context(root, cwd=str(payload.get("cwd", "")), compact=True)
        entries = pending(root, harness=harness, session=session)
        if entries:
            context += "\nPending checkpoint IDs: " + ", ".join(item["id"] for item in entries)
        if harness == "gemini":
            # Gemini headless prepends this output before firing BeforeAgent.
            context = f"[brain-checkpoint-startup]\n{context}\n{_GEMINI_CONTEXT_END}"
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    if event == start_event:
        native = payload.get("turn_id") or payload.get("timestamp")
        identifier = hashlib.sha256(native.encode()).hexdigest()[:32] if isinstance(native, str) and native else ""
        turn = session_turn(root, surface=surface, harness=harness, session=session,
                            begin=True, native_id=identifier)
        record_delivery(root, surface=surface, harness=harness, session=session, turn=turn, event=event)
        prompt = str(payload.get("prompt", ""))
        if harness == "gemini" and prompt.startswith("<hook_context>[brain-checkpoint-startup]"):
            _, delimiter, user_prompt = prompt.partition(_GEMINI_CONTEXT_END + "</hook_context>")
            if delimiter:
                prompt = user_prompt
        explicit = bool(_REMEMBER.search(prompt))
        return review_context(root, surface=surface, harness=harness, session=session,
                              turn=turn, event=event, explicit=explicit)
    turn = session_turn(root, surface=surface, harness=harness, session=session)
    if not turn:
        return {}
    record_delivery(root, surface=surface, harness=harness, session=session, turn=turn, event=event)
    if event == end_event and not has_turn(root, surface=surface, harness=harness, session=session, turn=turn):
        observe(root, surface=surface, harness=harness, session=session, turn=turn, trigger="review")
    if harness == "pi":
        scope = dict(surface=surface, harness=harness, session=session, turn=turn)
        if event == "agent_settled":
            reminder_callback(root, **scope, start=False)
        if event == end_event and reminder and payload.get("can_continue") is True:
            for item in pending(root, harness=harness, session=session):
                if item["turn"] == turn and claim_reminder(root, item["id"]):
                    reminder_callback(root, **scope, start=True)
                    return {"reminder": f"Resolve pending Brain checkpoint {item['id']} with the pilot tool. "
                            "If the tool is unavailable, finish with the checkpoint pending."}
    return {}


def review_context(root, *, surface: str, harness: str, session: str, turn: str,
                   event: str, explicit: bool) -> dict:
    trigger = "explicit_request" if explicit else "review"
    item = observe(root, surface=surface, harness=harness, session=session, turn=turn, trigger=trigger)
    if item["outcome"] != "pending":
        return {}
    context = "Explicit memory request. " if explicit else "At completion, review for a durable memory. "
    context += (f"Checkpoint ID: {item['id']}. Use brain_checkpoint_save for a verified fact, decision, "
                "lesson, project update, or milestone. Otherwise use brain_checkpoint_skip with a bounded reason.")
    earlier = [row["id"] for row in pending(root, harness=harness, session=session) if row["turn"] != turn]
    if earlier:
        context += "\nEarlier pending checkpoint IDs: " + ", ".join(earlier[-8:])
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def codex_event(payload: dict, *, surface: str, root) -> dict:
    """Handle Codex hooks; never request a continuation in observation mode."""
    if surface not in ("codex-cli", "codex-desktop"):
        raise ValueError("invalid Codex surface")
    event = payload.get("hook_event_name", "")
    session = payload.get("session_id", "")
    turn = payload.get("turn_id", "")
    if event not in {"SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "PostCompact", "Interrupt"} or not session:
        return {}
    # SessionStart has no turn identifier. A stable synthetic identifier is used
    # solely for delivery, never as a turn checkpoint.
    if event == "SessionStart":
        record_delivery(root, surface=surface, harness="codex", session=session, turn=boot_turn(payload), event=event)
        from .index import build_context
        entries = pending(root, harness="codex", session=session)
        context = build_context(root, cwd=str(payload.get("cwd", "")), compact=True)
        ids = ", ".join(item["id"] for item in entries)
        if ids:
            context += "\nPending checkpoint IDs: " + ids
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    if not turn:
        return {}
    record_delivery(root, surface=surface, harness="codex", session=session, turn=turn, event=event)
    if event == "UserPromptSubmit":
        explicit = bool(_REMEMBER.search(str(payload.get("prompt", ""))))
        return review_context(root, surface=surface, harness="codex", session=session,
                              turn=turn, event=event, explicit=explicit)
    if event == "Stop":
        entries = pending(root, harness="codex", session=session)
        if not any(item["turn"] == turn and item["surface"] == surface for item in entries):
            # Do not create a second checkpoint after this turn was already resolved.
            from .checkpoint import has_turn
            if not has_turn(root, surface=surface, harness="codex", session=session, turn=turn):
                observe(root, surface=surface, harness="codex", session=session, turn=turn, trigger="review")
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=("codex-cli", "codex-desktop", "antigravity-cli", "antigravity-desktop", "antigravity-ide", "claude-cli", "gemini-cli", "pi-cli"), required=True)
    parser.add_argument("--event", default="")
    parser.add_argument("--reminder", action="store_true")
    args = parser.parse_args(argv)
    # Hooks are usable only when explicitly enabled and pointed at a pilot store.
    if os.environ.get("GM_CHECKPOINT_PILOT") != "1" or not os.environ.get("GM_HOME"):
        print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            result = {}
        elif args.surface.startswith("codex-"):
            result = codex_event(payload, surface=args.surface, root=gm_home())
        elif args.surface.startswith("antigravity-"):
            result = antigravity_event(payload, event=args.event, surface=args.surface, root=gm_home(),
                                       reminder=args.reminder)
        else:
            result = standard_event(payload, surface=args.surface, root=gm_home(), reminder=args.reminder)
    except Exception:
        # Failure is observable to the client but never blocks a task or leaks input.
        if args.surface.startswith("antigravity-"):
            print(json.dumps({"decision": "allow"} if args.event == "Stop" else {}))
        else:
            print(json.dumps({"systemMessage": "Brain checkpoint hook could not record this event."}))
        return 0
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
