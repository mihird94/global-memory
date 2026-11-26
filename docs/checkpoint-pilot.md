# Brain checkpoint pilot

The pilot covers nine client surfaces: Codex desktop and CLI, Antigravity desktop, IDE and CLI, Claude Code CLI, Gemini CLI, Pi CLI (trusted `brain-mcp` + `.gm/checkpoints.sqlite3` ledger), and OpenCode CLI (restricted bundle via `brain-safe-mcp` + quarantined `safe_propose` inbox). Use a disposable workspace and a separate Brain home for each client. Generate or review client configuration before enabling it.

## Run the pilot

1. Generate a hook config for the target surface. Put it in the temporary project's hook configuration or pass it as a session settings file:

   ```sh
   .venv/bin/brain --home /absolute/path/to/pilot-brain checkpoint-hook-config --surface codex-cli
   ```

   | Client | Project or session configuration |
   | --- | --- |
   | Codex | In the temporary project, use `.codex/hooks.json` and review the hooks in the client. The CLI and desktop configs tag their deliveries separately. |
   | Antigravity | Use the temporary workspace's `.agents/hooks.json`. Add the pilot's stdio MCP config in `.agents/mcp_config.json`. Grant only the pilot tools needed for the test. |
   | Claude Code | Pass the generated JSON via `--settings` and an isolated `--strict-mcp-config --mcp-config`. The PreCompact hook records delivery; pending IDs are surfaced when SessionStart runs again. |
   | Gemini CLI | Put the generated hooks in the temporary profile's `.gemini/settings.json` with `hooksConfig.enabled` set to true. |
   | Pi | Set `GM_CHECKPOINT_PILOT=1`, `GM_CHECKPOINT_PYTHON` to the repository virtualenv's Python, and `GM_HOME` to the pilot store. Load `adapters/checkpoint/pi.ts` as an extension. If using `--no-extensions`, explicitly include `-e builtin:mcp` to enable the pilot server. Expose its checkpoint tools directly for the test. |

2. Configure a trusted stdio MCP server using the repository's `.venv/bin/brain-mcp` and set its `GM_HOME` to the same pilot directory as the hook. Give it access only to the disposable test store. Mark known tool approvals explicitly for noninteractive runs. Restart the client or its MCP connection after changes.
3. For a baseline, run the prompt with normal memory steering and no hooks. Then run with observation enabled and compare recorded deliveries, receipts, and the number of model turns. The default hook configuration never asks for another model turn. To test one extra pass for a pending explicit request, pass `--reminder` when generating the Antigravity CLI configuration, or set `GM_CHECKPOINT_REMINDER=1` for the Pi extension. Both require normal completion. Antigravity also requires fully idle background work.
4. Run the following cases using synthetic notes and source references. Inspect Markdown and the ledger separately. A missing event is unobserved. A pending review indicates evidence that a hook or tool opened the checkpoint.

   | Case | Expected evidence |
   | --- | --- |
   | “Remember the synthetic pilot color is teal.” | One explicit checkpoint, one saved receipt and one indexed note. Repeat the same callback and save payload and confirm the same receipt. Read the note through another client pointed at the same pilot home. |
   | Verified fix, tentative diagnosis, trivial edit | Save a lesson for the verified fix and include the verification source. For the other two, use explicit skip reasons and confirm no canonical note was made. |
   | Repeated atomic preference | Same subject, predicate and value returns the existing memory ID and leaves its bytes intact. |
   | Cancellation or compaction | Review stays pending if no write or explicit skip occurred. Check the same session's pending IDs after resume. |
   | Store unavailable | The hook times out or reports a bounded error, and the turn can finish. No saved receipt appears. |
   | Interrupted write | Simulate loss after Markdown persistence. Retrying recovers the same write and indexes it without inserting another note. An intervening revision prevents a stale overwrite. |

The loopback fixture exercises actual client hook and MCP transports with deterministic responses. It runs without account credentials or a hosted model:

```sh
.venv/bin/python adapters/checkpoint/local_smoke.py pi
.venv/bin/python adapters/checkpoint/local_smoke.py claude
.venv/bin/python adapters/checkpoint/local_smoke.py gemini
.venv/bin/python adapters/checkpoint/local_smoke.py gemini --case lesson
.venv/bin/python adapters/checkpoint/local_smoke.py gemini --steering-only
.venv/bin/python adapters/checkpoint/local_smoke.py pi --reminder
.venv/bin/python adapters/checkpoint/local_smoke.py pi --read-from /path/to/codex-pilot-brain notes/facts/pilot--color
.venv/bin/python adapters/checkpoint/local_smoke.py opencode
GM_NO_EMBED=1 GM_NO_RERANK=1 .venv/bin/pytest -q
```

