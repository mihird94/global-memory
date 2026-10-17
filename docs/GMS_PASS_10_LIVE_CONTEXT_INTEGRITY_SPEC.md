# GMS Pass 10 — Live Context Integrity and Evaluation Honesty

## Mission

Make Brain's **live** agent-resumption path as reliable and inspectable as its
fixture-level regression suite. This is a corrective integration pass, not a
new-memory-architecture pass.

The system currently has strong local regression coverage, but three
operational truths are out of sync:

1. Current code and episodic history have advanced materially, while the
   `global-memory` project bank still describes an older v2.1 state and has no
   active task, checkpoint, handoff, or concrete next action.
2. The October 5 scheduled Dream Cycle completed its process and unloaded the
   local model, but no configured provider returned schema-valid candidates.
   The public status gives only a generic failure reason.
3. Fixture evaluation is now safety-aware, but its compact CLI output can make
   correlated local variants and structural bundle checks look more conclusive
   than they are. The actual live resumption gate is currently closed.

Do **not** respond by adding another cognitive subsystem, a new score, a new
global agent rating, or a bulk rewrite of `~/memories`.

## Baseline (verify before editing)

- Repository: `/Users/mihirdeshpande/projects/global-memory`
- Memory root: `/Users/mihirdeshpande/memories`
- Current baseline commit: `f3c0fb3`
- Baseline suite: `333 passed, 1 skipped`
- Current registry: `75 mem_*` tools and `75 brain_*` aliases (`150` names).
- `brain eval-lab run --suite all --no-export` runs successfully in its
  isolated fixture root.
- The prior `brain eval-lab` import-path failure is resolved. Do not regress it.
- Generic-key/parser-error admission guards are implemented in `tools/schemas.py`
  and covered by `tests/test_control_plane_remediation.py`. Do not duplicate
  that work or mutate the historical `error` record as part of this pass.

### Current observed evidence (2026-10-05)

```text
Dream Cycle (03:10):
  status=degraded
  configured_model=qwen3:8b
  provider=none
  extraction_status=no_provider_succeeded
  duration=413.93s
  durable_writes=0
  model unload=confirmed; active_models=[]

Fixture evaluations:
  LongMemEval-inspired:      59/60 (one correlated historical-query variant)
  LoCoMo-inspired:           60/60
  MemoryAgentBench-inspired: 20/20
  Context bundle structure:   2/2

Live resumption evaluation:
  7/9 evaluable scenarios pass
  1 scenario is not evaluable because no active task/checkpoint/handoff exists
  quality_gate_passed=false
  failed: current-Mbrain-pass resumption (2/4 keys), opaque-status safety (0/1)
```

## Non-negotiable constraints

1. **No live-memory mutation during diagnosis.** All diagnostics, previews,
   fixtures, and evaluation runs must use either a read-only live root or an
   injected temporary root. Never create a fake live task to make the live
   resumption metric pass.
2. **No automatic rewriting of project banks.** A system may compute a
   deterministic reconciliation preview, but only an explicit registered actor
   plus rationale and optimistic-concurrency hash may apply it.
3. **No external model download or cloud dependency.** Keep local-first
   behavior. No model may load for Desktop startup, passive navigation, or
   ordinary packet generation.
4. **No synthetic quality/trust score.** Show source/evidence coverage,
   effective time, freshness, conflicts, and task state separately.
5. **Do not overclaim benchmarks.** The checked-in adapters are local,
   Brain-authored regression fixtures—not official LongMemEval, LoCoMo, or
   MemoryAgentBench runs, and not an LLM-agent continuation evaluation.
6. Preserve task/claim lifecycle history, source attribution, aliases,
   time-travel queries, deterministic context-packet hashes, and all existing
   admission guards.
7. Do not commit, deploy, install models, alter launchd, or modify live
   candidates/claims without explicit user approval.

## P0 — Explain and diagnose degraded Dream Cycle runs

### Problem

`brain harvest-status` shows a useful terminal state (`degraded`) but collapses
all provider failures into a generic `All configured extractors failed...`
message. A seven-minute run cannot be acted on without knowing whether the
cause was an unavailable Ollama service/model, timeout, malformed output,
schema rejection, lock contention, or a preceding provider failure.

### Required implementation

