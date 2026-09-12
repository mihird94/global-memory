# Mbrain Pass 6 — Context Control Plane and Harvest Integrity

## Mission

Turn Mbrain from a memory browser into a reliable context-engineering control plane for Mihir and multiple coding/research agents. This pass must make every durable record explain *why it exists*, help a new agent reconstruct project state quickly, and make nightly LLM harvesting auditable and operationally honest.

Pass 6 is an integrity and usefulness pass. Do not add decorative metrics, synthetic trust scores, or shallow entity counts. Do not commit or discard any existing working-tree changes.

## Starting point

Pass 5 introduced `gms-context-record-v1`, `gms_context_candidates`, a harvest-review UI/API/CLI, structured rendering, migration tooling, and local-model unloading. Treat all completion claims as hypotheses until independently verified.

Known facts to preserve:

- Repository: `/Users/mihirdeshpande/projects/global-memory`
- Brain root: `/Users/mihirdeshpande/memories`
- Nightly launchd schedule is 03:10 local time.
- Embeddings use `qwen3-embedding:0.6b`.
- Current installed harvesting baseline is `qwen3:8b`.
- `qwen3.5:9b` is the preferred A/B challenger, not an automatic replacement.
- No model may load on desktop startup, view navigation, search, or daytime capture.
- No global agent trust/reliability percentage is a valid product concept.
- All work remains uncommitted unless Mihir explicitly requests a commit.

## P0 — Establish a trustworthy baseline before changing code

1. Capture `git status --short` and preserve every pre-existing file, including icon assets.
2. Run the complete Python suite, JavaScript syntax checks, and `git diff --check`.
3. Inspect the live harvest queue and Dream Cycle status, but do not accept/reject candidates.
4. Check the live database for fixture-looking candidates, reviewers, or accepted facts created by manual smoke tests. Report any suspected pollution; do not silently delete it.
5. Record the exact current test count and distinguish temporary-test databases from the live Brain database.

## P0 — Test and dry-run isolation

Dry run means zero durable mutation. This is a hard invariant.

### Required behavior

- `tools/dream_cycle.py --dry-run` must not write candidates, claims, facts, graph edges, indexes, status history, project files, or episodic logs.
- It may return an in-memory preview and print exactly what would be staged.
- The result must explicitly expose `dry_run: true`, `candidates_extracted`, `candidates_would_stage`, and `durable_writes: 0`.
- Any model loaded during a dry run must still be unloaded with `keep_alive: 0` in every terminal path.
- Unit/integration tests must use injected temporary `MEMORY_ROOT` and database paths. No test may rely on or mutate `~/memories`.
- Add a sentinel test that hashes key live-Brain files before and after all dry-run paths and proves they are unchanged.
- Add a regression test that monkeypatches all durable write functions to fail if invoked during dry run.

### Production pollution audit

Detect, but do not automatically erase:

- candidates with fixture keys such as `mbrain.agent_trust_architecture`;
- reviewers such as `Mihir`, `tester`, `human-test`, or `UnrankedReviewer` created by test/smoke code;
- accepted claims whose provenance points to a fixture or fabricated source reference.

Provide a read-only report and an explicit, separately invocable cleanup command with `--dry-run` as its default. Cleanup requires a positive `--apply` flag and must write an audit record.

## P0 — Rationale-bearing review and authorship integrity

An accepted record is not trustworthy merely because a caller supplied an arbitrary reviewer string.

### Review contract

Every terminal review action—`accept`, `edit`, `merge`, `reject`, or `supersede`—must require:

- `reviewer_id` from a controlled local identity source;
- a substantive `review_rationale` (minimum 10 non-whitespace characters);
- `reviewed_at`;
- the original candidate content hash;
- the final accepted content hash when content changes;
- action type and any merge/supersession target;
- an append-only audit event.

`defer` may accept a short optional note but may not produce a canonical fact.

Do not let the browser invent authorship such as `Mihir` or `human-ui`. The UI must show the active local reviewer identity and require deliberate confirmation. APIs must reject missing, unknown, or client-forged reviewer identities. If robust OS identity is out of scope, implement an explicit locally configured reviewer registry and document its boundary; do not pretend it is cryptographic authentication.

### Semantic record contract

