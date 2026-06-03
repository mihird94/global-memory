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
  Tier 3: Local Ollama     (qwen3:0.6b)         — always-available, zero cost

Run via cron at 3am daily:
    0 3 * * * /home/mihir/global_skills/global-memory/.venv/bin/python \\
              /home/mihir/global_skills/global-memory/tools/dream_cycle.py \\
              >> /home/mihir/memories/logs/dream_cycle.log 2>&1

Design principles:
- Fully idempotent: safe to run multiple times in the same day.
- No external services except those already present on the system.
- Commits a git snapshot of ~/memories after successful completion.
- Writes a brief summary to episodic journal so agents know consolidation ran.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib import request

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
MEM_ROOT     = Path(os.environ.get("MEMORY_ROOT", "/home/mihir/memories"))
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL  = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
LOG_PREFIX   = "[dream_cycle]"
DRY_RUN      = os.environ.get("DREAM_DRY_RUN", "0") == "1"

# ── Cascade config ────────────────────────────────────────────────────────────
# Each tier: (name, callable) — tried in order, first success wins.
# Override which tiers to try via DREAM_PROVIDERS=antigravity,gemini,ollama
ENABLED_PROVIDERS = [
    p.strip() for p in
    os.environ.get("DREAM_PROVIDERS", "antigravity,gemini,ollama").split(",")
    if p.strip()
]

# CLI paths — resolved at startup
AGY_BIN    = os.environ.get("AGY_BIN",    "/home/mihir/.local/bin/agy")
GEMINI_BIN = os.environ.get("GEMINI_BIN", "/home/mihir/.nvm/versions/node/v22.22.2/bin/gemini")
OLLAMA_LLM = os.environ.get("DREAM_LLM_MODEL", "qwen3:0.6b")

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


# ──────────────────────────────────────────────────────────────────────────────
# LLM Cascade — Tier implementations
# ──────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT_TEMPLATE = """\
You are a memory consolidation engine for a software engineer's AI OS.
Extract ONLY durable, high-value facts from today's work journal that should
be permanently remembered — architectural decisions, system configuration
choices, verified production facts, key file paths, or lessons learned
that will still be relevant in 6 months.

DO NOT extract:
- Status updates ("fixed X today") or transient events
- Facts already in the existing list below

Existing facts (do not duplicate):
{existing_summary}

Today's journal:
{journal_text}

Respond with ONLY a valid JSON object mapping snake_case keys to string values.
If nothing is worth extracting, respond with: {{}}
Example:
{{
  "optimus_execution_engine": "Uses SQLite-backed runtime_state.py for canonical state",
  "skill_installation_policy": "Only install targeted skills with --skills flag"
}}

