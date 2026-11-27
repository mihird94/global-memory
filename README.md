# Brain

**Brain (GM v3.2)** is a local-first cross-harness memory store, inter-agent message board, and privacy-hardened bundle router shared across Antigravity, Claude Code, Codex, Gemini CLI, Pi, and (via a strictly scoped export boundary) OpenCode.

Plain Markdown in `~/memories` is the single source of truth. Disposable local SQLite indexes power passage-level hybrid search (FTS5 + Ollama embeddings + ONNX cross-encoder reranking), cross-session coordination, opt-in checkpoint receipts, and human-reviewed external exports.

---

## Architecture

### Trust Boundaries & System Overview

```mermaid
flowchart TB
    subgraph Trusted["Trusted Local Harnesses"]
        T1["Antigravity (UI / IDE / CLI)"]
        T2["Claude Code CLI"]
        T3["Codex (Desktop / CLI)"]
        T4["Gemini CLI & Pi CLI"]
        T5["brain CLI & Electron App (brain app)"]
    end

    subgraph Store["Canonical Brain Home (~/memories)"]
        MD["Markdown Truth (facts, decisions, lessons, projects, journals)"]
        RO["Read-Only Extra Roots (e.g. Obsidian wiki)"]
        IDX["Search Index (.gm/index.sqlite · FTS5 + Ollama Cosine)"]
        BRD["Agent Board (.gm/board.sqlite · WAL Threads & Cursors)"]
        CHK["Checkpoint Ledger (.gm/checkpoints.sqlite3 · WAL Receipts)"]
        SCR["Local Screen Cache (.gm/screen_cache.json · SHA-256)"]
    end

    subgraph Boundary["Privacy-Hardened External Boundary (~/brain-exports/<bundle>/)"]
        EXP["ONNX Privacy Screener + Suggestions + Manual Approval"]
        MAN["SHA-256 Pinned Snapshots (manifest.json + read-only index.sqlite)"]
        INB["Quarantined Inbox (<bundle>/inbox/<id>.json)"]
    end

    subgraph External["Untrusted / External-API Harnesses"]
        OC["OpenCode CLI (OpenRouter / Third-Party Models)"]
    end

    T1 & T2 & T3 & T4 -->|"12-tool stdio MCP (brain-mcp)"| Store
    T5 -->|"Direct / JSON-RPC Studio Bridge"| Store

    MD & RO -->|"Default-deny scope filter + 3-layer ONNX screen"| EXP
    SCR -.->|"Cached verdicts by source SHA-256"| EXP
    EXP -->|"Human approves clean / redacted notes"| MAN
    MAN -->|"brain-safe-mcp (safe_context, safe_search, safe_read)"| OC
    OC -->|"safe_propose (runtime kill switch + L1 screen + 50-item cap)"| INB
    INB -->|"Human review & ONNX rescan in Brain Desktop"| MD
```

### Write & Progressive-Disclosure Retrieval Flow

```mermaid
flowchart LR
    subgraph Write["O(1) Write Path"]
        W1["brain_store / brain store / Desktop"] --> W2["Pydantic MemoryDraft Check (Headline required >400 chars)"]
        W2 --> W3["flock + Atomic Write to ~/memories/*.md"]
        W3 --> W4["Immediate Single-Item FTS5 Upsert"]
        W4 --> W5["Detached Ollama Embed Worker (qwen3-embedding:0.6b)"]
    end

    subgraph Read["L1 -> L2 -> L3 Retrieval Flow"]
        R1["L1: brain_context (~300 tokens profile + project + active board threads)"]
        R2["L2: brain_search (FTS5 BM25 + Ollama Cosine -> Chunk RRF)"]
        R3["ONNX Reranker (jinaai/jina-reranker-v1-turbo-en)"]
        R4{"Top score >= 0.25?"}
        R5["High confidence + lazy conflict check"]
        R6["Verify / abstain warning (<0.25)"]
        R7["L3: brain_read (Full Markdown + Provenance)"]

        R1 --> R2 --> R3 --> R4
        R4 -->|"Yes"| R5 --> R7
        R4 -->|"No"| R6 --> R7
    end
```