1. In `tools/dream_cycle.py`, capture a bounded structured attempt record for
   every configured provider:

   ```json
   {
     "provider": "ollama",
     "model": "qwen3:8b",
     "outcome": "success|unavailable|timeout|invalid_output|schema_rejected|empty|skipped",
     "duration_seconds": 0.0,
     "candidate_count": 0,
     "error_code": "MODEL_NOT_INSTALLED|HTTP_ERROR|...",
     "safe_message": "short redacted diagnostic"
   }
   ```

   Do not persist raw model output, secrets, prompts, or stack traces in the
   status file.

2. Persist this as `provider_attempts` in the production run status only after
   a real run. Dry runs must return the field in memory/output but must not
   replace the last production status.
3. Expose the same data through:
   - `brain harvest-status`;
   - the harvest-status Desktop/API response;
   - the existing MCP status surface, if applicable.
4. Add an explicit read-only `diagnose` action only if the existing status
   command cannot cleanly expose the needed details. Prefer extending the
   existing status schema over adding a new tool.
5. Preserve the required unload behavior in every terminal path.

### Tests

- provider unavailable, timeout, invalid JSON, schema rejection, empty output,
  and success each produce one correctly classified attempt record;
- raw secret-like text and long tracebacks are absent/redacted;
- a dry run cannot overwrite last production attempt data;
- completed-but-no-provider state remains `degraded`, not `success`;
- Desktop/API/CLI status payloads agree on the attempt summary;
- existing local-harvest and scheduler telemetry tests remain green.

## P0 — Make project context freshness explicit and safe

### Problem

The `global-memory` project bank is not continuously reconciled with its newer
episodes and code. The briefing reports an older v2.1 goal, no active work, and
`Next action unavailable`; meanwhile the timeline contains verified Oct 4–5
milestones. An agent can therefore receive a structurally valid but obsolete
resumption packet.

### Required implementation

1. Add a **read-only project-context reconciliation preview** in the current
   project control plane (CLI, MCP, and Desktop API only where there is already
   parity). The preview must compare:

   - latest project-bank effective time;
   - latest relevant project timeline/episode effective time;
   - latest active task, checkpoint, and handoff;
   - unresolved decisions/conflicts;
   - whether the bank's stated next action is missing or stale.

2. Return a versioned, deterministic result such as:

   ```json
   {
     "schema_version": "gms-project-context-reconciliation-v1",
     "project": "global-memory",
     "bank_effective_at": "...",
     "latest_evidence_at": "...",
     "freshness": "current|behind|missing_active_context",
     "gaps": [{"field":"active_work","reason":"...","evidence_refs":["..."]}],
     "suggested_update": {"...": "..."},
     "snapshot_hash": "sha256:...",
     "apply_supported": false
   }
   ```

   The preview is a proposal, not a claim of truth. It must quote/link its
   source evidence and clearly label derived text as system synthesis.

3. If an apply path is added, it must be a separate explicit operation with a
   registered actor, substantive rationale, expected snapshot hash, and
   append-only audit event. Default behavior is preview-only. Do not implement
   autonomous writes in this pass unless all of those guards already exist and
   are reused.

4. Update `project_briefing` and `morning_briefing` to surface a concise
   `context_freshness_warning` when a project bank lags newer relevant evidence.
   Do not silently substitute a synthesized summary for the bank.

5. Do not infer a task owner, task completion, or next action when none exists.
   Report missing task continuity honestly.

### Tests

- a project bank older than a relevant verified episode produces `behind` and
  evidence links;
- old but irrelevant other-project episodes do not trigger a warning;
- same timestamp/current bank produces `current`;
- a missing task/handoff is reported as missing, not fabricated;
- preview is byte-for-byte deterministic for unchanged input and has no writes;
- any apply path rejects unknown actor, short rationale, and stale hash;
- existing project-briefing, morning-briefing, task-handoff, and API tests pass.

## P1 — Correct current-context ranking without breaking historical retrieval

### Problem

For a query such as “current global-memory context and next action,” older
lexically similar project-bank sections may outrank newer episode/timeline
evidence. File recency is not event recency; a file containing old dated
sections may be modified today.

### Required implementation

1. In `tools/context_retrieval_planner.py`, preserve and use section/event
   `effective_at` extracted from dated content before fallback file metadata.
2. For intents classified as `resume`, `current`, `status`, `next_action`, or
   `handoff`, apply a documented bounded effective-time boost **after**
   authority/scope/lifecycle filtering and before final diversification.
3. Never boost:
   - superseded, archived, expired, stale, or unresolved-conflict records into
     actionable position;
   - lower-authority inference over a relevant user instruction or verified
     system output solely because it is newer;
   - records after `as_of` for historical queries.
