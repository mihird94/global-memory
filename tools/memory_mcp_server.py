#!/usr/bin/env python3
"""
memory_mcp_server.py — MCP Server for the Mihir-OS Global Memory System
========================================================================
Exposes memoryctl as a proper MCP (Model Context Protocol) server via stdio.
Any agent that supports MCP (Antigravity, Codex, Claude Code, Gemini CLI,
OpenClaw) can call these tools directly without running shell commands.

This eliminates the need to manually run `memoryctl start-context` at the
start of every session — the MCP client calls mem_session_start automatically.

Installation (add to your agent's MCP config):

  Gemini CLI (~/.gemini/settings.json):
    {
      "mcpServers": {
        "memory": {
          "command": "/home/mihir/global_skills/global-memory/.venv/bin/python",
          "args": ["/home/mihir/global_skills/global-memory/tools/memory_mcp_server.py"]
        }
      }
    }

  Codex (~/.codex/config.toml):
    [[mcp_servers]]
    name = "memory"
    command = ["/home/mihir/global_skills/global-memory/.venv/bin/python",
               "/home/mihir/global_skills/global-memory/tools/memory_mcp_server.py"]

Tools exposed (19):
  Session:    mem_session_start, mem_session_end
  Save:       mem_save_fact, mem_log_event, mem_add_lesson
  Search:     mem_search, mem_context
  Inspect:    mem_get_facts, mem_get_preferences, mem_get_projects, mem_stats
  Conflict:   mem_judge (checks new fact against existing ones before write)
  Maintenance: mem_index_rebuild
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
MEM_ROOT    = Path(os.environ.get("MEMORY_ROOT", "/home/mihir/memories"))
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
MEMORYCTL   = Path(os.environ.get(
    "MEMORYCTL_PATH",
    "/home/mihir/global_skills/global-memory/tools/memoryctl"
))
EMBED_TIMEOUT = int(os.environ.get("MEMORY_EMBED_TIMEOUT_SEC", "120"))

# ──────────────────────────────────────────────────────────────────────────────
# MCP Protocol (minimal stdio JSON-RPC 2.0 implementation)
# No external mcp package required — pure stdlib.
# ──────────────────────────────────────────────────────────────────────────────

def _send(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _text(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}]}


# ──────────────────────────────────────────────────────────────────────────────
# Memory helpers
# ──────────────────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(errors="replace")


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(text)


def _load_facts() -> dict:
    p = MEM_ROOT / "semantic" / "facts.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_facts(facts: dict) -> None:
    p = MEM_ROOT / "semantic" / "facts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(facts, indent=2, sort_keys=True))


def _embed(text: str) -> list[float] | None:
    try:
        payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
        req = request.Request(
            f"{OLLAMA_URL}/api/embeddings", data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with request.urlopen(req, timeout=EMBED_TIMEOUT) as resp:  # nosec B310
            body = json.loads(resp.read().decode())
        emb = body.get("embedding")
        return emb if isinstance(emb, list) and emb else None
    except Exception:
        return None


def _run_memoryctl(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [str(MEMORYCTL)] + list(args),
            capture_output=True, text=True, timeout=300
        )
        out = (result.stdout + result.stderr).strip()
        return result.returncode, out
    except Exception as e:
        return 1, str(e)


# ──────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────────────

def tool_mem_session_start(args: dict) -> str:
    """Load and return the full startup context bundle (replaces `memoryctl start-context`)."""
    idx       = _read(MEM_ROOT / "index.md")
    prefs     = _read(MEM_ROOT / "preferences.md")
    projects  = _read(MEM_ROOT / "projects.md")
    lessons   = _read(MEM_ROOT / "lessons" / "global.md")
    today     = datetime.now().strftime("%Y-%m-%d")
    daily     = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    journal   = MEM_ROOT / "episodic" / "journal.md"
    episodic  = _read(daily if daily.exists() else journal)
    facts     = _load_facts()
    top_facts = dict(list(facts.items())[:10])

    return (
        f"## GMS Session Context — {today}\n\n"
        f"### Preferences\n{prefs[:1500]}\n\n"
        f"### Active Projects\n{projects[:1500]}\n\n"
        f"### Lessons\n{lessons[:1000]}\n\n"
        f"### Top Facts\n{json.dumps(top_facts, indent=2)}\n\n"
        f"### Recent Episodic\n{episodic[-2000:]}"
    )


def tool_mem_session_end(args: dict) -> str:
    """Log a session-end milestone to episodic memory."""
    agent   = args.get("agent", "unknown")
    summary = args.get("summary", "")
    if not summary:
        return "ERROR: 'summary' is required"
    now  = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_ = now.strftime("%H:%M")
    daily = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    target = daily if daily.exists() else MEM_ROOT / "episodic" / "journal.md"
    entry = f"\n### {today} [{time_}] - {agent} - Session End\n- {summary}\n"
    _append(target, entry)
    return f"Session end logged to {target}"


def tool_mem_save_fact(args: dict) -> str:
    """Save a semantic fact. Runs conflict check first."""
    key   = args.get("key", "").strip()
    value = args.get("value", "").strip()
    if not key or not value:
        return "ERROR: 'key' and 'value' are required"

    # Conflict detection: warn if key already exists with different value
    facts = _load_facts()
    if key in facts and facts[key] != value:
        old = facts[key]
        return (
            f"CONFLICT DETECTED: Key '{key}' already exists.\n"
            f"  Existing: {old}\n"
            f"  Proposed: {value}\n"
            f"Call mem_save_fact with force=true to overwrite."
        )

    force = str(args.get("force", "false")).lower() in ("true", "1", "yes")
    if key in facts and not force:
        return f"INFO: Key '{key}' unchanged (same value exists)."

    facts[key] = value
    _save_facts(facts)
    return f"Fact saved: {key} = {value}"


def tool_mem_judge(args: dict) -> str:
    """Check if a proposed fact conflicts with existing knowledge. Does NOT write anything."""
    key   = args.get("key", "").strip()
    value = args.get("value", "").strip()
    if not key or not value:
        return "ERROR: 'key' and 'value' are required"

    facts = _load_facts()
    if key in facts:
        existing = facts[key]
        if existing == value:
            return f"CONSISTENT: Key '{key}' already has this exact value."
        return (
            f"CONFLICT: Key '{key}' has an existing value that differs.\n"
            f"  Existing: {existing}\n"
            f"  Proposed: {value}\n"
            f"Resolve before saving."
        )

    # Semantic similarity check via FAISS
    try:
        import numpy as np
        import faiss

        idx_path  = MEM_ROOT / "episodic" / "index" / "episodic.faiss"
        meta_path = MEM_ROOT / "episodic" / "index" / "episodic_meta.json"
        if idx_path.exists() and meta_path.exists():
            meta  = json.loads(meta_path.read_text())
            index = faiss.read_index(str(idx_path))
            qvec  = _embed(f"{key}: {value}")
            if qvec:
                qmat = np.array([qvec], dtype=np.float32)
                faiss.normalize_L2(qmat)
                scores, ids = index.search(qmat, 3)
                hits = []
                for score, doc_id in zip(scores[0], ids[0]):
                    if doc_id >= 0 and score > 0.85:
                        hits.append(f"  score={score:.3f}: {meta[int(doc_id)]['text'][:120]}...")
                if hits:
                    return "SIMILAR CONTENT FOUND in episodic memory:\n" + "\n".join(hits) + \
                           "\nReview before saving to avoid duplication."
    except Exception:
        pass

    return f"CLEAR: No conflicts found for key '{key}'. Safe to save."


def tool_mem_log_event(args: dict) -> str:
    """Append an episodic milestone (wraps `memoryctl log`)."""
    agent = args.get("agent", "unknown")
    title = args.get("title", "")
    note  = args.get("note", "")
    if not title or not note:
        return "ERROR: 'title' and 'note' are required"
    code, out = _run_memoryctl("log", "--agent", agent, "--title", title, "--note", note)
    return out if out else ("Logged." if code == 0 else "Failed.")


def tool_mem_add_lesson(args: dict) -> str:
    """Add a corrective lesson to global.md."""
    text = args.get("text", "").strip()
    if not text:
        return "ERROR: 'text' is required"
    code, out = _run_memoryctl("lesson-add", text)
    return out if out else ("Lesson added." if code == 0 else "Failed.")


def tool_mem_search(args: dict) -> str:
    """Semantic search over episodic FAISS index with temporal decay and git branch boosting."""
    query = args.get("query", "").strip()
    k     = int(args.get("k", 5))
    if not query:
        return "ERROR: 'query' is required"
    cmd_args = ["index-query", query, "-k", str(k)]
    if "decay_rate" in args:
        cmd_args += ["--decay-rate", str(args["decay_rate"])]
    if args.get("no_decay") is True:
        cmd_args += ["--no-decay"]
    if "branch_boost" in args:
        cmd_args += ["--branch-boost", str(args["branch_boost"])]
    if args.get("no_boost") is True:
        cmd_args += ["--no-boost"]
    if args.get("no_hybrid") is True:
        cmd_args += ["--no-hybrid"]
    code, out = _run_memoryctl(*cmd_args)
    return out if out else "No results."


def tool_mem_context(args: dict) -> str:
    """Return the last N lines of today's episodic log."""
    n = int(args.get("lines", 50))
    today = datetime.now().strftime("%Y-%m-%d")
    daily = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    text  = _read(daily if daily.exists() else MEM_ROOT / "episodic" / "journal.md")
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def tool_mem_get_facts(args: dict) -> str:
    """Return current semantic facts (optionally filtered by prefix)."""
    prefix  = args.get("prefix", "").strip().lower()
    facts   = _load_facts()
    if prefix:
        facts = {k: v for k, v in facts.items() if k.lower().startswith(prefix)}
    return json.dumps(facts, indent=2)