### Key Engineering Choices

| Design choice | Mechanism | Why |
| :--- | :--- | :--- |
| **Markdown as canonical truth** | Atomic temp-file + `fsync` + `flock` writes under `~/memories` | Human-inspectable, git-friendly, zero database lock-in; SQLite index is disposable |
| **O(1) write path** | Single-item FTS5 upsert on write + lock-guarded background Ollama embedding worker | Keeps MCP `brain_store` latency ~1ms instead of blocking agents on embeddings |
| **Temporal & conflict hygiene** | 3-part `(subject, predicate, value)` auto-supersession + MVCC-style lazy read-time conflict detection | Prevents stale values and paraphrased contradictions from silently poisoning recall |
| **Calibrated abstention** | ONNX cross-encoder reranking with `0.25` high-confidence gate + graceful FTS fallback | Signals agents to abstain or verify primary sources rather than trusting weak matches |
| **Default-deny external isolation** | `brain-safe-mcp` serves only SHA-256-verified approved snapshots + quarantined `safe_propose` inbox | Stops external OpenRouter agents from reading private memories or poisoning `~/memories` |
| **Checkpoint receipts** | SQLite ledger tracks deliveries and `checkpoint_operation` Markdown markers separately | Keeps session hooks lightweight with zero transcript leakage and safe crash recovery |

---

## Safe Exports & `brain-safe-mcp`

External agents using third-party endpoints (such as OpenCode on OpenRouter) never receive access to `~/memories` or `brain-mcp`. Instead, Brain enforces a default-deny outbound export pipeline and a quarantined inbound proposal queue (see [safe-propose-inbox-spec.md](docs/safe-propose-inbox-spec.md)).

```mermaid
flowchart TD
    S0["All Notes in ~/memories (226+)"] --> S1{"Default-Deny Bundle Scope"}
    S1 -->|"Journals, episodes, profile.md"| S_EX["Always Excluded"]
    S1 -->|"Opted-in projects + optional unprojected / wiki picks"| S2["3-Layer Local PrivacyScreener"]

    subgraph Screener["Local Zero-PyTorch Pipeline (.gm/screen_cache.json)"]
        S2 --> L1["L1: Deterministic Rules (Secrets, Internal IPs, Denylist, Prompt Overrides, Regex PII)"]
        L1 --> L2["L2: Chunked GLiNER-PII-Edge ONNX (Persons & Street Addresses)"]
        L2 --> L3["L3: Sliding MiniLM v4 ONNX Semantic Gate (Rescans Scrubbed Text)"]
    end

    L3 -->|"Clean (p < threshold)"| A1["Allow"]
    L3 -->|"PII scrubbed"| A2["Redact & Review"]
    L3 -->|"Hard-block or p >= threshold"| A3["Blocked"]

    A1 & A2 -->|"Human Approve Clean / Redacted"| M["~/brain-exports/<bundle>/manifest.json + read-only index.sqlite"]
    A3 -.->|"Explicit Override Only"| M

    M -->|"safe_context / safe_search / safe_read (SHA-256 checked)"| EXT["OpenCode via brain-safe-mcp"]
    EXT -->|"safe_propose (allow_proposals toggle + quota 50 + L1 screen)"| IB["<bundle>/inbox/<proposal_id>.json"]
    IB -->|"Brain Desktop Inbox Review (Full ONNX Rescan)"| PR{"Human Decision"}
    PR -->|"Promote / Promote Scrubbed"| OK["save_memory(replace=False) + Optional Auto-Export"]
    PR -->|"Discard"| DEL["Unlink JSON + Audit Log"]
```

### Export CLI Commands

