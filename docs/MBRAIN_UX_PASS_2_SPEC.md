# Mbrain UX Pass 2 — Implementation Specification

**Owner:** Antigravity
**Product:** Mbrain Desktop Control Center
**Repository:** `global-memory`
**Status:** Ready for implementation
**Prerequisite:** UX Pass 1 is present in the working tree. Preserve all existing uncommitted work, including desktop icon assets.

## 1. Mission

Turn Mbrain from a technically functional memory viewer into a useful local knowledge-navigation product. Pass 2 must deepen the graph, entity intelligence, provenance, and cross-view navigation without replacing the current local-first architecture.

The primary outcome is:

> A user can reduce a noisy knowledge graph to a meaningful subgraph, understand why every node and edge exists, move fluidly between graph/entities/memories, and identify low-quality knowledge requiring cleanup.

This is not a visual-only pass. Every new control must have clear behavior, persistent state where appropriate, empty/error handling, and tests.

## 2. Product Principles

1. **Local-first:** No runtime CDN, hosted service, telemetry, or mandatory network dependency.
2. **Evidence before decoration:** A graph node is useful only if the user can reach the memories or claims supporting it.
3. **Progressive disclosure:** Default graph state should be calm and legible. Advanced controls belong in a collapsible settings panel.
4. **One connected workspace:** Explore, Graph, and Entities are alternate views of the same knowledge, not independent demos.
5. **No fabricated certainty:** Do not invent confidence scores. Expose evidence-derived metrics with transparent definitions.
6. **Preserve temporal semantics:** Active, historical, superseded, and as-of states must remain distinguishable.
7. **Performance is product quality:** Filtering and selection should feel immediate at the current database size and remain reasonable at 5,000 nodes / 20,000 edges.

## 3. Current Baseline

Pass 1 already provides:

- Clickable three-pane Explore workspace.
- Namespace and tier filtering.
- Memory inspector and related-search actions.
- Obsidian-inspired dot-node graph using local `vis-network`.
- Graph search, focus, neighbor selection, history toggle, and as-of date.
- Entity catalog with quality indicators.
- Cross-navigation among Graph, Entities, and Explore.
- Extraction preview with known/new entity resolution.
- Daily Notes action named **Process into Memory**.

Pass 2 must extend this baseline rather than reverting to the earlier table, box-node graph, static concepts grid, or CDN dependency.

## 4. Scope and Priorities

### P0 — Required

- Graph connection-count filtering.
- Advanced physics controls and stable defaults.
- Graph type, namespace, predicate, state, and isolate filters.
- Connected-component and neighborhood exploration.
- Evidence/provenance for entities and relationships.
- Canonical entity detail with aliases and possible-duplicate review.
- Cross-view selection state and back navigation.
- Automated backend and frontend behavior tests.

### P1 — Strongly desired

- Graph clustering by type, namespace, and connected component.
- Saved graph views.
- Degree distribution and filter-result summary.
- Search highlighting and multi-select comparison.
- Entity enrichment queue.
- Relationship timeline.

### P2 — Optional if P0/P1 are complete and verified

- Mini-map.
- Export current subgraph as JSON/PNG.
- Keyboard command palette for graph operations.
- Community detection if it can be implemented locally and deterministically.

## 5. Graph Experience

### 5.1 Default graph behavior

The current production graph contains many low-information nodes and isolated or one-edge literal nodes. The initial view must prioritize legibility.

Default state:

- Show active edges only.
- Hide isolated nodes by default.
- Set minimum connections to `2` by default. Allow `0`, `1`, `2`, `3`, `5`, `10+`.
- Keep the full graph available; filtering must not delete or mutate data.
- Fit visible nodes after initial stabilization.
- Stop physics after stabilization to prevent perpetual motion.
- Preserve user viewport when changing label visibility or opening an inspector.
- Re-fit only when the visible node set materially changes or the user presses Fit.

### 5.2 Filter panel

Add a collapsible left-side Graph Filters panel. It must not permanently consume canvas width when collapsed.

Required filters:

#### Minimum connections

- Slider or segmented control with values: `0`, `1+`, `2+`, `3+`, `5+`, `10+`.
- “Connections” means visible degree after active/time filtering, before the minimum-degree filter is applied.
- Show the current value prominently: e.g. **3+ connections**.
- Nodes selected explicitly through search must remain visible even when below the threshold. Mark them as temporarily revealed.

#### Entity types

- Multi-select checkboxes generated dynamically from API data.
- Each type displays its pre-filter count.
- Include Select all and Clear actions.
- Use a consistent color mapping across Graph and Entities.
- Normalize type casing in the backend or view model (`concept` and `CONCEPT` must not become separate types).

#### Relationship predicates

- Multi-select list ordered by frequency.
- Show predicate counts.
- Search predicates when there are more than 12.
- Selecting predicates must retain both endpoints of matching edges.

#### Temporal state

- Active only.
- Historical only.
- Active + historical.
- As-of date remains supported and takes precedence over simple state filtering.
- Historical edges must use muted red/orange dashed styling with a clear legend.

#### Connectivity

- Hide isolates toggle, default on.
- Largest connected component only toggle.
- Neighborhood depth: `1`, `2`, or `All`, enabled when a focus node is selected.
- “Only paths between selected nodes” when exactly two nodes are selected; optional if shortest-path computation is not yet available.

#### Text filter

- Filter node names and summaries, distinct from the existing search-and-focus box.
- Search-and-focus reveals one target; text filter reduces the entire graph.

### 5.3 Filter semantics

Implement graph filtering as a deterministic pipeline:

1. Apply temporal/as-of edge state.
2. Apply predicate filter.
3. Build candidate endpoint node set.
4. Apply entity-type filter.
5. Recompute visible degree.
6. Apply minimum-connections threshold.
7. Remove edges whose endpoints are no longer visible.
8. Apply isolate/largest-component/neighborhood constraints.
9. Re-add explicitly searched/revealed nodes with a `revealed` marker.
10. Produce filter metadata for the UI.

Return or calculate:

- Total nodes and edges.
- Visible nodes and edges.
- Hidden-by-reason counts: temporal, type, predicate, degree, component, isolate.
- Available type and predicate facets with counts.

Filtering must be unit-testable as a pure function. Prefer extracting it into a dedicated module instead of embedding it entirely in DOM rendering code.

### 5.4 Physics panel

Add an Advanced Physics section within Graph Filters.

Presets:

- **Balanced** — default; general browsing.
- **Loose** — more separation for dense graphs.
- **Compact** — tighter clusters.
- **Hierarchical** — directed relationship reading; use a left-to-right or top-to-bottom layout and disable force physics as needed.
- **Manual** — exposes individual controls.

Manual controls:

- Repulsion/gravitational constant.
- Central gravity.
- Spring length.
- Spring constant.
- Damping.
- Avoid overlap.
- Maximum velocity.
- Stabilization iterations.

Behavior:

- Show human-readable ranges, not undocumented raw internals alone.
- Debounce changes by 150–250 ms.
- Provide **Re-run physics** and **Reset defaults** actions.
- Do not re-run physics merely because the inspector opened.
- Persist the chosen preset and manual values in local storage.
- Guard against NaN, negative values outside supported ranges, and unusable extremes.
- Display a subtle “stabilizing” indicator while physics is active.
- Stop physics automatically after stabilization.

Recommended Balanced starting values for `forceAtlas2Based`:

```json
{
  "gravitationalConstant": -72,
  "centralGravity": 0.012,
  "springLength": 128,
  "springConstant": 0.045,
  "damping": 0.55,
  "avoidOverlap": 0.65,
  "maxVelocity": 28,
  "stabilizationIterations": 280
}
```