Never store a bare status value such as `retired`, `active`, `done`, or `blocked` when rationale affects future action. Decisions and policies must carry:

- statement/decision;
- rationale;
- actionable implications;
- scope and exclusions;
- source references with verifiable excerpt hashes;
- author/extractor/reviewer provenance;
- recorded and last-changed timestamps;
- supersession/review condition when applicable.

Do not set accepted content to synthetic `confidence: 1.0`. If a legacy storage field is unavoidable, isolate it from ranking and UI, document it as compatibility-only, and expose evidence completeness separately.

## P0 — Honest scheduler and runtime telemetry

There must be one source of truth for the nightly schedule.

- Remove the hard-coded `02:00 AM` response from `get_harvest_status`.
- Read the effective launchd schedule from the installed/configured plist or a shared schedule config used to generate the plist.
- The UI must distinguish configured schedule, last attempted run, last successful run, next expected run, provider/model, duration, candidate counts, durable-write count, and unload result.
- If launchd state cannot be read, show `Unavailable`; never manufacture a time.
- Add a test asserting the API agrees with the checked-in 03:10 plist.
- Status produced by a dry run must be labeled preview-only and must not overwrite last production success.

## P0 — Replace “agent trust” with evidence and outcomes

Remove remaining user-facing and decision-making dependence on alpha/beta reputation, Bayesian trust, reviewer trust weights, and global rankings.

The Review & Activity view should instead answer:

- What needs my attention now?
- What changed recently?
- Which records lack rationale or evidence?
- Which claims conflict or are stale?
- What did each agent contribute, and what happened to those contributions?

Allowed objective fields include proposed/accepted/edited/rejected counts, review turnaround, source coverage, schema-valid rate, duplicate rate, and task-scoped outcomes. These are descriptive facts, never a universal agent score. Keep legacy tables/functions only behind clearly marked compatibility boundaries if removing them would break stored data.

## P1 — Project Context Workspace as the primary product surface

The Projects view should be the fastest route for a new agent to understand and resume work.

### Project index

Default sort: recent meaningful activity. Offer recent activity, alphabetic, needs attention, and stale. Each project row shows:

- purpose in one line;
- current state;
- last meaningful change with absolute and relative time;
- active task/handoff count;
- unresolved decisions/conflicts;
- context freshness based on source timestamps, not a synthetic score;
- responsible/recent agents as attribution only.

Rows and all linked objects must be clickable and keyboard accessible.

### Project detail

Answer, in this order:

1. What is this project and why does it exist?
2. What is true now?
3. What decisions constrain the work, and why?
4. What is actively being worked on, by whom, and from which checkpoint?
5. What changed recently?
6. What is blocked, disputed, stale, or missing evidence?
7. What should the next agent read and do?

Provide tabs or sections for Overview, Decisions, Active Work, Timeline, Knowledge, and Handoffs. Preserve the existing Small/Standard/Deep context packet generator, but show inclusion reasons and provenance for every packet item.

### Agent/harness context support

Add context-engineering primitives useful across Codex, Antigravity, Gemini, terminal agents, and future harnesses:

- resumable task checkpoints with goal, progress, remaining work, blockers, evidence, commands/tests run, and changed files;
- explicit handoff bundles with producer, intended consumer, scope, assumptions, unresolved questions, and acceptance criteria;
- deterministic context packet hashes and source manifests;
- “copy launch prompt” and machine-readable JSON export;
- record-level freshness/supersession flags;
- trace from project → decision → evidence → task/handoff;
- no automatic dispatch or external messaging in this pass.

## P1 — Explore and harvesting UX

- Keep recent activity as Explore’s default and retain time groups.
- Render structured record summaries, not raw JSON or status-only values.
- Show `why this matters`, implications, scope, provenance, and review history without requiring Edit.
- Make entity paths navigational filters rather than decorative chips.
- Harvest Review must show original evidence excerpt beside the candidate and clearly mark inference versus quoted/source-backed content.
- Add filters for record type, project, source, review status, evidence completeness, and age.
- A review action must update the list, project detail, timeline, and context packet behavior consistently.

## P1 — Source-reference integrity

