# Brain

Brain shares local memory across Antigravity, Claude Code, Codex, Gemini CLI, and OpenCode. Markdown in `~/memories` holds the source documents. A disposable SQLite index supports passage-level search using FTS5, Ollama embeddings, and an ONNX cross-encoder.

## Architecture

```
Markdown truth (~/memories)
   │  atomic write + O(1) FTS5 upsert + detached Ollama worker (qwen3-embedding:0.6b)
   ▼
Disposable SQLite Index (.gm/index.sqlite)
   │  FTS5 lexical + dense cosine ──► Chunk-level RRF
   ▼
ONNX Cross-Encoder (jinaai/jina-reranker-v1-turbo-en)
   │  Calibrated 0.25 confidence gate + lazy read-time conflict detection
   ▼
CLI (`brain`) · 6-Tool MCP (`brain-mcp`) · Electron Desktop (`brain app`)
```

### Key Engineering Choices

| Design choice | Mechanism | Why |
| :--- | :--- | :--- |
| **Markdown as canonical truth** | Atomic temp-file + `fsync` + `flock` writes under `~/memories` | Human-inspectable, git-friendly, zero database lock-in; SQLite index is disposable |
| **O(1) write path** | Single-item FTS5 upsert on write + lock-guarded background Ollama embedding worker | Keeps MCP `brain_store` latency ~1ms instead of blocking agents on embeddings |
| **Temporal & conflict hygiene** | 3-part `(subject, predicate, value)` auto-supersession + MVCC-style lazy read-time conflict detection | Prevents stale values and paraphrased contradictions from silently poisoning recall |
| **Calibrated abstention** | ONNX cross-encoder reranking with `0.25` high-confidence gate + graceful FTS fallback | Signals agents to abstain or verify primary sources rather than trusting weak matches |

## Desktop app

The Brain desktop workspace browses the same memories as the CLI and MCP server. Search can be scoped to a project, memory type, and inclusive update dates. Open a match to see the full note, the matching passage, and the original Markdown. Index & usage shows chunk coverage and MCP activity.

Brain checks for new and updated memories every five seconds while the window is visible and when you return to it. Use **Refresh library** for an immediate scan, including during a search.

Use **New memory** to capture a fact, decision, lesson, journal entry, or project note. A mutable fact uses a subject and predicate as its identity. **Update value** records the previous value as superseded. The app protects read-only sources and checks for concurrent Markdown changes when you edit or archive a note.

Every record in the Facts view has a headline, including decisions, lessons, projects, and the profile. A fact note or mutable fact value over 400 characters requires a one-line headline. Brain derives headlines for the other records when the field is empty. The app shows headlines under memory titles in the library and reader.

### Run from the checkout

With Python 3.11+ and Node.js 22.12+ installed, run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
npm ci --prefix desktop
.venv/bin/brain app
```

The first Electron launch may download its runtime. Use `brain --home /path/to/memories app` to open a different store. Node and Electron are optional for the CLI and MCP server.

Press **⌘K** (macOS) or **Ctrl+K** to focus search. Submit with **Enter**.

## Agent board

Open **Agent board** in the sidebar to assign work, follow progress, and review deliverables. A supervisor gives the assignment a brief and a recipient. The assignee posts replies, flags blockers, and submits a review update. The supervisor can request changes or mark the assignment done. The thread retains the brief and every status change.

Sessions sharing a Brain home can coordinate from the CLI. Use the assignment number returned by `assign` in later commands.

```bash
brain board assign "Verify the desktop rollout" --by codex/review --to antigravity/build --brief "Run the regression suite and record any failures."
brain board list --for antigravity/build
brain board read 1
brain board post 1 --by antigravity/build --status in_progress
brain board post 1 "Regression suite passed. Review the test output." --by antigravity/build --status in_review
brain board post 1 --by codex/review --status done
```

Each board command supports `--json`. **Refresh board** checks for updates immediately. The board also updates while it stays open.

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

The `brain` MCP server exposes `brain_context`, `brain_search`, `brain_read`, `brain_store`, `brain_project`, and `brain_forget`. Writes update the affected FTS5 entry and schedule embeddings in the background. Search falls back to keyword retrieval when Ollama is unavailable. Cross-encoder scores below 0.25 call for verifying the source before acting.

For long facts, pass `headline` to `brain_store` or `--headline` to `brain store`. Brain prompts for it in interactive clients. `brain doctor` reports missing headlines, empty facts, and incomplete mutable identities. `brain backfill-headlines --dry-run` previews coverage and `brain backfill-headlines` fills missing headlines in writable Markdown.

## Read-only Markdown sources

Add an external Markdown folder such as your Obsidian wiki to `~/memories/.gm/config.json`:

```json
{
  "extra_roots": ["/path/to/obsidian/wiki"]
}
```

Refresh the desktop library or run `brain search` to pick up the new source. `brain reindex` is available when the disposable index needs a full rebuild.