Tune these against real production data rather than treating them as immutable.

### 5.5 Clustering

Provide a Cluster menu:

- None.
- By entity type.
- By namespace/domain when determinable.
- By connected component.

Cluster behavior:

- Cluster nodes must show member count and dominant type.
- Clicking selects and explains the cluster.
- Double-click expands the cluster.
- Expanded state should survive inspector opening.
- Clustering is a view transformation only; never persist synthetic cluster nodes as knowledge entities.
- If automatic community detection is implemented, use a deterministic local algorithm and label it **Communities**, not semantic truth.

### 5.6 Node rendering

- Circular nodes, not boxes.
- Node radius reflects visible degree using a capped nonlinear scale, such as square root or logarithmic scaling.
- Entity type controls color.
- Selected node: bright ring and higher-contrast label.
- Neighbor nodes: normal contrast.
- Non-neighbors during focus: dim to 15–25% opacity rather than disappearing unless neighborhood-only mode is enabled.
- Truncate displayed labels around 30–40 characters while preserving full label in tooltip and inspector.
- Labels should adapt to zoom:
  - Far zoom: selected/high-degree labels only.
  - Medium zoom: connected and meaningful labels.
  - Near zoom: all visible labels.
- Provide a manual label toggle: Important / All / None.
- Literal-like nodes containing very long values should render with lower default prominence.

### 5.7 Edge rendering

- Edge width may reflect evidence count if the backend can calculate it honestly.
- Arrow direction must remain visible at practical zoom levels.
- Predicate labels follow the Important / All / None label setting.
- Hovering an edge highlights both endpoints and shows:
  - Predicate.
  - Validity interval.
  - Active/historical state.
  - Evidence count.
  - Provenance source summary.
- Clicking an edge opens a Relationship Inspector.

### 5.8 Node inspector

Enhance the existing node inspector with:

- Canonical name.
- Type.
- Summary.
- Aliases.
- Active and historical relationship counts.
- Supporting memory/claim count.
- First seen and last seen timestamps when available.
- Relationship list with direction and target.
- Relationship-state filter inside the inspector.
- Actions:
  - Find related memories.
  - Open entity detail.
  - Focus one-hop neighbors.
  - Focus two-hop neighbors.
  - Hide from current view.
  - Add to comparison selection.

### 5.9 Relationship inspector

Create an inspector for a selected edge:

- Subject → predicate → object.
- Active or historical badge.
- `valid_from` and `valid_to`.
- Evidence/provenance references.
- Claim status.
- Agent/source attribution where available.
- Timeline of supersession/invalidation for the same subject + predicate.
- Actions to open the subject, object, and supporting memories.

No edit or deletion behavior is required in this pass unless it routes through the existing trust/steering workflow.

### 5.10 Selection and navigation

- Single click selects.
- Double click focuses and opens one-hop neighborhood.
- Shift-click adds/removes nodes from comparison selection.
- Escape clears search results, then selection, then focused subgraph in that order.
- Back/forward navigation should restore the previous app view and selection state.
- Switching from Entity → Graph must focus the same entity.
- Switching from Graph → Explore must search using the canonical entity identity, not only an arbitrary displayed substring.
- Preserve Graph filters and viewport when navigating away and back during the session.

### 5.11 Saved views

Allow saving named graph configurations locally. A saved view contains:

- Name.
- Filters.
- Physics preset/settings.
- Cluster mode.
- Label mode.
- Focus entity if any.
- Viewport position and scale if supported reliably.

Store saved views in Electron-local application storage or a small JSON preferences file. Do not put user UI preferences into semantic memory facts.

Provide:

- Save current view.
- Load view.
- Rename view.
- Delete view with confirmation.
- A built-in **Default** view that cannot be deleted.

## 6. Backend/API Enhancements

### 6.1 Graph API response

Extend `/api/graph` while preserving backward compatibility.

Suggested response:

```json
{
  "nodes": [
    {
      "id": 42,
      "label": "infra.minipc",
      "type": "INFRA",
      "summary": "Local compute node",
      "aliases": ["mini pc"],
      "active_degree": 5,
      "historical_degree": 2,
      "evidence_count": 7,
      "first_seen": "2026-06-01T10:00:00Z",
      "last_seen": "2026-09-07T22:00:00Z",
      "literal_like": false
    }
  ],
  "edges": [
    {
      "id": 91,
      "from": 42,
      "to": 87,
      "label": "runs",
      "active": true,
      "valid_from": "2026-08-01T00:00:00Z",
      "valid_to": null,
      "evidence_count": 3,
      "provenance": [
        {"kind": "claim", "id": 123, "memory_key": "infra.minipc", "agent": "Antigravity"}
      ]
    }
  ],
  "facets": {
    "types": {"INFRA": 12, "MODEL": 8},
    "predicates": {"runs": 14, "depends_on": 9}
  },
  "totals": {"nodes": 209, "edges": 111}
}
```

If schema limitations prevent an attribute, omit it or return `null`; do not synthesize values.

### 6.2 Provenance query

Add a read-only endpoint for entity/edge evidence, for example:

- `GET /api/entities/{id}`
- `GET /api/entities/{id}/memories`
- `GET /api/relationships/{id}`

The response should link existing claim, provenance, fact, episode, and relationship tables. Keep SQL parameterized. Add indexes if evidence queries are slow.

### 6.3 Entity aliases and duplicates

Add schema support only if needed and migration-safe:

- `gms_entity_aliases(entity_id, alias, normalized_alias, source, created_at)`.
- Unique normalized alias constraint where appropriate.
- Read-only duplicate suggestions based on transparent signals:
  - Exact case-insensitive match.
  - Normalized punctuation/spacing match.
  - Known alias match.
  - Conservative token similarity.

Do not automatically merge entities. Present suggestions in an Entity Review queue and route accepted merges through a deliberate backend operation with tests and recoverability.

### 6.4 Literal-node classification

The existing graph contains long values represented as entity nodes. Add an evidence-based `literal_like` classifier for presentation filtering. Example signals:

- Length above a threshold.
- Sentence-like whitespace/punctuation.
- JSON-like content.
- Date/version/URL/IP/value patterns.

This classification is a display hint, not a destructive migration. Users must be able to include literal nodes.

## 7. Entity Intelligence Pass

### 7.1 Entity detail

The Entity inspector/detail view must show:

- Canonical identity and type.
- Aliases.
- Summary.
- Connectivity metrics.
- Supporting memories and claims.
- Relationship list and temporal history.
- Source/agent distribution.
- Data quality status.
- Possible duplicates.

### 7.2 Quality status definitions

Use explainable states:

- **Well supported:** At least two independent supporting memory/claim references and at least one active relationship.
- **Thin evidence:** One supporting reference.
- **Unlinked:** No active relationships.
- **Missing summary:** Summary is empty.
- **Possible duplicate:** A duplicate rule matched.
- **Historical only:** No active relationships but at least one historical relationship.

If “independent” cannot be determined from provenance, use **Multiple references** instead of **Well supported**.

### 7.3 Entity review queue

Add filterable review categories:

- Possible duplicates.
- Missing summaries.
- Unclassified entities.
- Isolated entities.
- Literal-like entities.
- Historical-only entities.

Actions may include:

- Open evidence.
- Change type through a validated operation.
- Add/edit summary with provenance.
- Add alias.
- Propose merge.
- Ignore suggestion locally.

Destructive merges must be recoverable and tested. If merge semantics are not sufficiently safe, implement only the proposal/review UI during Pass 2.

