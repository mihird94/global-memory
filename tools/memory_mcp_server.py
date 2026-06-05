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
          "command": "<repo>/.venv/bin/python",
          "args": ["<repo>/tools/memory_mcp_server.py"]
        }
      }
    }

  Codex (~/.codex/config.toml):
    [[mcp_servers]]
    name = "memory"
    command = ["<repo>/.venv/bin/python",
               "<repo>/tools/memory_mcp_server.py"]

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
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
MEM_ROOT    = Path(os.environ.get("MEMORY_ROOT", "/home/mihir/memories"))
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
MEMORYCTL   = Path(os.environ.get(
    "MEMORYCTL_PATH",
    str(REPO_ROOT / "tools" / "memoryctl")
))
EMBED_TIMEOUT = int(os.environ.get("MEMORY_EMBED_TIMEOUT_SEC", "120"))

DB_PATH = MEM_ROOT / "gms_trust.sqlite"

# ──────────────────────────────────────────────────────────────────────────────
# Trust Database Helpers
# ──────────────────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_agent_reputation (
            agent_id TEXT PRIMARY KEY,
            alpha REAL DEFAULT 1.0,
            beta REAL DEFAULT 0.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_fact_provenance (
            fact_key TEXT PRIMARY KEY,
            agent_id TEXT,
            branch TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            quarantined INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_quarantined_facts (
            fact_key TEXT,
            value TEXT,
            agent_id TEXT,
            branch TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (fact_key, agent_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_kind TEXT,
            memory_key TEXT,
            value TEXT,
            agent_id TEXT,
            branch TEXT,
            status TEXT,
            supersedes_claim_id INTEGER,
            confidence REAL DEFAULT 1.0,
            contradiction_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_entities (
            entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            entity_type TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_relationships (
            relationship_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_entity_id INTEGER,
            predicate TEXT,
            object_entity_id INTEGER,
            object_literal TEXT,
            source_claim_id INTEGER,
            valid_from TIMESTAMP,
            valid_to TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(subject_entity_id) REFERENCES gms_entities(entity_id),
            FOREIGN KEY(object_entity_id) REFERENCES gms_entities(entity_id),
            FOREIGN KEY(source_claim_id) REFERENCES gms_claims(claim_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_procedures (
            procedure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            "trigger" TEXT,
            action TEXT,
            context TEXT,
            status TEXT DEFAULT 'active',
            source_claim_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(source_claim_id) REFERENCES gms_claims(claim_id)
        )
    """)
    try:
        cursor.execute("ALTER TABLE gms_claims ADD COLUMN confidence REAL DEFAULT 1.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE gms_claims ADD COLUMN contradiction_type TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def get_agent_trust(agent_id: str) -> float:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id = ?", (agent_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, 1.0, 0.0)", (agent_id,))
        conn.commit()
        alpha, beta = 1.0, 0.0
    else:
        alpha, beta = row
    conn.close()
    return (alpha + 1.0) / (alpha + beta + 2.0)


def increment_agent_alpha(agent_id: str, amount: float = 1.0):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT alpha FROM gms_agent_reputation WHERE agent_id = ?", (agent_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, 0.0)", (agent_id, 1.0 + amount))
    else:
        cursor.execute("UPDATE gms_agent_reputation SET alpha = alpha + ?, last_updated = CURRENT_TIMESTAMP WHERE agent_id = ?", (amount, agent_id))
    conn.commit()
    conn.close()


def increment_agent_beta(agent_id: str, amount: float = 1.0):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT beta FROM gms_agent_reputation WHERE agent_id = ?", (agent_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, 1.0, ?)", (agent_id, amount))
    else:
        cursor.execute("UPDATE gms_agent_reputation SET beta = beta + ?, last_updated = CURRENT_TIMESTAMP WHERE agent_id = ?", (amount, agent_id))
    conn.commit()
    conn.close()


def record_provenance(fact_key: str, agent_id: str, branch: str, quarantined: int = 0):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, quarantined, timestamp)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fact_key) DO UPDATE SET
            agent_id = excluded.agent_id,
            branch = excluded.branch,
            quarantined = excluded.quarantined,
            timestamp = CURRENT_TIMESTAMP
    """, (fact_key, agent_id, branch, quarantined))
    conn.commit()
    conn.close()


def get_fact_provenance(fact_key: str) -> tuple[str, str, int] | None:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT agent_id, branch, quarantined FROM gms_fact_provenance WHERE fact_key = ?", (fact_key,))
    row = cursor.fetchone()
    conn.close()
    return row


def quarantine_fact(fact_key: str, value: str, agent_id: str, branch: str):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gms_quarantined_facts (fact_key, value, agent_id, branch, timestamp)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fact_key, agent_id) DO UPDATE SET
            value = excluded.value,
            branch = excluded.branch,
            timestamp = CURRENT_TIMESTAMP
    """, (fact_key, value, agent_id, branch))
    conn.commit()
    conn.close()


def record_claim(kind: str, key: str, value: str, agent_id: str, branch: str, status: str, confidence: float = None, contradiction_type: str = None) -> int:
    import re
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    supersedes_id = None
    if status == "active":
        cursor.execute(
            "SELECT claim_id FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND status = 'active'",
            (kind, key)
        )
        rows = cursor.fetchall()
        if rows:
            supersedes_id = rows[-1][0]
            for row in rows:
                cursor.execute(
                    "UPDATE gms_claims SET status = 'superseded', confidence = 0.0 WHERE claim_id = ?",
                    (row[0],)
                )
    
    trust = get_agent_trust(agent_id)
    if confidence is None:
        if status == "active":
            confidence = trust
        elif status == "quarantined":
            confidence = 0.2
        elif status == "discarded":
            confidence = 0.0
        else:
            confidence = trust

    if contradiction_type is None:
        # Contextual coexistence check
        if "@" in key or "[" in key or "]" in key or (":" in key and not any(key.startswith(p + ":") for p in ["semantic", "operational", "procedural", "session"])):
            contradiction_type = "contextual_coexistence"
        else:
            # Temporal invalidation check
            time_keywords = ["valid_from", "valid_to", "expires", "since", "until", "timestamp", "start_date", "end_date", "current_task"]
            has_time_kw = any(kw in key.lower() or kw in value.lower() for kw in time_keywords)
            has_date_pattern = bool(re.search(r'\d{4}-\d{2}-\d{2}', key + " " + value))
            
            if supersedes_id is not None or has_time_kw or has_date_pattern:
                contradiction_type = "temporal_invalidation"
            else:
                cursor.execute(
                    "SELECT value FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND status = 'active' ORDER BY claim_id DESC LIMIT 1",
                    (kind, key)
                )
                row = cursor.fetchone()
                if row and row[0] != value:
                    contradiction_type = "exact_conflict"
                    if status == "quarantined":
                        confidence = 0.2
                        
    cursor.execute("""
        INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (kind, key, value, agent_id, branch, status, supersedes_id, confidence, contradiction_type))
    
    claim_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return claim_id


def parse_prov_key(prov_key: str) -> tuple[str, str]:
    if ":" in prov_key:
        parts = prov_key.split(":", 1)
        return parts[0], parts[1]
    return "semantic", prov_key


def _detect_branch() -> str:
    try:
        res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            branch = res.stdout.strip()
            if branch:
                return branch
    except Exception:
        pass
    return "main"


def log_security_event(event_type: str, message: str):
    try:
        log_dir = Path("/home/mihir/.codex/log")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "gms_security.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_file.open("a") as f:
            f.write(f"[{now}] [{event_type}] {message}\n")
    except Exception:
        pass


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


def _load_typed_facts(kind: str) -> dict:
    if kind == "session":
        return {}
    p = MEM_ROOT / kind / "facts.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_typed_facts(kind: str, facts: dict) -> None:
    if kind == "session":
        return
    p = MEM_ROOT / kind / "facts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(facts, indent=2, sort_keys=True))


def _load_facts() -> dict:
    return _load_typed_facts("semantic")


def _save_facts(facts: dict) -> None:
    _save_typed_facts("semantic", facts)


def determine_routing(key: str, value: str) -> str:
    k = key.lower()
    v = value.lower()
    
    # Session criteria: current conversation / ephemeral task state
    session_keywords = ["conversation", "task_state", "ephemeral", "session", "current_task", "chat_history", "temp"]
    if any(kw in k or kw in v for kw in session_keywords):
        return "session"
        
    # Operational criteria: agent behavior / config / preferences / policies
    operational_keywords = ["behavior", "config", "preferences", "policies", "policy", "settings", "rules", "agent_behavior", "agent_config", "agent_pref"]
    if any(kw in k or kw in v for kw in operational_keywords):
        return "operational"
        
    # Procedural criteria: learned reusable instructions / trigger-action patterns
    procedural_keywords = ["instruction", "trigger", "action", "how_to", "procedure", "recipe", "pattern", "trigger_action"]
    if any(kw in k or kw in v for kw in procedural_keywords):
        return "procedural"
        
    return "semantic"


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

    try:
        init_db()
        increment_agent_alpha(agent, 0.5)
    except Exception:
        pass

    return f"Session end logged to {target}"


def tool_mem_save_typed(args: dict) -> str:
    """Save a memory fact using typed routing (semantic, operational, procedural, session)."""
    key   = args.get("key", "").strip()
    value = args.get("value", "").strip()
    if not key or not value:
        return "ERROR: 'key' and 'value' are required"

    kind = args.get("kind", "").strip().lower()
    if not kind:
        kind = determine_routing(key, value)
    elif kind not in ("semantic", "operational", "procedural", "session"):
        return f"ERROR: Invalid memory kind '{kind}'. Must be semantic, operational, procedural, or session."

    if kind == "session":
        return f"SESSION_ONLY: Memory '{key}' is ephemeral task state/session-only and was not persisted to disk."

    agent_id = args.get("agent", "").strip() or "unknown"
    branch = _detect_branch()
    force = str(args.get("force", "false")).lower() in ("true", "1", "yes")

    try:
        init_db()
    except Exception as e:
        return f"ERROR: Database initialization failed: {e}"

    prov_key = key if kind == "semantic" else f"{kind}:{key}"

    facts = _load_typed_facts(kind)
    if key in facts and facts[key] != value:
        existing_owner_info = get_fact_provenance(prov_key)
        if existing_owner_info:
            existing_owner, existing_branch, was_quarantined = existing_owner_info
        else:
            existing_owner, existing_branch = "unknown", "main"

        new_trust = get_agent_trust(agent_id)
        old_trust = get_agent_trust(existing_owner)

        if existing_owner == "unknown" or agent_id == existing_owner or new_trust > old_trust or force:
            facts[key] = value
            _save_typed_facts(kind, facts)
            record_provenance(prov_key, agent_id, branch, quarantined=0)
            record_claim(kind, key, value, agent_id, branch, "active")
            increment_agent_alpha(agent_id, 1.0)
            if existing_owner != "unknown" and existing_owner != agent_id:
                increment_agent_beta(existing_owner, 1.0)
                log_security_event("OVERWRITE", f"[{kind.upper()}] Fact '{key}' overwritten by agent '{agent_id}' (Trust: {new_trust:.3f}) replacing '{existing_owner}' (Trust: {old_trust:.3f})")
            return (
                f"[{kind.upper()}] Fact saved (overwrote existing key '{key}').\n"
                f"  Previous Owner: {existing_owner} (Trust: {old_trust:.3f})\n"
                f"  New Owner: {agent_id} (Trust: {new_trust:.3f})"
            )
        else:
            quarantine_fact(prov_key, value, agent_id, branch)
            record_claim(kind, key, value, agent_id, branch, "quarantined")
            increment_agent_beta(agent_id, 1.0)
            log_security_event("QUARANTINE", f"[{kind.upper()}] Fact overwrite rejected for key '{key}' from agent '{agent_id}' (Trust: {new_trust:.3f}) vs Owner '{existing_owner}' (Trust: {old_trust:.3f})")
            return (
                f"CONFLICT/QUARANTINE: Overwrite of key '{key}' in bucket '{kind}' rejected due to insufficient trust.\n"
                f"  Existing Owner: {existing_owner} (Trust: {old_trust:.3f})\n"
                f"  Proposing Agent: {agent_id} (Trust: {new_trust:.3f})\n"
                f"Proposed fact has been quarantined for review."
            )

    if key in facts and facts[key] == value:
        existing_owner_info = get_fact_provenance(prov_key)
        if not existing_owner_info or existing_owner_info[0] == "unknown":
            record_provenance(prov_key, agent_id, branch, quarantined=0)
        try:
            trust = get_agent_trust(agent_id)
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT claim_id, confidence FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND value = ? AND status = 'active'",
                (kind, key, value)
            )
            row = cursor.fetchone()
            if row:
                claim_id, current_conf = row
                new_conf = min(1.0, (current_conf if current_conf is not None else 1.0) + 0.1 * trust)
                cursor.execute(
                    "UPDATE gms_claims SET confidence = ? WHERE claim_id = ?",
                    (new_conf, claim_id)
                )
                conn.commit()
            else:
                conn.close()
                record_claim(kind, key, value, agent_id, branch, "active")
                conn = None
            if conn:
                conn.close()
        except Exception:
            pass
        return f"INFO: Key '{key}' in bucket '{kind}' unchanged (same value exists)."

    facts[key] = value
    _save_typed_facts(kind, facts)
    record_provenance(prov_key, agent_id, branch, quarantined=0)
    record_claim(kind, key, value, agent_id, branch, "active")
    increment_agent_alpha(agent_id, 1.0)
    return f"[{kind.upper()}] Fact saved: {key} = {value}"


def tool_mem_save_fact(args: dict) -> str:
    """Save a semantic fact. Runs conflict check first."""
    args_copy = dict(args)
    args_copy["kind"] = "semantic"
    return tool_mem_save_typed(args_copy)


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
    """Return current facts for the specified bucket (optionally filtered by prefix)."""
    prefix  = args.get("prefix", "").strip().lower()
    kind    = args.get("kind", "semantic").strip().lower()
    
    if kind not in ("semantic", "operational", "procedural", "session"):
        return f"ERROR: Invalid memory kind '{kind}'. Must be semantic, operational, procedural, or session."
        
    facts   = _load_typed_facts(kind)
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


def tool_mem_resolve_quarantine(args: dict) -> str:
    """Resolve a quarantined fact by promoting it or discarding it."""
    key = args.get("key", "").strip()
    agent_id = args.get("agent_id", "").strip()
    action = args.get("action", "").strip().lower() # 'promote' or 'discard'
    
    if not key or not agent_id or not action:
        return "ERROR: 'key', 'agent_id', and 'action' are required"
        
    if action not in ("promote", "discard"):
        return "ERROR: 'action' must be 'promote' or 'discard'"
        
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT value, branch FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return f"ERROR: No quarantined entry found for key '{key}' and agent '{agent_id}'"
            
        value, branch = row
        
        kind, real_key = parse_prov_key(key)
        if action == "promote":
            facts = _load_typed_facts(kind)
            existing_owner_info = get_fact_provenance(key)
            existing_owner = existing_owner_info[0] if existing_owner_info else "unknown"
            
            facts[real_key] = value
            _save_typed_facts(kind, facts)
            
            record_provenance(key, agent_id, branch, quarantined=0)
            
            # --- Claim updates ---
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT claim_id FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND status = 'active'",
                (kind, real_key)
            )
            active_rows = cursor.fetchall()
            prior_active_id = None
            if active_rows:
                prior_active_id = active_rows[-1][0]
                for a_row in active_rows:
                    cursor.execute(
                        "UPDATE gms_claims SET status = 'superseded' WHERE claim_id = ?",
                        (a_row[0],)
                    )
            
            cursor.execute(
                "SELECT claim_id FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND agent_id = ? AND status = 'quarantined'",
                (kind, real_key, agent_id)
            )
            quar_rows = cursor.fetchall()
            trust = get_agent_trust(agent_id)
            if quar_rows:
                target_quar_id = quar_rows[-1][0]
                cursor.execute(
                    "UPDATE gms_claims SET status = 'active', supersedes_claim_id = ?, confidence = ?, contradiction_type = 'temporal_invalidation' WHERE claim_id = ?",
                    (prior_active_id, trust, target_quar_id)
                )
            else:
                cursor.execute("""
                    INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at)
                    VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 'temporal_invalidation', CURRENT_TIMESTAMP)
                """, (kind, real_key, value, agent_id, branch, prior_active_id, trust))
            
            cursor.execute("DELETE FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
            conn.commit()
            conn.close()
            
            resolver = args.get("agent", "unknown")
            increment_agent_alpha(resolver, 1.0)
            increment_agent_alpha(agent_id, 1.0)
            
            if existing_owner != "unknown" and existing_owner != agent_id:
                increment_agent_beta(existing_owner, 1.0)
                
            log_security_event("PROMOTION", f"Fact '{key}' promoted from quarantine for agent '{agent_id}' by resolver '{resolver}'")
            return f"SUCCESS: Fact '{key}' promoted. Owner is now '{agent_id}'."
            
        else: # discard
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
            cursor.execute(
                "UPDATE gms_claims SET status = 'discarded', confidence = 0.0 WHERE memory_kind = ? AND memory_key = ? AND agent_id = ? AND status = 'quarantined'",
                (kind, real_key, agent_id)
            )
            conn.commit()
            conn.close()
            
            increment_agent_beta(agent_id, 0.5)
            log_security_event("DISCARD", f"Quarantined fact '{key}' from agent '{agent_id}' discarded")
            return f"SUCCESS: Quarantined fact '{key}' from agent '{agent_id}' discarded."
            
    except Exception as e:
        return f"ERROR: Failed to resolve quarantine: {e}"


def tool_mem_get_reputations(_: dict) -> str:
    """Retrieve the trust score and reputation counts of all registered agents."""
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, alpha, beta, last_updated FROM gms_agent_reputation")
        rows = cursor.fetchall()
        conn.close()
        
        rep = []
        for agent_id, alpha, beta, last_updated in rows:
            trust = (alpha + 1.0) / (alpha + beta + 2.0)
            rep.append({
                "agent_id": agent_id,
                "alpha": alpha,
                "beta": beta,
                "trust_score": round(trust, 4),
                "last_updated": last_updated
            })
        return json.dumps(rep, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve reputations: {e}"


def tool_mem_get_quarantine(_: dict) -> str:
    """Retrieve all quarantined facts that were blocked due to trust violations."""
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT fact_key, value, agent_id, branch, timestamp FROM gms_quarantined_facts")
        rows = cursor.fetchall()
        conn.close()
        
        quar = []
        for fact_key, value, agent_id, branch, timestamp in rows:
            quar.append({
                "key": fact_key,
                "value": value,
                "agent_id": agent_id,
                "branch": branch,
                "timestamp": timestamp
            })
        return json.dumps(quar, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve quarantine: {e}"


def tool_mem_get_claims(args: dict) -> str:
    """Retrieve claims from the versioned claim ledger, optionally filtered by kind, key, and status."""
    kind = args.get("kind", "").strip().lower()
    key = args.get("key", "").strip()
    status = args.get("status", "").strip().lower()
    
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        query = "SELECT claim_id, memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at FROM gms_claims WHERE 1=1"
        params = []
        
        if kind:
            query += " AND memory_kind = ?"
            params.append(kind)
        if key:
            query += " AND memory_key = ?"
            params.append(key)
        if status:
            query += " AND status = ?"
            params.append(status)
            
        query += " ORDER BY claim_id ASC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        claims = []
        for row in rows:
            claims.append({
                "claim_id": row[0],
                "memory_kind": row[1],
                "memory_key": row[2],
                "value": row[3],
                "agent_id": row[4],
                "branch": row[5],
                "status": row[6],
                "supersedes_claim_id": row[7],
                "confidence": row[8],
                "contradiction_type": row[9],
                "created_at": row[10]
            })
            
        return json.dumps(claims, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve claims: {e}"


def _resolve_entity(cursor: sqlite3.Cursor, entity_id: int | None, name: str | None) -> int:
    if entity_id is not None:
        cursor.execute("SELECT entity_id FROM gms_entities WHERE entity_id = ?", (entity_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Entity ID {entity_id} does not exist.")
        return entity_id
    elif name:
        name = name.strip()
        cursor.execute("SELECT entity_id FROM gms_entities WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        else:
            cursor.execute("INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, '', '')", (name,))
            return cursor.lastrowid
    else:
        raise ValueError("Either entity_id or name must be provided.")


def tool_mem_upsert_entity(args: dict) -> str:
    """Create or update an entity in the local graph database."""
    name = args.get("name", "").strip()
    if not name:
        return "ERROR: 'name' is required"
    
    entity_type = args.get("entity_type", "")
    summary = args.get("summary", "")

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        cursor.execute("SELECT entity_id, entity_type, summary FROM gms_entities WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            entity_id = row[0]
            new_type = args.get("entity_type", row[1])
            new_summary = args.get("summary", row[2])
            cursor.execute("""
                UPDATE gms_entities
                SET entity_type = ?, summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE entity_id = ?
            """, (new_type, new_summary, entity_id))
        else:
            cursor.execute("""
                INSERT INTO gms_entities (name, entity_type, summary)
                VALUES (?, ?, ?)
            """, (name, entity_type, summary))
            entity_id = cursor.lastrowid
            
        conn.commit()
        
        cursor.execute("SELECT entity_id, name, entity_type, summary, created_at, updated_at FROM gms_entities WHERE entity_id = ?", (entity_id,))
        updated_row = cursor.fetchone()
        conn.close()
        
        entity_info = {
            "entity_id": updated_row[0],
            "name": updated_row[1],
            "entity_type": updated_row[2],
            "summary": updated_row[3],
            "created_at": updated_row[4],
            "updated_at": updated_row[5]
        }
        return json.dumps(entity_info, indent=2)
        
    except Exception as e:
        return f"ERROR: Failed to upsert entity: {e}"


def tool_mem_link_entities(args: dict) -> str:
    """Link two entities with a relationship, optionally referencing a claim id and validity window."""
    subject_id = args.get("subject_id")
    subject_name = args.get("subject_name")
    predicate = args.get("predicate", "").strip()
    object_id = args.get("object_id")
    object_name = args.get("object_name")
    object_literal = args.get("object_literal")
    source_claim_id = args.get("source_claim_id")
    valid_from = args.get("valid_from")
    valid_to = args.get("valid_to")

    if not predicate:
        return "ERROR: 'predicate' is required"

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        try:
            sub_id = _resolve_entity(cursor, subject_id, subject_name)
        except ValueError as e:
            conn.close()
            return f"ERROR: Invalid subject: {e}"

        obj_id = None
        if object_id is not None or object_name:
            try:
                obj_id = _resolve_entity(cursor, object_id, object_name)
            except ValueError as e:
                conn.close()
                return f"ERROR: Invalid object entity: {e}"

        if obj_id is None and object_literal is None:
            conn.close()
            return "ERROR: Either object (id/name) or object_literal must be provided"

        if source_claim_id is not None:
            cursor.execute("SELECT 1 FROM gms_claims WHERE claim_id = ?", (source_claim_id,))
            if not cursor.fetchone():
                conn.close()
                return f"ERROR: Source claim ID {source_claim_id} does not exist"

        cursor.execute("""
            INSERT INTO gms_relationships (
                subject_entity_id, predicate, object_entity_id, object_literal,
                source_claim_id, valid_from, valid_to
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sub_id, predicate, obj_id, object_literal, source_claim_id, valid_from, valid_to))
        
        rel_id = cursor.lastrowid
        conn.commit()

        cursor.execute("""
            SELECT relationship_id, subject_entity_id, predicate, object_entity_id, object_literal,
                   source_claim_id, valid_from, valid_to, created_at
            FROM gms_relationships
            WHERE relationship_id = ?
        """, (rel_id,))
        row = cursor.fetchone()
        conn.close()

        rel_info = {
            "relationship_id": row[0],
            "subject_entity_id": row[1],
            "predicate": row[2],
            "object_entity_id": row[3],
            "object_literal": row[4],
            "source_claim_id": row[5],
            "valid_from": row[6],
            "valid_to": row[7],
            "created_at": row[8]
        }
        return json.dumps(rel_info, indent=2)

    except Exception as e:
        return f"ERROR: Failed to link entities: {e}"


def tool_mem_get_entity_graph(args: dict) -> str:
    """Retrieve entities and relationships from the graph. If entity_id or name is specified, retrieves the ego network."""
    entity_id = args.get("entity_id")
    name = args.get("name")

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        target_id = None
        if entity_id is not None:
            cursor.execute("SELECT entity_id FROM gms_entities WHERE entity_id = ?", (entity_id,))
            row = cursor.fetchone()
            if row:
                target_id = row["entity_id"]
        elif name:
            cursor.execute("SELECT entity_id FROM gms_entities WHERE name = ?", (name.strip(),))
            row = cursor.fetchone()
            if row:
                target_id = row["entity_id"]

        if target_id is not None:
            cursor.execute("""
                SELECT DISTINCT subject_entity_id AS id FROM gms_relationships WHERE subject_entity_id = ? OR object_entity_id = ?
                UNION
                SELECT DISTINCT object_entity_id AS id FROM gms_relationships WHERE (subject_entity_id = ? OR object_entity_id = ?) AND object_entity_id IS NOT NULL
            """, (target_id, target_id, target_id, target_id))
            related_ids = [r["id"] for r in cursor.fetchall()]
            related_ids.append(target_id)
            related_ids = list(set(related_ids))

            placeholders = ",".join("?" for _ in related_ids)
            cursor.execute(f"SELECT * FROM gms_entities WHERE entity_id IN ({placeholders})", related_ids)
            entities = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT * FROM gms_relationships
                WHERE subject_entity_id = ? OR object_entity_id = ?
            """, (target_id, target_id))
            relationships = [dict(r) for r in cursor.fetchall()]
        else:
            cursor.execute("SELECT * FROM gms_entities")
            entities = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM gms_relationships")
            relationships = [dict(r) for r in cursor.fetchall()]

        conn.close()

        graph = {
            "entities": entities,
            "relationships": relationships
        }
        return json.dumps(graph, indent=2)

    except Exception as e:
        return f"ERROR: Failed to retrieve entity graph: {e}"


def tool_mem_upsert_procedure(args: dict) -> str:
    """Create or update a reusable trigger-action playbook."""
    name = args.get("name", "")
    if not name or not isinstance(name, str) or not name.strip():
        return "ERROR: 'name' is required and must be a non-empty string"
    name = name.strip()

    trigger = args.get("trigger")
    if trigger is None:
        trigger = ""
    trigger = str(trigger)

    action = args.get("action")
    if action is None:
        action = ""
    action = str(action)

    context = args.get("context")
    if context is None:
        context = ""
    context = str(context)

    status = args.get("status")
    if status is None:
        status = "active"
    status = str(status).strip().lower()

    if status not in ("active", "archived"):
        return f"ERROR: Invalid status '{status}'. Must be 'active' or 'archived'."

    source_claim_id = args.get("source_claim_id")
    if source_claim_id is not None:
        try:
            source_claim_id = int(source_claim_id)
        except (ValueError, TypeError):
            return "ERROR: 'source_claim_id' must be an integer"

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        # Validate claim linkage if source_claim_id is provided
        if source_claim_id is not None:
            cursor.execute("SELECT 1 FROM gms_claims WHERE claim_id = ?", (source_claim_id,))
            if not cursor.fetchone():
                conn.close()
                return f"ERROR: Source claim ID {source_claim_id} does not exist"

        cursor.execute("SELECT procedure_id, \"trigger\", action, context, status, source_claim_id FROM gms_procedures WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            proc_id = row[0]
            new_trigger = trigger if "trigger" in args else row[1]
            new_action = action if "action" in args else row[2]
            new_context = context if "context" in args else row[3]
            new_status = status if "status" in args else row[4]
            new_source_claim_id = source_claim_id if "source_claim_id" in args else row[5]

            # Re-validate status
            new_status = str(new_status).strip().lower()
            if new_status not in ("active", "archived"):
                conn.close()
                return f"ERROR: Invalid status '{new_status}'. Must be 'active' or 'archived'."

            # Re-validate claim linkage if it changed
            if new_source_claim_id is not None and new_source_claim_id != row[5]:
                cursor.execute("SELECT 1 FROM gms_claims WHERE claim_id = ?", (new_source_claim_id,))
                if not cursor.fetchone():
                    conn.close()
                    return f"ERROR: Source claim ID {new_source_claim_id} does not exist"

            cursor.execute("""
                UPDATE gms_procedures
                SET "trigger" = ?, action = ?, context = ?, status = ?, source_claim_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE procedure_id = ?
            """, (new_trigger, new_action, new_context, new_status, new_source_claim_id, proc_id))
            procedure_id = proc_id
        else:
            cursor.execute("""
                INSERT INTO gms_procedures (name, "trigger", action, context, status, source_claim_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, trigger, action, context, status, source_claim_id))
            procedure_id = cursor.lastrowid

        conn.commit()

        cursor.execute("SELECT procedure_id, name, \"trigger\", action, context, status, source_claim_id, created_at, updated_at FROM gms_procedures WHERE procedure_id = ?", (procedure_id,))
        updated_row = cursor.fetchone()
        conn.close()

        proc_info = {
            "procedure_id": updated_row[0],
            "name": updated_row[1],
            "trigger": updated_row[2],
            "action": updated_row[3],
            "context": updated_row[4],
            "status": updated_row[5],
            "source_claim_id": updated_row[6],
            "created_at": updated_row[7],
            "updated_at": updated_row[8]
        }
        return json.dumps(proc_info, indent=2)

    except Exception as e:
        return f"ERROR: Failed to upsert procedure: {e}"


def tool_mem_get_procedures(args: dict) -> str:
    """Retrieve procedures from the database, optionally filtered by status, name, or source_claim_id."""
    status = args.get("status")
    name = args.get("name")
    source_claim_id = args.get("source_claim_id")

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT procedure_id, name, \"trigger\", action, context, status, source_claim_id, created_at, updated_at FROM gms_procedures"
        conditions = []
        params = []

        if status is not None:
            conditions.append("status = ?")
            params.append(str(status).strip().lower())
        if name is not None:
            conditions.append("name = ?")
            params.append(str(name).strip())
        if source_claim_id is not None:
            try:
                source_claim_id = int(source_claim_id)
                conditions.append("source_claim_id = ?")
                params.append(source_claim_id)
            except (ValueError, TypeError):
                conn.close()
                return "ERROR: 'source_claim_id' must be an integer"

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        procedures = [dict(r) for r in rows]
        return json.dumps(procedures, indent=2)

    except Exception as e:
        return f"ERROR: Failed to retrieve procedures: {e}"


def tool_mem_list_episodes(args: dict) -> str:
    """List episodic sources with enough metadata to select a source deterministically."""
    limit = args.get("limit")
    type_filter = args.get("type")
    
    limit_val = None
    if limit is not None:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            return "ERROR: 'limit' must be an integer"
            
    if type_filter is not None:
        type_filter = str(type_filter).strip().lower()
        if type_filter not in ("journal", "history"):
            return "ERROR: 'type' must be 'journal' or 'history'"
            
    import re
    sources = []
    
    # 1. Journal
    journal_path = MEM_ROOT / "episodic" / "journal.md"
    if type_filter is None or type_filter == "journal":
        if journal_path.exists():
            try:
                content = journal_path.read_text(errors="replace")
                line_count = len(content.splitlines())
                sources.append({
                    "source": str(journal_path),
                    "date": None,
                    "type": "journal",
                    "size_bytes": journal_path.stat().st_size,
                    "line_count": line_count
                })
            except Exception:
                pass

    # 2. History
    history_dir = MEM_ROOT / "episodic" / "history"
    if type_filter is None or type_filter == "history":
        if history_dir.exists():
            try:
                for p in sorted(history_dir.glob("*.md"), key=lambda x: x.name, reverse=True):
                    stem = p.stem
                    date_val = stem if re.match(r'^\d{4}-\d{2}-\d{2}$', stem) else None
                    content = p.read_text(errors="replace")
                    line_count = len(content.splitlines())
                    sources.append({
                        "source": str(p),
                        "date": date_val,
                        "type": "history",
                        "size_bytes": p.stat().st_size,
                        "line_count": line_count
                    })
            except Exception:
                pass
                
    if limit_val is not None:
        sources = sources[:limit_val]
        
    return json.dumps(sources, indent=2)


def tool_mem_get_episode(args: dict) -> str:
    """Retrieve details or raw content of a specific episodic source by date or source path."""
    import re
    source = args.get("source")
    date = args.get("date")
    mode = args.get("mode", "summary").strip().lower()
    episodic_root = (MEM_ROOT / "episodic").resolve()
    
    if mode not in ("summary", "deep"):
        return "ERROR: 'mode' must be either 'summary' or 'deep'"
        
    source_path = None
    if source:
        s = str(source).strip()
        p = Path(s)
        if p.is_absolute() and p.exists():
            source_path = p
        elif (MEM_ROOT / s).exists():
            source_path = MEM_ROOT / s
        elif (MEM_ROOT / "episodic" / s).exists():
            source_path = MEM_ROOT / "episodic" / s
        elif (MEM_ROOT / "episodic" / "history" / s).exists():
            source_path = MEM_ROOT / "episodic" / "history" / s
        elif (MEM_ROOT / "episodic" / "history" / f"{s}.md").exists():
            source_path = MEM_ROOT / "episodic" / "history" / f"{s}.md"
        else:
            return f"ERROR: Source file '{s}' not found."
    elif date:
        d = str(date).strip()
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
            return "ERROR: 'date' must be in YYYY-MM-DD format"
        p = MEM_ROOT / "episodic" / "history" / f"{d}.md"
        if p.exists():
            source_path = p
        else:
            return f"ERROR: No history file found for date '{d}'"
    else:
        return "ERROR: Either 'date' or 'source' must be provided."

    try:
        resolved_source = source_path.resolve()
    except Exception:
        return "ERROR: Could not resolve episodic source path."

    if episodic_root not in resolved_source.parents and resolved_source != episodic_root:
        return "ERROR: Source must live under the episodic memory root."
        
    try:
        content = resolved_source.read_text(errors="replace")
        lines = content.splitlines()
        line_count = len(lines)
        size_bytes = resolved_source.stat().st_size
        
        # Derive date and type
        stem = resolved_source.stem
        date_val = stem if re.match(r'^\d{4}-\d{2}-\d{2}$', stem) else None
        
        if resolved_source.name == "journal.md":
            source_type = "journal"
        else:
            source_type = "history"
            
        metadata = {
            "source": str(resolved_source),
            "date": date_val,
            "type": source_type,
            "size_bytes": size_bytes,
            "line_count": line_count
        }
        
        if mode == "summary":
            headers = [line.strip() for line in lines if line.strip().startswith("#")]
            excerpt_lines = lines[-20:] if len(lines) > 20 else lines
            excerpt = "\n".join(excerpt_lines)
            
            result = {
                "metadata": metadata,
                "headers": headers,
                "excerpt": excerpt
            }
        else:
            result = {
                "metadata": metadata,
                "raw_text": content
            }
            
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: Failed to read episodic source: {e}"


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
                "agent": {"type": "string", "description": "Calling agent name (e.g. Antigravity, Codex)"},
            },
            "required": ["key", "value"],
        },
    },
    "mem_save_typed": {
        "fn": tool_mem_save_typed,
        "description": "Save a memory fact using typed routing (semantic, operational, procedural, session). Routes dynamically based on keys/values if kind is omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "Memory key"},
                "value": {"type": "string", "description": "Memory value"},
                "kind":  {"type": "string", "description": "Explicit bucket override: semantic, operational, procedural, session"},
                "force": {"type": "boolean", "description": "Overwrite existing value if conflicting"},
                "agent": {"type": "string", "description": "Calling agent name (e.g. Antigravity, Codex)"},
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
        "description": "Return facts from a specific bucket (semantic, operational, procedural, session), optionally filtered by key prefix.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Filter key prefix"},
                "kind":   {"type": "string", "description": "Memory bucket (defaults to semantic): semantic, operational, procedural, session"},
            },
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
    "mem_get_reputations": {
        "fn": tool_mem_get_reputations,
        "description": "Retrieve the trust score and reputation counts of all registered agents.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_get_quarantine": {
        "fn": tool_mem_get_quarantine,
        "description": "Retrieve all quarantined facts that were blocked due to trust violations.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_resolve_quarantine": {
        "fn": tool_mem_resolve_quarantine,
        "description": "Resolve a quarantined fact by promoting it to facts.json or discarding it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":      {"type": "string", "description": "snake_case fact key"},
                "agent_id": {"type": "string", "description": "The agent who proposed the fact"},
                "action":   {"type": "string", "description": "Action to take ('promote' or 'discard')"},
                "agent":    {"type": "string", "description": "The agent resolving the quarantine (e.g. Master, User)"},
            },
            "required": ["key", "agent_id", "action"],
        },
    },
    "mem_get_claims": {
        "fn": tool_mem_get_claims,
        "description": "Retrieve claims from the versioned claim ledger, optionally filtered by kind, key, and status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind":   {"type": "string", "description": "Filter by memory kind (semantic, operational, procedural)"},
                "key":    {"type": "string", "description": "Filter by memory key"},
                "status": {"type": "string", "description": "Filter by claim status (active, superseded, quarantined, discarded)"},
            },
            "required": [],
        },
    },
    "mem_upsert_entity": {
        "fn": tool_mem_upsert_entity,
        "description": "Create or update an entity in the local graph database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Unique name of the entity"},
                "entity_type": {"type": "string", "description": "Type of entity (e.g. Person, Project, Concept)"},
                "summary":     {"type": "string", "description": "Brief description or summary of the entity"},
            },
            "required": ["name"],
        },
    },
    "mem_link_entities": {
        "fn": tool_mem_link_entities,
        "description": "Link two entities with a relationship, optionally referencing a claim id and validity window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject_id":      {"type": "integer", "description": "Entity ID of the subject"},
                "subject_name":    {"type": "string", "description": "Name of the subject entity (auto-created if not exists)"},
                "predicate":       {"type": "string", "description": "The relationship type / predicate (e.g., works_on, member_of)"},
                "object_id":       {"type": "integer", "description": "Entity ID of the object entity"},
                "object_name":     {"type": "string", "description": "Name of the object entity (auto-created if not exists)"},
                "object_literal":  {"type": "string", "description": "Literal value of the object if not referencing another entity"},
                "source_claim_id": {"type": "integer", "description": "Optional ID of the source claim from gms_claims"},
                "valid_from":      {"type": "string", "description": "Optional start timestamp of validity"},
                "valid_to":        {"type": "string", "description": "Optional end timestamp of validity"},
            },
            "required": ["predicate"],
        },
    },
    "mem_get_entity_graph": {
        "fn": tool_mem_get_entity_graph,
        "description": "Retrieve the entity graph. If entity_id or name is specified, retrieves the ego network for that entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "integer", "description": "Filter by entity ID"},
                "name":      {"type": "string", "description": "Filter by entity name"},
            },
            "required": [],
        },
    },
    "mem_upsert_procedure": {
        "fn": tool_mem_upsert_procedure,
        "description": "Create or update a reusable trigger-action playbook.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":            {"type": "string", "description": "Unique name of the procedure"},
                "trigger":         {"type": "string", "description": "The trigger condition or event pattern"},
                "action":          {"type": "string", "description": "The playbook action or sequence of instructions"},
                "context":         {"type": "string", "description": "Optional context or execution environment details"},
                "status":          {"type": "string", "description": "Status of the procedure (active or archived)", "default": "active"},
                "source_claim_id": {"type": "integer", "description": "Optional source claim ID linking to GMS claims ledger"},
            },
            "required": ["name"],
        },
    },
    "mem_get_procedures": {
        "fn": tool_mem_get_procedures,
        "description": "Retrieve procedures from the database, optionally filtered by status, name, or source_claim_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status":          {"type": "string", "description": "Filter by status (active or archived)"},
                "name":            {"type": "string", "description": "Filter by specific name"},
                "source_claim_id": {"type": "integer", "description": "Filter by source claim ID"},
            },
            "required": [],
        },
    },
    "mem_list_episodes": {
        "fn": tool_mem_list_episodes,
        "description": "List episodic sources with enough metadata to select a source deterministically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Optional limit on the number of sources returned"},
                "type":  {"type": "string", "description": "Optional type filter ('journal' or 'history')"},
            },
            "required": [],
        },
    },
    "mem_get_episode": {
        "fn": tool_mem_get_episode,
        "description": "Retrieve details or content of a specific episodic source by date or source path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date":   {"type": "string", "description": "Optional date of history file (YYYY-MM-DD)"},
                "source": {"type": "string", "description": "Optional file path or filename"},
                "mode":   {"type": "string", "description": "Retrieval mode ('summary' or 'deep')", "default": "summary"},
            },
            "required": [],
        },
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