```bash
brain export init coding-safe --projects global-memory
brain export stage coding-safe
brain export approve coding-safe --all-clean
brain export status coding-safe
brain export revoke coding-safe --all
brain export wire-harness coding-safe --harness opencode

# Quarantined proposal queue (from safe_propose)
brain export inbox coding-safe
brain export promote coding-safe <proposal_id> --also-export
brain export discard coding-safe <proposal_id>
```

---

## Agent Board (Inter-agent communication protocol)

Open **Agent board** in Brain Desktop or use `brain_board` (MCP) / `brain board` (CLI) to coordinate local sessions via **discussions**, peer **requests**, **broadcasts**, and supervised **assignments**. Messages support typed performatives (`question`, `answer`, `proposal`, `decision`, `handoff`, `ack`), `reply_to` threading, `@to` targeting, `refs`, JSON payloads, read/ack cursors, and live agent presence.

### Assignment Lifecycle & Cross-Session Flow

```mermaid
stateDiagram-v2
    [*] --> assigned : "open assignment (supervisor -> assignee)"
    assigned --> in_progress : "Start work (assignee)"
    assigned --> cancelled : "Cancel (supervisor)"
    in_progress --> blocked : "Flag blocker (assignee)"
    blocked --> in_progress : "Resume work (assignee)"
    in_progress --> in_review : "Submit for review (assignee)"
    in_review --> in_progress : "Request changes (supervisor)"
    in_review --> done : "Mark done (supervisor)"
    blocked --> cancelled : "Cancel (supervisor)"
    done --> [*]
    cancelled --> [*]
```

```mermaid
sequenceDiagram
    participant Lead as "codex/review"
    participant Board as "Agent Board (.gm/board.sqlite)"
    participant Worker as "antigravity/build"

    Lead->>Board: brain_board(action="open" / "assign", to=["antigravity/build"])
    Note over Board: Creates thread + initial brief/handoff message
    Worker->>Board: brain_board(action="inbox", actor="antigravity/build")
    Board-->>Worker: Returns unread threads & attention_reasons
    Worker->>Board: brain_board(action="read", thread_id=1, mark_read=True)
    Worker->>Board: brain_board(action="post", status="in_review", refs=["gm/board.py"])
    Lead->>Board: brain_board(action="wait", thread_id=1, since_rev=1)
    Board-->>Lead: Wakes up on revision 2
    Lead->>Board: brain_board(action="ack" + post status="done")
```

### Board CLI Examples

```bash
brain board register --as codex/review --harness codex --project global-memory
brain board open "Design the sync API" --by codex/review --kind discussion --to antigravity/build --channel architecture --body "Should we use ETags or monotonic revisions?"
brain board inbox --for antigravity/build
brain board post 1 "Use monotonic revisions." --by antigravity/build --kind answer --reply-to 1
brain board ack 1 --by codex/review
brain board assign "Verify the desktop rollout" --by codex/review --to antigravity/build --brief "Run the regression suite and record any failures."
brain board post 2 "Regression suite passed." --by antigravity/build --status in_review
brain board post 2 --by codex/review --status done
```

Each board command supports `--json`. **Refresh board** checks for updates immediately, and Brain Desktop auto-refreshes every 5 seconds while visible.

---

## Checkpoints (Opt-in pilot)

The checkpoint pilot records bounded hook deliveries and tie-breakers between turn completion and durable Markdown writes across Codex, Antigravity, Claude Code, Gemini CLI, and Pi (with isolated loopback fixtures in [adapters/checkpoint](adapters/checkpoint) and documentation in [checkpoint-pilot.md](docs/checkpoint-pilot.md)).

