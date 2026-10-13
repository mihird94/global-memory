"""Cross-Agent Task Continuation and Resumption benchmark adapter.

Evaluates realistic multi-agent software engineering handoffs across real projects:
1. Reconstructing project purpose, current truth, binding decisions, and constraints from a bounded bundle.
2. Identifying the correct next action without rereading the full repository or conversation history.
3. Preventing cross-project context and collision leakage.
4. Measuring token compression ratio against the raw project memory bank.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContinuationTestCase:
    id: str
    project: str
    target_format: str = "antigravity"
    expected_goal_keywords: tuple[str, ...] = ()
    expected_constraints: tuple[str, ...] = ()
    expected_decisions: tuple[str, ...] = ()
    expected_next_action_keywords: tuple[str, ...] = ()
    prohibited_leakage_keywords: tuple[str, ...] = ()
    min_compression_ratio: float = 3.0
    description: str = ""


CONTINUATION_CASES: list[ContinuationTestCase] = [
    ContinuationTestCase(
        id="cont_global_memory_resume",
        project="global-memory",
        target_format="antigravity",
        expected_goal_keywords=("unified", "memory", "coordination"),
        expected_constraints=("offline-first", "zero daytime model loading", "do not commit"),
        expected_decisions=("retired global agent trust", "wal mode", "contestable curation"),
        expected_next_action_keywords=("verification", "task", "eval"),
        prohibited_leakage_keywords=("alphaos.swing.plugin.version", "robinhood"),
        min_compression_ratio=3.5,
        description="Fresh agent resuming Global Memory / Brain project without AlphaOS collision leakage.",
    ),
    ContinuationTestCase(
        id="cont_learning_os_resume",
        project="learning-os",
        target_format="codex",
        expected_goal_keywords=("learning", "tutor", "concept"),
        expected_constraints=("local", "convention", "privacy"),
        expected_decisions=("llm-cascade-adapter", "memorygateway", "friction"),
        expected_next_action_keywords=("pomodoro", "quiz", "code playground", "backlog", "unavailable"),
        prohibited_leakage_keywords=("alphaos.swing",),
        min_compression_ratio=2.0,
        description="Fresh agent resuming Learning OS personal tutor loop with privacy constraints.",
    ),
]