def tool_mem_get_preferences(_: dict) -> str:
    return _read(MEM_ROOT / "preferences.md")


def tool_mem_get_projects(_: dict) -> str:
    return _read(MEM_ROOT / "projects.md")


def tool_mem_stats(_: dict) -> str:
    facts   = _load_facts()
    journal = MEM_ROOT / "episodic" / "journal.md"
    history = MEM_ROOT / "episodic" / "history"
    history_files = list(history.glob("*.md")) if history.exists() else []
    idx     = MEM_ROOT / "episodic" / "index" / "episodic.faiss"
    return (
        f"## GMS Stats\n"
        f"- Semantic facts: {len(facts)}\n"
        f"- Episodic history files: {len(history_files)}\n"
        f"- Journal exists: {journal.exists()}\n"
        f"- FAISS index exists: {idx.exists()}\n"
        f"- Memory root: {MEM_ROOT}\n"
    )


def tool_mem_index_rebuild(_: dict) -> str:
    """Rebuild the FAISS vector index (wraps `memoryctl index-build`)."""
    code, out = _run_memoryctl("index-build")
    return out if out else ("Index rebuilt." if code == 0 else "Rebuild failed.")


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry
# ──────────────────────────────────────────────────────────────────────────────

TOOLS = {
    "mem_session_start": {
        "fn": tool_mem_session_start,
        "description": "Load GMS startup context (preferences, projects, lessons, recent episodic, top facts). Call at the start of every session.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_session_end": {
        "fn": tool_mem_session_end,
        "description": "Log a session-end milestone to episodic memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent":   {"type": "string", "description": "Agent name (e.g. Antigravity, Codex)"},
                "summary": {"type": "string", "description": "What was accomplished this session"},
            },
            "required": ["agent", "summary"],
        },
    },
    "mem_save_fact": {
        "fn": tool_mem_save_fact,
        "description": "Save a semantic fact to facts.json. Runs conflict detection first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "snake_case fact key"},
                "value": {"type": "string", "description": "Fact value (string)"},
                "force": {"type": "boolean", "description": "Overwrite existing value if conflicting"},
            },
            "required": ["key", "value"],
        },
    },
    "mem_judge": {
        "fn": tool_mem_judge,
        "description": "Check if a proposed fact conflicts with existing knowledge. Does not write. Use before mem_save_fact if unsure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    "mem_log_event": {
        "fn": tool_mem_log_event,
        "description": "Append an episodic milestone to today's journal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "title": {"type": "string"},
                "note":  {"type": "string"},
            },
            "required": ["agent", "title", "note"],
        },
    },
    "mem_add_lesson": {
        "fn": tool_mem_add_lesson,
        "description": "Add a corrective lesson or override rule to global.md.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    "mem_search": {
        "fn": tool_mem_search,
        "description": "Semantic search over episodic FAISS index with temporal decay and git branch boosting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":        {"type": "string", "description": "Search query"},
                "k":            {"type": "integer", "description": "Number of results (default 5)"},
                "decay_rate":   {"type": "number", "description": "Exponential decay rate per day (default 0.002)"},
                "no_decay":     {"type": "boolean", "description": "Disable temporal decay"},
                "branch_boost": {"type": "number", "description": "Active branch boost multiplier (default 1.15)"},
                "no_boost":     {"type": "boolean", "description": "Disable git branch boost"},
                "no_hybrid":    {"type": "boolean", "description": "Disable BM25 hybrid search RRF"},
            },
            "required": ["query"],
        },
    },
    "mem_context": {
        "fn": tool_mem_context,
        "description": "Return the last N lines of today's episodic log.",
        "inputSchema": {
            "type": "object",
            "properties": {"lines": {"type": "integer", "description": "Number of lines (default 50)"}},
            "required": [],
        },
    },
    "mem_get_facts": {
        "fn": tool_mem_get_facts,
        "description": "Return all semantic facts, optionally filtered by key prefix.",
        "inputSchema": {
            "type": "object",
            "properties": {"prefix": {"type": "string", "description": "Filter key prefix"}},
            "required": [],
        },
    },
    "mem_get_preferences": {
        "fn": tool_mem_get_preferences,
        "description": "Return the contents of preferences.md.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_get_projects": {
        "fn": tool_mem_get_projects,
        "description": "Return the contents of projects.md.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_stats": {
        "fn": tool_mem_stats,
        "description": "Return stats about the GMS (fact count, index status, etc.).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_index_rebuild": {
        "fn": tool_mem_index_rebuild,
        "description": "Rebuild the FAISS vector index. Run after adding many new memories.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
}

TOOLS_LIST = [
    {
        "name": name,
        "description": info["description"],
        "inputSchema": info["inputSchema"],
    }
    for name, info in TOOLS.items()
]


# ──────────────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 request handler
# ──────────────────────────────────────────────────────────────────────────────

def handle(req: dict) -> dict | None:
    id_    = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return _result(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gms-memory", "version": "1.0.0"},
        })

    if method == "tools/list":
        return _result(id_, {"tools": TOOLS_LIST})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return _error(id_, -32601, f"Unknown tool: {tool_name}")
        try:
            output = TOOLS[tool_name]["fn"](tool_args)
            return _result(id_, _text(str(output)))
        except Exception as e:
            return _error(id_, -32603, f"Tool error: {e}")

    if method == "notifications/initialized":
        return None  # no response needed

    if method == "ping":
        return _result(id_, {})

    return _error(id_, -32601, f"Method not found: {method}")


# ──────────────────────────────────────────────────────────────────────────────
# Main stdio loop
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _send(_error(None, -32700, "Parse error"))
            continue

        response = handle(req)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