Each smoke command prints the disposable directory containing evidence. In addition to the default remember case, use `--case lesson`, `--case unverified`, or `--case trivial`. The fixture verifies the checkpoint ID appears in the model request before asking the client to call the relevant tool. It checks startup and completion deliveries, lesson provenance, or a skip reason and zero writes as applicable. The fixture shows that the transport works. A live model's judgment about durable memories requires the prompts and cases above.

## Use and inspect a checkpoint

- Use `brain_checkpoint_observe` to open a checkpoint explicitly when a prompt hook is unavailable. The observation takes a bounded surface, harness, session, turn, trigger and optional project. Pass the checkpoint ID to `brain_checkpoint_save` for a verified fact, decision, lesson, project state, or episode.
- Use `brain_checkpoint_skip` with `no_durable_information`, `unverified`, or `user_declined`. Use `brain_checkpoint_pending` to recover the open reviews for the current session.
- For an intended change to an existing memory, inspect it with `brain_checkpoint_revision` and use its revision in the save call. Retry an interrupted save with identical draft fields. The receipt references the Markdown write or the matching atomic fact.
- The CLI equivalents are `checkpoint-observe`, `checkpoint-save` (draft JSON on stdin), `checkpoint-skip`, `checkpoint-pending`, and `checkpoint-revision`. Specify `brain --home /absolute/path/to/pilot-brain` before the subcommand when running locally.
- `.gm/checkpoints.sqlite3` keeps hook deliveries separate from checkpoint outcomes. The ledger stores identifiers, timestamps, revision hashes and reason codes. Draft content lives in Markdown after a save. An indexing retry uses the canonical write marker as evidence and proceeds through the existing incremental indexer.

## Native validation

| Surface and installed version | Startup and completion observed | Receipt and model result | Status |
| --- | --- | --- | --- |
| Codex CLI 0.172.0 | SessionStart, UserPromptSubmit, Stop | Live model saved one atomic fact through MCP and skipped an unverified hypothesis. An earlier run with no tool approval left the checkpoint pending. | Pass for remember and unverified cases. |
| Claude Code CLI 2.1.186 | SessionStart, UserPromptSubmit, Stop | Fact and lesson saved through MCP, with two skip cases producing zero writes over separate runs. Account login was unavailable for the hosted-model run. | Pass for loopback transport cases. |
| Gemini CLI 0.52.0 | SessionStart, BeforeAgent, AfterAgent | Fact and lesson saved through MCP, with two skip cases producing zero writes. Headless startup context is excluded from the explicit request check. | Pass for loopback transport cases. |
| Pi CLI 1.6.1 | session_start, before_agent_start, agent_before_settle, agent_settled | Fact and lesson saved through MCP, with two skip cases producing zero writes. Read back a fact Codex CLI saved in the same store. The reminder case used three model requests versus two for the ordinary save and finished one reminder. | Pass for loopback transport, cross-client read, and reminder. |
| Antigravity CLI 1.5.16 | SessionStart, PreInvocation, Stop | Live model saved one atomic fact. A resumed conversation returned the existing memory ID for the repeated preference. A separate reminder run requested one continuation and recorded its next stop. | Pass for remember, repeat, and reminder cases. |
| OpenCode CLI 1.18.11 | Restricted `brain-safe-mcp` (no direct store/ledger access) | `safe_propose` queued one quarantined proposal with zero direct writes to `GM_HOME`; separate human promotion wrote the audited canonical note. | Pass for restricted `safe_propose` + human promotion loopback case. |
| Codex desktop 26.1117.41037 | Unobserved | Separate project hook config prepared. | Native validation pending (GUI app interactive run). |
| Antigravity desktop 2.35.2 | Unobserved | Separate workspace hook config prepared. | Blocked by Computer Use access (requires interactive GUI run). |
| Antigravity IDE 2.7.0 | Unobserved | Separate workspace hook config prepared. | Blocked by Computer Use access (requires interactive GUI run). |

CLI results apply to the named surface and case. The default configurations requested zero automatic continuations. Pi, Claude Code, and Gemini each took two model requests in the ordinary steering baseline and produced one note with no checkpoint receipt. Semantic capture rates and remaining per-client cancellation, resume, and live steering comparisons still need runs. Full rollout and global settings are separate decisions.

Hook contracts: [Codex](https://learn.chatgpt.com/docs/hooks), [Antigravity](https://antigravity.google/docs/hooks), [Claude Code](https://code.claude.com/docs/en/hooks), [Gemini CLI](https://geminicli.com/docs/hooks/reference/). For Pi, the installed extension reference documents `agent_before_settle`.