### 7.4 Extraction lab

Improve the lab from a raw triple output into a review surface:

- Highlight spans in input text associated with detected entities.
- Show known/new/possible-match status.
- Show the rule or pattern that produced each fact or relationship.
- Show schema validation outcome.
- Surface possible duplicates before persistence.
- Permit removing individual candidates from the preview.
- Do not persist anything without an explicit final action.
- If persistence is added, label it **Review and add to memory**, show the exact changes, and route writes through trust/schema gates.

### 7.5 Nightly LLM concept enrichment

Concept quality requires an LLM-assisted lane, but the model must not remain resident during normal desktop use. Implement enrichment as an asynchronous nightly batch owned by the existing Dream Cycle lifecycle.

#### Architecture

Use a two-speed pipeline:

**Daytime — lightweight collection**

- Daily Notes, session harvesting, fact writes, and episode ingestion continue using deterministic/heuristic extraction.
- These paths enqueue concept-enrichment work; they do not invoke an LLM synchronously.
- Mbrain remains responsive and incurs no idle model RAM cost.
- Existing known/new entity resolution remains available as an immediate preview.

**Nighttime — bounded LLM enrichment**

- A single nightly coordinator drains the queue in batches.
- Load one local model once, process bounded batches, validate all structured output, write through a staging/review layer, then explicitly unload the model.
- Prefer integrating this phase into `tools/dream_cycle.py` rather than creating competing nightly jobs that can overlap.
- Use launchd on macOS. Keep systemd compatibility for the Linux/Mini PC deployment.

Do not use a permanently running in-app LLM process. Mbrain should only read queue/enrichment status and optionally request that an item be queued.

#### Queue schema

Add a migration-safe SQLite queue table similar to:

```sql
CREATE TABLE IF NOT EXISTS gms_concept_enrichment_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    text_excerpt TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT,
    leased_at TEXT,
    lease_owner TEXT,
    completed_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_kind, source_ref, source_hash)
);
```

Supported statuses:

- `pending`
- `leased`
- `completed`
- `retry`
- `dead_letter`
- `superseded`

Requirements:

- Enqueue is idempotent through `source_kind + source_ref + source_hash`.
- Do not store entire sensitive documents unnecessarily; store a bounded excerpt or stable source reference.
- Lease work atomically so a second scheduler invocation cannot process the same items concurrently.
- Expire abandoned leases after a configurable interval.
- Retry transient model/parser failures with bounded exponential backoff.
- Move an item to `dead_letter` after the configured attempt limit; surface this in Mbrain.
- A newer source hash may supersede an older pending item for the same source reference.

#### Candidate and audit schema

LLM output must never write directly to canonical entities or relationships. Store candidates first:

```sql
CREATE TABLE IF NOT EXISTS gms_concept_candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id INTEGER NOT NULL,
    candidate_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(queue_id) REFERENCES gms_concept_enrichment_queue(queue_id)
);
```

Candidate kinds:

- `entity`
- `alias`
- `summary`
- `relationship`
- `duplicate_suggestion`
- `type_suggestion`

Store a batch-run record containing start/end timestamps, provider/model, prompt version, input/output counts, invalid-output counts, token estimates when available, and terminal status. This is operational audit data, not a semantic fact.

#### LLM responsibilities

The nightly model may propose:

- Canonical entity boundaries.
- Entity type from an allowed enum.
- Short evidence-grounded summaries.
- Aliases explicitly supported by source text.
- Typed relationships.
- Possible duplicate pairs with an explanation.
- Literal versus entity classification.
- Salience classification for graph presentation.

The model must not:

- Invent facts absent from the supplied excerpts.
- Merge or delete entities.
- Promote candidates directly into canonical memory.
- Produce an opaque numerical confidence score.
- Resolve contradictions on its own.
- access arbitrary files outside the bounded input packet.

Use categorical, explainable assessment fields such as:

- `evidence_strength`: `explicit`, `strong_context`, or `weak_context`.
- `novelty`: `existing`, `possible_match`, or `new`.
- `action`: `keep`, `review`, or `discard`.
- `reason`: concise evidence-grounded explanation.

#### Structured output contract

Use a versioned JSON schema. Example:

```json
{
  "schema_version": "concept-enrichment-v1",
  "source_hash": "sha256:...",
  "entities": [
    {
      "surface_form": "mini pc",
      "canonical_name": "infra.minipc",
      "entity_type": "INFRA",
      "summary": "Local compute node used by AlphaOS.",
      "aliases": ["mini pc"],
      "evidence_quote": "...bounded exact excerpt...",
      "evidence_strength": "explicit",
      "novelty": "possible_match",
      "possible_entity_ids": [42],
      "action": "review",
      "reason": "Surface form matches an existing infrastructure node."
    }
  ],
  "relationships": [
    {
      "subject": "infra.minipc",
      "predicate": "runs",
      "object": "AlphaOS",
      "evidence_quote": "...",
      "evidence_strength": "explicit",
      "valid_from": null,
      "valid_to": null,
      "action": "review"
    }
  ]
}
```

Validation requirements:

- Reject unknown schema versions.
- Reject entity types and predicates outside configured allowlists unless explicitly routed as review-only suggestions.
- Verify evidence quotes occur in the supplied source text after safe whitespace normalization.
- Resolve proposed existing IDs against the database.
- Bound field lengths and collection sizes.
- Reject malformed dates and self-referential relationships.
- Normalize casing and whitespace deterministically after validation, not before evidence verification.

#### Batching strategy

Default limits, configurable through environment variables:

- Maximum queue items per nightly run: `100`.
- Maximum source excerpts per LLM request: `8`.
- Maximum combined input characters per request: `24,000`.
- Maximum output candidates per source: `25`.
- Maximum total runtime: `20 minutes`.
- Maximum attempts per queue item: `3`.
- Lease duration: `30 minutes`.

Group inputs by source/project/domain when that improves coherence, but never mix content requiring different privacy boundaries. Include nearby known entities and aliases as bounded retrieval context instead of sending the entire graph.

Use content hashes and prompt versions so unchanged source material is not repeatedly reprocessed. Re-enrich only when:

- Source content changed.
- Prompt/schema version changed and a migration run is explicitly requested.
- User manually requests reprocessing.
- Prior processing failed or yielded reviewable ambiguity.

#### Provider policy

Default nightly concept provider should be local Ollama for privacy and predictable cost. Reuse the existing Dream Cycle provider abstraction where practical, but concept enrichment needs an explicit provider policy separate from durable-fact extraction.

Recommended environment variables:

```text
CONCEPT_ENRICHMENT_ENABLED=1
CONCEPT_PROVIDER=ollama
CONCEPT_MODEL=<small-instruct-model>
CONCEPT_BATCH_SIZE=8
CONCEPT_MAX_ITEMS=100
CONCEPT_MAX_RUNTIME_SECONDS=1200
CONCEPT_MAX_ATTEMPTS=3
CONCEPT_AUTO_PROMOTE=0
CONCEPT_KEEP_ALIVE=0
```

`CONCEPT_AUTO_PROMOTE` must default to `0`. If automatic promotion is ever introduced, restrict it to deterministic exact-match updates with explicit evidence and trust-gateway validation.

Cloud/frontier providers may be optional fallbacks only when explicitly enabled. Never send private journal or memory content to Antigravity/Gemini/cloud providers merely because local Ollama failed.

#### RAM and model lifecycle

The nightly process must guarantee model release:

- Send Ollama requests with `keep_alive: 0` on the final request or call the appropriate unload request in a `finally` block.
- Do not leave a Python model object, llama.cpp server, or child process resident after the job.
- If a dedicated local inference subprocess is used, start it only after acquiring the nightly lock and terminate it gracefully at completion; force-kill only after a bounded shutdown timeout.
- Record peak resident memory when available, but monitoring failure must not fail enrichment.
- Check available memory before loading the model. If below a configurable safety floor, defer the queue without incrementing attempts.
- Default safety floor: at least 4 GB available memory or a model-specific threshold.
- Process one model at a time. Embedding rebuild must not overlap with the enrichment LLM unless explicitly proven safe.
- Run concept enrichment before embedding/graph rebuild so accepted changes are included in the same nightly index cycle.

Recommended nightly order:

1. Acquire global Dream Cycle lock.
2. Backup SQLite.
3. Recover expired enrichment leases.
4. Drain concept-enrichment queue in bounded batches.
5. Explicitly unload LLM and verify termination best-effort.
6. Validate/store candidates.
7. Apply only deterministic safe updates; leave all merge/type/relationship ambiguity in review.
8. Run existing durable-fact consolidation.
9. Rebuild graph/index once.
10. Run retention/calibration reports.
11. Write summary and release lock.

#### launchd integration

Prefer one launchd job for the complete Dream Cycle rather than a backup job, concept job, and consolidation job all starting at 03:00.

Add `deploy/com.user.gms-dream-cycle.plist` with:

- Label: `com.user.gms-dream-cycle`.
- `StartCalendarInterval`: daily at a configurable documented time, default 03:10.
- `RunAtLoad`: false.
- Absolute Python and script paths.
- Explicit `MEMORY_ROOT`, `PATH`, provider/model, batch, timeout, and keep-alive environment variables.
- Separate stdout and stderr logs under `~/memories/logs/`.
- No `KeepAlive` key that would relaunch a successful job.
- A process type/QoS appropriate for background maintenance.

Avoid scheduler collisions:

- Move standalone backup earlier, e.g. 02:50, or make backup step 2 of the unified Dream Cycle.
- Use an advisory lock file or SQLite lease so manual and scheduled runs cannot overlap.
- A second invocation should exit cleanly with an “already running” status.
- Document `launchctl bootstrap`, `bootout`, `kickstart`, and status commands without automatically installing the agent during tests.
- Provide an equivalent systemd timer/service for the Linux host if the existing deployment contract requires parity.

#### Mbrain status UI

Add a small Concept Enrichment status area, not a permanent LLM process control center.

Display:

- Pending queue count.
- Items processed in last run.
- Review candidates count.
- Dead-letter count.
- Last run time, duration, provider/model, and status.
- Next scheduled run when known.
- Whether a model is currently active.

Actions:

- Queue selected source for tonight.
- Requeue failed item.
- Open candidate review.
- Run a dry-run preview manually.

A manual full run may be exposed only with a clear warning that it temporarily loads the local model. It must not run implicitly when the Entities screen opens.

#### Failure handling

- Ollama unavailable: leave queue pending and record `provider_unavailable`; do not fall through to cloud by default.
- Out of memory or below safety floor: defer without poisoning attempt count.
- Timeout: mark batch retryable; preserve unprocessed items.
- Malformed JSON: store bounded raw diagnostic output in logs, not canonical memory; increment attempts.
- Partial batch success: commit validated per-source results and retry only failed sources.
- Database locked: bounded retry, then defer.
- Prompt/schema mismatch: stop the run and require code/config correction rather than accepting best-effort output.
- Model unload failure: log prominently and attempt one bounded cleanup; next run checks for stale inference state.

#### Privacy and safety

- Local provider is the default.
- Log hashes, IDs, counts, and error summaries—not full personal journal text or complete prompts.
- Redact obvious credentials/tokens before queueing or prompting.
- Respect source-level sensitivity metadata if present.
- Exclude credentials/reference namespaces by default.
- Candidate evidence may contain only the minimum excerpt necessary for review.
- All canonical writes retain source hash, prompt version, provider/model, and candidate ID provenance.

#### Tests for nightly enrichment

Add deterministic tests with a fake provider for:

- Idempotent enqueue.
- Atomic lease acquisition.
- Expired lease recovery.
- Batch size/character/runtime limits.
- Structured output validation.
- Evidence-quote verification.
- Existing/new/possible-match resolution.
- No direct canonical writes from unreviewed candidates.
- Retry and dead-letter transitions.
- Partial-batch success.
- Provider unavailable behavior.
- Low-memory deferral without attempt increment.
- Final model-unload call on success, validation failure, exception, and timeout.
- Global lock preventing overlap.
- One graph/index rebuild per completed nightly run.
- Dry-run produces no canonical mutations.
- Sensitive namespace exclusion/redaction.
- launchd plist syntax validation with `plutil -lint` on macOS.

#### Acceptance criteria for LLM enrichment

1. Normal Mbrain browsing never loads an LLM.
2. Daytime ingestion adds idempotent queue records in milliseconds.
3. Nightly job loads at most one concept model at a time.
4. Model is explicitly unloaded after every terminal path.
5. No unreviewed LLM suggestion can merge/delete canonical entities.
6. Every candidate is traceable to source hash, evidence, model/provider, and prompt version.
7. Re-running unchanged inputs creates no duplicate work or candidates.
8. Offline/local-provider failure does not transmit memory content to cloud.
9. Mbrain accurately reports queue, run, failure, and review status.
10. The full Dream Cycle uses one lock and avoids duplicate graph/index rebuilds.

### 7.6 Multi-agent context operating system

Mbrain must evolve into the human control plane for context moving across Codex, Antigravity, Gemini, Claude-compatible harnesses, terminal agents, scheduled workers, and future tools. The product should answer five questions immediately:

1. What is every agent currently doing?
2. What does each agent know, and from which sources?
3. Where are agents duplicating, conflicting, or blocking one another?
4. What is the smallest correct context packet for the next task?
5. What durable knowledge should survive after a task ends?

The system must not attempt to mirror every token of every conversation. It should manage structured context boundaries, evidence, task state, and deliberate handoffs.

#### Information hierarchy

Represent context in six scopes:

1. **Global operating context**
   - User preferences.
   - Safety and execution policies.
   - Environment and tool contracts.
   - Cross-project lessons.
2. **Project context**
   - Project brief.
   - Architecture and system patterns.
   - Technical environment.
   - Current focus.
   - Progress and known gaps.
3. **Workstream context**
   - A bounded initiative within a project, such as Mbrain Graph Pass 2.
   - Goals, decisions, dependencies, deliverables, and open questions.
4. **Task context**
   - Exact objective, scope, owner, state, revision, and acceptance criteria.
5. **Session context**
   - Current conversation/run, active files, recent commands, assumptions, and transient reasoning artifacts.
6. **Evidence context**
   - Claims, files, commits, test results, URLs, notes, entities, and relationships supporting conclusions.

Every context item must declare its scope. Context promotion is directional: session → task → workstream → project → global. Higher-scope promotion requires stronger durability and validation.

#### Agent and harness registry

Add an Agent Registry that distinguishes the reasoning identity from the execution surface.

Agent/facet examples:

- Codex.
- Antigravity.
- Gemini CLI.
- Dream Cycle.
- Human/Mihir.
- Specialized trading or research agents.

Harness examples:

- Codex Desktop.
- Codex CLI.
- Antigravity IDE.
- `agy` headless CLI.
- Gemini CLI.
- MCP server.
- launchd scheduled job.
- Remote SSH worker.

Suggested data model:

