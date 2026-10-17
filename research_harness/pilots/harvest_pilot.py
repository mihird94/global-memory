"""Freeze then run a small synthetic consolidation pilot on loopback Ollama only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import time
from urllib import request

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "http://127.0.0.1:11434"
CASES = Path(__file__).with_name("harvest_cases_v1.json")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2) + "\n")


def freeze(bundle):
    bundle.mkdir(parents=True, exist_ok=False)
    inputs = bundle / "inputs"
    inputs.mkdir()
    files = [CASES, Path(__file__), ROOT / "tools/dream_cycle.py",
             ROOT / "tools/schemas.py", ROOT / "tools/eval_model_harvesting.py",
             ROOT / "tools/concept_enrichment.py"]
    hashes = {}
    for src in files:
        dst = inputs / src.name
        shutil.copy2(src, dst)
        hashes[src.relative_to(ROOT).as_posix()] = digest(src)
    schedule = [(m, c["id"]) for m in ["qwen2.5-coder:7b", "qwen3:8b"]
                for c in json.loads(CASES.read_text())]
    random.Random(1742).shuffle(schedule)
    protocol = {
        "classification": "new_author_created_pilot_not_blind_holdout",
        "scope": "synthetic harvesting only; no graph extraction or CCMP efficacy claims",
        "models": ["qwen2.5-coder:7b", "qwen3:8b"], "think": False,
        "seed": 1742, "temperature": 0, "num_ctx": 8192, "num_predict": 1536,
        "max_calls": 8, "max_seconds": 1200, "request_timeout_seconds": 120,
        "max_reported_tokens": 32000, "request_token_reservation": 9728,
        "token_limit_note": "Conservative full context plus completion reservation; not a tokenizer measurement",
        "schedule": schedule, "source_sha256": hashes,
        "analysis": "Report raw and admitted keyword proxies, canary leaks, no-write behavior, schema failures, latency and missingness. Independently inspect semantics; no significance or non-inferiority claim. No tuning or retries after responses.",
    }
    dump(bundle / "protocol.json", protocol)
    (bundle / "protocol.sha256").write_text(digest(bundle / "protocol.json") + "\n")


def http(path, payload=None, timeout=5):
    data = None if payload is None else json.dumps(payload).encode()
    req = request.Request(ENDPOINT + path, data=data,
                          headers={"Content-Type": "application/json"})
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise RuntimeError("Local pilot forbids redirects")
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def execute(bundle):
    protocol = json.loads((bundle / "protocol.json").read_text())
    if digest(bundle / "protocol.json") != (bundle / "protocol.sha256").read_text().strip():
        raise ValueError("Protocol changed after freeze")
    for name, expected in protocol["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Frozen source changed: " + name)
    ledger = bundle / "dispatch.jsonl"
    if ledger.exists():
        raise ValueError("A run cannot be resumed or overwritten")
    # Set an isolated memory root before importing product helpers.
    with tempfile.TemporaryDirectory(prefix="gms_heldout_") as tmp:
        os.environ["MEMORY_ROOT"] = tmp
        os.environ["OLLAMA_URL"] = ENDPOINT
        from tools import eval_model_harvesting as evaluator
        from tools import schemas
        template = evaluator.CONTEXT_HARVEST_PROMPT_TEMPLATE
        if not template:
            raise RuntimeError("Frozen prompt unavailable")
        cases = {c["id"]: c for c in json.loads(CASES.read_text())}
        tags = http("/api/tags")
        dump(bundle / "installed_models.json", tags)
        available = {m["name"] for m in tags["models"]}
        if not set(protocol["models"]).issubset(available):
            raise RuntimeError("Required installed model missing; no download allowed")
        dump(bundle / "initial_residency.json", http("/api/ps"))
        started = time.monotonic()
        tokens = 0
        status = "COMPLETED"
        results = []

        def event(obj):
            with ledger.open("a") as f:
                f.write(json.dumps(obj) + "\n")
                f.flush()
                os.fsync(f.fileno())

        try:
            for index, (model, case_id) in enumerate(protocol["schedule"]):
                remaining = protocol["max_seconds"] - (time.monotonic() - started)
                if remaining <= 0 or index >= protocol["max_calls"] or tokens + protocol["request_token_reservation"] > protocol["max_reported_tokens"]:
                    status = "HALTED_BUDGET"
                    break
                c = cases[case_id]
                prompt = template.format(journal_text=c["excerpt"], existing_summary="None.",
                    extractor_agent="synthetic-pilot", source_ref="synthetic/" + case_id + ".md",
                    source_hash=hashlib.sha256(c["excerpt"].encode()).hexdigest(),
                    extracted_at="2026-10-17T00:00:00Z")
                payload = {"model": model, "prompt": prompt, "format": "json", "stream": False,
                           "keep_alive": 0, "think": False,
                           "options": {k: protocol[k] for k in ["seed", "temperature", "num_ctx", "num_predict"]}}
                event({"index": index, "state": "STARTED", "case": case_id, "request": payload})
                t0 = time.monotonic()
                try:
                    raw = http("/api/generate", payload, min(remaining, protocol["request_timeout_seconds"]))
                    # Persist full response before parsing or scoring.
                    event({"index": index, "state": "RESPONSE", "response": raw, "seconds": time.monotonic() - t0})
                    if raw.get("prompt_eval_count") is None or raw.get("eval_count") is None:
                        raise RuntimeError("Missing usage counts")
                    tokens += raw["prompt_eval_count"] + raw["eval_count"]
                    parsed = json.loads(raw.get("response", ""))
                    candidates = parsed.get("candidates")
                    if not isinstance(candidates, list):
                        raise ValueError("Missing candidates array")
                    admitted, decisions = [], []
                    for candidate in candidates:
                        ok, normalized, reason = schemas.validate_context_candidate(candidate)
                        decisions.append({"valid": ok, "reason": reason})
                        if ok and normalized:
                            admitted.append(normalized)
                    result = {"model": model, "case": case_id, "raw_candidates": candidates,
                        "admitted_candidates": admitted, "admission": decisions,
                        "raw_proxy": evaluator.score_candidate_proxies(c["expected_candidates"], candidates),
                        "admitted_proxy": evaluator.score_candidate_proxies(c["expected_candidates"], admitted),
                        "boundary": evaluator.verify_isolated_storage_boundary(case_id, candidates, admitted, [], [], c["prohibited_extracts"]),
                        "latency_seconds": time.monotonic() - t0}
                    results.append(result)
                    event({"index": index, "state": "COMPLETED", "result": result})
                except (ValueError, KeyError) as exc:
                    event({"index": index, "state": "INVALID_OUTPUT", "error": str(exc)})
                    results.append({"model": model, "case": case_id, "invalid_output": str(exc)})
                except Exception as exc:
                    event({"index": index, "state": "ERROR", "error": str(exc)})
                    status = "FAILED_BACKEND"
                    break
        except BaseException:
            status = "INTERRUPTED"
            raise
        finally:
            unload = {}
            for model in protocol["models"]:
                try:
                    http("/api/generate", {"model": model, "keep_alive": 0}, timeout=10)
                    unload[model] = "requested"
                except Exception as exc:
                    unload[model] = str(exc)
            try:
                residency = http("/api/ps")
            except Exception as exc:
                residency = {"unavailable": str(exc)}
            dump(bundle / "summary.json", {"status": status, "results": results,
                 "reported_tokens": tokens, "seconds": time.monotonic() - started,
                 "unload": unload, "final_residency": residency,
                 "empirical_scope": protocol["classification"]})
            dump(bundle / "manifest.json", {p.name: digest(p) for p in bundle.iterdir() if p.is_file() and p.name != "manifest.json"})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["freeze", "execute"])
    p.add_argument("bundle", type=Path)
    args = p.parse_args()
    if args.mode == "freeze":
        freeze(args.bundle)
    else:
        execute(args.bundle)


if __name__ == "__main__":
    main()
