#!/usr/bin/env python3
"""Fail-closed, preflight-first Ollama pilot for the frozen 72-call DF protocol.

Run as a module from repository root. No access to ~/memories, production tools,
cloud endpoints or live infrastructure. A simulator grades JSON action objects.
The gold/hidden annotations NEVER enter writer or reader prompts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research_harness.decision_fidelity.corpus import ALL_DEVELOPMENT_FAMILIES
from research_harness.decision_fidelity.models import ActionOutcome
from research_harness.decision_fidelity.representations.arm_a_full_source import ArmAFullSource
from research_harness.decision_fidelity.representations.arm_b_extractive_excerpts import ArmBExtractiveExcerpts
from research_harness.decision_fidelity.representations.arm_d_source_bound import (
    ArmDSourceBound, SourceBoundConstraintRecord,
)
from research_harness.decision_fidelity.simulators.domain_simulators import get_simulator_for_family

DIR = Path(__file__).resolve().parent
SCHEDULE_PATH = DIR / "docs" / "frozen_schedule.json"
REPORT_ROOT = DIR / "reports" / "model_pilot"
ARMS = (
    "Arm_A_Full_Source", "Arm_B_Extractive_Excerpts",
    "Arm_C_Ordinary_Structured", "Arm_D_Source_Bound",
)
WRITERS = ARMS[2:]


def parse_model_object(raw: str) -> dict:
    """Never salvage truncated JSON with regex or parse array/empty objects as actions."""
    value = json.loads(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError("A nonempty, complete JSON object was required")
    return value


def bind_case(step: dict):
    case = ALL_DEVELOPMENT_FAMILIES[step["family_id"]]
    if step["variant_id"] == "canonical":
        source, task, gold, alternatives = (
            case.canonical_source, case.canonical_task,
            case.gold_canonical_action, case.valid_canonical_alternatives,
        )
    elif step["variant_id"] == "minimal_pair":
        source, task, gold, alternatives = (
            case.minimal_pair_source, case.minimal_pair_task,
            case.gold_minimal_pair_action, [],
        )
    else:
        raise ValueError("Unrecognized variant")
    if source.source_id != step["source_id"] or source.sha256 != step["source_sha256"]:
        raise ValueError("Frozen schedule source digest mismatch")
    if step["stage"] == "reader" and task.task_id != step["task_id"]:
        raise ValueError("Frozen schedule task identity mismatch")
    return case, source.to_public_input(), task, gold, alternatives


def preflight(schedule: dict) -> dict:
    steps = schedule["scheduled_calls"]
    if schedule.get("total_calls") != 72 or len(steps) != 72:
        raise ValueError("Exactly 72 calls are required")
    if schedule.get("total_scenarios") != 12 or schedule.get("think") is not False:
        raise ValueError("Protocol scenario count or thinking state differs")
    counts = Counter()
    for idx, step in enumerate(steps, start=1):
        if idx != step["call_index"] or step["arm_id"] not in ARMS:
            raise ValueError("Bad frozen schedule call index/arm")
        if step["stage"] not in ("writer", "reader"):
            raise ValueError("Invalid stage")
        if step["stage"] == "writer" and step["arm_id"] not in WRITERS:
            raise ValueError("A/B cannot have writer stage")
        if (step["model"] != schedule["model"] or
            step["max_tokens"] != schedule["max_completion_tokens"] or
            step["timeout_seconds"] != schedule["timeout_per_call_seconds"] or
            step["seed"] != schedule["seed"]):
            raise ValueError("Per-call options differ from frozen manifest")
        bind_case(step)
        counts[(step["family_id"], step["variant_id"], step["arm_id"], step["stage"])] += 1
    if len(counts) != 72 or any(v != 1 for v in counts.values()):
        raise ValueError("Schedule duplicates/omissions")
    if len(schedule["pilot_families"]) != 6:
        raise ValueError("Expected six source families")
    for family in schedule["pilot_families"]:
        for variant in ("canonical", "minimal_pair"):
            for arm in ARMS:
                if counts[(family, variant, arm, "reader")] != 1:
                    raise ValueError("Missing reader cell")
                if arm in WRITERS and counts[(family, variant, arm, "writer")] != 1:
                    raise ValueError("Missing writer cell")
    return {"calls": 72, "reader_calls": 48, "writer_calls": 24, "families": 6}


def validate_loopback(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "http" or p.hostname not in ("localhost", "127.0.0.1")
            or not p.port or p.username or p.password or p.path not in ("", "/")
            or p.query or p.fragment):
        raise ValueError("Only plain HTTP loopback Ollama base URLs are permitted")
    return url.rstrip("/") + "/api/generate"


def generate(endpoint: str, prompt: str, schedule: dict) -> dict:
    request = {
        "model": schedule["model"], "prompt": prompt,
        "stream": False, "think": False, "format": "json", "keep_alive": 0,
        "options": {
            "temperature": schedule["temperature"], "seed": schedule["seed"],
            "num_predict": schedule["max_completion_tokens"], "num_ctx": 8192,
        },
    }
    req = urllib.request.Request(
        endpoint, json.dumps(request).encode("utf-8"),
        {"Content-Type": "application/json"}, method="POST",
    )
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=schedule["timeout_per_call_seconds"]) as response:
        result = json.loads(response.read().decode("utf-8"))
    result["wall_seconds"] = round(time.monotonic() - start, 3)
    if result.get("done_reason") != "stop":
        raise RuntimeError("Model did not stop cleanly: " + str(result.get("done_reason")))
    if result.get("thinking"):
        raise RuntimeError("Unexpected thinking-channel output under think=false")
    return result


def make_writer_prompt(arm: str, source: str) -> str:
    if arm == "Arm_C_Ordinary_Structured":
        instruction = (
            "Extract operational rules from SOURCE into a concise ordinary "
            "structured JSON record (policy, rules, parameters, summary). "
            "Preserve scopes, negatives, units and order without verbatim citations."
        )
    elif arm == "Arm_D_Source_Bound":
        instruction = (
            "Extract decision constraints from SOURCE as a JSON object with "
            "primary_statement:string; applicability_scope, exceptions_and_negation, "
            "numeric_value, numeric_unit, execution_order, required_prerequisites, "
            "optional_prerequisites, rationale (nullable); span_citations:object. "
            "Every nonnull asserted field including primary_statement must have "
            "an exact verbatim supporting source excerpt under its own span_citations "
            "key. Never infer unsupported facts; use null if unmentioned."
        )
    else:
        raise ValueError("Not a writer arm")
    return instruction + "\nSOURCE:\n" + source + "\nOnly output one JSON object."


def make_reader_prompt(memory: str, task) -> str:
    return (
        "You are an operations decision agent in a synthetic hermetic simulation. "
        "No actions execute outside this test. Follow the memory policy.\n"
        "CONTEXT:\n" + memory + "\nTASK:\n" + task.prompt +
        "\nENVIRONMENT:\n" + json.dumps(task.environment_context, sort_keys=True) +
        "\nReturn one complete JSON object with action and required parameters. "
        "If prohibited/out of scope/missing mandatory prerequisites, use "
        '{"action":"abstain","reason":"brief explanation"} or '
        '{"action":"refuse","reason":"brief explanation"}. '
        "Never invent facts. Output JSON only."
    )


def memory_context(step: dict, source, task, writers: dict) -> tuple[str, bool, list[str]]:
    arm = step["arm_id"]
    if arm == ARMS[0]:
        return ArmAFullSource().build_reader_context(source, task), True, []
    if arm == ARMS[1]:
        return ArmBExtractiveExcerpts(top_k=2, task_conditioned=True).build_reader_context(source, task), True, []
    writer = writers[(step["family_id"], step["variant_id"], arm)]
    if arm == ARMS[2]:
        return json.dumps(writer, sort_keys=True), True, []
    fields = {
        "primary_statement", "applicability_scope", "exceptions_and_negation",
        "numeric_value", "numeric_unit", "execution_order",
        "required_prerequisites", "optional_prerequisites", "rationale",
        "span_citations",
    }
    if set(writer) - fields or not isinstance(writer.get("primary_statement"), str):
        raise ValueError("Invalid source-bound writer schema")
    if not isinstance(writer.get("span_citations"), dict):
        raise ValueError("Missing span citations")
    record = SourceBoundConstraintRecord(
        source_id=source.source_id, source_sha256=source.sha256,
        **{k: v for k, v in writer.items() if k in fields},
    )
    return ArmDSourceBound().admit_memory(source, task, injected_record=record)


def run(execute: bool, url: str) -> int:
    raw_schedule = SCHEDULE_PATH.read_bytes()
    schedule = json.loads(raw_schedule)
    print("PREFLIGHT:", json.dumps(preflight(schedule), sort_keys=True))
    if not execute:
        print("No inference run or artifact written. Use --execute to opt in.")
        return 0
    endpoint = validate_loopback(url)
    out = REPORT_ROOT / datetime.now(timezone.utc).strftime("pilot_%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=False)
    (out / "schedule.json").write_bytes(raw_schedule)
    writer_outputs, records = {}, []
    failed = None
    with (out / "traces.jsonl").open("w", encoding="utf-8") as stream:
        for step in schedule["scheduled_calls"]:
            row = {k: step[k] for k in ("call_index", "stage", "family_id", "variant_id", "arm_id", "source_sha256")}
            row["status"] = "PENDING"
            try:
                case, source, task, gold, alternatives = bind_case(step)
                if step["stage"] == "writer":
                    prompt = make_writer_prompt(step["arm_id"], source.content)
                else:
                    context, admitted, errors = memory_context(step, source, task, writer_outputs)
                    row.update(admission_passed=admitted, admission_errors=errors, carrier_chars=len(context))
                    prompt = make_reader_prompt(context, task)
                row["prompt"] = prompt
                result = generate(endpoint, prompt, schedule)
                row["raw_response"] = result.get("response", "")
                for key in ("prompt_eval_count", "eval_count", "wall_seconds", "done_reason",
                            "total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
                    row[key] = result.get(key)
                parsed = parse_model_object(row["raw_response"])
                if step["stage"] == "writer":
                    writer_outputs[(step["family_id"], step["variant_id"], step["arm_id"])] = parsed
                else:
                    simulation = get_simulator_for_family(case.family_id).execute(
                        action=parsed, task=task, gold_action=gold, valid_alternatives=alternatives,
                    )
                    row["parsed_action"] = parsed
                    row["outcome"] = simulation.outcome.value
                    row["correct"] = simulation.outcome in (
                        ActionOutcome.CORRECT_ACTION, ActionOutcome.LEGITIMATE_ABSTENTION,
                    )
                    row["before_hash"] = simulation.state_before_hash
                    row["after_hash"] = simulation.state_after_hash
                    row["simulator_details"] = simulation.details
                row["status"] = "COMPLETED"
            except Exception as exc:
                row.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
                failed = {"call": step["call_index"], "reason": str(exc)}
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            records.append(row)
            if failed:
                break  # Fail closed; never silently retry or score an incomplete run.
    readers = [r for r in records if r["stage"] == "reader" and r["status"] == "COMPLETED"]
    summary = {
        "status": "INCOMPLETE" if failed else "COMPLETED",
        "failure": failed, "scheduled_calls": 72,
        "completed_calls": sum(r["status"] == "COMPLETED" for r in records),
        "completed_reader_calls": len(readers), "scheduled_reader_calls": 48,
        "schedule_sha256": hashlib.sha256(raw_schedule).hexdigest(),
        "model": schedule["model"], "think": False,
        "result_scope": "AUTHOR_CONSTRUCTED_DEVELOPMENT_PILOT",
        "arms": {
            arm: {
                "completed_reader_calls": sum(r["arm_id"] == arm for r in readers),
                "correct": sum(bool(r["correct"]) for r in readers if r["arm_id"] == arm),
                "outcomes": dict(Counter(r["outcome"] for r in readers if r["arm_id"] == arm)),
                "full_pipeline_prompt_tokens": sum(r.get("prompt_eval_count") or 0 for r in records if r["arm_id"] == arm),
                "full_pipeline_completion_tokens": sum(r.get("eval_count") or 0 for r in records if r["arm_id"] == arm),
            } for arm in ARMS
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2), encoding="utf-8")
    print("ARTIFACT:", out)
    print(json.dumps(summary, indent=2))
    return 2 if failed or len(readers) != 48 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly opt in to 72 local inference calls")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    try:
        return run(args.execute, args.url)
    except Exception as exc:
        print(f"Pilot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