```sql
CREATE TABLE IF NOT EXISTS gms_agent_instances (
    instance_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    harness TEXT NOT NULL,
    host_id TEXT,
    model TEXT,
    working_directory TEXT,
    project_id TEXT,
    session_id TEXT,
    status TEXT NOT NULL,
    capabilities_json TEXT,
    privacy_boundary TEXT,
    started_at TEXT,
    last_heartbeat_at TEXT,
    ended_at TEXT,
    metadata_json TEXT
);
```

Required distinctions:

- `agent_id`: stable logical facet.
- `instance_id`: one running invocation.
- `harness`: execution environment.
- `session_id`: conversation/run identity from that harness.
- `host_id`: machine or remote execution host.
- `model`: optional and mutable across turns.

Statuses:

- `starting`
- `active`
- `waiting`
- `needs_input`
- `blocked`
- `completed`
- `failed`
- `stale`

Do not infer “active” forever. Mark instances stale after a configurable heartbeat timeout while retaining their last reported state.

#### Context dashboard / Mission Control

Add a top-level **Mission Control** view as the default operational landing page once mature.

It should show:

- Active projects and workstreams.
- Running/recent agent instances grouped by project.
- Current objective for each agent.
- Task status and revision.
- Last meaningful checkpoint.
- Files or systems currently in scope.
- Dependencies and blockers.
- Required user decisions.
- Recent completions.
- Context freshness warnings.
- Conflicts or overlapping work.
- Nightly/scheduled worker status.

Avoid a noisy activity feed. Rank cards by actionability:

1. Needs user decision.
2. Failed/blocked/stale work.
3. Conflicting changes or claims.
4. Active work nearing completion.
5. Recent completed work.
6. Informational background activity.

Each agent card should expose:

- Open task.
- Read latest checkpoint.
- Build context packet.
- Prepare handoff.
- Compare with another agent.
- Mark stale/closed if the harness failed to report completion.
- Open project context.

Mbrain should be an observation and orchestration surface; it must not terminate or redirect agents unless an adapter explicitly supports that operation and the user intentionally invokes it.

#### Task and workstream board

Build a project-scoped task board backed by the existing GMS task revision/lease/checkpoint/handoff primitives.

Columns:

- Inbox.
- Ready.
- In progress.
- Waiting.
- Needs review.
- Blocked.
- Completed.

Task record requirements:

- Stable task ID.
- Project and optional workstream.
- Objective.
- Scope boundaries.
- Acceptance criteria.
- Priority.
- Owner agent and active instance.
- Revision number.
- Lease status and expiration.
- Dependencies.
- Context packet version used to start.
- Latest checkpoint.
- Handoff package.
- Deliverables and file/commit references.
- Verification results.
- Blocker and required decision.
- Created/updated/completed timestamps.

Important behavior:

- Use optimistic revision checks so stale agents cannot overwrite newer state.
- Make lease ownership visible.
- Detect abandoned leases and permit deliberate recovery.
- Show a task’s full state transition timeline.
- Do not equate “agent stopped producing output” with “completed.”
- Allow one parent task to contain multiple bounded agent assignments without erasing ownership history.

#### Context packet builder

The most important Mbrain workflow is **Build context for agent**.

A context packet is a versioned, bounded, portable artifact containing only what a target agent needs.

Packet fields:

```json
{
  "packet_version": "gms-context-v1",
  "packet_id": "ctx_...",
  "created_at": "...",
  "project": "global-memory",
  "workstream": "mbrain-pass-2",
  "task_id": "...",
  "target": {
    "agent": "Antigravity",
    "harness": "Antigravity IDE",
    "host": "local"
  },
  "objective": "...",
  "scope": {
    "included": ["..."],
    "excluded": ["..."]
  },
  "acceptance_criteria": ["..."],
  "current_state": "...",
  "decisions": ["..."],
  "constraints": ["..."],
  "relevant_memories": ["..."],
  "entities": ["..."],
  "files": ["..."],
  "git_state": {"branch": "...", "head": "...", "dirty_paths": ["..."]},
  "dependencies": ["..."],
  "open_questions": ["..."],
  "verification": ["..."],
  "response_contract": "...",
  "context_budget": {"max_tokens": 12000, "estimated_tokens": 8300},
  "source_refs": ["..."],
  "content_hash": "sha256:..."
}
```

Builder behavior:

- Start from task/project context, not global memory indiscriminately.
- Retrieve context using stable links, recent checkpoints, semantic search, graph neighbors, and file references.
- Rank content by direct relevance, authority, freshness, and durability.
- Deduplicate repeated facts and summaries.
- Detect contradictory active claims and include the conflict explicitly.
- Show estimated token cost before export.
- Provide Small / Standard / Deep packet sizes.
- Let the user include/exclude individual sections.
- Redact secrets and excluded namespaces.
- Preview the exact payload before sending or copying.
- Generate plain Markdown, structured JSON, and harness-specific prompt formats.
- Store the packet hash and source references so later results can be traced to what the agent actually received.
- Never silently add private cross-project context.

Recommended packet profiles:

- **Small:** Objective, constraints, current state, acceptance criteria, latest checkpoint, essential files.
- **Standard:** Small plus decisions, relevant memories, dependencies, verification state, graph context.
- **Deep:** Standard plus selected historical evidence, alternatives considered, and broader architecture context.

#### Context routing rules

Introduce explicit routing policies determining what context reaches which agents.

Examples:

- Coding agent receives project architecture, target files, tests, working-tree state, and relevant decisions.
- Research agent receives research question, existing corpus, date requirements, source-quality policy, and citation contract.
- Trading agent receives only fresh broker/regime/risk data and trading policies, never stale position context.
- Nightly consolidation receives new/changed sources, existing canonical matches, and privacy-safe excerpts.
- External/cloud harness receives only context approved for its privacy boundary.

Each routing rule should declare:

- Matching project/task/harness/agent.
- Included scopes/namespaces.
- Excluded scopes/namespaces.
- Freshness requirements.
- Required evidence types.
- Maximum context budget.
- Redaction policy.
- Whether user preview/approval is required.

Expose a **Why included?** explanation for every item in a generated packet.

#### Context freshness and expiry

Not all context ages equally. Add freshness policies:

- Static architecture decision: durable until superseded.
- Repository branch/HEAD: stale on checkout change.
- Working-tree status: stale within minutes.
- Test result: stale when relevant files change.
- Broker position/price: stale within seconds/minutes according to policy.
- Agent task checkpoint: stale when task revision advances.
- User preference: durable until explicitly changed.

Every context packet should flag:

- Fresh.
- Possibly stale.
- Stale.
- Superseded.
- Conflicted.
- Missing required refresh.

Use dependency fingerprints where possible. For example, test evidence can record hashes of relevant files and become stale when those hashes change.

#### Handoff composer

Add a guided handoff workflow. A handoff is not merely a chat summary.

Required fields:

- Task ID and revision.
- Sender agent/instance/harness.
- Intended receiver or `unassigned`.
- Objective and why the handoff is occurring.
- Completed work.
- Exact current state.
- Changed files/commits/artifacts.
- Commands/tests run and results.
- Assumptions made.
- Decisions and rationale.
- Unresolved questions.
- Known failures and attempted fixes.
- Next recommended action.
- Risks and do-not-touch boundaries.
- Required credentials/permissions without embedding secrets.
- Context packet references.

Handoff quality checks:

- Reject “continue from here” without current state and next action.
- Warn when referenced files no longer match recorded hashes.
- Warn when tests are missing or stale.
- Warn when the sender still holds the task lease.
- Detect missing blockers or acceptance criteria.
- Allow receiver acknowledgement and amendment.

