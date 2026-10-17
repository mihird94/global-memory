# Frozen local harvesting pilot

This is the next evidence step after the October 17 two-paper review. It tests new synthetic consolidation cases, not live private memory or CCMP action recovery.

## Frozen design

Bundle: `research_harness/reports/harvest_pilot_20261017_v1/`.

Four newly authored scenarios cover scoped backup retention with a rejected alternative, configuration units and supersession, an ordered procedure with a synthetic secret-format canary and chatter, and a no-write conversation. Cases and expected proxies were fixed before inference. The author also designed the evaluator: this is a new-case development pilot, not a blinded independent holdout or public benchmark.

Compare installed `qwen2.5-coder:7b` and `qwen3:8b`, both with `think=false`, temperature zero, seed 1742, context 8192 and completion cap 1536. Eight requests are scheduled in a seeded shuffled order with no retries or output-driven prompt revisions. Limits: 120 seconds per request, 1200 seconds total, and 32000 reported tokens with conservative full-context-plus-output reservation before dispatch. Record failed or invalid responses and stopping conditions.

Raw request and full raw response are fsynced to an append-only dispatch ledger before scoring. Prompt, code, corpus, and protocol hashes are captured; the protocol has a separate digest. Product helpers import under an isolated temporary `MEMORY_ROOT`. Only loopback Ollama is permitted; proxies and redirects are disabled. No cloud fallback, downloads, private memory ingestion or promotion is part of this run.

## Analysis

Report raw/admitted candidate counts and automated keyword proxies separately from semantic inspection. Inspect scope, rejected proposals, supersession, units, ordering, failure handling, canary/chatter exclusion and no-write behavior directly against the frozen excerpts. Empty no-write output is correct behavior; F1 on an empty gold set is not a meaningful summary.

The existing persistence audit is a surrogate JSON/SQLite readback check. Its results must not be described as production storage or graph/index safety. No live graph extraction is scheduled. Model effects are descriptive: four shared scenarios with one sample per model do not support general superiority or non-inferiority claims.

## Next boundary

After this pilot, freeze any resulting repair and obtain independently authored held-out cases before a paper-level evaluation. CCMP's held-out action-recovery study remains a separate next experiment: freeze its task schedule, model inputs and action oracles before model calls, and carry over the schedule-aware paired analysis. Do not report this consolidation pilot as CCMP efficacy evidence.

Agy is not messaged automatically. Share the frozen bundle, observed failures and scope limits after the run is complete.