- Source references must resolve to a real file plus a stable anchor or line/excerpt locator.
- `excerpt_hash` must hash the cited normalized excerpt, not the entire source file unless the reference explicitly covers the entire file.
- Migration tooling may not invent rationale or fake anchors. If rationale is not present, classify the item as an observation or stage it as `needs_rationale`.
- UI must provide “open source” and clearly report missing/moved/mismatched evidence.
- Add tests for valid excerpts, changed excerpts, missing files, nonexistent anchors, and whole-file references.

## P1 — Local model evaluation and lifecycle

Keep `qwen3:8b` as the operational default until a checked-in A/B evaluation proves a replacement.

Build a reproducible evaluator comparing installed `qwen3:8b` with optional `qwen3.5:9b` on representative checked-in harvesting fixtures. Measure:

- JSON/schema-valid rate;
- rationale faithfulness to source;
- unsupported inference rate;
- correct record-type classification;
- source-reference accuracy;
- decision/policy unsafe-promotion count (must be zero);
- deduplication quality;
- latency and peak memory;
- model unload success.

The evaluator must not download a model automatically. If `qwen3.5:9b` is unavailable, report `not installed` and complete the baseline evaluation. Recommend switching only if the challenger materially improves semantic quality with acceptable latency/memory. Do not use generic benchmark reputation as the decision.

## P2 — Concepts and graph usefulness

Do not use nightly LLM output merely to create noun fragments.

- Concepts should represent canonical topics, systems, people/agents, projects, artifacts, decisions, and policies with aliases and evidence.
- Show why a concept exists, where it appears, recent activity, connected projects, and unresolved merge suggestions.
- Graph defaults should suppress isolated/noisy nodes and allow minimum degree filters such as 1+, 2+, 3+, 5+.
- Provide relationship-type, project, recency, and record-type filters.
- Use stable Obsidian-like physics with pause/resume, reset, fit, focus neighborhood, and saved layout positions.
- Edge clicks must show relationship evidence and temporal validity.
- Graph and Concepts must navigate into Project, Explore, and source views.

## API and CLI expectations

Keep public responses typed and versioned. Add or harden endpoints/commands for:

- harvest status and preview;
- candidate list/show/review;
- review audit history;
- source validation;
- pollution audit and explicit cleanup preview/apply;
- project list/detail/timeline/context packet;
- local model evaluation report.

All write endpoints require validated local reviewer identity, action rationale where specified, optimistic concurrency using the candidate content hash, and a structured audit result.

## Tests and acceptance gates

At minimum, add regression coverage for:

1. Dream Cycle dry run performs zero durable writes.
2. Tests never touch the live Brain root.
3. Every accept/edit/merge/reject/supersede action has valid reviewer identity and rationale.
4. A stale candidate hash cannot be reviewed after concurrent modification.
5. Accepted decisions/policies remain rationale-rich through storage, Explore, Projects, and context packets.
6. No user-facing trust percentage or global reputation ordering remains.
7. Schedule API matches the 03:10 plist and handles unavailable state honestly.
8. Source excerpt hashes are verifiable and migrations never invent rationale.
9. `qwen3:8b` evaluation completes without model persistence; optional challenger is skipped honestly when absent.
10. Project lists sort by meaningful recent activity and all navigation is functional.
11. Graph minimum-degree and relationship/project/recency filters compose correctly.
12. Existing tests remain green.

Final verification:

```bash
PYTHONPATH=.:tools pytest tests/ -q
find desktop -name '*.js' -exec node --check {} \;
git diff --check
```

Also run a live-root immutability check around every dry-run command and report before/after hashes. Do not run `--apply`, accept/reject live candidates, install a model, change launchd configuration, or delete suspected pollution without explicit approval.

## Required handoff

Return:

1. outcome-first summary;
2. exact files changed;
3. baseline and final test counts;
4. live-state reads performed;
5. proof of dry-run immutability;
6. reviewer-identity and rationale enforcement details;
7. schedule source-of-truth proof;
8. source-integrity test results;
9. model evaluation results and recommendation;
10. known limitations and deferred work;
11. `git status --short`;
12. confirmation that no commit, model download, launchd mutation, live review decision, or cleanup was performed.

Stop and report rather than guessing if an action would mutate production Brain data or require Mihir’s product decision.