Provide **Resume in another harness** output formats:

- Copyable prompt.
- Markdown handoff file.
- Structured JSON.
- CLI command that prints the packet.
- MCP resource/reference.

Do not automatically transmit to a third-party harness without the user selecting the destination and reviewing privacy-sensitive context.

#### Checkpoint timeline

Create a unified timeline combining:

- User instructions.
- Task state changes.
- Agent checkpoints.
- Handoffs.
- Claims/facts promoted.
- Files/commits referenced.
- Tests and verification.
- Reviews/approvals.
- Scheduled/nightly consolidations.

Timeline requirements:

- Filter by project, workstream, task, agent, harness, event type, and date.
- Collapse noisy heartbeats and repeated unchanged status.
- Highlight meaningful deltas.
- Support “state as of this checkpoint.”
- Link directly to entities, memories, tasks, and evidence.
- Clearly distinguish agent-reported status from independently verified evidence.

#### Decision ledger

Add a first-class Decision Ledger rather than burying decisions in conversation summaries.

Decision fields:

- Decision ID.
- Project/workstream.
- Question.
- Decision.
- Status: proposed, accepted, superseded, rejected.
- Decision owner.
- Participating agents.
- Rationale.
- Alternatives considered.
- Evidence references.
- Constraints affected.
- Effective date.
- Superseding decision.

Useful views:

- Active decisions for current project.
- Decisions made since an agent’s context packet was built.
- Conflicting implementation against an accepted decision.
- Decisions awaiting user approval.

Agents should be able to cite decision IDs in checkpoints and code-review notes.

#### Open questions and user decision inbox

Aggregate questions requiring Mihir into one inbox rather than leaving them scattered across agent chats.

Each item includes:

- Concrete question.
- Why it matters.
- Which task/agents are blocked.
- Options and tradeoffs.
- Recommended option where justified.
- Deadline/urgency.
- Default safe behavior if unanswered.
- Evidence/context links.

Merge duplicate questions from multiple agents. When the user answers, record one decision and notify/refresh affected task contexts.

Do not create fake urgency. Scheduled jobs should stay quiet on unchanged, non-actionable state.

#### Conflict and overlap detection

Detect several types of cross-agent collision:

- Two active tasks modifying the same file paths.
- Two agents holding logically overlapping task scopes.
- Divergent decisions for the same question.
- Contradictory active facts/claims.
- One agent using a stale context packet after a newer revision.
- Duplicate research or implementation effort.
- One task depending on an uncommitted change owned by another task.

Conflict cards must show evidence and severity:

- **Informational:** Adjacent work with no shared writes.
- **Potential overlap:** Shared entities/files but compatible objectives.
- **Coordination required:** Same files, APIs, decisions, or state.
- **Blocking conflict:** Incompatible active changes or claims.

Never automatically cancel or merge tasks. Recommend coordination actions:

- Share checkpoint.
- Split file ownership.
- Sequence tasks.
- Build a shared context packet.
- Request human decision.
- Rebase/revalidate after dependency completion.

#### Context diff and comparison

Provide comparison tools:

- What changed since this agent started?
- Compare two agents’ context packets.
- Compare project context at two timestamps.
- Compare claimed completion with repository/test evidence.
- Compare a handoff packet with current working-tree state.

Diff categories:

- Added/removed/changed decisions.
- New/superseded claims.
- Task revision changes.
- File/commit changes.
- New blockers.
- New user instructions.
- Verification invalidated by later edits.

Use semantic summaries only as navigation aids; retain exact structured diffs underneath.

#### Harness adapters

Create a narrow adapter contract rather than hard-coding every harness into the core.

Adapter capabilities may include:

- Discover current session identity.
- Report heartbeat/status.
- Publish checkpoint.
- Read context packet.
- Publish handoff.
- Report files/commands/tests touched.
- Receive a user-approved follow-up prompt.
- Report completion/failure.

Suggested adapter interface:

```python
class HarnessAdapter(Protocol):
    name: str
    def capabilities(self) -> set[str]: ...
    def discover_sessions(self) -> list[SessionRef]: ...
    def get_status(self, session: SessionRef) -> AgentStatus: ...
    def send_context(self, session: SessionRef, packet: ContextPacket) -> DeliveryReceipt: ...
    def request_checkpoint(self, session: SessionRef) -> Checkpoint | None: ...
```

Initial adapters:

- GMS/MCP-native generic adapter.
- Codex task/thread adapter when the app surface is available.
- File/CLI adapter for agents that can read a packet path but have no control API.
- Scheduled-worker adapter for launchd/systemd jobs.

Antigravity IDE integration should begin as file/CLI handoff unless a reliable supported session API exists. Do not automate GUI scraping as a foundational protocol.

Adapters must declare supported operations. Mbrain must not display a Send/Interrupt/Resume action when the adapter cannot guarantee it.

#### Agent inbox and subscriptions

Each agent can have a durable inbox of context events:

- User decision resolved.
- Dependency completed.
- Relevant decision superseded.
- Context packet invalidated.
- File conflict detected.
- Review requested.
- Handoff assigned.

Inbox items should be acknowledged idempotently. Harnesses can poll through MCP/CLI at session start and checkpoints.

Subscriptions must be scoped:

- Project.
- Workstream.
- Task dependency.
- Entity.
- Decision.
- File path pattern.

Avoid broadcasting every memory update to every agent.

#### Context policies and privacy boundaries

Add policy labels:

- `local_only`
- `private_personal`
- `project_internal`
- `shareable_external`
- `secret_reference_only`

Rules:

- Credentials are referenced by secret name/location, never copied into packets.
- Personal daily notes default to local/private.
- Cross-project inclusion requires an explicit rule or user selection.
- Cloud harness delivery previews exactly what leaves the machine.
- Store delivery receipts with packet hash, target, timestamp, and redaction policy.
- Revocation cannot erase a third party’s received context; communicate this clearly.

#### Working-tree awareness

For coding projects, context management must understand repository state:

- Project path.
- Git repository identity and remote.
- Branch and HEAD.
- Dirty/staged/untracked files.
- Worktree identity.
- Task-to-file ownership claims.
- Commit and PR references.
- Test commands/results.

Before building a coding-agent packet:

- Snapshot git status read-only.
- Mark files with unrelated user edits as protected context.
- Include applicable `AGENTS.md`/skill instructions by reference and required excerpts.
- Record base revision.
- State whether the task runs in the saved checkout or an isolated worktree.

After completion:

- Compare actual changed paths to declared scope.
- Re-run or invalidate verification as appropriate.
- Build a review/handoff packet.

#### Personal workflow integrations

Mbrain can unify context beyond coding while respecting source boundaries:

- Apple Notes/Obsidian: project and learning context sources.
- Apple Reminders: actionable commitments, not semantic truth.
- Calendar: time constraints and upcoming review points.
- Research library: papers, notes, experiments, and claims.
- Trading systems: highly freshness-sensitive operational context.
- Learning systems: curriculum progress and next milestone.

Each integration needs a declared role:

- Source of evidence.
- Source of tasks.
- Destination for summaries.
- Read-only reference.

Do not flatten all external content into the same memory tier.

#### Context health metrics

Add a Context Health view using explainable operational metrics:

- Tasks without recent checkpoints.
- Active tasks using stale context packets.
- Decisions missing evidence.
- Handoffs missing tests/current state.
- Entities lacking provenance.
- Duplicate open questions.
- Conflicting active claims.
- Unowned blocked tasks.
- Failed scheduled jobs.
- Queue backlog age.
- Context packet size and compression ratio.
- Retrieval usefulness feedback when available.

