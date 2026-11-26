"""Run installed Pi, Claude Code, Gemini CLI, and isolated OpenCode CLI against a synthetic local model."""

from contextlib import closing
import argparse
from http.server import HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading

from gm.checkpoint_hooks import standard_config
from gm.export import init_bundle, list_inbox_proposals, promote_inbox_proposal
from gm.screening import PrivacyScreener
from smoke_provider import SmokeProvider

REPO = Path(__file__).resolve().parents[2]
PROMPT = "Remember the synthetic checkpoint pilot preference: the color is teal."
CASES = {
    "remember": (PROMPT, "brain_checkpoint_save", "explicit_request", "saved", "fact", None),
    "lesson": ("A synthetic test proved the previous empty input path crashed and the guard fixed it.",
               "brain_checkpoint_save", "review", "saved", "lesson",
               {"kind": "lesson", "title": "Handle empty pilot input",
                "content": "Empty input crashed. A guard fixed it and the synthetic regression test passed.",
                "source": "test_pilot_empty_input.py"}),
    "unverified": ("The synthetic failure may come from an empty input. This is an unverified hypothesis.",
                   "brain_checkpoint_skip", "review", "skipped", "", {"reason": "unverified"}),
    "trivial": ("Treat this as a synthetic whitespace-only edit with no durable information.",
                "brain_checkpoint_skip", "review", "skipped", "", {"reason": "no_durable_information"}),
}
EVENTS = {
    "pi": {"session_start", "before_agent_start", "agent_before_settle"},
    "claude": {"SessionStart", "UserPromptSubmit", "Stop"},
    "gemini": {"SessionStart", "BeforeAgent", "AfterAgent"},
    "opencode": set(),
}


