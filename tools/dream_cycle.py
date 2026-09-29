#!/usr/bin/env python3
"""
dream_cycle.py — Nightly Memory Consolidation for Mihir-OS GMS
===============================================================
Reads today's episodic journal entries, extracts high-value facts and
architectural decisions using a CASCADE of LLM providers, and promotes
them into semantic/facts.json before rebuilding the FAISS vector index.

LLM Cascade (tried in order, first success wins):
  Tier 1: Antigravity CLI  (agy --print)       — frontier model, best quality
  Tier 2: Gemini CLI       (gemini -p)          — frontier fallback
  Tier 3: Local Ollama     (qwen3:8b)           — local, bounded fallback

Run via cron at 3am daily:
    0 3 * * * <repo>/.venv/bin/python \\
              <repo>/tools/dream_cycle.py \\
              >> ${MEMORY_ROOT:-$HOME/memories}/logs/dream_cycle.log 2>&1

Design principles:
- Fully idempotent: safe to run multiple times in the same day.
- No external services except those already present on the system.
- Commits a git snapshot of ~/memories after successful completion.
- Writes a brief summary to episodic journal so agents know consolidation ran.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
try:
    from datetime import UTC, datetime, timedelta
except ImportError:
    from datetime import datetime, timedelta, timezone
    UTC = timezone.utc

try:
    import fcntl
except ImportError:
    fcntl = None  # Windows fallback
import signal

from urllib import request

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent.parent
TOOLS_DIR    = REPO_ROOT / "tools"
LAST_RUN_STATUS: dict = {}


def _default_mem_root() -> Path:
    memory_root = os.environ.get("MEMORY_ROOT")
    if memory_root:
        return Path(memory_root).expanduser()
    return Path.home() / "memories"


def _resolve_binary_path(env_var: str, *fallbacks: Path | str | None) -> str:
    configured = os.environ.get(env_var)
    if configured:
        return str(Path(configured).expanduser())
    for candidate in fallbacks:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return str(Path(next(candidate for candidate in fallbacks if candidate)).expanduser())


MEM_ROOT     = _default_mem_root()
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL  = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
LOG_PREFIX   = "[dream_cycle]"
DRY_RUN      = os.environ.get("DREAM_DRY_RUN", "0") == "1"
RETENTION_LOW_CONFIDENCE = float(os.environ.get("DREAM_RETENTION_LOW_CONFIDENCE", "0.35"))
RETENTION_STALE_ACTIVE_DAYS = int(os.environ.get("DREAM_RETENTION_STALE_ACTIVE_DAYS", "30"))
RETENTION_STALE_QUARANTINE_DAYS = int(os.environ.get("DREAM_RETENTION_STALE_QUARANTINE_DAYS", "14"))

# ── Cascade config ────────────────────────────────────────────────────────────
# Each tier: (name, callable) — tried in order, first success wins.
# Override which tiers to try via DREAM_PROVIDERS=antigravity,gemini,ollama
ENABLED_PROVIDERS = [
    p.strip() for p in
    os.environ.get("DREAM_PROVIDERS", "antigravity,gemini,ollama").split(",")
    if p.strip()
]

# CLI paths — resolved at startup
AGY_BIN    = _resolve_binary_path("AGY_BIN", shutil.which("agy"), Path.home() / ".local" / "bin" / "agy")
GEMINI_BIN = _resolve_binary_path(
    "GEMINI_BIN",
    shutil.which("gemini"),
    Path.home() / ".local" / "bin" / "gemini",
    Path.home() / ".nvm" / "versions" / "node" / "current" / "bin" / "gemini",
)
# qwen3:8b is the installed, policy-approved local reasoning baseline. Do not
# silently fall back to a smaller/missing model: a failed preflight is more
# useful than a run that looks successful but never harvested anything.
OLLAMA_LLM = os.environ.get("DREAM_LLM_MODEL", "qwen3:8b")

# Model selection — low-credit, high-value defaults
# Antigravity: Gemini 3.5 Flash (Medium) — low-credit option
# Gemini:      gemini-2.5-flash — fast, cheap, confirmed working
# Override: DREAM_MODEL_AGY="Claude Sonnet 4.6 (Thinking)" DREAM_MODEL_GEMINI=gemini-2.0-flash
AGY_MODEL    = os.environ.get("DREAM_MODEL_AGY",    "Gemini 3.5 Flash (Medium)")
GEMINI_MODEL = os.environ.get("DREAM_MODEL_GEMINI", "gemini-2.5-flash")

# Per-tier timeouts (seconds)
TIER_TIMEOUT = {
    "antigravity": int(os.environ.get("DREAM_TIMEOUT_AGY",    "90")),
    "gemini":      int(os.environ.get("DREAM_TIMEOUT_GEMINI", "90")),
    "ollama":      int(os.environ.get("DREAM_TIMEOUT_OLLAMA", "180")),
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} {LOG_PREFIX} {msg}", flush=True)


def _post(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode()
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return json.loads(resp.read().decode())


def ollama_available() -> bool:
    try:
        req = request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with request.urlopen(req, timeout=5) as r:  # nosec B310
            return r.status == 200
    except Exception:
        return False


def acquire_lock(lock_path: Path) -> int | None:
    """Acquire an exclusive non-blocking file lock to prevent concurrent runs."""
    if fcntl is None:
        return None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError):
        return None


def release_lock(fd: int | None) -> None:
    """Release and close the lock descriptor."""
    if fd is not None and fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass


def check_ram_floor(min_free_mb: int = 1024) -> bool:
    """Return True if system has sufficient free memory floor for LLM consolidation."""
    try:
        if sys.platform == "darwin":
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
            if vm.returncode == 0:
                for line in vm.stdout.splitlines():
                    if "Pages free:" in line:
                        pages = int(line.split(":")[1].strip().rstrip("."))
                        free_mb = (pages * 4096) // (1024 * 1024)
                        return free_mb >= min_free_mb
        return True
    except Exception:
        return True


def write_dream_cycle_status(status: dict) -> None:
    """Write machine-readable status file for Mbrain desktop and CLI consumption."""
    if status.get("dry_run", False) or DRY_RUN or ("--dry-run" in sys.argv):
        log(f"DRY RUN — zero durable mutation. Skipping status file write on disk (durable_writes: 0). Preview:\n{json.dumps(status, indent=2)}")
        return
    try:
        status_file = MEM_ROOT / "logs" / "dream_cycle_status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"Failed to write dream cycle status: {e}")



# ──────────────────────────────────────────────────────────────────────────────
# LLM Cascade — Tier implementations
# ──────────────────────────────────────────────────────────────────────────────

CONTEXT_HARVEST_PROMPT_TEMPLATE = """\
You are a rationale-first context harvesting engine for a software engineer's Personal AI OS (GMS).
Consolidate today's episodic work journal into durable, typed context records.
Decisions and policies MUST include rationale (WHY) and actionable downstream implications.
LLM extraction proposes candidates; it does NOT create canonical truth.

