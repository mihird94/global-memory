# Quarantined Write-Inbox (`safe_propose`) Specification for `brain-safe-mcp`

**Target repo:** `global-memory` (repository root)  
**Audience:** Codex implementation agent  
**Goal:** Allow external agents connected via `brain-safe-mcp` (Pi, OpenCode) to propose new candidate memories into an isolated, human-reviewed bundle inbox (`<bundle>/inbox/`) without ever giving them direct write, overwrite, or delete access to `~/memories`.

---

## 1. Security Model & Threat Matrix

`brain-safe-mcp` currently exposes 3 strictly read-only tools (`safe_context`, `safe_search`, `safe_read`) over a human-approved bundle snapshot (`~/brain-exports/<bundle>/`). Adding unrestricted writes to `~/memories` would undermine that isolation.

### Why Direct Writes Are Forbidden

| Threat | Mechanism without Quarantine | Quarantine Mitigation (`safe_propose`) |
| :--- | :--- | :--- |
| **Cross-harness memory poisoning** | Untrusted workspace code or web docs prompt-inject Pi/OpenCode into saving adversarial instructions into `~/memories`, which Antigravity, Claude Code, or Codex later retrieve via `brain_search`. | Proposals land only in `<bundle>/inbox/<proposal_id>.json` (`manifest.json` and `~/memories` are untouched). Prompt-override rules (`PROMPT_OVERRIDE`) flag and block auto-promotion. |
| **Silent fact overwrites / deletion** | Calling `save_memory(..., subject=..., predicate=..., replace=True)` or `forget_memory(...)` silently clobbers or archives durable memory. | `safe_propose` has no `subject`, `predicate`, `replace`, or `forget` parameters. Human promotion always uses `replace=False` and creates a new audited note with `source="safe-inbox:..."` and `author="external:<harness>"`. |
| **Secret / PII exfiltration loop** | Agent echoes an `.env` secret or internal IP into memory and reads it back later across sessions. | Stage-1 `DeterministicScreener` runs at ingest (~1 ms) without loading ONNX in the MCP subprocess; Stage-2 full `PrivacyScreener` (L1 + Chunked GLiNER ONNX + Sliding MiniLM v4 ONNX) runs during CLI/Desktop review and blocks secret/hard-block promotions unless explicitly forced. |
| **Disk / queue flooding** | Runaway loop writes megabytes or thousands of notes. | Hard size caps (`content <= 12,000` chars), max `50` pending proposals per bundle, SHA-256 deduplication of identical pending payloads, and an immediate runtime `allow_proposals` kill switch in `bundle_config.json`. |

### Hard Invariants (Must Not Be Violated)

1. **`brain-safe-mcp` isolation:** `gm/safe_mcp_server.py` MUST NEVER read, open, write, or import `gm_root` (`~/memories`), `.gm/index.sqlite`, `save_memory`, or `index_single_item`. It operates strictly inside `bundle_dir`.
2. **Runtime kill switch:** `bundle_config.json["allow_proposals"]` (default `True`) is checked from disk on every `safe_propose` call so disabling proposals in Brain Desktop takes effect immediately without restarting Pi or OpenCode.
3. **Fail-closed path validation:** Proposal IDs, filenames, symlinks inside `<bundle>/inbox/`, and non-ASCII/control characters must be rejected identically to `_safe_note_path`.
4. **Atomic `0600` persistence:** Use existing `atomic_write_text` from `gm/store.py` (mode `0600`) for all JSON writes.
5. **No new dependencies & no PyTorch:** Zero additions to `pyproject.toml` or `desktop/package.json`.
6. **Strict Electron CSP:** Zero `innerHTML` anywhere in `desktop/`; construct all DOM nodes using `element()`, `document.createElement(...)`, `textContent`, and `replaceChildren()`.
7. **Never run `brain reindex`:** On promotion, call `save_memory` followed by `index_single_item(gm_root, item)`.

---

## 2. Quarantined Storage Layout & Validation

### Directory & ID Format

