# New-case local harvesting pilot — partial result

2026-10-17. Run state: **FAILED_BACKEND**, halted under the frozen no-retry rule. This is a newly authored synthetic development pilot, not a blinded holdout, public benchmark, or completed paired model comparison.

## Execution

- Planned: four synthetic scenarios × two installed local models = eight generation calls.
- Actual: six attempted calls, five raw responses captured, one timeout; two scheduled calls unattempted.
- Elapsed: approximately 478 seconds, including final unload checks.
- Known reported usage: 10,702 tokens. Usage from the timeout is unavailable; this is not a total measured-token claim.
- Both models used `think=false`, temperature 0, seed 1742, context 8192 and completion cap 1536. Request timeout was 120 seconds. Inputs, code copies, protocol and schedule were frozen before inference; no prompts or thresholds were changed after responses.
- Only loopback Ollama was contacted, proxies/redirects were disabled, and all source excerpts were newly authored synthetic text. No stored private memory was used or changed. Final `/api/ps` reported no resident models.

| Model | Scheduled | Attempted | Parseable JSON | Truncated/invalid | Timeout |
| --- | ---: | ---: | ---: | ---: | ---: |
| qwen2.5-coder:7b | 4 | 2 | 0 | 1 | 1 |
| qwen3:8b, thinking disabled | 4 | 4 | 4 | 0 | 0 |

The coder's configuration-update response terminated with `done_reason=length` at 1536 output tokens. Its later procedure request timed out. Neither truncated output nor missing output was silently salvaged, retried, or scored as correct. Its no-write and backup-scope cases were not attempted. This protocol uses strict complete JSON parsing; comparisons against earlier salvaging parsers need to acknowledge that difference.

## Observations from Qwen3's four cases

1. **Procedure plus canary:** two candidates emitted, one admitted. The second candidate reproduced the synthetic secret-format canary; admission rejected it. The admitted procedure preserves stop/restore/check/restart order and failure handling. Its structured project scope is the generic `project-name`, so schema validity does not establish accurate scope metadata.
2. **No-write control:** three candidates emitted despite an explicit non-durable conversation, including irrelevant chatter. All three were rejected. Model-level no-write behavior failed; post-admission no-write behavior passed for this case.
3. **Backup scope:** two candidates emitted, one admitted. The admitted decision preserves Cedar-only encrypted backups and 21-day retention in its statement/implications. Its rationale adds “minimizing storage overhead,” which the source did not supply. The keyword rationale proxy still credits it: keyword coverage is not faithful causal attribution.
4. **Configuration update:** two candidates were admitted. The decision preserves `request_timeout_ms=4500` and retirement of the old key, but embellishes the source rationale. A second procedure adds workflow and testing prerequisites absent from the source. Some repetition may be a defensible extraction alternative; invented prerequisites need to remain distinguishable from source-backed constraints. No independently adjudicated semantic accuracy is claimed.

Across those four parseable responses, nine candidates were emitted and four admitted. Automated one-to-one gold matching credits three admitted targets out of three expected target records, with one unmatched admitted record. These are keyword/schema proxies, not a claim of perfect semantic recall. The empty-gold no-write case is evaluated by candidate counts rather than F1.

The surrogate storage checks found no configured prohibited strings in the admitted Qwen3 records. That does not establish general secret/noise safety, graph safety, or the behavior of the production promotion/index/retrieval path. No graph extraction was scheduled. `raw_candidates` in scoring records can contain in-place schema normalization; use the unmodified full `RESPONSE` events as the authoritative raw model output.

## Evidence

- `protocol.json` and `protocol.sha256`: frozen design, shuffled schedule and source hashes.
- `inputs/`: exact corpus, runner and key product-helper copies used to identify the run.
- `dispatch.jsonl`: fsynced request-start, full-response, scoring and error events.
- `installed_models.json`: installed model tags/digests captured before dispatch.
- `summary.json`: terminal status, available usage, per-case results and unload observations.
- `manifest.json`: original raw-artifact checksums, preserved without rewriting after analysis.
- `analysis.json`: independent event counts, missing schedule entries and integrity checks. Original manifest and frozen source copies verified successfully.

## Interpretation and next action

The fresh evidence does not support a universal “coder models outperform reasoning models” claim. Thinking-disabled Qwen3 was operationally usable on these four inputs; the coder encountered bounded-output/runtime failures on its two attempted inputs. The incomplete schedule and tiny authored corpus prevent a fair aggregate superiority conclusion.

Preserve this failed/partial run. Before a larger study, test a source-faithful prompt with explicit abstention and scope handling, preregister strict parsing versus salvage as an experimental factor, and obtain independently authored held-out cases. Changes belong to a new version; do not tune this run into a retrospective pass. The separate CCMP action-recovery study has not run and receives no efficacy evidence from this pilot. Agy has not been messaged.