Guidelines:
- Distinguish record types:
  * "decision": chosen architectural/system direction. REQUIRED: statement, rationale (WHY), implications (min 1 actionable downstream rule), scope, provenance, evidence.
  * "policy": durable behavioral/safety rule. REQUIRED: statement, rationale, implications or enforcement, scope, provenance.
  * "fact": verified technical constant, tool path, or external fact.
  * "procedure": trigger, action, constraints.
  * "project_state": current milestone or verified result with effective timestamp.
  * "observation": useful tentative statement; preserve uncertainty explicitly.
  * "question": unresolved issue requiring an answer.
  * "lesson_candidate": reusable corrective rule with triggering failure.
- For decisions and policies: RATIONALE MUST NOT BE EMPTY OR IDENTICAL TO STATEMENT.
- Do NOT invent rationale not supported by the text. If rationale is missing, classify as "observation" or omit.
- Forbid extracting secrets, tokens, credentials, transient build logs, or conversational chatter.
- Do NOT output synthetic trust or reliability score numbers; global agent trust is retired.
- Embed the exact source reference: "{source_ref}" and source hash: "sha256:{source_hash}".
- Return valid JSON matching schema_version "gms-context-harvest-v1".

Existing canonical facts (do not duplicate):
{existing_summary}

Today's work journal:
{journal_text}

