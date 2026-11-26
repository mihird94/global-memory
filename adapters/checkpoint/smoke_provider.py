"""Loopback model fixture for synthetic checkpoint tests of native clients."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlparse


def checkpoint_id(ledger: Path, request: dict) -> str | None:
    supplied = re.findall(r"Checkpoint ID: ([0-9a-f]{32})", json.dumps(request))
    if not supplied:
        return None
    if not ledger.is_file():
        return None
    with sqlite3.connect(ledger) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoints'").fetchone():
            return None
        row = db.execute("SELECT id FROM checkpoints ORDER BY rowid DESC LIMIT 1").fetchone()
        return row[0] if row and row[0] in supplied else None


class SmokeProvider(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tools = request.get("tools") or []
        names = [tool.get("name") or tool.get("function", {}).get("name") for tool in tools]
        if hasattr(self.server, "requests"):
            self.server.requests.append((path, [name for name in names if name]))
        if path == "/v1/chat/completions":
            self.chat(request)
        elif path == "/v1/messages":
            self.anthropic(request)
        elif path.endswith(":streamGenerateContent"):
            self.gemini(request)
        else:
            self.send_error(404)

    def start_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

    def frame(self, data, event=None):
        if event:
            self.wfile.write(f"event: {event}\n".encode())
        self.wfile.write(b"data: " + json.dumps(data).encode() + b"\n\n")

    def tool_call(self, names, request, *, pending):
        if not pending:
            return None, None
        read = getattr(self.server, "read_note", "")
        if read:
            name = next((name for name in names if name.endswith("brain_read")), None)
            return name, {"id_or_path": read} if name else None
        target = getattr(self.server, "action", "brain_checkpoint_save")
        name = next((name for name in names if name.endswith(target)), None)
        if not name:
            return None, None
        if target == "brain_store":
            return name, {"content": "teal", "kind": "fact", "subject": "checkpoint-pilot",
                          "predicate": "color", "source": "user"}
        if target == "safe_propose":
            return name, {"title": "Synthetic pilot color", "content": "The synthetic checkpoint pilot preference is teal.",
                          "kind": "fact", "project": "pilot", "harness": "opencode"}
        if getattr(self.server, "wait_for_reminder", False) and "Resolve pending Brain checkpoint" not in json.dumps(request):
            return None, None
        checkpoint = checkpoint_id(self.server.ledger, request) if self.server.ledger else None
        if not checkpoint:
            return None, None
        fields = getattr(self.server, "fields", {
            "content": "teal", "kind": "fact", "subject": "checkpoint-pilot",
            "predicate": "color", "source": "user",
        })
        return name, {"checkpoint_id": checkpoint, **fields}

    def completion(self, results):
        if getattr(self.server, "read_note", ""):
            return "PILOT_READ_OK" if "**Value:** teal" in json.dumps(results) else "PILOT_READ_MISSING"
        return "PILOT_OK"

    def chat(self, request):
        tools = request.get("tools") or []
        results = [msg for msg in request["messages"] if msg["role"] == "tool"]
        name, fields = self.tool_call((tool["function"]["name"] for tool in tools), request, pending=not results)
        delta, finish = {"content": self.completion(results)}, "stop"
        if fields:
            delta = {"tool_calls": [{"index": 0, "id": "call_checkpoint", "type": "function",
                                     "function": {"name": name, "arguments": json.dumps(fields)}}]}
            finish = "tool_calls"
        self.start_stream()
        for part, reason in (({"role": "assistant", **delta}, None), ({}, finish)):
            chunk = {"id": "pilot-response", "object": "chat.completion.chunk", "created": 0,
                     "model": request["model"], "choices": [{"index": 0, "delta": part, "finish_reason": reason}]}
            self.frame(chunk)
        self.wfile.write(b"data: [DONE]\n\n")

    def anthropic(self, request):
        results = [part for msg in request["messages"] for part in msg["content"]
                   if isinstance(part, dict) and part.get("type") == "tool_result"]
        names = (tool["name"] for tool in request.get("tools", []))
        name, fields = self.tool_call(names, request, pending=not results)
        if fields:
            block = {"type": "tool_use", "id": "toolu_checkpoint", "name": name, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(fields)}
        else:
            block = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": self.completion(results)}
        usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        message = {"id": "msg_checkpoint", "type": "message", "role": "assistant",
                   "model": request["model"], "content": [], "stop_reason": None, "usage": usage}
        self.start_stream()
        events = [
            ("message_start", {"message": message}),
            ("content_block_start", {"index": 0, "content_block": block}),
            ("content_block_delta", {"index": 0, "delta": delta}),
            ("content_block_stop", {"index": 0}),
            ("message_delta", {"delta": {"stop_reason": "tool_use" if fields else "end_turn"}, "usage": usage}),
            ("message_stop", {}),
        ]
        for event, payload in events:
            self.frame({"type": event, **payload}, event)

    def gemini(self, request):
        names = (tool["name"] for group in request.get("tools", []) for tool in group.get("functionDeclarations", []))
        results = [part for msg in request["contents"] for part in msg["parts"] if "functionResponse" in part]
        name, fields = self.tool_call(names, request, pending=not results)
        part = {"text": self.completion(results)}
        if fields:
            part = {"functionCall": {"name": name, "args": fields}}
        self.start_stream()
        self.frame({"candidates": [{"content": {"role": "model", "parts": [part]}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    with HTTPServer(("127.0.0.1", 0), SmokeProvider) as server:
        server.ledger = args.ledger
        args.port_file.write_text(str(server.server_port))
        server.serve_forever()
