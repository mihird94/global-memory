# GMS System Design

## Purpose

The Global Memory System (GMS) is a local-first memory platform for multi-agent workflows. Its design goal is to make durable memory usable across agents without collapsing correctness, provenance, or security.

The implemented system centers on one principle: all durable memory promotion must pass through a trust-aware control plane, regardless of whether the caller arrives through MCP, CLI, Dream Cycle, or the terminal UI.

## Design Goals

- Local-first storage and operation
- MCP-first interoperability for agent clients
- Backward-compatible CLI access for tools and scripts
- Typed memory instead of one flat fact bag
- Versioned, auditable claims instead of silent overwrite
- Quarantine and reviewer workflows for conflicting writes
- Nightly consolidation without bypassing trust controls
- SSH-friendly operator workflows

## Non-Goals

- Managed cloud control plane
- External graph database dependency
- LLM-only trust decisions
- Perfect truth resolution across all domains

## Top-Level Architecture

GMS is implemented as a set of local tools around a shared memory root.

### Surfaces

- `tools/memory_mcp_server.py`
  - MCP server and trust-aware write surface
- `tools/memoryctl.py`
  - CLI and operator commands
- `tools/gms_tui.py`
  - curses terminal UI for SSH use
- `tools/dream_cycle.py`
  - nightly consolidation, calibration, and retention work
- `tools/gms_inspect.py`
  - snapshot and inspection helpers
- `tools/gms_eval.py`
  - deterministic evaluation harness

### Shared Storage

- Typed `facts.json` files for current state
- `gms_trust.sqlite` for claims, provenance, trust, quarantine, reviews, procedures, and graph edges
- episodic markdown logs for narrative history
- optional embedding index files under the memory root

## Data Model

### Typed Memory

GMS routes writes into one of these memory kinds:

- `semantic`
  - durable world or project facts
- `operational`
  - agent behavior, policies, settings, and contracts
- `procedural`
  - reusable trigger-action knowledge
- `session`
  - ephemeral task-local state that should not become durable fact storage

Current fact state for non-session kinds is stored in `<kind>/facts.json`.

### Trust Database

The SQLite trust database is the authoritative audit layer.

Key tables:

- `gms_agent_reputation`
  - `alpha` and `beta` evidence for each agent or reviewer
- `gms_fact_provenance`
  - last known provenance for the active fact surface
- `gms_quarantined_facts`
  - conflicting fact proposals awaiting resolution
- `gms_claims`
  - append-oriented claim ledger with status and confidence
- `gms_entities`
  - lightweight entity registry
- `gms_relationships`
  - graph edges sourced from claims
- `gms_procedures`
  - extracted procedural memory
- `gms_quarantine_reviews`
  - reviewer endorsements, rejections, and abstentions

### Claim States

Claims move through explicit lifecycle states:

- `active`
- `superseded`
- `quarantined`
- `discarded`
- `archived`

This is the main mechanism that replaces silent overwrite. The current facts view is a projection. The claim ledger is the history.

### Task Handoff State

Durable memory is not a substitute for in-progress work state. GMS keeps
cross-agent coordination in the same local SQLite database, but outside the
typed fact projection:

- `gms_tasks` stores a project-scoped task, its owner, lease, lifecycle state,
  and optimistic revision.
- `gms_task_checkpoints` stores immutable, versioned state bundles and
  references to artifacts, claims, and episodes.
- `gms_handoffs` stores the recipient-facing summary: completed work, next
  action, blockers, acceptance criteria, and bounded context.

A claim, checkpoint, handoff, and completion must carry the task's expected
revision. A stale operation returns the current task rather than overwriting it.
Claiming a targeted handoff records acknowledgement. This provides local task
continuity without promoting transient work state into global facts.

## Write Path

### Normal Fact Promotion

The canonical durable write path is:

1. determine memory kind
2. inspect existing active state
3. evaluate conflict and trust
4. either promote directly or quarantine
5. record claim
6. update current typed fact projection
7. record provenance

This path is exposed through MCP and reused by CLI and Dream Cycle operations.

### Conflict Handling

Conflicting writes do not directly replace current state when the proposed write is insufficiently trusted or materially inconsistent.

Instead, the system:

- writes a quarantined proposal
- records a quarantined claim
- preserves active fact state
- exposes the item for human or agent review

### Reviewer Weighting

Quarantined items can accumulate structured reviews:

- `endorse`
- `reject`
- `abstain`

Each review is weighted by the reviewer’s trust at the time of review. Recommendation summaries collapse these weighted reviews into a promote, discard, or neutral recommendation. When the operator resolves the item, reviewer reputation is updated based on whether the reviewer aligned with the final decision.

## Trust and Calibration

### Reputation Model

Baseline reputation uses a Jøsang-style Beta evidence model:

- positive outcomes increase `alpha`
- negative outcomes increase `beta`
- trust is derived from the posterior expectation