Do not turn these into a single opaque “AI health score.” Show component status and remediation actions.

#### Daily and weekly briefing

Generate a quiet, action-oriented local briefing.

Daily briefing:

- What completed since yesterday.
- What is active now.
- What needs a user decision.
- What is blocked/stale.
- Which context packets became invalid.
- Scheduled worker outcomes.
- Suggested next three actions.

Weekly review:

- Project progress against milestones.
- Decisions made/superseded.
- Repeated blockers or coordination failures.
- Memory quality issues.
- Agent/harness effectiveness by task type, based on evidence such as completion and rework—not popularity.
- Candidate lessons to promote globally.

Briefings are generated during a batch window and cached. Opening Mbrain must not load an LLM merely to display them.

#### Multi-agent evaluation and learning

Track outcomes so context routing improves over time:

- Was the task completed?
- Did acceptance tests pass?
- How much rework was needed?
- Which supplied context items were cited/used?
- Which missing context caused failure?
- Which included context was irrelevant?
- Did the agent violate scope or overwrite unrelated work?
- Was the handoff sufficient for another agent to resume?

Use this to recommend packet templates and routing changes. Do not silently change global policies based on a small number of runs. Proposed lessons must be reviewable.

#### Command palette

Add a keyboard-first command palette for frequent context operations:

- Switch project/workstream.
- Find task, decision, entity, memory, or agent.
- Build context packet.
- Create checkpoint.
- Prepare handoff.
- Open decision inbox.
- Compare contexts.
- Show recent completions.
- Queue source for nightly enrichment.
- Copy harness-specific resume prompt.

Commands must be filtered by current adapter capabilities and user permissions.

#### Mobile/terminal companion

Preserve and enhance the existing `brain`/`memoryctl` CLI as the lightweight companion.

Suggested commands:

```text
brain mission-control
brain agents
brain tasks --project global-memory
brain decisions --needs-input
brain context-build <task-id> --profile standard --target antigravity
brain context-show <packet-id>
brain handoff-create <task-id>
brain inbox --agent Codex
brain context-diff <old-packet> <new-packet>
brain health --project global-memory
brain briefing daily
```

CLI and desktop must read the same canonical database and schemas. Avoid desktop-only state that makes terminal recovery impossible, except ephemeral visual layout preferences.

#### Multi-agent API/MCP surface

Keep the surface small and composable:

- `context.build`
- `context.get`
- `context.diff`
- `context.deliver`
- `agent.register`
- `agent.heartbeat`
- `agent.inbox`
- `task.create`
- `task.claim`
- `task.checkpoint`
- `task.handoff`
- `task.complete`
- `decision.propose`
- `decision.resolve`
- `conflict.list`
- `briefing.get`

All mutations require agent identity, project scope, idempotency key, and expected revision where applicable. Read responses should include timestamps and freshness status.

#### Multi-agent testing requirements

Add deterministic tests for:

- Stable agent versus instance identities.
- Heartbeat and stale-instance transitions.
- Task lease/revision conflicts.
- Context packet deterministic hashing.
- Packet size profiles and token-budget enforcement.
- Deduplication and relevance ordering.
- Cross-project exclusion.
- Secret-reference redaction.
- Cloud-boundary preview requirements.
- Freshness invalidation after file/task/decision changes.
- Handoff completeness validation.
- Duplicate user-question aggregation.
- File overlap detection.
- Contradictory decision detection.
- Adapter capability gating.
- Idempotent inbox acknowledgement.
- Exact context delivery receipts.
- Timeline as-of reconstruction.
- Working-tree scope comparison.
- No agent/harness action executed merely by viewing Mission Control.

#### Multi-agent acceptance criteria

1. Mbrain can show all active/recent agent instances with task, harness, project, freshness, and latest checkpoint.
2. A user can build a bounded Small/Standard/Deep context packet for a task and inspect exactly why each item was included.
3. The same packet can be exported to Markdown/JSON and rendered for at least Codex, Antigravity file/CLI handoff, and generic MCP use.
4. Every delivered packet has a hash, target, privacy boundary, and delivery receipt.
5. Tasks use revision-safe claims, checkpoints, and handoffs; stale updates are rejected visibly.
6. User decisions propagate to dependent task inboxes without broadcasting unrelated context.
7. Context freshness changes when its source revision/file/decision changes.
8. Overlapping agent file scopes and contradictory decisions produce evidence-backed conflict cards.
9. A receiver can resume from a handoff without reading the sender’s full conversation.
10. Mission Control performs no external mutation simply by loading or refreshing.
11. CLI and desktop expose the same canonical tasks, decisions, packets, and agent status.
12. Daily briefing is cached from batch processing and does not load an LLM on app open.
13. Context routing obeys project, privacy, freshness, and token-budget policies.
14. Context-health reporting uses explainable component metrics rather than a fabricated aggregate score.
15. Tests cover concurrency, revisions, privacy, freshness, adapter capability boundaries, and recovery after stale agents.

## 8. Explore and Provenance Integration

Enhance the existing memory inspector:

- Show claim status and claim ID when available.
- Show created/updated timestamps.
- Show agent/source provenance.
- Show linked entities as clickable chips.
- Add **Open in Graph** when linked entities exist.
- Add **Show evidence chain**.
- For episodic files, show full source path and entry date.
- Related-memory search should prefer linked evidence and semantic retrieval, then fall back to text matching.

Keep Explore fast. Load heavy provenance lazily when a memory is selected.

## 9. App-Level Navigation State

Introduce a small central state object or store containing:

- Active view.
- Back/forward history.
- Global search query.
- Selected memory ID/key.
- Selected entity ID.
- Selected relationship ID.
- Graph filter state.
- Graph focus and viewport.

Requirements:

- Avoid a large framework migration unless clearly justified.
- Vanilla JavaScript modules are acceptable.
- State changes should have explicit actions/functions.
- View render calls must not silently erase unrelated state.
- Cross-navigation must use stable IDs wherever possible.

## 10. Visual and Interaction Design

- Continue the restrained dark desktop aesthetic from Pass 1.
- Reduce inline styles in modified views; move reusable rules into `styles.css`.
- Maintain accessible contrast.
- Every icon-only button requires a title and accessible label.
- Add clear hover, focus, selected, disabled, loading, empty, and error states.
- Support keyboard focus rings; do not remove outlines without replacement.
- Minimum click target: approximately 30×30 px for compact desktop controls.
- Inspector transitions should remain under 250 ms.
- Do not use emoji as the primary visual language for core navigation/actions.
- Avoid marketing language such as “AI-powered,” “magic,” or “autonomous” unless behavior warrants it.

## 11. Performance Requirements

Targets on the current Apple Silicon development machine:

- Initial graph data request: under 500 ms for current production data.
- Filter update: under 100 ms for 1,000 nodes / 5,000 edges.
- Search results visible: under 100 ms after debounce.
- Inspector open: under 50 ms after selection.
- No continuous high CPU use after graph stabilization.
- No memory growth from repeatedly switching views or rebuilding networks.

Implementation notes:

- Destroy old `vis.Network` instances before creating replacements.
- Remove event listeners when views are torn down or ensure render replacement cannot accumulate global listeners.
- Prefer `DataSet.update/remove` for filter changes rather than constructing a new network every time.
- Cache immutable facet calculations until graph data changes.
- Avoid rendering thousands of DOM rows at once in inspectors.

## 12. Accessibility

