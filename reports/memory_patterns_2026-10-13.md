# Observed patterns across Mac and MiniPC memory

Read-only inspection on 2026-10-13. Sources: each host's `~/memories/semantic/facts.json`, project banks, corrective lessons, episodic history metadata, and SQLite aggregates. SQLite aggregates were computed from disposable database/WAL copies; this is a qualitative inspection, not a transactionally synchronized cross-host census or behavioral experiment.

| Stored representation | Mac | MiniPC |
| --- | ---: | ---: |
| Semantic fact keys | 127 | 23 |
| Claim rows, all statuses | 185 | 27 |
| Entities | 393 | 69 |
| Relationships | 241 | 52 |
| Episodic daily Markdown files | 32 | 24 |
| Structured task rows | 1 | 0 |
| Claims with supersession links | 20 | 1 |

These representations overlap; their counts must not be summed as unique memories or interpreted as quality scores.

## Observations and interpretations

1. **Host specialization:** Mac project banks cover global-memory and learning-os plus a demo bank; MiniPC banks cover six AlphaOS/Optimus workstreams. Code deployment parity does not imply memory replication. Inference: the hosts accumulate complementary context, with a risk of context loss when work changes host.
2. **Shared governance vocabulary:** Mac records distinguish operational tests from research validity and reject global agent trust scores. MiniPC records distinguish discovery, qualification, order review, execution authority, and proven fill attribution. Inference: provenance and explicit authority boundaries are recurring design principles across domains.
3. **Corrective feedback becomes policy:** Mac lessons capture prior sizing, compatibility, and attribution mistakes; MiniPC stores a correction against treating platform-assurance warnings as automatic supervised-trade vetoes. Inference: history is being compressed into reusable constraints, although this inspection does not establish that retrieval reliably applies them.
4. **Safety versus inertia:** MiniPC explicitly records the user's preference for bounded supervised progress over perfection, alongside preserved mandatory risk and provenance checks. Mac preferences favor autonomy with evidence and reasonable assumptions. Inference: useful future steering should distinguish hard safety boundaries from unresolved research and optional diagnostics.
5. **Uneven consolidation and stale assertions:** Mac has 20 supersession links and MiniPC one; this is structural evidence of some revision, not a comparable revision-rate metric. Mac still contains a flat `gms.sota.status` assertion of broad parity/supremacy while later project records qualify internal adapters and invalidate overbroad efficacy claims. Treat the old assertion as unsupported by this inspection; it needs reconciliation rather than reuse as current truth.
6. **Narrative-heavy continuity:** Extensive project updates coexist with only one structured task on Mac and none on MiniPC. Several MiniPC briefs remain templates while active-context files carry detailed operational history. Inference: continuity currently depends heavily on reading narrative rather than explicit task state.
7. **Limited graph semantics:** `configured_as` accounts for 166/241 Mac relationships and 20/52 MiniPC relationships. MiniPC also contains extraction-shaped entity names such as `Codex - Session End\\n-`. No duplicate case-insensitive names were found, but that does not establish semantic deduplication. Graph size alone does not demonstrate causal reasoning or novel insight.

## Scope of conclusions

These are emergent patterns in stored content and workflow, not proof of emergent model capability, autonomous learning efficacy, or improved decision outcomes. Project-bank updates are agent-authored reports unless independently verified. No memory records were edited, merged, synchronized, or promoted during this inspection.