This is used both for proposing agents and for quarantine reviewers.

### Multi-Rater Calibration

Nightly calibration computes overlap and disagreement from the claim ledger and runs a symmetric Dawid-Skene EM pass when there is enough multi-observer overlap.

Outputs include:

- overlap counts
- agreement and disagreement counts
- inferred observer accuracy
- convergence metadata

This calibration is a corrective layer, not a replacement for explicit trust updates from real workflow outcomes.

## Typed Routing

Routing is intentionally simple and heuristic. The system classifies writes by key and value patterns:

- operational keywords route to `operational`
- procedural keywords route to `procedural`
- session keywords route to `session`
- everything else defaults to `semantic`

This follows the design principle that simple routing is better than a large opaque router until the schema pressure proves otherwise.

## Entity and Relationship Layer

GMS includes a lightweight graph substrate rather than a separate graph database. Claims can source entity and relationship records, which enables:

- provenance-aware structured relations
- future graph exploration
- relationship validity windows

This is intentionally narrow. The graph layer exists to enrich memory semantics, not to become an independent persistence platform.

## Dream Cycle

The Dream Cycle is the nightly consolidation job. It:

1. reads recent episodic journal material
2. extracts candidate durable facts through a provider cascade
3. routes those candidates through the same trust-aware save path used elsewhere
4. rebuilds the embedding index when appropriate
5. emits a calibration report
6. runs retention pruning
7. appends a summary entry to episodic history

Provider cascade:

- Antigravity CLI
- Gemini CLI
- Ollama local fallback

The critical design constraint is that Dream Cycle is not privileged to bypass the trust layer.

## Retrieval and Search

GMS uses a hybrid retrieval approach:

- direct fact lookup through typed fact stores
- semantic and textual retrieval through the CLI and MCP tools
- recency-aware episodic retrieval
- drift reporting over embedding/index state

The current system is optimized for local operation and operator visibility rather than maximal retrieval sophistication.

## Retention and Forgetting

Retention is implemented as explicit pruning logic rather than implicit decay alone.

The nightly retention pass can:

- archive stale, low-confidence active claims
- remove their projected current facts
- flush stale quarantines
- preserve ledger auditability

This means forgetting changes the active surface without destroying historical accountability.

## Operator Surfaces

### CLI

The CLI is the stable fallback and scripting surface. It supports:

- session context startup
- search and inspection
- logging and fact writes
- trust and quarantine reporting
- calibration, drift, and retention reporting
- quarantine actions

### MCP

MCP is the preferred agent-facing interface. It exposes the same trust-aware operations without requiring shell execution in the caller.

It also exposes task creation, revision-safe claiming, checkpointing, handoff,
resumption, completion, and project-state inspection. These tools are a local
control plane modelled around A2A-style tasks and artifacts; an external A2A
transport can be added later without changing GMS storage semantics.

### Terminal UI

The curses TUI is the current primary operator surface for SSH use. It provides:

- summary view
- quarantine queue
- trust view
- claims view
- drill-down panes
- keyboard and mouse navigation

This gives operators a fast local review workflow without adding a web dependency.

## Evaluation Strategy

The repo includes deterministic evaluation scenarios in `tools/gms_eval.py` and a growing unit test suite under `tests/`.

Current evaluation themes:

- trusted overwrite behavior
- quarantine resistance
- episodic summary recall
- abstention on missing context
- weighted quarantine resolution
- retention archival
- drift reporting
- calibration behavior
- TUI behavior

This is meant to keep architecture claims tied to executable checks.

## Failure Modes and Defenses

### Memory Poisoning

Defense:

- trust-gated writes
- quarantine
- reviewer weighting
- claim history

### Silent Overwrite

Defense:

- append-oriented claim ledger
- supersession state
- provenance recording

### Nightly Consolidation Corruption

Defense:

- Dream Cycle uses the same write gate as operators and agents
- multi-provider extraction fallback
- journal logging

### Stale Low-Trust Facts

Defense:

- retention pruning
- archival rather than destructive deletion

## Compatibility Model

The repo moved from `global_skills` to `projects`, but remains backward-compatible through:

- stable CLI wrapper behavior
- MCP registration updates
- path-safe sibling resolution in tools
- old-path symlink compatibility

This matters because agents and steering files may still call the older skill-era paths.

## Current Limitations

- Typed routing is still heuristic rather than schema-driven
- Graph exploration is present in storage but only lightly surfaced
- Drift monitoring is practical but not yet a full research-grade anomaly pipeline
- The TUI is strong for queue review but not yet a full graph browser

## Near-Term Evolution

The highest-value remaining work is mostly operator-surface refinement:

- deeper quarantine review workflows in TUI
- graph exploration in terminal form
- more explicit branch, project, and agent scoping
- broader adversarial evaluation packs

See [ROADMAP.md](ROADMAP.md) for the longer product direction.