- All graph controls reachable by keyboard.
- Search result list supports Arrow Up/Down, Enter, Escape.
- Visible focus state.
- Filter checkboxes have explicit labels.
- Inspector announces selected entity/relationship where feasible.
- Color is not the sole indicator of historical state, selection, or quality.
- Provide textual counts/status alongside color encodings.
- Respect reduced-motion preference for inspector and viewport animations where practical.

## 13. Testing Requirements

### 13.1 Backend tests

Add tests for:

- Type normalization.
- Active/historical degree calculations.
- Predicate facet counts.
- Entity evidence retrieval.
- Relationship evidence retrieval.
- Alias uniqueness and lookup if aliases are implemented.
- Duplicate suggestion rules.
- Literal-like classification.
- Empty database behavior.
- Invalid IDs and malformed dates.
- SQL parameterization-sensitive inputs.
- Backward compatibility of existing graph response fields.

### 13.2 Pure graph-filter tests

Create deterministic fixtures and test:

- Minimum degree `0`, `1+`, `3+`, `10+`.
- Degree recomputation after predicate filtering.
- Multi-type selection.
- Isolate hiding.
- Largest component selection.
- One-hop and two-hop neighborhoods.
- Temporal filtering.
- Explicitly revealed low-degree search target.
- No dangling edges after filtering.
- Stable hidden-by-reason counts.

### 13.3 Frontend interaction tests

Add a lightweight test harness appropriate to the existing stack. Cover:

- Filters update visible datasets and counts.
- Search selects/focuses an entity.
- Entity → Graph navigation preserves entity ID.
- Graph → Explore navigation uses canonical identity.
- Inspector close does not reset filters.
- Physics setting persistence.
- Label-mode behavior.
- Network instance teardown.
- Empty/error/loading views.
- Extraction candidates can be reviewed without persistence.

### 13.4 Manual QA matrix

Verify against:

- Empty database.
- Current production database.
- Dense synthetic component.
- Many isolates.
- All-lowercase entity types.
- Mixed active/historical edges.
- Long literal node labels.
- 5,000-node / 20,000-edge synthetic dataset.
- Offline mode with all runtime assets loading locally.

## 14. Acceptance Criteria

Pass 2 is complete only when all are true:

1. User can select **3+ connections** and the graph deterministically shows only qualifying nodes/edges.
2. Filters can be combined without dangling edges or incorrect counts.
3. Physics has presets, manual tuning, reset, persistence, and automatic stabilization stop.
4. Graph remains fully functional with internet disconnected.
5. Search can reveal and focus a filtered-out low-degree entity.
6. Clicking an entity or relationship exposes its evidence/provenance or explicitly says none exists.
7. Entity → Graph → Explore navigation retains the intended identity.
8. Long literal nodes no longer dominate the default graph.
9. Current production data produces a legible default canvas.
10. Existing 106 tests continue to pass and new tests cover filter/provenance behavior.
11. JavaScript syntax checks and `git diff --check` pass.
12. No unrelated user changes, icon edits, or memory-system behavior are overwritten.
13. README documents new filters, physics, saved views, and offline behavior.
14. A final implementation note lists changed files, migrations, test results, known limitations, and recommended Pass 3 work.
15. Nightly concept enrichment is queued, bounded, evidence-traceable, local by default, scheduler-safe, and demonstrably unloads its model on every terminal path.

## 15. Recommended Implementation Sequence

### Stage A — Data contracts and pure filtering

1. Snapshot current tests and working tree.
2. Define normalized graph response and backward compatibility.
3. Implement graph facet/degree/provenance queries.
4. Extract pure client-side graph filtering into a testable module.
5. Add backend and filter-unit tests.

### Stage B — Graph control surface

1. Add collapsible filters panel.
2. Implement degree/type/predicate/state/isolate filters.
3. Add visible/total/hidden counts.
4. Implement search reveal and focus behavior.
5. Verify no dangling edges.

### Stage C — Physics and rendering

1. Add presets and manual controls.
2. Add persistence and reset.
3. Add zoom-aware label modes.
4. Tune node prominence and literal handling against production data.
5. Add cluster modes.

### Stage D — Evidence and navigation

1. Add entity and relationship evidence endpoints.
2. Build node and relationship inspectors.
3. Add entity quality/review categories.
4. Add central navigation/selection state.
5. Verify Graph ↔ Entities ↔ Explore journeys.

### Stage E — Nightly concept intelligence

1. Add the idempotent enrichment queue, candidate staging, and run-audit schemas.
2. Add a fake-provider-tested batch coordinator integrated with Dream Cycle locking.
3. Add the local Ollama provider with structured output validation and guaranteed unload.
4. Add launchd/systemd scheduling artifacts and collision-safe lifecycle documentation.
5. Add queue/run/review status to Mbrain without loading a model during browsing.

### Stage F — Hardening

1. Add frontend interaction tests.
2. Run performance fixtures.
3. Run offline verification.
4. Perform visual QA at common window sizes.
5. Update README and Brain/project handoff.

## 16. Product correction: retire global agent trust

A single agent-level trust or reputation score is not a valid organizing concept for Mbrain. It collapses unrelated dimensions—task domain, claim provenance, evidence quality, recency, review history, and failure severity—into a number that looks more certain than the underlying data. In particular, a 100% ratio from one accepted claim must never be presented as comparable to a long, well-audited history.

The product UI must therefore not display a global trust percentage, Bayesian trust tier, fleet trust index, or leaderboard. Existing `alpha`, `beta`, and reputation fields may remain temporarily as backward-compatible storage or routing inputs, but they are implementation details and must not drive user-facing identity judgments.

Replace them with inspectable dimensions:

- agent identity and execution surface;
- most recent contribution time;
- active claims attributed to that agent;
- accepted, disputed, superseded, and retracted contribution counts;
- namespaces and projects touched;
- source and evidence links for each claim;
- unresolved items requiring human review;
- task-scoped outcomes when a meaningful evaluator exists.

All summaries must remain descriptive. Do not combine these dimensions into a renamed proxy score such as reliability, confidence, quality, reputation, or health. Decisions belong at the claim or task level, with provenance attached.

## 17. Non-Goals

- Replacing SQLite.
- Introducing a cloud graph database.
- Automatically merging entities without review.
- Generating unsupported confidence numbers.
- Replacing Electron or vanilla JavaScript solely for fashion.
- Migrating or deleting the legacy reputation tables in this UI pass; the user-facing trust model is retired immediately, while storage cleanup can be a separate compatibility migration.
- Redesigning Dream Cycle or broker/trading workflows.
- Modifying existing memory data destructively to make the graph look cleaner.
- Committing or discarding unrelated icon changes without explicit instruction.

## 18. AGY Execution Prompt

Use this specification as the authoritative implementation contract:

```text
Implement Mbrain UX Pass 2 from docs/MBRAIN_UX_PASS_2_SPEC.md.

Work directly in the existing global-memory repository and preserve all user changes, especially uncommitted desktop icon assets and the completed UX Pass 1 implementation. Begin by reading the full specification, inspecting the current working tree, and running the existing tests.

Implement in the staged order from the specification. Prioritize P0 requirements. Do not perform a cosmetic-only rewrite. Keep the system local-first, retain the installed local vis-network dependency, preserve backward compatibility, and never fabricate confidence or provenance. Use stable entity/relationship IDs for cross-view navigation.

After each stage:
- run relevant tests and JavaScript syntax checks;
- record a concise checkpoint in Brain/GMS;
- inspect the real production-data behavior;
- fix regressions before continuing.

Do not commit unless explicitly asked. At completion, provide changed files, migrations, tests and results, performance observations, visual QA performed, known limitations, and Pass 3 recommendations.
```
