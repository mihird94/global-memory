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
import argparse

try:
    import ollama_preflight
except ImportError:
    ollama_preflight = None


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
    os.environ.get("DREAM_PROVIDERS", "ollama").split(",")
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
# qwen2.5-coder:7b is the installed, policy-approved local reasoning and extraction baseline.
# It provides deterministic JSON compliance without reasoning-loop token starvation.
OLLAMA_LLM = os.environ.get("DREAM_LLM_MODEL", "qwen2.5-coder:7b")

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
        raw_text = resp.read().decode()
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            # Handle possible NDJSON lines if stream was chunked
            lines = [l.strip() for l in raw_text.strip().splitlines() if l.strip()]
            for l in reversed(lines):
                try:
                    d = json.loads(l)
                    if isinstance(d, dict) and ("response" in d or "done" in d):
                        return d
                except Exception:
                    continue
            raise


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
    if status.get("dry_run", False) or status.get("smoke", False) or DRY_RUN or ("--dry-run" in sys.argv) or ("--smoke" in sys.argv):
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
- Choose the most accurate record_type:
  * "decision": Intentional architectural or strategic choices with trade-offs. REQUIRED: statement, rationale (WHY), implications (min 1 actionable downstream rule), scope, provenance, evidence.
  * "procedure": Concrete trigger/workflow/CLI execution recipes. REQUIRED: trigger, action, constraints.
  * "fact": Verified constants, tool paths, or environment specifications. REQUIRED: statement, scope, provenance, evidence.
  * "policy": Durable behavioral or security rules. REQUIRED: statement, rationale, enforcement or implications, scope, provenance.
  * "project_state": current milestone or verified result with effective timestamp.
  * "observation": useful tentative statement; preserve uncertainty explicitly.
  * "lesson_candidate": reusable corrective rule with triggering failure.