JSON output:"""


def _parse_json_facts(raw: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    # Find first { ... } block in case of preamble text
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    result = json.loads(raw)
    if not isinstance(result, dict):
        return {}
    return {str(k): str(v) for k, v in result.items() if k and v}


def _tier_antigravity(prompt: str) -> dict:
    """Tier 1: Antigravity CLI (agy --print) with model override via temp settings.
    
    agy has no --model flag, so we inject a temporary settings file that
    overrides the model for this single invocation, then clean it up.
    """
    import tempfile, shutil
    if not Path(AGY_BIN).exists():
        raise FileNotFoundError(f"agy not found at {AGY_BIN}")

    agy_settings = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
    original_model = None
    backed_up = False

    try:
        # Patch the model in settings temporarily
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
        # Always restore original model
        if backed_up and original_model is not None and agy_settings.exists():
            settings = json.loads(agy_settings.read_text())
            settings["model"] = original_model
            agy_settings.write_text(json.dumps(settings, indent=2))
            log(f"  agy model restored: {original_model}")

    if result.returncode != 0:
        raise RuntimeError(f"agy exited {result.returncode}: {result.stderr[:200]}")
    return _parse_json_facts(result.stdout)


def _tier_gemini(prompt: str) -> dict:
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
    return _parse_json_facts(result.stdout)


def _tier_ollama(prompt: str) -> dict:
    """Tier 3: Local Ollama (always-available fallback)."""
    resp = _post(f"{OLLAMA_URL}/api/generate", {
        "model": OLLAMA_LLM,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 800},
    }, timeout=TIER_TIMEOUT["ollama"])
    return _parse_json_facts(resp.get("response", ""))


TIER_FNS = {
    "antigravity": _tier_antigravity,
    "gemini":      _tier_gemini,
    "ollama":      _tier_ollama,
}


def extract_facts_with_cascade(journal_text: str, existing_facts: dict) -> tuple[dict, str]:
    """
    Try each enabled provider in order. Return (facts_dict, provider_used).
    Returns ({}, "none") if all tiers fail.
    """
    existing_summary = "\n".join(
        f"- {k}: {v}" for k, v in list(existing_facts.items())[:20]
    )
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        existing_summary=existing_summary,
        journal_text=journal_text,
    )

    for provider in ENABLED_PROVIDERS:
        fn = TIER_FNS.get(provider)
        if fn is None:
            log(f"Unknown provider '{provider}' — skipping")
            continue
        log(f"Trying tier: {provider} ...")
        try:
            facts = fn(prompt)
            log(f"✓ {provider} extracted {len(facts)} fact(s): {list(facts.keys())}")
            return facts, provider
        except subprocess.TimeoutExpired:
            log(f"✗ {provider} timed out — trying next tier")
        except FileNotFoundError as e:
            log(f"✗ {provider} not available ({e}) — trying next tier")
        except Exception as e:
            log(f"✗ {provider} failed: {e} — trying next tier")

    log("All tiers exhausted — no facts extracted")
    return {}, "none"



def rebuild_faiss_index() -> bool:
    """Invoke memoryctl index-build via subprocess."""
    memoryctl = Path("/home/mihir/global_skills/global-memory/tools/memoryctl")
    if not memoryctl.exists():
        memoryctl = Path("/home/mihir/.local/bin/memoryctl")

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


def append_dream_cycle_log(new_facts_count: int, provider: str = "unknown") -> None:
    """Write a brief record to episodic journal so agents know the cycle ran."""
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    daily = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    journal = MEM_ROOT / "episodic" / "journal.md"
    target = daily if daily.exists() else journal

    entry = (
        f"\n### {today} [{now}] - DreamCycle - Nightly Consolidation\n"
        f"- Provider used: {provider}\n"
        f"- Extracted and promoted {new_facts_count} new semantic fact(s) to facts.json.\n"
        f"- FAISS index rebuilt.\n"
    )
    if DRY_RUN:
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


def main() -> int:
    log("=" * 60)
    log("Starting Dream Cycle (nightly memory consolidation)")
    log(f"DRY_RUN={DRY_RUN} | EMBED={EMBED_MODEL}")
    log(f"Provider cascade: {' → '.join(ENABLED_PROVIDERS)}")
    log("=" * 60)

    # 1. Verify Ollama is up (needed for FAISS rebuild regardless of LLM tier)
    if not ollama_available():
        log("WARNING: Ollama not reachable — FAISS rebuild will fail if triggered")
    else:
        log("Ollama: reachable")

    # 2. Read today's journal
    journal_text = read_today_journal()
    provider_used = "none"
    new_facts: dict = {}

    if not journal_text:
        log("No episodic entries found for today — skipping LLM extraction")
    else:
        log(f"Journal text: {len(journal_text)} chars")

        # 3. Load existing facts
        existing_facts = load_existing_facts()
        log(f"Existing facts: {len(existing_facts)} entries")

        # 4. Run cascade extraction
        new_facts, provider_used = extract_facts_with_cascade(journal_text, existing_facts)

        # 5. Merge and save
        if new_facts:
            merged = {**existing_facts, **new_facts}
            if not DRY_RUN:
                save_facts(merged)
            else:
                log(f"DRY RUN — would write facts: {json.dumps(new_facts, indent=2)}")
        else:
            log("No new facts to promote — facts.json unchanged")

    # 6. Rebuild FAISS index
    if not DRY_RUN:
        rebuild_faiss_index()
    else:
        log("DRY RUN — skipping FAISS rebuild")

    # 7. Append to episodic log
    append_dream_cycle_log(len(new_facts), provider=provider_used)

    # 8. Git commit
    if not DRY_RUN:
        git_commit_memories()
    else:
        log("DRY RUN — skipping git commit")

    log(f"Dream Cycle complete. Provider used: {provider_used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