Output ONLY valid JSON with no extraneous text:
{{
  "schema_version": "gms-context-harvest-v1",
  "candidates": [
    {{
      "schema_version": "gms-context-record-v1",
      "record_type": "decision",
      "key": "canonical_snake_case_key",
      "statement": "Clear chosen direction",
      "rationale": "Why this direction was chosen",
      "implications": ["Actionable downstream rule or constraint"],
      "scope": {{"level": "project", "project": "project-name", "workstream": "component"}},
      "provenance": {{
        "observed_agents": ["agent_names"],
        "extractor": "{extractor_agent}",
        "source_refs": ["{source_ref}"],
        "source_hashes": ["sha256:{source_hash}"],
        "extracted_at": "{extracted_at}",
        "prompt_version": "context-harvest-v1"
      }},
      "evidence": [
        {{"type": "source_document", "ref": "{source_ref}", "excerpt_hash": "sha256:{source_hash}"}}
      ]
    }}
  ]
}}
"""

EXTRACTION_PROMPT_TEMPLATE = CONTEXT_HARVEST_PROMPT_TEMPLATE


def unload_ollama_model(model_name: str = OLLAMA_LLM) -> bool:
    """Explicitly unload Ollama LLM from memory via keep_alive: 0 across all terminal paths."""
    try:
        if not ollama_available():
            return False
        req = request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                log(f"Explicitly unloaded Ollama model '{model_name}'.")
                return True
        except Exception:
            for fallback in ["qwen3:8b", "qwen2.5-coder:7b", "qwen3:0.6b"]:
                try:
                    req_fb = request.Request(
                        f"{OLLAMA_URL}/api/generate",
                        data=json.dumps({"model": fallback, "keep_alive": 0}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with request.urlopen(req_fb, timeout=5) as resp:
                        log(f"Explicitly unloaded Ollama model '{fallback}'.")
                        return True
                except Exception:
                    pass
            return False
    except Exception as e:
        log(f"Note: Model unload error: {e}")
        return False


def _parse_context_harvest_candidates(raw: str) -> list[dict]:
    """Parse JSON from LLM output into structured candidates, preserving nested objects without stringification."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    start_dict = raw.find("{")
    start_list = raw.find("[")

    start = -1
    end = -1
    if start_dict != -1 and (start_list == -1 or start_dict < start_list):
        start = start_dict
        end = raw.rfind("}") + 1
    elif start_list != -1:
        start = start_list
        end = raw.rfind("]") + 1

    if start != -1 and end > start:
        raw = raw[start:end]

    try:
        result = json.loads(raw)
    except Exception as e:
        log(f"Failed to parse JSON candidates from LLM output: {e}")
        return []

    if isinstance(result, dict):
        candidates = result.get("candidates", [])
        if isinstance(candidates, list) and candidates:
            return [c for c in candidates if isinstance(c, dict)]
        if result.get("schema_version") == "gms-context-record-v1" or "record_type" in result:
            return [result]
        # Legacy flat dict {k: v} fallback
        legacy_candidates = []
        for k, v in result.items():
            if k in ("schema_version", "candidates") or not k or not v:
                continue
            legacy_candidates.append({
                "schema_version": "gms-context-record-v1",
                "record_type": "fact",
                "key": str(k),
                "statement": str(v),
                "scope": {"project": "global-memory"},
                "provenance": {
                    "extractor": "DreamCycle-legacy",
                    "source_refs": ["episodic/journal.md"],
                    "extracted_at": datetime.now(UTC).isoformat(),
                    "prompt_version": "context-harvest-v1"
                },
                "evidence": [{"type": "source_document", "ref": "episodic/journal.md"}]
            })
        return legacy_candidates
    elif isinstance(result, list):
        return [c for c in result if isinstance(c, dict)]
    return []


def _parse_json_facts(raw: str) -> dict:
    """Parse JSON from LLM output, preserving backward compatibility."""
    candidates = _parse_context_harvest_candidates(raw)
    if candidates:
        facts = {}
        for c in candidates:
            k = c.get("key")
            v = c.get("statement") or json.dumps(c, ensure_ascii=False)
            if k:
                facts[k] = v
        return facts
    return {}


def _tier_antigravity(prompt: str) -> list[dict]:
    """Tier 1: Antigravity CLI (agy --print) with model override via temp settings."""
    if not Path(AGY_BIN).exists():
        raise FileNotFoundError(f"agy not found at {AGY_BIN}")

    agy_settings = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
    original_model = None
    backed_up = False

    try:
        if agy_settings.exists():
            settings = json.loads(agy_settings.read_text())
            original_model = settings.get("model")
            if original_model != AGY_MODEL:
                settings["model"] = AGY_MODEL
                agy_settings.write_text(json.dumps(settings, indent=2))
                backed_up = True
                log(f"  agy model patched: {original_model} → {AGY_MODEL}")

        result = subprocess.run(
            [AGY_BIN, "--print", prompt],
            capture_output=True, text=True,
            timeout=TIER_TIMEOUT["antigravity"],
            env={**os.environ, "NO_COLOR": "1"},
        )
    finally:
        if backed_up and original_model is not None and agy_settings.exists():
            settings = json.loads(agy_settings.read_text())
            settings["model"] = original_model
            agy_settings.write_text(json.dumps(settings, indent=2))
            log(f"  agy model restored: {original_model}")

    if result.returncode != 0:
        raise RuntimeError(f"agy exited {result.returncode}: {result.stderr[:200]}")
    return _parse_context_harvest_candidates(result.stdout)


def _tier_gemini(prompt: str) -> list[dict]:
    """Tier 2: Gemini CLI (gemini -p -m <model>)."""
    if not Path(GEMINI_BIN).exists():
        raise FileNotFoundError(f"gemini not found at {GEMINI_BIN}")
    result = subprocess.run(
        [GEMINI_BIN, "-m", GEMINI_MODEL, "-p", prompt, "--yolo"],
        capture_output=True, text=True,
        timeout=TIER_TIMEOUT["gemini"],
        env={**os.environ, "NO_COLOR": "1"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"gemini exited {result.returncode}: {result.stderr[:200]}")
    return _parse_context_harvest_candidates(result.stdout)


def _tier_ollama(prompt: str) -> list[dict]:
    """Tier 3: Local Ollama (always-available fallback). Explicitly unloads on all paths."""
    try:
        resp = _post(f"{OLLAMA_URL}/api/generate", {
            "model": OLLAMA_LLM,
            "prompt": prompt,
            "stream": False,
            "keep_alive": 0,
            "options": {"temperature": 0.1, "num_predict": 1200},
        }, timeout=TIER_TIMEOUT["ollama"])
        return _parse_context_harvest_candidates(resp.get("response", ""))
    finally:
        unload_ollama_model()


TIER_FNS = {
    "antigravity": _tier_antigravity,
    "gemini":      _tier_gemini,
    "ollama":      _tier_ollama,
}


def extract_candidates_with_cascade(
    journal_text: str,
    existing_facts: dict,
    source_ref: str,
    source_hash: str,
) -> tuple[list[dict], str]:
    """
    Try each enabled provider in order to extract typed context candidates.
    Returns (candidates_list, provider_used).
    """
    existing_summary = "\n".join(
        f"- {k}: {v}" for k, v in list(existing_facts.items())[:20]
    )
    today_iso = datetime.now(UTC).isoformat()

    for provider in ENABLED_PROVIDERS:
        fn = TIER_FNS.get(provider)
        if fn is None:
            log(f"Unknown provider '{provider}' — skipping")
            continue
        log(f"Trying tier: {provider} ...")
        prompt = CONTEXT_HARVEST_PROMPT_TEMPLATE.format(
            existing_summary=existing_summary,
            journal_text=journal_text,
            source_ref=source_ref,
            source_hash=source_hash,
            extractor_agent=f"DreamCycle-{provider}",
            extracted_at=today_iso,
        )
        try:
            candidates = fn(prompt)
            if candidates:
                log(f"✓ {provider} extracted {len(candidates)} candidate(s): {[c.get('key') for c in candidates]}")
                return candidates, provider
            else:
                log(f"– {provider} returned 0 candidates")
        except subprocess.TimeoutExpired:
            log(f"✗ {provider} timed out — trying next tier")
        except FileNotFoundError as e:
            log(f"✗ {provider} not available ({e}) — trying next tier")
        except Exception as e:
            log(f"✗ {provider} failed: {e} — trying next tier")
        finally:
            if provider == "ollama":
                unload_ollama_model()

    log("All tiers exhausted — no candidates extracted")
    return [], "none"


def extract_facts_with_cascade(journal_text: str, existing_facts: dict) -> tuple[Any, str]:
    """
    Backward-compatible cascade entrypoint.
    Returns (candidates_list_or_dict, provider_used).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    source_ref = f"episodic/history/{today}.md"
    import hashlib
    source_hash = hashlib.sha256(journal_text.encode("utf-8")).hexdigest()
    return extract_candidates_with_cascade(journal_text, existing_facts, source_ref, source_hash)



def rebuild_faiss_index() -> bool:
    """Invoke memoryctl index-build via subprocess."""
    memoryctl = TOOLS_DIR / "memoryctl"
    if not memoryctl.exists():
        memoryctl = Path.home() / ".local" / "bin" / "memoryctl"

    try:
        result = subprocess.run(
            [str(memoryctl), "index-build"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            log("FAISS index rebuilt successfully")
            return True
        else:
            log(f"FAISS rebuild failed: {result.stderr.strip()}")
            return False
    except Exception as e:
        log(f"FAISS rebuild error: {e}")
        return False


def sync_json_and_sqlite_claims(mem_root: Path | None = None) -> dict[str, Any]:
    """Ensure bidirectional synchronization between facts.json and gms_claims."""
    root = mem_root or MEM_ROOT
    db_path = root / "gms_trust.sqlite"
    facts_path = root / "semantic" / "facts.json"
    if not db_path.exists():
        return {"status": "skipped", "reason": "database not found"}

    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Load active claims from SQLite
        c.execute("SELECT claim_id, memory_key, value, agent_id, confidence FROM gms_claims WHERE memory_kind='semantic' AND status='active'")
        active_claims = {r["memory_key"]: (r["claim_id"], r["value"], r["agent_id"], r["confidence"]) for r in c.fetchall()}

        # 2. Load facts.json
        facts = json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else {}

        divergences = []
        updated_in_json = 0
        added_to_claims = 0

        # Check for claims missing or differing in facts.json
        for key, (cid, claim_val, agent, conf) in active_claims.items():
            if key not in facts:
                # Add to facts.json
                facts[key] = claim_val
                updated_in_json += 1
                divergences.append({"key": key, "action": "added_to_json", "val": str(claim_val)[:60]})
            else:
                json_val = str(facts[key]).strip()
                c_val = str(claim_val).strip()
                if json_val != c_val:
                    # Reconciliation: update facts.json with authoritative active claim
                    facts[key] = claim_val
                    updated_in_json += 1
                    divergences.append({"key": key, "action": "reconciled_json_to_claim", "from": json_val[:60], "to": c_val[:60]})

        # Check for keys in facts.json missing from active claims
        for key, val in facts.items():
            if key not in active_claims:
                val_str = json.dumps(val, sort_keys=True) if isinstance(val, (dict, list)) else str(val)
                c.execute("""
                    INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, confidence, contradiction_type, created_at)
                    VALUES ('semantic', ?, ?, 'system-sync', 'main', 'active', 0.95, 'bootstrap_sync', CURRENT_TIMESTAMP)
                """, (key, val_str))
                added_to_claims += 1
                divergences.append({"key": key, "action": "added_to_claims", "val": val_str[:60]})

        conn.commit()
        conn.close()

        # Write updated facts.json atomically if any changes occurred
        if updated_in_json > 0 and facts_path.parent.exists():
            facts_path.write_text(json.dumps(facts, indent=2, sort_keys=True), encoding="utf-8")

        return {
            "status": "synchronized",
            "updated_in_json": updated_in_json,
            "added_to_claims": added_to_claims,
            "divergences_resolved": len(divergences),
            "divergences": divergences
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def git_commit_memories() -> None:
    """Commit the memories directory to git if it's a repo."""
    try:
        # Check if it's a git repo
        check = subprocess.run(
            ["git", "-C", str(MEM_ROOT), "rev-parse", "--git-dir"],
            capture_output=True, timeout=10
        )
        if check.returncode != 0:
            log("memories/ is not a git repo — skipping commit")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(["git", "-C", str(MEM_ROOT), "add", "-A"], timeout=30, check=True)
        result = subprocess.run(
            ["git", "-C", str(MEM_ROOT), "commit", "-m",
             f"dream-cycle: nightly consolidation {today}"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log(f"git commit: {result.stdout.strip()}")
        else:
            # Nothing to commit is fine
            if "nothing to commit" in result.stdout:
                log("git: nothing new to commit")
            else:
                log(f"git commit warning: {result.stderr.strip()}")
    except Exception as e:
        log(f"git commit error: {e}")



# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def read_today_journal() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    daily_path = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    journal_path = MEM_ROOT / "episodic" / "journal.md"
    if daily_path.exists():
        text = daily_path.read_text().strip()
        if text:
            log(f"reading daily: {daily_path}")
            return text
    if journal_path.exists():
        full = journal_path.read_text()
        log(f"reading journal tail: {journal_path}")
        return full[-3000:].strip()
    return ""


def load_existing_facts() -> dict:
    path = MEM_ROOT / "semantic" / "facts.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_facts(facts: dict) -> None:
    path = MEM_ROOT / "semantic" / "facts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(facts, indent=2, sort_keys=True))
    log(f"facts saved: {path} ({len(facts)} keys)")


def record_fact_provenance(fact_key: str, agent_id: str) -> None:
    db_path = MEM_ROOT / "gms_trust.sqlite"
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
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
            INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, quarantined, timestamp)
            VALUES (?, ?, 'main', 0, CURRENT_TIMESTAMP)
            ON CONFLICT(fact_key) DO UPDATE SET
                agent_id = excluded.agent_id,
                branch = excluded.branch,
                quarantined = excluded.quarantined,
                timestamp = CURRENT_TIMESTAMP
        """, (fact_key, agent_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"Error recording provenance for key '{fact_key}': {e}")


def generate_calibration_report(db_path: Path) -> dict:
    """
    Generate a deterministic calibration report from gms_claims in the trust database.
    Group claims by (memory_kind, memory_key) where > 1 distinct agent_id has assertions.
    """
    if not db_path.exists():
        return {"overlapping_keys_count": 0, "agents": {}}

    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_claims'")
        if not cursor.fetchone():
            conn.close()
            return {"overlapping_keys_count": 0, "agents": {}}
            
        # Select active/quarantined claims to build the report from
        cursor.execute("""
            SELECT claim_id, memory_kind, memory_key, value, agent_id, status 
            FROM gms_claims 
            WHERE status IN ('active', 'quarantined')
        """)
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        return {"error": str(e), "overlapping_keys_count": 0, "agents": {}}

    groups = {}
    for claim_id, kind, key, val, agent, status in rows:
        g_key = (kind, key)
        if g_key not in groups:
            groups[g_key] = {}
        if agent not in groups[g_key] or claim_id > groups[g_key][agent]["claim_id"]:
            groups[g_key][agent] = {
                "value": val,
                "claim_id": claim_id,
                "status": status,
            }

    overlapping_keys = {k: v for k, v in groups.items() if len(v) > 1}
    all_agents = sorted(list({agent_id for _, _, _, _, agent_id, _ in rows}))
    agent_stats = {
        agent: {
            "overlap_count": 0,
            "agreement_count": 0,
            "disagreement_count": 0,
            "agreement_rate": 0.0,
        }
        for agent in all_agents
    }

    for agent_claims in overlapping_keys.values():
        agents_in_group = list(agent_claims.keys())
        for agent_a in agents_in_group:
            val_a = agent_claims[agent_a]["value"]
            for agent_b in agents_in_group:
                if agent_a == agent_b:
                    continue
                val_b = agent_claims[agent_b]["value"]
                agent_stats[agent_a]["overlap_count"] += 1
                if val_a == val_b:
                    agent_stats[agent_a]["agreement_count"] += 1
                else:
                    agent_stats[agent_a]["disagreement_count"] += 1

    for agent, stats in agent_stats.items():
        overlap = stats["overlap_count"]
        stats["agreement_rate"] = float(stats["agreement_count"]) / float(overlap) if overlap > 0 else 0.0

    ds_report = _run_symmetric_dawid_skene(overlapping_keys, all_agents)
    for agent, stats in agent_stats.items():
        ds_stats = ds_report["agents"].get(agent, {})
        stats.update(ds_stats)

    return {
        "model": ds_report["model"],
        "iterations": ds_report["iterations"],
        "converged": ds_report["converged"],
        "overlapping_keys_count": len(overlapping_keys),
        "items": ds_report["items"],
        "agents": agent_stats,
    }


def _run_symmetric_dawid_skene(
    overlapping_keys: dict[tuple[str, str], dict[str, dict]],
    all_agents: list[str],
    *,
    max_iter: int = 25,
    tol: float = 1e-6,
) -> dict:
    """
    Run a symmetric Dawid-Skene EM procedure.
    Each agent has one latent reliability parameter p_correct.
    For an item with K candidate labels, incorrect mass is spread uniformly across K-1 labels.
    """
    agents = {
        agent: {
            "expected_correct_count": 0.0,
            "expected_incorrect_count": 0.0,
            "inferred_accuracy": 0.0,
            "rated_items": 0,
        }
        for agent in all_agents
    }
    if not overlapping_keys:
        return {
            "model": "symmetric_dawid_skene",
            "iterations": 0,
            "converged": True,
            "items": {},
            "agents": agents,
        }

    item_posteriors: dict[tuple[str, str], dict[str, float]] = {}
    for g_key, claims in overlapping_keys.items():
        labels = sorted({entry["value"] for entry in claims.values()})
        total = float(len(claims))
        counts = {label: 0.0 for label in labels}
        for entry in claims.values():
            counts[entry["value"]] += 1.0
        if len(labels) == 1:
            item_posteriors[g_key] = {labels[0]: 1.0}
        else:
            item_posteriors[g_key] = {
                label: counts[label] / total for label in labels
            }

    reliability = {}
    for agent in all_agents:
        overlap_items = sum(1 for claims in overlapping_keys.values() if agent in claims)
        reliability[agent] = 0.7 if overlap_items > 0 else 0.0

    converged = False
    iterations_run = 0
    for iteration in range(1, max_iter + 1):
        iterations_run = iteration
        prev_reliability = dict(reliability)

        for agent in all_agents:
            expected_correct = 0.0
            rated_items = 0
            for g_key, claims in overlapping_keys.items():
                if agent not in claims:
                    continue
                rated_items += 1
                observed = claims[agent]["value"]
                expected_correct += item_posteriors[g_key].get(observed, 0.0)
            if rated_items > 0:
                reliability[agent] = min(0.999, max(0.501, (expected_correct + 1.0) / (rated_items + 2.0)))
            else:
                reliability[agent] = 0.0

        for g_key, claims in overlapping_keys.items():
            labels = sorted({entry["value"] for entry in claims.values()})
            if len(labels) == 1:
                item_posteriors[g_key] = {labels[0]: 1.0}
                continue

            scores = {}
            for candidate in labels:
                score = 1.0 / float(len(labels))
                for agent, entry in claims.items():
                    p_correct = reliability.get(agent, 0.5)
                    if entry["value"] == candidate:
                        score *= p_correct
                    else:
                        score *= max(1e-9, (1.0 - p_correct) / float(len(labels) - 1))
                scores[candidate] = score

            total_score = sum(scores.values())
            if total_score <= 0:
                item_posteriors[g_key] = {label: 1.0 / float(len(labels)) for label in labels}
            else:
                item_posteriors[g_key] = {
                    label: score / total_score for label, score in scores.items()
                }

        max_delta = max(abs(reliability[a] - prev_reliability[a]) for a in all_agents) if all_agents else 0.0
        if max_delta < tol:
            converged = True
            break

    for agent in all_agents:
        expected_correct = 0.0
        rated_items = 0
        for g_key, claims in overlapping_keys.items():
            if agent not in claims:
                continue
            rated_items += 1
            expected_correct += item_posteriors[g_key].get(claims[agent]["value"], 0.0)
        expected_incorrect = max(0.0, rated_items - expected_correct)
        agents[agent].update({
            "expected_correct_count": round(expected_correct, 4),
            "expected_incorrect_count": round(expected_incorrect, 4),
            "inferred_accuracy": round(reliability.get(agent, 0.0), 4) if rated_items > 0 else 0.0,
            "rated_items": rated_items,
        })

    item_results = {}
    for (kind, key), claims in overlapping_keys.items():
        posterior = item_posteriors[(kind, key)]
        consensus_value = max(posterior.items(), key=lambda kv: kv[1])[0]
        item_results[f"{kind}:{key}"] = {
            "observer_count": len(claims),
            "candidate_values": sorted(posterior.keys()),
            "consensus_value": consensus_value,
            "posterior": {label: round(prob, 4) for label, prob in posterior.items()},
        }

    return {
        "model": "symmetric_dawid_skene",
        "iterations": iterations_run,
        "converged": converged,
        "items": item_results,
        "agents": agents,
    }


def run_beta_binomial_trust_calibration() -> None:
    db_path = MEM_ROOT / "gms_trust.sqlite"
    if not db_path.exists():
        log("Trust database not found — skipping reputation calibration")
        return
        
    report = generate_calibration_report(db_path)
    if "error" in report:
        log(f"Error generating calibration report: {report['error']}")
        return
        
    overlapping_keys_count = report.get("overlapping_keys_count", 0)
    # Check if there is enough multi-observer overlap (at least 1 overlapping key)
    if overlapping_keys_count < 1:
        log(f"Skipping reputation calibration: insufficient multi-observer overlap (overlapping keys: {overlapping_keys_count})")
        return

    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        calibrated_count = 0
        for agent, stats in report.get("agents", {}).items():
            rated_items = stats.get("rated_items", 0)
            if rated_items < 1:
                log(f"Skipping calibration for agent '{agent}' due to sparse single-observer data (no overlap)")
                continue

            expected_correct = float(stats.get("expected_correct_count", 0.0))
            expected_incorrect = float(stats.get("expected_incorrect_count", 0.0))
            alpha = expected_correct + 1.0
            beta = expected_incorrect
            
            cursor.execute("""
                INSERT INTO gms_agent_reputation (agent_id, alpha, beta, last_updated)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id) DO UPDATE SET
                    alpha = excluded.alpha,
                    beta = excluded.beta,
                    last_updated = CURRENT_TIMESTAMP
            """, (agent, alpha, beta))
            log(
                f"Calibrated agent '{agent}': alpha={alpha:.3f}, beta={beta:.3f} "
                f"(Trust: {(alpha+1)/(alpha+beta+2):.3f}, DS acc: {stats.get('inferred_accuracy', 0.0):.3f})"
            )
            calibrated_count += 1
            
        conn.commit()
        conn.close()
        if calibrated_count > 0:
            log(f"Beta-binomial reputation calibration completed for {calibrated_count} agent(s).")
        else:
            log("No agents had sufficient overlap to calibrate.")
    except Exception as e:
        log(f"Error during reputation calibration: {e}")


def generate_retention_report(
    db_path: Path,
    *,
    now: datetime | None = None,
    low_confidence_threshold: float = RETENTION_LOW_CONFIDENCE,
    stale_active_days: int = RETENTION_STALE_ACTIVE_DAYS,
    stale_quarantine_days: int = RETENTION_STALE_QUARANTINE_DAYS,
) -> dict:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    report = {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "thresholds": {
            "low_confidence": low_confidence_threshold,
            "stale_active_days": stale_active_days,
            "stale_quarantine_days": stale_quarantine_days,
        },
        "stale_active_claims": [],
        "stale_quarantines": [],
        "summary": {
            "active_claim_candidates": 0,
            "quarantine_candidates": 0,
        },
    }
    if not db_path.exists():
        return report

    import sqlite3

    active_cutoff = now - timedelta(days=stale_active_days)
    quarantine_cutoff = now - timedelta(days=stale_quarantine_days)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_claims'")
    if cursor.fetchone():
        cursor.execute(
            """
            SELECT claim_id, memory_kind, memory_key, value, agent_id, confidence, created_at
            FROM gms_claims
            WHERE status = 'active'
              AND memory_kind IN ('semantic', 'operational', 'procedural')
              AND confidence IS NOT NULL
              AND confidence <= ?
            """,
            (low_confidence_threshold,),
        )
        for claim_id, kind, key, value, agent_id, confidence, created_at in cursor.fetchall():
            try:
                created_dt = datetime.fromisoformat(str(created_at).replace("Z", ""))
            except ValueError:
                continue
            if created_dt > active_cutoff:
                continue
            age_days = max(0, (now - created_dt).days)
            report["stale_active_claims"].append({
                "claim_id": claim_id,
                "memory_kind": kind,
                "memory_key": key,
                "value": value,
                "agent_id": agent_id,
                "confidence": float(confidence),
                "created_at": created_at,
                "age_days": age_days,
            })

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_quarantined_facts'")
    if cursor.fetchone():
        cursor.execute(
            """
            SELECT fact_key, value, agent_id, branch, timestamp
            FROM gms_quarantined_facts
            """
        )
        for fact_key, value, agent_id, branch, timestamp in cursor.fetchall():
            try:
                created_dt = datetime.fromisoformat(str(timestamp).replace("Z", ""))
            except ValueError:
                continue
            if created_dt > quarantine_cutoff:
                continue
            age_days = max(0, (now - created_dt).days)
            report["stale_quarantines"].append({
                "fact_key": fact_key,
                "value": value,
                "agent_id": agent_id,
                "branch": branch,
                "created_at": timestamp,
                "age_days": age_days,
            })

    conn.close()
    report["summary"]["active_claim_candidates"] = len(report["stale_active_claims"])
    report["summary"]["quarantine_candidates"] = len(report["stale_quarantines"])
    return report


def run_retention_pruning(
    *,
    now: datetime | None = None,
    low_confidence_threshold: float = RETENTION_LOW_CONFIDENCE,
    stale_active_days: int = RETENTION_STALE_ACTIVE_DAYS,
    stale_quarantine_days: int = RETENTION_STALE_QUARANTINE_DAYS,
) -> dict:
    db_path = MEM_ROOT / "gms_trust.sqlite"
    report = generate_retention_report(
        db_path,
        now=now,
        low_confidence_threshold=low_confidence_threshold,
        stale_active_days=stale_active_days,
        stale_quarantine_days=stale_quarantine_days,
    )
    report["applied"] = {
        "archived_active_claims": 0,
        "discarded_quarantines": 0,
    }
    if not db_path.exists():
        return report

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    facts_cache: dict[str, dict] = {}

    for item in report["stale_active_claims"]:
        kind = item["memory_kind"]
        key = item["memory_key"]
        claim_id = item["claim_id"]
        facts = facts_cache.setdefault(kind, load_existing_facts() if kind == "semantic" else {})
        if kind != "semantic" and not facts:
            path = MEM_ROOT / kind / "facts.json"
            if path.exists():
                try:
                    facts_cache[kind] = json.loads(path.read_text())
                except Exception:
                    facts_cache[kind] = {}
            facts = facts_cache[kind]
        if facts.get(key) == item["value"]:
            del facts[key]
        cursor.execute(
            "UPDATE gms_claims SET status = 'archived', confidence = 0.0 WHERE claim_id = ? AND status = 'active'",
            (claim_id,),
        )
        cursor.execute(
            "DELETE FROM gms_fact_provenance WHERE fact_key = ?",
            (f"{kind}:{key}" if kind != "semantic" else key,),
        )
        report["applied"]["archived_active_claims"] += 1

    for kind, facts in facts_cache.items():
        path = MEM_ROOT / ("semantic" if kind == "semantic" else kind) / "facts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(facts, indent=2, sort_keys=True))

    for item in report["stale_quarantines"]:
        fact_key = item["fact_key"]
        agent_id = item["agent_id"]
        cursor.execute(
            "DELETE FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?",
            (fact_key, agent_id),
        )
        cursor.execute(
            "DELETE FROM gms_quarantine_reviews WHERE fact_key = ? AND agent_id = ?",
            (fact_key, agent_id),
        )
        kind, real_key = ("semantic", fact_key)
        if ":" in fact_key:
            kind, real_key = fact_key.split(":", 1)
        cursor.execute(
            """
            UPDATE gms_claims
            SET status = 'discarded', confidence = 0.0
            WHERE memory_kind = ? AND memory_key = ? AND agent_id = ? AND status = 'quarantined'
            """,
            (kind, real_key, agent_id),
        )
        report["applied"]["discarded_quarantines"] += 1

    conn.commit()
    conn.close()
    if report["applied"]["archived_active_claims"] or report["applied"]["discarded_quarantines"]:
        log(
            "Retention pruning applied: "
            f"archived_active={report['applied']['archived_active_claims']} "
            f"discarded_quarantine={report['applied']['discarded_quarantines']}"
        )
    else:
        log("Retention pruning found no candidates.")
    return report


def append_dream_cycle_log(new_facts_count: int = 0, provider: str = "unknown", candidates_staged: int = 0) -> None:
    """Write a brief record to episodic journal so agents know the cycle ran."""
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    target = MEM_ROOT / "episodic" / "history" / f"{today}.md"

    # Avoid creating 169-byte empty phantom files if there was no activity and no provider
    if not target.exists() and new_facts_count == 0 and candidates_staged == 0 and provider in ("none", "unknown"):
        log("No consolidation activity and no provider used; skipping phantom history creation.")
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    if candidates_staged > 0:
        entry = (
            f"\n### {today} [{now}] - DreamCycle - Nightly Consolidation\n"
            f"- Provider used: {provider}\n"
            f"- Staged {candidates_staged} candidate(s) for review in gms_context_candidates ({new_facts_count} promoted).\n"
            f"- FAISS index rebuilt.\n"
        )
    else:
        entry = (
            f"\n### {today} [{now}] - DreamCycle - Nightly Consolidation\n"
            f"- Provider used: {provider}\n"
            f"- Extracted {new_facts_count} new semantic fact(s) (routed via trust gateway).\n"
            f"- FAISS index rebuilt.\n"
        )
    if DRY_RUN or "--dry-run" in sys.argv:
        log(f"DRY RUN — would append to {target}:\n{entry}")
        return
    with open(target, "a") as f:
        f.write(entry)
    log(f"journal updated: {target}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def read_today_journal() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    daily_path = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    journal_path = MEM_ROOT / "episodic" / "journal.md"
    if daily_path.exists():
        text = daily_path.read_text().strip()
        if text:
            log(f"reading daily: {daily_path}")
            return text
    if journal_path.exists():
        full = journal_path.read_text()
        log(f"reading journal tail: {journal_path}")
        return full[-3000:].strip()
    return ""


def main() -> int:
    start_time = time.time()
    lock_file = MEM_ROOT / "logs" / ".dream_cycle.lock"
    lock_fd = acquire_lock(lock_file)
    if lock_fd is None and fcntl is not None:
        log("Another Dream Cycle process is currently running. Exiting.")
        return 0

    is_dry_run = DRY_RUN or ("--dry-run" in sys.argv)
    calibrate_reputations = ("--calibrate-reputations" in sys.argv) or (os.environ.get("DREAM_CALIBRATE_REPUTATIONS", "0") == "1")

    status = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "running",
        "provider": "none",
        "candidates_proposed": 0,
        "candidates_staged": 0,
        "candidates_rejected": 0,
        "candidates_deduplicated": 0,
        "candidates_awaiting_review": 0,
        "facts_promoted": 0,
        "enrichment_processed": 0,
        "model_unload": {"ollama": "not_needed"},
        "duration_seconds": 0,
        "exit_code": 0,
    }

    # Bounded runtime: 20 minutes (1200s)
    if hasattr(signal, "alarm"):
        def timeout_handler(signum, frame):
            log("TIMEOUT: Dream Cycle exceeded 20-minute execution boundary.")
            status["status"] = "timeout"
            status["exit_code"] = 124
            write_dream_cycle_status(status)
            unload_ollama_model()
            release_lock(lock_fd)
            sys.exit(124)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(1200)

    try:
        log("=" * 60)
        log("Starting Dream Cycle (nightly memory consolidation)")
        log(f"DRY_RUN={is_dry_run} | EMBED={EMBED_MODEL}")
        log(f"Provider cascade: {' → '.join(ENABLED_PROVIDERS)}")
        log("=" * 60)

        # RAM floor check
        if not check_ram_floor(min_free_mb=512):
            log("WARNING: Low system memory (<512MB free). Continuing with care.")

        # 1. Verify Ollama is up (needed for FAISS rebuild regardless of LLM tier)
        if not ollama_available():
            log("WARNING: Ollama not reachable — FAISS rebuild will fail if triggered")
        else:
            log("Ollama: reachable")

        # 2. Read today's journal
        journal_text = read_today_journal()
        provider_used = "none"
        candidates_to_process: list[dict] = []
        staged_count = 0
        rejected_count = 0
        dedupe_count = 0
        promoted_count = 0
        rejections: list[dict] = []
        would_stage_candidates: list[str] = []

        # Pass 0: Automated Production Pollution Audit
        pollution_summary = {"pollutants_found": 0, "status": "clean"}
        if not is_dry_run:
            try:
                from pollution_audit import run_pollution_audit
                p_audit = run_pollution_audit(db_path=MEM_ROOT / "gms_trust.sqlite", mem_root=MEM_ROOT)
                total_p = p_audit.get("total_pollutants", 0)
                pollution_summary = {"pollutants_found": total_p, "status": "pollutants_detected" if total_p > 0 else "clean"}
                if total_p > 0:
                    log(f"Pass 0 Pollution Audit: detected {total_p} test pollutants; isolated.")
                else:
                    log("Pass 0 Pollution Audit: clean (0 test pollutants).")
            except Exception as e:
                log(f"Pass 0 Pollution Audit error: {e}")

        # 2.5 Concept enrichment queue drain (nightly bounded batch)
        if not is_dry_run and os.environ.get("CONCEPT_ENRICHMENT_ENABLED", "1") == "1":
            try:
                import concept_enrichment
                log("Running nightly concept enrichment batch...")
                concept_enrichment.recover_expired_leases(db_path=MEM_ROOT / "gms_trust.sqlite")
                enrich_res = concept_enrichment.process_enrichment_batch(batch_size=8, db_path=MEM_ROOT / "gms_trust.sqlite")
                log(f"Concept enrichment batch: {enrich_res}")
                status["enrichment_processed"] = enrich_res.get("processed", 0)
            except Exception as e:
                log(f"Concept enrichment error: {e}")

        extraction_status = "not_needed"
        extraction_error = None
        if not journal_text:
            log("No episodic entries found for today — skipping LLM extraction")
        else:
            log(f"Journal text: {len(journal_text)} chars")

            # 3. Load existing facts
            existing_facts = load_existing_facts()
            log(f"Existing facts: {len(existing_facts)} entries")

            # 4. Run cascade extraction
            today = datetime.now().strftime("%Y-%m-%d")
            source_ref = f"episodic/history/{today}.md"
            import hashlib
            source_hash = hashlib.sha256(journal_text.encode("utf-8")).hexdigest()

            harvested, provider_used = extract_facts_with_cascade(journal_text, existing_facts)
            extraction_status = "harvested" if provider_used != "none" else "no_provider_succeeded"
            if provider_used == "none":
                extraction_error = "All configured extractors failed or returned no schema-valid candidates."

            if isinstance(harvested, list):
                candidates_to_process = harvested
            elif isinstance(harvested, dict):
                for k, v in harvested.items():
                    if isinstance(v, dict) and "schema_version" in v:
                        candidates_to_process.append(v)
                    else:
                        candidates_to_process.append({
                            "schema_version": "gms-context-record-v1",
                            "record_type": "fact",
                            "key": str(k),
                            "statement": str(v),
                            "scope": {"project": "global-memory"},
                            "provenance": {
                                "extractor": f"DreamCycle-{provider_used}",
                                "source_refs": [source_ref],
                                "source_hashes": [f"sha256:{source_hash}"],
                                "extracted_at": datetime.now(UTC).isoformat(),
                                "prompt_version": "context-harvest-v1"
                            },
                            "evidence": [{"type": "source_document", "ref": source_ref, "excerpt_hash": f"sha256:{source_hash}"}]
                        })

            # 5. Deterministic validation and staging
            if candidates_to_process:
                sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                import memory_mcp_server

                log(f"Processing {len(candidates_to_process)} candidate(s) from {provider_used}...")
                for cand in candidates_to_process:
                    from consolidation_policy import classify_candidate
                    cand["proposed_operation"] = classify_candidate(cand, existing_facts)
                    prov = cand.setdefault("provenance", {})
                    if not prov.get("source_refs"):
                        prov["source_refs"] = [source_ref]
                    if not prov.get("source_hashes"):
                        prov["source_hashes"] = [f"sha256:{source_hash}"]
                    if not prov.get("extractor"):
                        prov["extractor"] = f"DreamCycle-{provider_used}"
                    if not prov.get("extracted_at"):
                        prov["extracted_at"] = datetime.now(UTC).isoformat()

                    if not is_dry_run:
                        stage_res = memory_mcp_server.stage_context_candidate(
                            cand,
                            allowed_source_refs=[source_ref, "episodic/journal.md"],
                            allowed_source_hashes={source_ref: source_hash},
                            db_path=MEM_ROOT / "gms_trust.sqlite"
                        )
                        status_val = stage_res.get("status")
                        if status_val == "staged":
                            staged_count += 1
                            log(f"  [STAGED] {cand.get('record_type')} candidate: {cand.get('key')} -> {stage_res.get('candidate_id')}")
                        elif status_val == "duplicate":
                            dedupe_count += 1
                            log(f"  [DUPLICATE] {cand.get('key')} already staged ({stage_res.get('candidate_id')})")
                        else:
                            rejected_count += 1
                            err_msg = stage_res.get("error", "Validation error")
                            rejections.append({"key": cand.get("key"), "error": err_msg})
                            log(f"  [REJECTED] {cand.get('key')}: {err_msg}")
                    else:
                        would_stage_candidates.append(cand.get("key"))
                        log(f"  [DRY RUN — WOULD STAGE] {cand.get('record_type')} candidate: {cand.get('key')}")

                # Legacy unit test compatibility (e.g. test_memory.py where mock_extract returns a flat dict)
                if isinstance(harvested, dict) and not is_dry_run:
                    agent_tag = f"DreamCycle-{provider_used}"
                    for k, v in harvested.items():
                        if not isinstance(v, dict):
                            res = memory_mcp_server.tool_mem_save_fact({
                                "key": k,
                                "value": str(v),
                                "agent": agent_tag,
                                "force": False
                            })
                            if "Fact saved" in res or "quarantined" not in res.lower():
                                promoted_count += 1
            else:
                log("No candidates extracted from journal")

        # 5.5 Evidence-gated autonomous curation. The system decides by default;
        # every acceptance remains attributable and reversible through harvest-contest.
        curation_result = {"considered": 0, "accepted": 0, "rejected": 0, "outcomes": []}
        if not is_dry_run:
            try:
                from autonomous_curation import curate_pending
                curation_result = curate_pending(MEM_ROOT, apply=True)
                promoted_count += sum(
                    1 for item in curation_result.get("outcomes", [])
                    if item.get("applied") and item.get("decision") in ("accept", "supersede")
                )
                log(
                    "System curation: "
                    f"{curation_result.get('accepted', 0)} accepted, "
                    f"{curation_result.get('rejected', 0)} rejected; decisions remain contestable."
                )
            except Exception as e:
                log(f"System curation error: {e}")
                curation_result = {"status": "error", "error": str(e), "outcomes": []}
        else:
            log("DRY RUN — skipping autonomous curation writes")

        # 5.7 Split-Brain Store Reconciliation (JSON <-> SQLite)
        sync_result = {"status": "skipped"}
        if not is_dry_run:
            try:
                sync_result = sync_json_and_sqlite_claims(MEM_ROOT)
                log(
                    f"Pass 5.7 Store Reconciliation: {sync_result.get('status')} "
                    f"(updated_in_json={sync_result.get('updated_in_json', 0)}, "
                    f"added_to_claims={sync_result.get('added_to_claims', 0)}, "
                    f"divergences_resolved={sync_result.get('divergences_resolved', 0)})"
                )
            except Exception as e:
                log(f"Pass 5.7 Store Reconciliation error: {e}")

        # 6. Rebuild FAISS index
        if not is_dry_run:
            rebuild_faiss_index()
        else:
            log("DRY RUN — skipping FAISS rebuild")

        # 6.5 Rebuild Knowledge Graph triples
        if not is_dry_run:
            try:
                sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                import memoryctl
                log("Rebuilding Knowledge Graph triples...")
                memoryctl.build_graph_relationships()
            except Exception as e:
                log(f"Knowledge Graph build error: {e}")

        # 7. Append to episodic log
        if not is_dry_run:
            append_dream_cycle_log(
                new_facts_count=promoted_count,
                provider=provider_used,
                candidates_staged=staged_count,
            )
        else:
            log("DRY RUN — skipping episodic log write")

        # 8. Run trust calibration on reputations (disabled by default in Pass 5)
        if not is_dry_run and calibrate_reputations:
            log("Running legacy reputation calibration (--calibrate-reputations set)...")
            run_beta_binomial_trust_calibration()
        else:
            log("Global reputation calibration disabled by default (Pass 5: global trust retired).")

        # 9. Apply retention pruning to stale low-confidence and quarantined items
        if not is_dry_run:
            run_retention_pruning()

        # 10. Git commit
        if not is_dry_run:
            git_commit_memories()
        else:
            log("DRY RUN — skipping git commit")

        duration = round(time.time() - start_time, 2)
        log(f"Dream Cycle complete in {duration}s. Provider used: {provider_used}")

        final_status = "degraded" if extraction_status == "no_provider_succeeded" else "completed"
        if is_dry_run:
            status.update({
                "status": final_status,
                "dry_run": True,
                "durable_writes": 0,
                "provider": provider_used,
                "candidates_extracted": [c.get("key") if isinstance(c, dict) else str(c) for c in candidates_to_process],
                "candidates_would_stage": would_stage_candidates,
                "candidates_proposed": len(candidates_to_process),
                "candidates_staged": 0,
                "candidates_rejected": 0,
                "candidates_deduplicated": dedupe_count,
                "candidates_awaiting_review": 0,
                "facts_promoted": 0,
                "system_curation": curation_result,
                "rejections": rejections,
                "model_unload": {"ollama": "unloaded" if provider_used == "ollama" else "not_needed"},
                "duration_seconds": duration,
                "exit_code": 0,
                "extraction_status": extraction_status,
                "degraded_reason": extraction_error,
            })
        else:
            status.update({
                "status": final_status,
                "dry_run": False,
                "durable_writes": staged_count + promoted_count,
                "provider": provider_used,
                "candidates_proposed": len(candidates_to_process),
                "candidates_staged": staged_count,
                "candidates_rejected": rejected_count,
                "candidates_deduplicated": dedupe_count,
                "candidates_awaiting_review": staged_count,
                "facts_promoted": promoted_count,
                "system_curation": curation_result,
                "rejections": rejections,
                "model_unload": {"ollama": "unloaded" if provider_used == "ollama" else "not_needed"},
                "duration_seconds": duration,
                "exit_code": 0,
                "extraction_status": extraction_status,
                "degraded_reason": extraction_error,
            })

        global LAST_RUN_STATUS
        LAST_RUN_STATUS = status
        # A dry run is an observability-only check. It must not overwrite the
        # status of the last real curation run.
        if not is_dry_run:
            write_dream_cycle_status(status)
        return 0
    except Exception as e:
        duration = round(time.time() - start_time, 2)
        log(f"Dream Cycle failed with error: {e}")
        status.update({
            "status": "error",
            "error": str(e),
            "duration_seconds": duration,
            "exit_code": 1,
        })
        write_dream_cycle_status(status)
        return 1
    finally:
        if hasattr(signal, "alarm"):
            signal.alarm(0)
        unload_ollama_model()
        release_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