- Do NOT classify concrete technical workflows or path setups as decisions; classify them as procedures or facts.
- Reserve "decision" strictly for choices where alternative paths were considered and chosen with rationale.
- For decisions and policies: RATIONALE MUST NOT BE EMPTY OR IDENTICAL TO STATEMENT.
- Do NOT invent rationale not supported by the text. If rationale is missing, classify as "observation" or omit.
- Forbid extracting secrets, tokens, credentials, transient build logs, or conversational chatter.
- Do NOT output synthetic trust or reliability score numbers; global agent trust is retired.
- Extract the 3 to 6 highest-signal candidates. Avoid trivial conversational noise.
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
      "key": "example_architectural_choice",
      "statement": "Clear chosen direction",
      "rationale": "Why this direction was chosen over alternatives",
      "implications": ["Actionable downstream rule or constraint"],
      "scope": {{"level": "project", "project": "project-name", "workstream": "component"}},
      "provenance": {{
        "observed_agents": ["agent_names"],
        "extractor": "{extractor_agent}",
        "source_refs": ["{source_ref}"],
        "source_hashes": ["sha256:{source_hash}"],
        "extracted_at": "{extracted_at}",
        "prompt_version": "context-harvest-v2"
      }},
      "evidence": [
        {{"type": "source_document", "ref": "{source_ref}", "excerpt_hash": "sha256:{source_hash}"}}
      ]
    }},
    {{
      "schema_version": "gms-context-record-v1",
      "record_type": "procedure",
      "key": "example_workflow_recipe",
      "trigger": "When executing or automating workflow X",
      "action": "Run command or CLI script Y",
      "constraints": ["Required precondition or platform constraint"],
      "scope": {{"level": "project", "project": "project-name"}},
      "provenance": {{
        "observed_agents": ["agent_names"],
        "extractor": "{extractor_agent}",
        "source_refs": ["{source_ref}"],
        "source_hashes": ["sha256:{source_hash}"],
        "extracted_at": "{extracted_at}",
        "prompt_version": "context-harvest-v2"
      }}
    }}
  ]
}}
"""

EXTRACTION_PROMPT_TEMPLATE = CONTEXT_HARVEST_PROMPT_TEMPLATE


def confirm_ollama_unload(model_name: str | None = None) -> dict:
    """Explicitly unload Ollama LLM from memory via keep_alive: 0 and verify via /api/ps."""
    target = model_name or OLLAMA_LLM
    if ollama_preflight is not None:
        return ollama_preflight.confirm_model_unload(target, base_url=OLLAMA_URL)
    try:
        if not ollama_available():
            return {"requested": False, "command_sent": False, "confirmed": True, "active_models": []}
        req = request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": target, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                log(f"Explicitly unloaded Ollama model '{target}'.")
                return {"requested": True, "command_sent": resp.status == 200, "confirmed": True, "active_models": []}
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
                        return {"requested": True, "command_sent": resp.status == 200, "confirmed": True, "active_models": []}
                except Exception:
                    pass
            return {"requested": True, "command_sent": False, "confirmed": False, "active_models": []}
    except Exception as e:
        log(f"Note: Model unload error: {e}")
        return {"requested": True, "command_sent": False, "confirmed": False, "active_models": [], "error": str(e)}


def unload_ollama_model(model_name: str = OLLAMA_LLM) -> bool:
    """Explicitly unload Ollama LLM from memory via keep_alive: 0 across all terminal paths."""
    res = confirm_ollama_unload(model_name)
    return bool(res.get("confirmed") or res.get("command_sent"))



def _salvage_json_candidates(raw: str) -> list[dict]:
    """Salvage valid individual candidate dicts from truncated or malformed JSON."""
    cands: list[dict] = []
    idx = 0
    while idx < len(raw):
        start = raw.find("{", idx)
        if start == -1:
            break
        depth = 0
        in_str = False
        escape = False
        end = -1
        for i in range(start, len(raw)):
            ch = raw[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        if end != -1:
            chunk = raw[start:end]
            try:
                obj = json.loads(chunk)
                if isinstance(obj, dict):
                    if "candidates" in obj and isinstance(obj["candidates"], list):
                        for c in obj["candidates"]:
                            if isinstance(c, dict) and c not in cands:
                                cands.append(c)
                    elif obj.get("schema_version") == "gms-context-record-v1" or "record_type" in obj or "key" in obj:
                        if obj not in cands:
                            cands.append(obj)
            except Exception:
                pass
            idx = end
        else:
            idx = start + 1
    return cands


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
        salvaged = _salvage_json_candidates(raw)
        if salvaged:
            log(f"Recovered {len(salvaged)} candidate(s) from truncated JSON")
            return salvaged
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
    # Pre-evict any active models (e.g. idle embedding model) to prevent unified memory contention
    try:
        req = request.Request(f"{OLLAMA_URL}/api/ps", method="GET")
        with request.urlopen(req, timeout=3.0) as ps_resp:
            loaded = json.loads(ps_resp.read().decode("utf-8")).get("models", [])
            for m in loaded:
                m_name = m.get("name", "")
                if m_name and m_name != OLLAMA_LLM:
                    unload_ollama_model(m_name)
    except Exception:
        pass

    try:
        resp = _post(f"{OLLAMA_URL}/api/generate", {
            "model": OLLAMA_LLM,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "keep_alive": 0,
            "options": {"temperature": 0.1, "num_predict": 2048, "num_ctx": 8192},
        }, timeout=TIER_TIMEOUT["ollama"])
        raw = resp.get("response", "")
        if not raw and resp.get("thinking"):
            raw = resp.get("thinking", "")
        return _parse_context_harvest_candidates(raw)
    finally:
        confirm_ollama_unload(OLLAMA_LLM)


TIER_FNS = {
    "antigravity": _tier_antigravity,
    "gemini":      _tier_gemini,
    "ollama":      _tier_ollama,
}


def _redact_safe_message(msg: str) -> str:
    """Redact secrets, bearer tokens, API keys, file paths with secrets, and truncate."""
    if not msg:
        return ""
    import re
    redacted = re.sub(r"(?:api_?key|bearer|token|secret|password)[=:\s]+[A-Za-z0-9_\-\.]{8,}", "[REDACTED]", str(msg), flags=re.IGNORECASE)
    if "Traceback (most recent call last):" in redacted:
        redacted = redacted.split("Traceback (most recent call last):")[-1].strip().splitlines()[-1]
    redacted = re.sub(r"/Users/[^/\s]+", "~", redacted)
    redacted = " ".join(redacted.split())
    return redacted[:120]


PROVIDER_MODELS = {
    "antigravity": AGY_MODEL,
    "gemini": GEMINI_MODEL,
    "ollama": OLLAMA_LLM,
}

LAST_PROVIDER_ATTEMPTS: list[dict[str, Any]] = []


def _parse_context_harvest_candidates_with_error(raw: str) -> tuple[list[dict], str | None]:
    """Parse JSON from LLM output into structured candidates, returning (candidates, parse_error)."""
    raw = (raw or "").strip()
    if not raw:
        return [], "Empty output from provider"

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
        salvaged = _salvage_json_candidates(raw)
        if salvaged:
            return salvaged, None
        return [], f"Failed to parse JSON candidates from LLM output: {e}"

    if isinstance(result, dict):
        candidates = result.get("candidates", [])
        if isinstance(candidates, list) and candidates:
            return [c for c in candidates if isinstance(c, dict)], None
        if result.get("schema_version") == "gms-context-record-v1" or "record_type" in result:
            return [result], None
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
        return legacy_candidates, None
    elif isinstance(result, list):
        return [c for c in result if isinstance(c, dict)], None
    return [], "Unrecognized JSON candidate format"


def _evaluate_provider_attempt(
    provider: str,
    prompt: str,
    source_ref: str,
    source_hash: str,
) -> tuple[list[dict], dict[str, Any]]:
    """Execute extraction for a specific provider and capture a bounded structured attempt record."""
    model_name = PROVIDER_MODELS.get(provider, provider)
    t0 = time.perf_counter()

    # Preflight checks
    if provider == "antigravity" and not Path(AGY_BIN).exists():
        dur = round(time.perf_counter() - t0, 3)
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": "unavailable",
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": "BINARY_NOT_FOUND",
            "safe_message": _redact_safe_message(f"agy not found at {AGY_BIN}"),
        }
    elif provider == "gemini" and not Path(GEMINI_BIN).exists():
        dur = round(time.perf_counter() - t0, 3)
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": "unavailable",
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": "BINARY_NOT_FOUND",
            "safe_message": _redact_safe_message(f"gemini not found at {GEMINI_BIN}"),
        }
    elif provider == "ollama":
        if not ollama_available():
            dur = round(time.perf_counter() - t0, 3)
            return [], {
                "provider": provider,
                "model": model_name,
                "outcome": "unavailable",
                "duration_seconds": dur,
                "candidate_count": 0,
                "error_code": "SERVICE_UNAVAILABLE",
                "safe_message": "Ollama service unreachable",
            }
        if ollama_preflight is not None:
            m_ok, _ = ollama_preflight.check_model_available(OLLAMA_LLM)
            if not m_ok:
                dur = round(time.perf_counter() - t0, 3)
                return [], {
                    "provider": provider,
                    "model": model_name,
                    "outcome": "unavailable",
                    "duration_seconds": dur,
                    "candidate_count": 0,
                    "error_code": "MODEL_NOT_INSTALLED",
                    "safe_message": _redact_safe_message(f"Model {OLLAMA_LLM} not installed in Ollama"),
                }

    fn = TIER_FNS.get(provider)
    if fn is None:
        dur = round(time.perf_counter() - t0, 3)
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": "unavailable",
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": "UNKNOWN_PROVIDER",
            "safe_message": f"Provider '{provider}' is unknown",
        }

    try:
        raw_or_cands = fn(prompt)
        dur = round(time.perf_counter() - t0, 3)

        if not raw_or_cands:
            return [], {
                "provider": provider,
                "model": model_name,
                "outcome": "empty",
                "duration_seconds": dur,
                "candidate_count": 0,
                "error_code": "ZERO_CANDIDATES",
                "safe_message": "Provider returned zero candidates",
            }

        import schemas
        valid_cands = []
        schema_errors = []
        for c in raw_or_cands:
            if not isinstance(c, dict):
                continue
            is_valid, norm, err = schemas.validate_context_candidate(c)
            if is_valid and norm:
                valid_cands.append(norm)
            else:
                schema_errors.append(err or "Schema validation failed")

        if not valid_cands and schema_errors:
            return [], {
                "provider": provider,
                "model": model_name,
                "outcome": "schema_rejected",
                "duration_seconds": dur,
                "candidate_count": 0,
                "error_code": "SCHEMA_VALIDATION_FAILED",
                "safe_message": _redact_safe_message("; ".join(schema_errors[:2])),
            }

        if not valid_cands:
            return [], {
                "provider": provider,
                "model": model_name,
                "outcome": "empty",
                "duration_seconds": dur,
                "candidate_count": 0,
                "error_code": "ZERO_CANDIDATES",
                "safe_message": "Provider returned zero valid candidates",
            }

        return valid_cands, {
            "provider": provider,
            "model": model_name,
            "outcome": "success",
            "duration_seconds": dur,
            "candidate_count": len(valid_cands),
            "error_code": None,
            "safe_message": f"Extracted {len(valid_cands)} schema-valid candidate(s)",
        }
    except subprocess.TimeoutExpired:
        dur = round(time.perf_counter() - t0, 3)
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": "timeout",
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": "TIMEOUT",
            "safe_message": f"{provider} timed out after {TIER_TIMEOUT.get(provider, 90)}s",
        }
    except FileNotFoundError as e:
        dur = round(time.perf_counter() - t0, 3)
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": "unavailable",
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": "BINARY_NOT_FOUND",
            "safe_message": _redact_safe_message(str(e)),
        }
    except json.JSONDecodeError as e:
        dur = round(time.perf_counter() - t0, 3)
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": "invalid_output",
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": "INVALID_JSON",
            "safe_message": _redact_safe_message(str(e)),
        }
    except Exception as e:
        dur = round(time.perf_counter() - t0, 3)
        err_str = str(e)
        if "HTTP Error" in err_str or "HTTPError" in err_str:
            code_m = re.search(r"HTTP Error (\d+)", err_str)
            err_code = f"HTTP_{code_m.group(1)}" if code_m else "HTTP_ERROR"
            outcome = "unavailable"
        elif "JSON" in err_str or "parse" in err_str.lower() or "Expecting value" in err_str:
            err_code = "INVALID_JSON"
            outcome = "invalid_output"
        elif "timeout" in err_str.lower():
            err_code = "TIMEOUT"
            outcome = "timeout"
        else:
            err_code = "PROVIDER_ERROR"
            outcome = "unavailable"
        return [], {
            "provider": provider,
            "model": model_name,
            "outcome": outcome,
            "duration_seconds": dur,
            "candidate_count": 0,
            "error_code": err_code,
            "safe_message": _redact_safe_message(err_str),
        }
    finally:
        if provider == "ollama":
            confirm_ollama_unload(OLLAMA_LLM)


def extract_candidates_with_cascade(
    journal_text: str,
    existing_facts: dict,
    source_ref: str,
    source_hash: str,
) -> tuple[list[dict], str]:
    """
    Try each enabled provider in order to extract typed context candidates.
    Captures structured attempt records in LAST_PROVIDER_ATTEMPTS.
    Returns (candidates_list, provider_used).
    """
    global LAST_PROVIDER_ATTEMPTS
    attempts: list[dict[str, Any]] = []

    existing_summary = "\n".join(
        f"- {k}: {v}" for k, v in list(existing_facts.items())[:20]
    )
    today_iso = datetime.now(UTC).isoformat()
    success_provider = None
    successful_candidates: list[dict] = []

    if any(provider != "ollama" for provider in ENABLED_PROVIDERS):
        raise ValueError("Private memory extraction is local-only; cloud providers are disabled.")

    for provider in ENABLED_PROVIDERS:
        if success_provider is not None:
            attempts.append({
                "provider": provider,
                "model": PROVIDER_MODELS.get(provider, provider),
                "outcome": "skipped",
                "duration_seconds": 0.0,
                "candidate_count": 0,
                "error_code": None,
                "safe_message": f"Skipped because tier {success_provider} succeeded",
            })
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
        cands, attempt = _evaluate_provider_attempt(provider, prompt, source_ref, source_hash)
        attempts.append(attempt)
        if attempt["outcome"] == "success" and cands:
            log(f"✓ {provider} extracted {len(cands)} candidate(s): {[c.get('key') for c in cands]}")
            success_provider = provider
            successful_candidates = cands
        else:
            log(f"– {provider} {attempt['outcome']} ({attempt.get('error_code')}): {attempt.get('safe_message')}")

    LAST_PROVIDER_ATTEMPTS = attempts
    if success_provider:
        return successful_candidates, success_provider

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dream Cycle memory consolidation")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without mutating live memories")
    parser.add_argument("--smoke", action="store_true", help="Run hermetic local preflight smoke check")
    parser.add_argument("--report", default=None, help="Path to write machine-readable report JSON")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout")
    parser.add_argument("--provider", default=None, help="Force LLM provider")
    parser.add_argument("--model", default=None, help="Force LLM model")
    parser.add_argument("--calibrate-reputations", action="store_true", help="Run legacy reputation calibration")

    raw_args = sys.argv[1:] if argv is None else argv
    args, _ = parser.parse_known_args(raw_args)

    global ENABLED_PROVIDERS, OLLAMA_LLM, LAST_RUN_STATUS
    if args.provider:
        ENABLED_PROVIDERS = [p.strip() for p in args.provider.split(",") if p.strip()]
    if args.model:
        OLLAMA_LLM = args.model

    start_time = time.time()
    lock_file = MEM_ROOT / "logs" / ".dream_cycle.lock"
    lock_fd = acquire_lock(lock_file)
    if lock_fd is None and fcntl is not None:
        log("Another Dream Cycle process is currently running. Exiting.")
        return 0

    is_smoke = args.smoke
    is_dry_run = DRY_RUN or args.dry_run or is_smoke
    calibrate_reputations = args.calibrate_reputations or (os.environ.get("DREAM_CALIBRATE_REPUTATIONS", "0") == "1")
    report_file = args.report
    print_json = args.json

    duration_breakdown = {
        "model_load": 0.0,
        "generation": 0.0,
        "validation": 0.0,
        "staging_preview": 0.0,
        "unload": 0.0,
        "total": 0.0,
    }

    if is_smoke:
        log("=" * 60)
        log(f"Running hermetic local smoke verification for model: {OLLAMA_LLM}")
        log("=" * 60)
        preflight_res = ollama_preflight.run_ollama_preflight(
            model_name=OLLAMA_LLM,
            timeout=float(TIER_TIMEOUT.get("ollama", 180)),
            base_url=OLLAMA_URL,
        ) if ollama_preflight is not None else {
            "state": "service_unavailable",
            "ok": False,
            "model": OLLAMA_LLM,
            "error": "ollama_preflight module not found",
            "candidates": [],
            "duration_breakdown": duration_breakdown,
            "unload_state": {"requested": True, "command_sent": False, "confirmed": False, "active_models": []},
        }

        final_status = "completed" if preflight_res["ok"] else "degraded"
        smoke_status = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": final_status,
            "smoke": True,
            "dry_run": True,
            "durable_writes": 0,
            "provider": "ollama" if preflight_res["ok"] else "none",
            "configured_model": OLLAMA_LLM,
            "extraction_status": preflight_res["state"],
            "degraded_reason": preflight_res.get("error"),
            "candidates_extracted": [c.get("key") for c in preflight_res.get("candidates", [])],
            "candidates_would_stage": [c.get("key") for c in preflight_res.get("candidates", [])],
            "candidates_proposed": len(preflight_res.get("candidates", [])),
            "candidates_staged": 0,
            "candidates_rejected": 0,
            "candidates_deduplicated": 0,
            "candidates_awaiting_review": 0,
            "facts_promoted": 0,
            "system_curation": {"status": "skipped", "reason": "smoke_run"},
            "rejections": [],
            "model_unload": preflight_res.get("unload_state", {}),
            "duration_breakdown": preflight_res.get("duration_breakdown", {}),
            "duration_seconds": preflight_res.get("duration_breakdown", {}).get("total", 0.0),
            "exit_code": 0 if preflight_res["ok"] else 1,
            "provider_attempts": [{
                "provider": "ollama",
                "model": OLLAMA_LLM,
                "outcome": "success" if preflight_res["ok"] else "unavailable",
                "duration_seconds": preflight_res.get("duration_breakdown", {}).get("total", 0.0),
                "candidate_count": len(preflight_res.get("candidates", [])),
                "error_code": None if preflight_res["ok"] else preflight_res.get("state"),
                "safe_message": _redact_safe_message(preflight_res.get("error") or "Smoke run"),
            }],
        }
        LAST_RUN_STATUS = smoke_status

        if report_file:
            try:
                Path(report_file).write_text(json.dumps(smoke_status, indent=2), encoding="utf-8")
                log(f"Wrote smoke report to {report_file}")
            except Exception as e:
                log(f"Failed to write report to {report_file}: {e}")

        if print_json:
            print(json.dumps(smoke_status, indent=2))

        release_lock(lock_fd)
        return 0 if preflight_res["ok"] else 1

    status = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "running",
        "dry_run": is_dry_run,
        "durable_writes": 0,
        "provider": "none",
        "configured_model": OLLAMA_LLM,
        "extraction_status": "not_started",
        "degraded_reason": None,
        "provider_attempts": [],
        "candidates_proposed": 0,
        "candidates_staged": 0,
        "candidates_rejected": 0,
        "candidates_deduplicated": 0,
        "candidates_awaiting_review": 0,
        "facts_promoted": 0,
        "enrichment_processed": 0,
        "model_unload": {"requested": False, "command_sent": False, "confirmed": False, "active_models": []},
        "duration_breakdown": duration_breakdown,
        "duration_seconds": 0,
        "exit_code": 0,
    }

    # Bounded runtime: 20 minutes (1200s)
    if hasattr(signal, "alarm"):
        def timeout_handler(signum, frame):
            log("TIMEOUT: Dream Cycle exceeded 20-minute execution boundary.")
            status["status"] = "timeout"
            status["exit_code"] = 124
            duration_breakdown["total"] = round(time.time() - start_time, 2)
            status["duration_breakdown"] = duration_breakdown
            status["duration_seconds"] = duration_breakdown["total"]
            unload_info = confirm_ollama_unload()
            status["model_unload"] = unload_info
            write_dream_cycle_status(status)
            if report_file:
                try:
                    Path(report_file).write_text(json.dumps(status, indent=2), encoding="utf-8")
                except Exception:
                    pass
            if print_json:
                print(json.dumps(status, indent=2))
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

            t_gen_start = time.perf_counter()
            harvested, provider_used = extract_facts_with_cascade(journal_text, existing_facts)
            duration_breakdown["generation"] = round(time.perf_counter() - t_gen_start, 3)

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
                t_val_start = time.perf_counter()
                valid_candidates = []
                for cand in candidates_to_process:
                    try:
                        import schemas
                        is_valid, norm, err = schemas.validate_context_candidate(cand)
                        if is_valid and norm:
                            valid_candidates.append(norm)
                        else:
                            log(f"  [DISCARDED] Pre-validation failed for {cand.get('key')}: {err}")
                            rejected_count += 1
                            rejections.append({"key": cand.get("key"), "error": err or "Pre-validation failed"})
                    except Exception as ex:
                        log(f"  [DISCARDED] Pre-validation exception for {cand.get('key')}: {ex}")
                        rejected_count += 1
                        rejections.append({"key": cand.get("key"), "error": str(ex)})
                candidates_to_process = valid_candidates
                duration_breakdown["validation"] = round(time.perf_counter() - t_val_start, 3)


                t_prev_start = time.perf_counter()
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

                duration_breakdown["staging_preview"] = round(time.perf_counter() - t_prev_start, 3)

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

        if provider_used in (None, "none") or extraction_status == "no_provider_succeeded":
            final_status = "degraded"
            if not extraction_error:
                extraction_error = "No configured extractor succeeded or returned valid candidates."
        else:
            final_status = "completed"

        t_un_start = time.perf_counter()
        unload_info = confirm_ollama_unload(OLLAMA_LLM)
        duration_breakdown["unload"] = round(time.perf_counter() - t_un_start, 3)
        duration_breakdown["total"] = duration

        status_common = {
            "status": final_status,
            "provider": provider_used,
            "configured_model": OLLAMA_LLM,
            "duration_seconds": duration,
            "duration_breakdown": duration_breakdown,
            "model_unload": unload_info,
            "exit_code": 0,
            "extraction_status": extraction_status,
            "degraded_reason": extraction_error,
            "provider_attempts": list(LAST_PROVIDER_ATTEMPTS),
        }

        if is_dry_run:
            status.update({
                **status_common,
                "dry_run": True,
                "durable_writes": 0,
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
            })
        else:
            status.update({
                **status_common,
                "dry_run": False,
                "durable_writes": staged_count + promoted_count,
                "candidates_proposed": len(candidates_to_process),
                "candidates_staged": staged_count,
                "candidates_rejected": rejected_count,
                "candidates_deduplicated": dedupe_count,
                "candidates_awaiting_review": staged_count,
                "facts_promoted": promoted_count,
                "system_curation": curation_result,
                "rejections": rejections,
            })

        LAST_RUN_STATUS = status
        # A dry run is an observability-only check. It must not overwrite the
        # status of the last real curation run.
        if not is_dry_run:
            write_dream_cycle_status(status)

        if report_file:
            try:
                Path(report_file).write_text(json.dumps(status, indent=2), encoding="utf-8")
                log(f"Wrote report to {report_file}")
            except Exception as e:
                log(f"Failed to write report to {report_file}: {e}")

        if print_json:
            print(json.dumps(status, indent=2))

        return 0
    except Exception as e:
        duration = round(time.time() - start_time, 2)
        log(f"Dream Cycle failed with error: {e}")
        duration_breakdown["total"] = duration
        unload_info = confirm_ollama_unload(OLLAMA_LLM)
        status.update({
            "status": "error",
            "error": str(e),
            "configured_model": OLLAMA_LLM,
            "duration_breakdown": duration_breakdown,
            "duration_seconds": duration,
            "model_unload": unload_info,
            "exit_code": 1,
        })
        if not is_dry_run:
            write_dream_cycle_status(status)
        if report_file:
            try:
                Path(report_file).write_text(json.dumps(status, indent=2), encoding="utf-8")
            except Exception:
                pass
        if print_json:
            print(json.dumps(status, indent=2))
        return 1
    finally:
        if hasattr(signal, "alarm"):
            signal.alarm(0)
        confirm_ollama_unload(OLLAMA_LLM)
        release_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