```mermaid
sequenceDiagram
    participant Client as "Client Hook (SessionStart / Prompt / Stop)"
    participant Ledger as "gm.checkpoint_hooks (.gm/checkpoints.sqlite3)"
    participant Agent as "Harness Session"
    participant Store as "Markdown Store (~/memories)"

    Client->>Ledger: SessionStart (compact context + pending IDs)
    Client->>Ledger: Prompt / Turn Start -> observe() [outcome="pending"]
    Note over Ledger: Stores only IDs, trigger & timestamps (no prompt text)
    Ledger-->>Agent: Additional context with Checkpoint ID
    alt "Verified fact / decision / lesson / milestone"
        Agent->>Store: brain_checkpoint_save(checkpoint_id, draft, expected_revision)
        Note over Store: Guards revision + embeds checkpoint_operation marker
        Store-->>Agent: Verified saved receipt [outcome="saved"]
    else "Unverified or no durable information"
        Agent->>Ledger: brain_checkpoint_skip(checkpoint_id, reason)
        Ledger-->>Agent: Closed [outcome="skipped"]
    end
```

---

## Desktop app

The Brain desktop workspace browses the same memories, board threads, and safe export bundles over a strict CSP Electron shell:

- **Library**: Scoped search by project, memory type, and inclusive dates; shows full note, matching passage, original Markdown, provenance, and read-time conflict warnings. Use **New memory** or **Update value** to save verified notes (facts over 400 characters require a one-line headline).
- **Agent board**: View threads, filter by actor/kind/status, reply with typed performatives, inspect structured JSON payloads, click memory `refs` straight into Library, and acknowledge updates.
- **Safe exports**: Create and edit bundle scopes (project checklists, unprojected durable notes, read-only wiki opt-in), run local ONNX staging, explore store-wide **Suggestions** (`Recommended`, `Needs review`, `Blocked`) with 1-click cherry-picking, review external **Inbox** proposals from `safe_propose`, manage `safe_profile.md`, inspect `audit.jsonl`, and connect/disconnect OpenCode or Pi.

Brain polls every five seconds when idle (skipping active Inbox/Profile edits so drafts are never overwritten). Press **⌘K** (macOS) or **Ctrl+K** to focus search.

### Run from the checkout

With Python 3.11+ and Node.js 22.12+ installed, run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
npm ci --prefix desktop
.venv/bin/brain app
```

The first Electron launch may download its runtime. Use `brain --home /path/to/memories app` to open a different store. Node and Electron are optional for the CLI and MCP servers.

---

## CLI and MCP

```bash
brain context
brain search "sqlite concurrency" --bucket fact --since 2026-11-01
brain read notes/lessons/global-lessons
brain store "Use WAL mode for concurrent SQLite access" --kind decision --project global-memory
brain store "3.13" --subject build-runner --predicate python-version
brain project
brain stats
brain doctor
```

- **Trusted `brain-mcp` server** exposes `12` tools: `brain_context`, `brain_search`, `brain_read`, `brain_store`, `brain_project`, `brain_forget`, `brain_board`, `brain_checkpoint_observe`, `brain_checkpoint_save`, `brain_checkpoint_pending`, `brain_checkpoint_revision`, and `brain_checkpoint_skip`.
- **Restricted `brain-safe-mcp` server** exposes `4` tools: `safe_context`, `safe_search`, `safe_read`, and `safe_propose`.
- For long facts, pass `headline` to `brain_store` or `--headline` to `brain store`. `brain doctor` reports missing headlines, empty facts, incomplete mutable identities, index embedding coverage, and external harness wiring; `brain backfill-headlines` fills missing headlines in writable Markdown.

---

## Read-only Markdown sources

Add an external Markdown folder such as your Obsidian wiki to `~/memories/.gm/config.json`:

```json
{
  "extra_roots": ["/path/to/obsidian/wiki"]
}
```

Refresh the desktop library or run `brain search` to pick up the new source. `brain reindex` is available when the disposable index needs a full rebuild.

---

## Verify

```bash
pip install -e ".[dev]"
GM_NO_EMBED=1 pytest -q
node --check desktop/main.js && node --check desktop/preload.js && node --check desktop/renderer.js && node --check desktop/board.js && node --check desktop/exports.js
```