- Directory: `<bundle_dir>/inbox/`
- Proposal ID format: `prop-YYYYMMDDTHHMMSSZ-<8hex>` (e.g., `prop-20261124T223000Z-a1b2c3d4`), generated with UTC timestamp + `os.urandom(4).hex()` (or `secrets.token_hex(4)`).
- Safe path helper: `_safe_inbox_path(bundle_dir: Path, proposal_id: str) -> Path`
  - Reject empty string, `\0`, `/`, `\`, `"."`, `".."`, or any ID not matching `^prop-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$`.
  - Reject if `<bundle_dir>/inbox` or `<bundle_dir>/inbox/<id>.json` is a symlink.
  - Assert `resolved.is_relative_to((bundle_dir / "inbox").resolve())`.

### Proposal JSON Schema (`<bundle_dir>/inbox/<proposal_id>.json`)

```json
{
  "id": "prop-20261124T223000Z-a1b2c3d4",
  "created_at": "2026-11-24T22:30:00Z",
  "status": "pending",
  "bundle_name": "coding-safe",
  "harness": "pi",
  "title": "Asyncpg timeout under PgBouncer transaction pooling",
  "headline": "Use statement_cache_size=0 with PgBouncer transaction mode to avoid prepared statement errors.",
  "kind": "lesson",
  "project": "global-memory",
  "tags": ["postgres", "pgbouncer"],
  "content": "When connecting asyncpg through PgBouncer in transaction mode...",
  "content_sha256": "<64-char hex sha256 of raw UTF-8 content>",
  "l1_screen": {
    "action": "allow",
    "entity_types": [],
    "hard_block_rules": []
  },
  "full_screen": null,
  "promoted_doc_id": "",
  "reviewed_at": ""
}
```

### Ingest Validation & Quotas

Enforced inside `propose_to_inbox(bundle_dir, ...)`:

- **Enabled check:** Read `bundle_config.json`; if `not cfg.get("allow_proposals", True)`, raise `PermissionError(f"Proposals are disabled for bundle {bundle_dir.name!r}.")`.
- **Allowed `kind`:** Strictly `("fact", "decision", "lesson")`. Reject `"profile"`, `"project"`, `"journal"`, `"episode"`, or unknown kinds with `ValueError`.
- **String limits (stripped of leading/trailing whitespace):**
  - `title`: non-empty, `<= 160` chars.
  - `content`: non-empty, `<= 12_000` chars.
  - `headline`: `<= 300` chars (optional at ingest; auto-derived or required at promotion if promoted as a `fact` > `FACT_HEADLINE_THRESHOLD` = `400` chars).
  - `project`: optional, `<= 64` chars, normalized via `normalize_project_slug` if non-empty.
  - `harness`: optional short label (`pi`, `opencode`, etc.), `<= 48` chars, normalized to safe characters `[a-z0-9_-]` (fallback `"external"`).
  - `tags`: accepts `str` (comma-separated) or `list[str]`; max `10` tags, each `<= 40` chars, deduplicated preserving order.
- **Deduplication:** Before enforcing the quota on new files or allocating a new ID, scan existing `*.json` files in `<bundle_dir>/inbox/`. If a `pending` proposal already has the exact same `content_sha256` and `title`, return that existing record with `"deduplicated": True` instead of creating a duplicate.
- **Quota:** Count pending JSON files in `<bundle_dir>/inbox/`; if `>= 50`, raise `ValueError("Bundle inbox is full (50 pending proposals). Review or discard items in Brain Desktop.")`.

### Two-Stage Screening Pipeline

1. **Stage 1 — Fast Ingest Screening (`DeterministicScreener` inside `gm/safe_mcp_server.py` / `propose_to_inbox`):**
   - Keeps `brain-safe-mcp` fast and lightweight (no ONNX model memory in every external agent MCP child process).
   - Instantiate `DeterministicScreener(denylist=tuple(dict.fromkeys([*DEFAULT_DENYLIST_TERMS, *cfg.get("extra_denylist", ())])))`.
   - Run `findings = det.scan(f"{title}\n\n{headline}\n\n{content}")`.
   - Record `l1_screen = {"action": ..., "entity_types": sorted({f.entity_type for f in findings}), "hard_block_rules": sorted({f.rule for f in findings if f.entity_type in HARD_BLOCK_ENTITIES})}`:
     - `"block"` if any finding has `entity_type in HARD_BLOCK_ENTITIES` (`SECRET_CREDENTIAL`, `ORG_DENYLIST`, `INTERNAL_IP`, `PROMPT_OVERRIDE`),
     - `"redact_and_review"` if any non-hard-block PII entity was matched,
     - `"allow"` otherwise.
   - Note: still store the proposal in `<bundle>/inbox/` so the human can see what the external agent attempted and either discard or fix it, while flagging `l1_screen["action"]` clearly in `audit.jsonl` and the tool response.
2. **Stage 2 — Full Local ONNX Review Screening (`PrivacyScreener` inside `list_inbox_proposals` / `promote_inbox_proposal`):**
   - Uses `_screen_with_cache(combined_markdown, proposal["content_sha256"], sc, cache)` keyed on `content_sha256` + `sc.rules_hash` inside `.gm/screen_cache.json` (passing `gm_root` when called from CLI/Desktop review).
   - Populates `full_screen = {"action", "entity_types", "hard_block_rules", "p_post_scrub", "scrubbed_body", "diff_preview", "rules_hash"}`.
   - Does **not** rewrite the proposal file unnecessarily on every read if cached in `.gm/screen_cache.json`, or caches `full_screen` deterministically per `sc.rules_hash`.

---

## 3. Exact Module-by-Module Changes

### 3.1 `gm/export.py`

1. **Imports:** Import `DEFAULT_DENYLIST_TERMS`, `DeterministicScreener`, `HARD_BLOCK_ENTITIES` from `.screening`, and `save_memory` from `.store` (plus `index_single_item` from `.index` inside `promote_inbox_proposal` or top-level).
2. **Constants:**
   - `ALLOWED_PROPOSAL_KINDS: tuple[str, ...] = ("fact", "decision", "lesson")`
   - `MAX_INBOX_PENDING = 50`
   - `MAX_PROPOSAL_CONTENT_CHARS = 12_000`
3. **Config support (`allow_proposals`):**
   - Add `allow_proposals: bool = True` parameter to `_validated_bundle_cfg`, `init_bundle`, and `update_bundle_config`.
   - Persist `"allow_proposals": bool(allow_proposals)` in `bundle_config.json` (treat missing `"allow_proposals"` on older configs such as `coding-safe` as `True`).
4. **Inbox helpers & public functions:**
   - `_safe_inbox_path(bundle_dir: Path, proposal_id: str) -> Path`
   - `_pending_inbox_count(bundle_dir: Path) -> int`: lightweight helper reading `inbox/*.json` (count files not symlinked with valid JSON) for `list_bundles()`.
   - `propose_to_inbox(bundle_dir: Path, *, title: str, content: str, kind: str = "lesson", project: str = "", headline: str = "", tags: list[str] | tuple[str, ...] | str = (), harness: str = "") -> dict[str, Any]`
     - Validates `bundle_config.json` existence and `allow_proposals`, validates inputs/limits, runs Stage-1 `DeterministicScreener`, handles SHA-256 dedup & `MAX_INBOX_PENDING`, writes `<bundle_dir>/inbox/<proposal_id>.json` atomically.
     - Returns `{"proposal_id": ..., "status": "pending", "bundle": bundle_dir.name, "deduplicated": bool, "l1_action": ..., "l1_entity_types": ..., "l1_hard_block_rules": ...}`.
   - `list_inbox_proposals(gm_root: Path, bundle_dir: Path, *, screener: PrivacyScreener | None = None) -> list[dict[str, Any]]`
     - Reads all valid `*.json` files in `<bundle_dir>/inbox/`, ordered newest `created_at` first.
     - Resolves `PrivacyScreener` (respecting `cfg["threshold"]`, `cfg["extra_denylist"]`) and runs `_screen_with_cache` on `# {title}\n\n{content}` using `content_sha256` (so repeated polls every 5s in Brain Desktop hit `.gm/screen_cache.json` with 0 ms ONNX overhead).
     - Attaches `full_screen` (`action`, `entity_types`, `hard_block_rules`, `p_post_scrub`, `scrubbed_body`, `diff_preview`).
   - `promote_inbox_proposal(gm_root: Path, bundle_dir: Path, proposal_id: str, *, use_scrubbed: bool = False, also_export: bool = False, force_blocked: bool = False, title: str | None = None, headline: str | None = None, project: str | None = None, content: str | None = None, tags: list[str] | None = None, screener: PrivacyScreener | None = None) -> dict[str, Any]`
     - Loads & validates `_safe_inbox_path(bundle_dir, proposal_id)`.
     - Verifies `content_sha256` integrity of stored proposal before edits.
     - Applies any explicit human edits (`title`, `headline`, `project`, `content`, `tags`), ensuring `kind` remains in `ALLOWED_PROPOSAL_KINDS`.
     - Computes final screening via `sc.screen_markdown(...)` (note: if `use_scrubbed=True`, takes `scr.scrubbed_body` first, then re-scans for remaining `HARD_BLOCK_ENTITIES`).
     - If final `action == "block"` or `hard_block_rules` is non-empty (especially `PROMPT_OVERRIDE` or `SECRET_CREDENTIAL`) and `not force_blocked`: raise `ValueError(...)` refusing unsafe promotion.
     - For `final_kind == "fact"` and `len(final_content) > FACT_HEADLINE_THRESHOLD`: ensure `final_headline` is non-empty (or use `infer_fact_headline(final_content, final_title)` if empty? Wait: per `MemoryDraft`, >400-char facts require an explicit headline — surface clean `ValueError` asking for a headline in CLI/Desktop unless the human supplies one!).
     - Calls `item = save_memory(gm_root, final_content, title=final_title, kind=final_kind, project=final_project, tags=final_tags, headline=final_headline, source=f"safe-inbox:{bundle_dir.name}/{proposal_id}", epistemic="verified", author=f"external:{harness}", replace=False)`.
     - Calls `index_single_item(gm_root, item)`.
     - If `also_export=True`: calls `add_bundle_candidates(gm_root, bundle_dir, doc_ids=[item.id], approve_if_clean=True, screener=sc)` (if blocked/redacted, `add_bundle_candidates` still stages it in `manual_include_ids` without bypassing review).
     - Removes `<bundle_dir>/inbox/<proposal_id>.json` (or moves/unlinks — prefer `unlink()` so `<bundle>` holds zero stale untrusted inbox files after promotion) and appends an event to `<bundle_dir>/audit.jsonl`: `{"ts": ..., "tool": "inbox_promote", "status": "ok", "proposal_id": proposal_id, "doc_id": item.id}`.
     - Returns `{"promoted_doc_id": item.id, "rel_path": item.rel_path, "also_exported": also_export}`.
   - `discard_inbox_proposal(bundle_dir: Path, proposal_id: str) -> dict[str, Any]`
     - Validates `_safe_inbox_path(bundle_dir, proposal_id)` and exists check (`FileNotFoundError` if missing).
     - Unlinks the proposal JSON file immediately.
     - Appends `{"ts": ..., "tool": "inbox_discard", "status": "ok", "proposal_id": proposal_id}` to `<bundle_dir>/audit.jsonl`.
     - Returns `{"discarded": proposal_id}`.
5. **`list_bundles()` & `read_bundle_detail()` updates:**
   - Add `"allow_proposals": cfg.get("allow_proposals", True)` and `"inbox_pending_count": _pending_inbox_count(child)` in `list_bundles()`.
   - In `read_bundle_detail(gm_root, bundle_dir)`: only scan `list_inbox_proposals` when `include_inbox=True` OR when `_pending_inbox_count(bundle_dir) > 0` (if `0` pending files, return `"inbox": []` immediately in 0 ms!). Attach `"inbox"` and `"inbox_pending_count"` to the returned dict.
     - Pass `screener: PrivacyScreener | None = None` to `read_bundle_detail(..., screener=None)` so `Desktop` reuses its cached `self._screener_for(bdir)` instead of re-loading ONNX on every read!

---

### 3.2 `gm/safe_mcp_server.py`

1. Import `propose_to_inbox` from `.export`.
2. Add `safe_propose_impl`:
   ```python
   def safe_propose_impl(
       bundle_dir: Path,
       *,
       title: str,
       content: str,
       kind: str = "lesson",
       project: str = "",
       headline: str = "",
       tags: str = "",
       harness: str = "",
   ) -> str:
   ```
   - Calls `propose_to_inbox(...)`.
   - Logs to `<bundle_dir>/audit.jsonl` via `_audit_log(bundle_dir, "safe_propose", "ok", t0, doc_id=res["proposal_id"], kind=kind, l1=res["l1_action"])`. (On `PermissionError` or `ValueError`, logs `status="denied"` or `"rejected"` and re-raises as `ToolError` in the `@server.tool()` wrapper.)
   - Returns a concise human-readable confirmation that **never** echoes secret values, e.g.:
     - `"Queued proposal prop-... as 'pending' in bundle 'coding-safe' inbox (human approval in Brain Desktop required before entering Brain store). L1 status: allow."` (plus any entity type names / hard-block rule names if `l1_action != "allow"`).
3. Register 4th MCP tool inside `create_safe_mcp(bundle_dir: Path)`:
   ```python
   @server.tool()
   def safe_propose(
       title: str,
       content: str,
       kind: str = "lesson",
       project: str = "",
       headline: str = "",
       tags: str = "",
       harness: str = "",
   ) -> str:
       """Submit a candidate fact, decision, or lesson into the bundle's quarantined review inbox (never writes directly to Brain)."""
       try:
           return safe_propose_impl(
               bundle_dir,
               title=title,
               content=content,
               kind=kind,
               project=project,
               headline=headline,
               tags=tags,
               harness=harness,
           )
       except Exception as exc:
           raise ToolError(str(exc)) from None
   ```
4. Update `argparse` description in `main()` from `"Read-only fail-closed..."` to `"Scoped fail-closed Brain export MCP server (quarantined inbox proposals optional)"`.

---

### 3.3 `gm/cli.py`

Add subcommands under `brain export`:
- `brain export init <bundle> ... [--no-proposals]`: optionally set `allow_proposals=not args.no_proposals`.
- `brain export inbox <bundle> [--json]`: calls `list_inbox_proposals(root, bdir)` and prints table/JSON of pending proposals (`proposal_id`, `created_at`, `harness`, `kind`, `project`, `full_screen.action`, `title`).
- `brain export promote <bundle> <proposal_id> [--use-scrubbed] [--also-export] [--force-blocked] [--project <slug>] [--headline <text>]`: calls `promote_inbox_proposal(...)` and prints JSON result.
- `brain export discard <bundle> <proposal_id>`: calls `discard_inbox_proposal(bdir, args.proposal_id)` and prints JSON result.

---

### 3.4 `gm/desktop.py` & `desktop/main.js`

1. **`gm/desktop.py`:**
   - Import `discard_inbox_proposal`, `promote_inbox_proposal` from `.export`.
   - Update `_parse_export_scope` to extract `"allow_proposals": bool(params["allow_proposals"]) if "allow_proposals" in params else None`.
   - Pass `allow_proposals` in `export_init` and `export_update_config`.
   - Pass `screener=self._screener_for(bdir)` into `read_bundle_detail(self.root, bdir, screener=self._screener_for(bdir))` inside `export_read` (and any export handler returning `read_bundle_detail`) when `_pending_inbox_count(bdir) > 0` or `BRAIN_SCREEN_DETERMINISTIC == "1"` so cached ONNX models are reused instead of reloaded!
   - Register 2 new actions in `Desktop.request`:
     - `export_inbox_promote(self, params)` -> validates `bundle`, `proposal_id`, optional edited `title`/`headline`/`project`/`content`, `use_scrubbed`, `also_export`, `force_blocked`, calls `promote_inbox_proposal(...)`, returns updated `read_bundle_detail(self.root, bdir, screener=...)`.
     - `export_inbox_discard(self, params)` -> calls `discard_inbox_proposal(bdir, field(params, "proposal_id"))`, returns updated `read_bundle_detail(...)`.
2. **`desktop/main.js`:**
   - Add `'export_inbox_promote'` and `'export_inbox_discard'` to the strict `actions` `Set`.

---

### 3.5 Brain Desktop UI (`desktop/index.html`, `desktop/exports.js`, `desktop/styles.css`)

1. **`desktop/index.html`:**
   - Inside `#export-tabs`, add tab button:
     `<button type="button" data-etab="inbox" id="export-tab-inbox">Inbox</button>`
   - Inside `.export-paper`, add pane:
     `<div id="export-inbox-pane" class="export-inbox-pane" hidden></div>`
   - Inside `#bundle-dialog` -> `#bundle-form` (under Additional sources / permissions):
     `<label class="inline-check"><input type="checkbox" name="allow_proposals" id="bundle-allow-proposals" checked>Allow quarantined write proposals via <code>safe_propose</code> (human review required)</label>`
2. **`desktop/exports.js` (strict CSP — NO `innerHTML`):**
   - Sidebar bundle row (`bundleRow(b)`): when `b.inbox_pending_count > 0`, show a warning/accent pill `${b.inbox_pending_count} inbox`.
   - Bundle tabs (`renderBundleDetail(detail)`):
     - Set `#export-tab-inbox` label to `Inbox (${pendingCount})` when `pendingCount > 0` else `Inbox`.
     - Show/hide `#export-inbox-pane` when `exportsState.tab === 'inbox'` and call `renderInboxPane(detail)`.
   - `openBundleDialog` & `#bundle-form` submit:
     - Populate `#bundle-allow-proposals` (`cfg.allow_proposals !== false`) and submit `allow_proposals` in `export_init` / `export_update_config`.
   - `renderInboxPane(detail)`:
     - Banner explaining quarantine status (enabled/disabled badge matching `cfg.allow_proposals !== false`, plus quick toggle button or `Edit scope` hint).
     - Empty state when `!(detail.inbox || []).length`: clear note that Pi & OpenCode can call `safe_propose(...)` and nothing touches `~/memories` until promoted here.
     - For each proposal in `detail.inbox`:
       - Card showing **Untrusted external proposal** header, `id`, `harness`, `created_at`, `kind`, full ONNX verdict pill (`Allow`, `Redact & review`, `Blocked`), `p=...`, L1/L2 entity/hard-block pills (highlighting `PROMPT_OVERRIDE` / `SECRET_CREDENTIAL` in danger style).
       - Editable inputs (`title`, `headline`, `project`, `content` textarea) prefilled with the proposal values so the user can clean or reclassify before saving into `~/memories`.
       - Expandable `details` showing scrubbed diff & sanitized body when `full_screen.diff_preview` or `full_screen.scrubbed_body` differs.
       - Checkbox: `Also stage & approve into "<bundle>"` (`also_export`).
       - Action buttons:
         - **Promote to Brain** (`use_scrubbed: false`; if `full_screen.action === 'block'`, prompt `window.confirm(...)` and require explicit `force_blocked: true` or rename button **Force promote…** with danger styling).
         - **Promote scrubbed** (shown whenever `full_screen.scrubbed_body` differs from `content`, sends `use_scrubbed: true`).
         - **Discard** (`export_inbox_discard`, removes the quarantined JSON immediately).
3. **`desktop/styles.css`:**
   - Add cohesive styles for `.export-inbox-pane`, `.export-inbox-card`, `.export-inbox-fields`, `.export-inbox-notice` using existing CSS variables (`--line`, `--paper`, `--accent`, `--muted`, `--mono`).

---

## 4. Testing & Verification Checklist

### Required Unit & Integration Tests

1. **`tests/test_export_safe_mcp.py`:**
   - `safe_propose_impl` writes strictly to `<bundle>/inbox/<id>.json` and does **not** touch `gm_root` or `manifest.json`.
   - `safe_propose_impl` rejects invalid `kind` (`journal`, `project`, `profile`), oversized content (`> 12,000` chars), path-traversal/invalid IDs, and fails closed when `allow_proposals=False` in `bundle_config.json`.
   - Quota test: `51`st distinct pending proposal is rejected; duplicate pending `content_sha256` deduplicates cleanly.
   - L1 `PROMPT_OVERRIDE` (`SYSTEM_OVERRIDE`, `ignore all previous instructions`) and `SECRET_CREDENTIAL` flag `l1_screen.action == "block"`; `promote_inbox_proposal` refuses promotion unless `force_blocked=True`, while clean proposals promote into `~/memories` with `source="safe-inbox:..."`, `author="external:..."`, appear in `brain search`, and unlink from `inbox/`.
   - `also_export=True` on clean promotion stages and approves the new note into `manifest.json` + `index.sqlite` so `safe_read_impl` can read it.
   - `discard_inbox_proposal` deletes the proposal file immediately and logs to `audit.jsonl`.
   - `safe_read_impl` / `safe_search_impl` / `safe_context_impl` cannot read anything inside `<bundle>/inbox/`.
2. **`tests/test_desktop.py`:**
   - Extend bridge tests (`BRAIN_SCREEN_DETERMINISTIC=1`) covering `export_update_config({"allow_proposals": False})`, `safe_propose_impl` denial when disabled, re-enabling, submitting clean + PII proposals, reading `inbox` via `export_read`, calling `export_inbox_promote` (clean & `also_export=True`), and `export_inbox_discard`.

### Final Verification Commands

```bash
cd <repo-root>
node --check desktop/main.js && node --check desktop/preload.js && node --check desktop/renderer.js && node --check desktop/board.js && node --check desktop/exports.js
.venv/bin/pytest -q tests
```

Plus a quick stdio JSON-RPC check against `.venv/bin/python -m gm.desktop` verifying `export_list` and `export_read` return `allow_proposals` and `inbox_pending_count` without error on the user's existing `coding-safe` bundle (read-only check; do not modify `~/memories`).

### Out of Scope / Guardrails

- Do **not** modify `~/memories` or `~/.pi` / `~/.config/opencode` during tests (always use `tmp_path` + `monkeypatch` for `Path.home()` and `BRAIN_EXPORTS_DIR`).
- Do **not** run `brain reindex` or commit/push git changes unless explicitly instructed.