def dump(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def client_command(client, base, endpoint, brain, *, prompt, tool, hooks):
    profile = base / "profile"
    profile.mkdir()
    env = {
        **os.environ, "GM_CHECKPOINT_PILOT": "1" if hooks else "0", "GM_CHECKPOINT_PYTHON": sys.executable,
        "GM_HOME": str(brain), "GM_NO_EMBED": "1", "GM_NO_RERANK": "1",
    }
    server = {
        "command": sys.executable, "args": ["-m", "gm.mcp_server"],
        "env": {"GM_HOME": str(brain), "GM_NO_EMBED": "1", "GM_NO_RERANK": "1"},
    }
    mcp_tool = "mcp__brain__" + tool
    if client == "opencode":
        bundle = base / "bundle"
        init_bundle(bundle, projects=["pilot"])
        for sub in ("config", "data", "state", "cache"):
            (profile / sub).mkdir()
        env.pop("GM_HOME", None)
        env.pop("GM_CHECKPOINT_PILOT", None)
        env.update(
            XDG_CONFIG_HOME=str(profile / "config"),
            XDG_DATA_HOME=str(profile / "data"),
            XDG_STATE_HOME=str(profile / "state"),
            XDG_CACHE_HOME=str(profile / "cache"),
            OPENCODE_CONFIG=str(base / "opencode.json"),
        )
        dump(base / "opencode.json", {
            "$schema": "https://opencode.ai/config.json",
            "provider": {"pilot": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Pilot Loopback",
                "options": {"baseURL": endpoint + "/v1", "apiKey": "synthetic"},
                "models": {"checkpoint-fixture": {"name": "Checkpoint Fixture"}},
            }},
            "mcp": {"brain-safe": {
                "type": "local",
                "command": [sys.executable, "-m", "gm.safe_mcp_server", "--bundle", str(bundle)],
                "enabled": True,
            }},
        })
        command = ["opencode", "run", "--pure", "-m", "pilot/checkpoint-fixture"]
    elif client == "pi":
        env.update(PI_CODING_AGENT_DIR=str(profile), PI_OFFLINE="1", PI_TELEMETRY="0")
        dump(profile / "models.json", {"providers": {"pilot": {
            "baseUrl": endpoint + "/v1", "api": "openai-completions", "apiKey": "synthetic",
            "models": [{"id": "checkpoint-fixture", "name": "Checkpoint Fixture"}],
        }}})
        dump(profile / "mcp.json", {"mcpServers": {"brain": {
            **server, "exposure": "direct",
        }}})
        command = ["pi", "--provider", "pilot", "--model", "checkpoint-fixture", "--no-session",
                   "--no-extensions", "--no-skills", "--no-context-files", "--no-builtin-tools",
                   "--extension", "builtin:mcp",
                   "--extension", str(REPO / "adapters/checkpoint/pi.ts"),
                   "--tools", mcp_tool, "-p"]
    elif client == "claude":
        env.update(CLAUDE_CONFIG_DIR=str(profile), ANTHROPIC_API_KEY="pilot-fixture",
                   ANTHROPIC_BASE_URL=endpoint, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        dump(base / "hooks.json", standard_config(surface="claude-cli", root=brain) if hooks else {})
        dump(base / "mcp.json", {"mcpServers": {"brain": server}})
        command = ["claude", "--setting-sources", "", "--settings", str(base / "hooks.json"),
                   "--strict-mcp-config", "--mcp-config", str(base / "mcp.json"),
                   "--allowedTools", mcp_tool, "--tools", "",
                   "--no-session-persistence", "--model", "sonnet", "-p"]
    else:
        env.update(GEMINI_CLI_HOME=str(profile), GEMINI_API_KEY="pilot-fixture",
                   GOOGLE_GEMINI_BASE_URL=endpoint, GEMINI_TELEMETRY_ENABLED="false")
        (profile / ".gemini").mkdir()
        dump(profile / ".gemini/settings.json", {
            **standard_config(surface="gemini-cli", root=brain),
            "hooksConfig": {"enabled": hooks},
            "security": {"auth": {"selectedType": "gemini-api-key"}},
            "mcpServers": {"brain": {**server, "trust": True, "includeTools": [tool]}},
        })
        command = ["gemini", "--skip-trust", "--allowed-mcp-server-names=brain",
                   "--model", "gemini-2.5-flash", "-p"]
    return [*command, prompt], env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", choices=EVENTS)
    parser.add_argument("--case", choices=CASES, default="remember")
    parser.add_argument("--steering-only", action="store_true",
                        help="Use ordinary memory steering and save, with checkpoint hooks disabled")
    parser.add_argument("--reminder", action="store_true", help="Exercise the one-continuation Pi path")
    parser.add_argument("--read-from", nargs=2, metavar=("PILOT_HOME", "MEMORY_ID"),
                        help="Read one synthetic note saved in another client's pilot store")
    args = parser.parse_args()
    client = args.client
    if args.steering_only and (args.read_from or args.case != "remember" or client == "opencode"):
        parser.error("the steering baseline applies only to trusted clients in the remember case")
    if args.reminder and (client != "pi" or args.steering_only or args.read_from or args.case != "remember"):
        parser.error("the reminder requires the Pi remember case")
    if client == "opencode" and (args.read_from or args.case != "remember"):
        parser.error("opencode smoke exercises the restricted safe_propose remember case")
    base = Path(tempfile.mkdtemp(prefix=f"brain-{client}-pilot-"))
    brain, read_note = (Path(args.read_from[0]).resolve(), args.read_from[1]) if args.read_from else (base / "brain", "")
    prompt, tool, trigger, expected, kind, fields = CASES[args.case]
    if client == "opencode":
        tool = "safe_propose"
    elif read_note:
        prompt, tool = f"Read this synthetic pilot note: {read_note}.", "brain_read"
    elif args.steering_only:
        prompt += " Use the ordinary brain_store tool to save that verified preference."
        tool = "brain_store"
    work = base / "work"
    work.mkdir()
    print(f"Pilot evidence: {base}", flush=True)
    with HTTPServer(("127.0.0.1", 0), SmokeProvider) as server:
        server.ledger = None if client == "opencode" else brain / ".gm/checkpoints.sqlite3"
        server.requests = []
        server.read_note = read_note
        server.action = tool
        server.wait_for_reminder = args.reminder
        if fields:
            server.fields = fields
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
        command, env = client_command(client, base, endpoint, brain, prompt=prompt, tool=tool,
                                      hooks=not (read_note or args.steering_only or client == "opencode"))
        env["GM_CHECKPOINT_REMINDER"] = "1" if args.reminder else "0"
        try:
            result = subprocess.run(command, env=env, cwd=work, timeout=45, capture_output=True,
                                    stdin=subprocess.DEVNULL)
        finally:
            server.shutdown()
    (base / "stdout.txt").write_bytes(result.stdout)
    (base / "stderr.txt").write_bytes(result.stderr)
    dump(base / "model-requests.json", server.requests)
    if client == "opencode":
        bundle = base / "bundle"
        sc = PrivacyScreener(deterministic_only=True)
        no_direct_write = not (brain / "notes").exists() and not (brain / ".gm" / "checkpoints.sqlite3").exists()
        os.environ["GM_NO_EMBED"] = "1"
        os.environ["GM_NO_RERANK"] = "1"
        pending_props = list_inbox_proposals(brain, bundle, screener=sc)
        promoted = None
        if len(pending_props) == 1:
            promoted = promote_inbox_proposal(brain, bundle, pending_props[0]["id"], screener=sc)
        remaining = list_inbox_proposals(brain, bundle, screener=sc)
        ok = (result.returncode == 0 and no_direct_write and len(pending_props) == 1
              and promoted is not None and (brain / promoted["rel_path"]).is_file()
              and "safe-inbox:" in (brain / promoted["rel_path"]).read_text() and len(remaining) == 0)
        print(json.dumps({
            "client": client, "case": "safe_propose", "exit": result.returncode,
            "no_direct_write": no_direct_write, "queued": len(pending_props),
            "promoted_doc_id": promoted["promoted_doc_id"] if promoted else "",
            "model_requests": len(server.requests), "pass": ok,
        }))
        raise SystemExit(0 if ok else 1)
    if read_note:
        ok = result.returncode == 0 and b"PILOT_READ_OK" in result.stdout
        print(json.dumps({"client": client, "cross_client_read": ok, "memory_id": read_note}))
        raise SystemExit(0 if ok else 1)
    if args.steering_only:
        note = brain / "notes/facts/checkpoint-pilot--color.md"
        ok = result.returncode == 0 and note.is_file() and not server.ledger.exists()
        print(json.dumps({"client": client, "baseline_pass": ok, "model_requests": len(server.requests)}))
        raise SystemExit(0 if ok else 1)
    if not server.ledger.exists():
        raise SystemExit(f"{client}: no hook delivery recorded (exit {result.returncode})")
    with closing(sqlite3.connect(server.ledger)) as db:
        events = {row[0] for row in db.execute("SELECT event FROM hook_deliveries")}
        outcomes = db.execute("SELECT trigger,outcome FROM checkpoints").fetchall()
        reason = (db.execute("SELECT reason FROM checkpoint_skips").fetchall()
                  if expected == "skipped" and outcomes == [(trigger, expected)] else [])
        has_reminders = db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_reminders'").fetchone()
        reminders = db.execute("SELECT phase FROM checkpoint_reminders").fetchall() if has_reminders else []
    notes = list((brain / "notes").glob("*/*.md"))
    note_count = int(bool(kind))
    evidence_ok = len(notes) == note_count and all(note.parent.name == f"{kind}s" for note in notes)
    if args.case == "lesson" and evidence_ok:
        evidence_ok = "source: test_pilot_empty_input.py" in notes[0].read_text()
    if expected == "skipped":
        evidence_ok = evidence_ok and reason == [(fields["reason"],)]
    print(json.dumps({"client": client, "case": args.case, "exit": result.returncode,
                      "events": sorted(events), "outcomes": outcomes, "notes": len(notes),
                      "model_requests": len(server.requests), "reminders": reminders}))
    expected_reminders = [("finished",)] if args.reminder else []
    if (result.returncode or not EVENTS[client].issubset(events)
            or outcomes != [(trigger, expected)] or reminders != expected_reminders or not evidence_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