4. Keep deterministic tie-breaking and packet hashes stable for unchanged
   inputs. Report the recency component in inclusion reasons/manifest so users
   can see why something moved.
5. Add a fallback rule: if the project has no active task/handoff, the packet
   must say that explicitly rather than selecting a stale “next action” as if
   it were live.

### Tests

- newer dated section beats an older lexical near-duplicate for a current
  context query;
- the reverse is true for an `as_of` query before the newer record;
- a permanent policy/user instruction remains correctly prioritized;
- project isolation and diversity caps remain intact;
- deterministic packet hash is stable across repeated unchanged runs;
- add the current live resumption failure shape as a temporary-root regression
  fixture, not a dependency on `~/memories`.

## P1 — Make evaluation output decision-useful

### Problem

The fixture adapter safety rules are now sounder: answerable cases require
supported/actionable evidence; abstention cases must be non-actionable and
leak-free. However, the compact output foregrounds one aggregate percentage,
even though 48 of 60 LongMemEval- and LoCoMo-inspired cases are correlated
variants and context-bundle checks do not invoke a fresh agent.

### Required implementation

1. Keep the existing strict pass logic. Do not loosen safety checks to recover
   the single failing historical-query variant.
2. In `eval/cli.py` and JSON reports, print/report separately:
   - canonical cases: passed/total;
   - correlated robustness variants: passed/total;
   - answerable: passed/total;
   - expected abstentions: passed/total;
   - retrieval-only hits;
   - answerable non-supported passes (must be zero);
   - actionable prohibited leaks (must be zero);
   - official benchmark status (`false`);
   - whether a fresh model/agent continuation was actually run.
3. Report the single failing case ID and its evidence/actionability state in a
   compact failures section. Do not print raw private fixture content by
   default.
4. Make the command's final verdict three-valued:

   ```text
   regression_green       # fixture safety and required thresholds pass
   regression_degraded    # fixtures run, but a required threshold fails
   not_external_benchmark # always when only internal adapters were run
   ```

   This is metadata, not a new aggregate trust/quality score.

5. Resumption output must continue to distinguish `failed`, `not_evaluable`,
   and `not_run`. A missing live task/handoff must keep the quality gate closed.

### Tests

- canonical/variant counts are exact and never silently combined;
- one answerable case with insufficient evidence is a retrieval-only failure,
  not a pass;
- one expected abstention with actionable evidence is a failure;
- compact output includes the non-official disclaimer and continuation mode;
- no raw fixture/secret content appears in default failure output;
- existing evaluation tests and tuning holdout tests pass.

## P2 — Demonstrate real task continuity without manufacturing it

### Goal

The resumption benchmark requires at least one real lifecycle-shaped example,
but the product must not generate fictitious live work merely to satisfy an
evaluation.

### Required implementation

1. Add/retain a hermetic integration fixture proving:

   ```text
   task create → claim → checkpoint → handoff → targeted claim → resume → complete
   ```

   It must prove revision/concurrency enforcement, artifact references,
   explicit blockers, acceptance criteria, and one next action survive the
   handoff.
2. Add a **read-only live readiness check** that says whether a suitable real
   task/checkpoint/handoff exists. It must not create one.
3. The live resumption quality gate must stay closed when none exists; this is
   correct behavior, not an error to bypass.

## Verification checklist

Run before handoff; report exact outputs and distinguish fixture from live-root
checks:

```bash
git status --short
git diff --check
PYTHONPATH=.:tools .venv/bin/python -m pytest tests -q
brain eval-lab run --suite all --no-export
brain eval-lab ablate --no-export
brain eval-resumption run --project global-memory
brain harvest-status
brain project-briefing get --project global-memory --profile condensed
```

Also run focused tests for Dream Cycle telemetry, project reconciliation,
current-context ranking, evaluation reporting, and task handoff.

## Deliverable and stopping condition

Return:

```text
IMPLEMENTED=
TESTS=
LIVE_READ_ONLY_CHECKS=
FIXTURE_EVAL_VERDICT=
LIVE_RESUMPTION_VERDICT=
DREAM_CYCLE_DIAGNOSIS=
PROJECT_CONTEXT_FRESHNESS=
KNOWN_LIMITATIONS=
```

Stop after the specification is implemented and verified. Do not commit,
deploy, trigger a real Dream Cycle, modify launchd, install/download a model,
or mutate `~/memories` without explicit approval.
