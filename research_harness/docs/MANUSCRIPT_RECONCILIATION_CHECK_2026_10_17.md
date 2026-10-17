# Reconciliation check after the ten-point claim audit

2026-10-17. Read the latest Agy update and current drafts. This pass verifies wording changes; no model runs or code changes were needed for these editorial corrections.

## Substantially addressed

Paper 2 now distinguishes PACMI's significant main comparison from its nonsignificant cascade-removal ablation, acknowledges the cited 20-use length sweep, presents amortization as conditional, uses the correct first strict integer savings boundary, separates the full-reset cost model, labels A0 proposed, and calls turn-related failure mechanisms hypotheses. Paper 1's body now labels tiered routing proposed, limits mixed-authority gating, corrects the query denominator to45, identifies synthetic dense vectors, and states thinking-disabled generation is not universally necessary or sufficient. These are meaningful repairs.

## Residual contradictions to fix before closure

1. **Paper 1 abstract, line12:** still says default thinking mode “guarantees JSON truncation” and the corroboration boundary “prevents” unverified extractions from laundering authority. These contradict the repaired body and the observed mixed-authority probe. Replace with a specific observed single-fixture failure and a scoped all-uncorroborated-focus heuristic.
2. **Paper 1 introduction, line21:** still describes PACMI as reporting nonsignificant paired text-QA deltas without distinguishing its significant main comparison. Paper 2's corrected characterization must also appear here. Line30 continues to imply broad laundering prevention.
3. **Paper 1 timing scope:** its abstract attaches 2.38ms/8.22ms to the142-case suite, although those medians come from the45-query ablation. Keep suite and ablation denominators and timing populations separate.
4. **Reproduction claims:** a manuscript disclaimer does not change script behavior. The inspected runner still scores subprocess success via exit codes, can skip Paper2 when its path is absent, and uses hardcoded test-count labels. Default mode verifies contracts/tests/retrieval rather than reproducing all live findings. Either explicitly accept these limits or repair the runner before calling all ten findings fully resolved.

## Verdict

Most targeted body-level edits accepted. The claim that every point is resolved across every document remains too strong: run an abstract/introduction/conclusion consistency pass, not another inference sweep. The empirical readiness boundary is unchanged: partial local pilot and authored regressions do not constitute a completed held-out comparison or CCMP efficacy study.
