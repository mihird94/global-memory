#!/usr/bin/env python3
"""
tools/ollama_preflight.py — Explicit Ollama Preflight & Unload Verification Harness.

Distinguishes 6 operational states for local model harvesting:
1. service_unavailable: Ollama daemon unreachable
2. model_unavailable: Model not installed in Ollama
3. generate_endpoint_failure: /api/generate non-200 HTTP or server crash
4. malformed_candidate_json: Generation succeeded but returned invalid/unparseable JSON or schema failure
5. timeout: Bounded execution exceeded
6. successful_extraction: Schema-valid candidates extracted

Guarantees:
- keep_alive=0 sent on all terminal paths (success, error, timeout)
- Explicit unload confirmed via /api/ps
- Bounded timing telemetry for: model_load, generation, validation, staging_preview, unload, total
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

import schemas

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("DREAM_LLM_MODEL", "qwen3:8b")

DEFAULT_PREFLIGHT_PROMPT = """\
You are a rationale-first context harvesting engine for GMS.
Consolidate the following note into typed context records.
Return valid JSON matching schema_version "gms-context-harvest-v1".

Note:
2026-09-28: Decided to enable SQLite WAL mode across all agent connections because high concurrency caused database locked errors. Implication: specify busy_timeout=5000.

Output ONLY valid JSON:
{
  "schema_version": "gms-context-harvest-v1",
  "candidates": [
    {
      "schema_version": "gms-context-record-v1",
      "record_type": "decision",
      "key": "sqlite_wal_mode_concurrency",
      "statement": "Enable SQLite WAL mode across all agent connections",
      "rationale": "High concurrency caused database locked errors",
      "implications": ["Specify busy_timeout=5000"],
      "scope": {"project": "global-memory", "level": "system"},
      "provenance": {
        "extractor": "preflight-ollama",
        "source_refs": ["episodic/history/2026-09-28.md"],
        "source_hashes": ["sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
        "extracted_at": "2026-09-28T20:00:00Z",
        "prompt_version": "context-harvest-v1"
      },
      "evidence": [
        {"type": "source_document", "ref": "episodic/history/2026-09-28.md", "excerpt_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
      ]
    }
  ]
}
"""


def check_ollama_service(base_url: str = OLLAMA_URL, timeout: float = 3.0) -> Tuple[bool, Optional[str]]:
    """Check if the Ollama service is reachable via /api/tags."""
    try:
        req = request.Request(f"{base_url}/api/tags", method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, None
            return False, f"HTTP status {resp.status}"
    except Exception as e:
        return False, str(e)


def check_model_available(
    model_name: str,
    base_url: str = OLLAMA_URL,
    timeout: float = 3.0,
) -> Tuple[bool, List[str]]:
    """Check if a specific model is installed in Ollama without pulling/downloading."""
    try:
        req = request.Request(f"{base_url}/api/tags", method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed = [m.get("name", "") for m in data.get("models", [])]
            # Match exact or tag prefix e.g. "qwen3:8b" vs "qwen3:8b-instruct"
            is_present = any(
                m == model_name or m.startswith(f"{model_name}:") or m.startswith(model_name)
                for m in installed
            )
            return is_present, installed
    except Exception:
        return False, []


def get_loaded_models(base_url: str = OLLAMA_URL, timeout: float = 3.0) -> List[str]:
    """Query /api/ps to see which models are currently loaded in memory."""
    try:
        req = request.Request(f"{base_url}/api/ps", method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def confirm_model_unload(
    model_name: str,
    base_url: str = OLLAMA_URL,
    max_wait_sec: float = 1.5,
) -> Dict[str, Any]:
    """
    Send keep_alive: 0 to /api/generate and poll /api/ps to confirm unload.
    Returns unload verification state.
    """
    command_sent = False
    models_to_unload = [model_name]
    if ":" in model_name:
        models_to_unload.append(model_name.split(":")[0])

    for target in models_to_unload:
        try:
            payload = json.dumps({"model": target, "keep_alive": 0}).encode("utf-8")
            req = request.Request(
                f"{base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    command_sent = True
        except Exception:
            pass

    # Verify via /api/ps
    deadline = time.time() + max_wait_sec
    active_models: List[str] = []
    confirmed = False

    while time.time() <= deadline:
        active_models = get_loaded_models(base_url=base_url)
        target_stem = model_name.split(":")[0]
        model_still_loaded = any(
            m == model_name or m.startswith(f"{target_stem}:") or m == target_stem
            for m in active_models
        )
        if not model_still_loaded:
            confirmed = True
            break
        time.sleep(0.15)

    if not confirmed:
        active_models = get_loaded_models(base_url=base_url)
        target_stem = model_name.split(":")[0]
        confirmed = not any(
            m == model_name or m.startswith(f"{target_stem}:") or m == target_stem
            for m in active_models
        )

    return {
        "requested": True,
        "command_sent": command_sent,
        "confirmed": confirmed,
        "active_models": active_models,
    }


def parse_raw_candidates(raw: str) -> List[Dict[str, Any]]:
    """Parse candidate dictionaries from model output text."""
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
    except Exception:
        return []

    if isinstance(result, dict):
        candidates = result.get("candidates", [])
        if isinstance(candidates, list) and candidates:
            return [c for c in candidates if isinstance(c, dict)]
        if result.get("schema_version") == "gms-context-record-v1" or "record_type" in result:
            return [result]
        return []
    elif isinstance(result, list):
        return [c for c in result if isinstance(c, dict)]
    return []


def run_ollama_preflight(
    model_name: str = DEFAULT_MODEL,
    prompt: Optional[str] = None,
    timeout: float = 60.0,
    base_url: str = OLLAMA_URL,
    existing_facts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run an explicit Ollama preflight check with fine-grained state classification,
    bounded timing telemetry, and guaranteed model unload.
    """
    t_start = time.perf_counter()
    report: Dict[str, Any] = {
        "state": "service_unavailable",
        "ok": False,
        "model": model_name,
        "error": None,
        "candidates": [],
        "raw_preview": "",
        "duration_breakdown": {
            "model_load": 0.0,
            "generation": 0.0,
            "validation": 0.0,
            "staging_preview": 0.0,
            "unload": 0.0,
            "total": 0.0,
        },
        "unload_state": {
            "requested": False,
            "command_sent": False,
            "confirmed": False,
            "active_models": [],
        },
    }

    # Step 1: Check service availability
    online, svc_err = check_ollama_service(base_url=base_url)
    if not online:
        t_total = time.perf_counter() - t_start
        report["state"] = "service_unavailable"
        report["error"] = f"Ollama service unreachable at {base_url}: {svc_err}"
        report["duration_breakdown"]["total"] = round(t_total, 3)
        return report

    # Step 2: Check model installation
    installed, model_list = check_model_available(model_name, base_url=base_url)
    if not installed:
        t_total = time.perf_counter() - t_start
        report["state"] = "model_unavailable"
        report["error"] = (
            f"Model '{model_name}' is not installed in Ollama. "
            f"Installed models: {model_list}. Prohibited from auto-downloading."
        )
        report["duration_breakdown"]["total"] = round(t_total, 3)
        return report

    # Step 3: Run inference with keep_alive: 0 and format: json
    eff_prompt = prompt if prompt is not None else DEFAULT_PREFLIGHT_PROMPT
    payload = {
        "model": model_name,
        "prompt": eff_prompt,
        "format": "json",
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": 0.1, "num_predict": 1200},
    }

    resp_data: Optional[Dict[str, Any]] = None
    gen_exception: Optional[Exception] = None
    t_post_start = time.perf_counter()

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{base_url}/api/generate",
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                resp_data = json.loads(resp.read().decode("utf-8"))
            else:
                report["state"] = "generate_endpoint_failure"
                report["error"] = f"HTTP {resp.status} from /api/generate"
    except (error.URLError, socket.timeout, TimeoutError) as e:
        is_timeout = False
        err_str = str(e).lower()
        if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in err_str or "time out" in err_str:
            is_timeout = True
        elif isinstance(e, error.URLError) and isinstance(e.reason, (socket.timeout, TimeoutError)):
            is_timeout = True

        if is_timeout:
            report["state"] = "timeout"
            report["error"] = f"Inference timed out after {timeout}s: {e}"
        else:
            report["state"] = "generate_endpoint_failure"
            report["error"] = f"Inference network failure: {e}"
        gen_exception = e
    except Exception as e:
        report["state"] = "generate_endpoint_failure"
        report["error"] = f"Inference exception: {e}"
        gen_exception = e
    finally:
        # Mandatory unload confirmation across all terminal paths
        t_unload_start = time.perf_counter()
        unload_res = confirm_model_unload(model_name, base_url=base_url)
        t_unload = time.perf_counter() - t_unload_start
        report["unload_state"] = unload_res
        report["duration_breakdown"]["unload"] = round(t_unload, 3)

    t_post_end = time.perf_counter()
    post_wall = t_post_end - t_post_start

    # If generation failed or timed out, finalize and return
    if resp_data is None:
        report["duration_breakdown"]["total"] = round(max(time.perf_counter() - t_start, 0.001), 3)
        return report

    # Extract model load and generation timings from Ollama metadata if available
    load_dur_ns = resp_data.get("load_duration", 0)
    eval_dur_ns = resp_data.get("eval_duration", 0)

    if load_dur_ns and load_dur_ns > 0:
        model_load_sec = load_dur_ns / 1e9
    else:
        model_load_sec = 0.0

    if eval_dur_ns and eval_dur_ns > 0:
        generation_sec = eval_dur_ns / 1e9
    else:
        generation_sec = max(0.0, post_wall - model_load_sec)

    report["duration_breakdown"]["model_load"] = round(model_load_sec, 3)
    report["duration_breakdown"]["generation"] = round(generation_sec, 3)

    raw_response = resp_data.get("response", "")
    if not raw_response and resp_data.get("thinking"):
        raw_response = resp_data.get("thinking", "")
    report["raw_preview"] = raw_response[:200]

    # Step 4: Parse candidate JSON
    candidates = parse_raw_candidates(raw_response)
    if not candidates:
        report["state"] = "malformed_candidate_json"
        report["error"] = f"Could not parse valid candidates from output: {raw_response[:200]}"
        report["duration_breakdown"]["total"] = round(time.perf_counter() - t_start, 3)
        return report

    # Step 5: Deterministic schema validation
    t_val_start = time.perf_counter()
    valid_candidates: List[Dict[str, Any]] = []
    validation_errors: List[str] = []

    for c in candidates:
        is_valid, norm, err = schemas.validate_context_candidate(c)
        if is_valid and norm:
            valid_candidates.append(norm)
        else:
            validation_errors.append(f"{c.get('key', 'unknown')}: {err}")

    t_val = time.perf_counter() - t_val_start
    report["duration_breakdown"]["validation"] = round(t_val, 3)

    if not valid_candidates:
        report["state"] = "malformed_candidate_json"
        report["error"] = f"Candidate validation failed: {'; '.join(validation_errors)}"
        report["duration_breakdown"]["total"] = round(max(time.perf_counter() - t_start, 0.001), 3)
        return report

    # Step 6: Staging preview (zero durable writes)
    t_prev_start = time.perf_counter()
    try:
        from consolidation_policy import classify_candidate
        existing = existing_facts or {}
        for vc in valid_candidates:
            vc["proposed_operation"] = classify_candidate(vc, existing)
    except Exception:
        pass
    t_prev = time.perf_counter() - t_prev_start
    report["duration_breakdown"]["staging_preview"] = round(t_prev, 3)

    # Success
    report["state"] = "successful_extraction"
    report["ok"] = True
    report["candidates"] = valid_candidates
    wall_total = time.perf_counter() - t_start
    component_total = model_load_sec + generation_sec + t_val + t_prev + t_unload
    report["duration_breakdown"]["total"] = round(max(wall_total, component_total), 3)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Explicit Ollama Preflight & Unload Check")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name to probe")
    parser.add_argument("--timeout", type=float, default=60.0, help="Inference timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Output full JSON report")
    args = parser.parse_args()

    result = run_ollama_preflight(model_name=args.model, timeout=args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Preflight state: {result['state']}")
        print(f"Success: {result['ok']}")
        print(f"Model: {result['model']}")
        if result['error']:
            print(f"Error: {result['error']}")
        print("Duration breakdown:", json.dumps(result["duration_breakdown"], indent=2))
        print("Unload state:", json.dumps(result["unload_state"], indent=2))
        print(f"Candidates extracted: {len(result['candidates'])}")
    sys.exit(0 if result["ok"] else 1)
