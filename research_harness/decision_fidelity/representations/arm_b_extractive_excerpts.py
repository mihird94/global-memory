"""
arm_b_extractive_excerpts.py — Arm B: Extractive Source Excerpts
================================================================
Implements an extractive compression baseline:
  1. Main Implementable Baseline: Sentence-level BM25/lexical ranker matching
     public task keywords against source sentences without hidden labels.
     Supports both task-conditioned retrieval (default) and task-agnostic top-sentence mode.
  2. Diagnostic Upper Bound: Oracle span extractor using gold support spans
     (explicitly labeled as Arm_B_Diagnostic_Oracle with is_diagnostic_oracle=True).
"""

from __future__ import annotations

import math
import re
from typing import Union
from research_harness.decision_fidelity.models import AuthoritativeSource, DownstreamTask, PublicSourceInput
from research_harness.decision_fidelity.representations.base import BaseMemoryRepresentation


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", text) if len(t) > 1]


def _rank_sentences_bm25(sentences: list[str], query: str, top_k: int = 2) -> list[str]:
    """Deterministic BM25 ranker over candidate sentences."""
    if not sentences:
        return []
    if len(sentences) <= top_k:
        return sentences

    q_tokens = _tokenize(query)
    doc_tokens = [_tokenize(s) for s in sentences]
    n_docs = len(sentences)
    avg_dl = sum(len(dt) for dt in doc_tokens) / max(1, n_docs)
    k1 = 1.5
    b = 0.75

    scores = []
    for idx, dt in enumerate(doc_tokens):
        score = 0.0
        dl = len(dt)
        dt_counts = {t: dt.count(t) for t in set(dt)}
        for qt in q_tokens:
            df = sum(1 for d in doc_tokens if qt in d)
            if df == 0:
                continue
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            tf = dt_counts.get(qt, 0)
            numerator = tf * (k1 + 1.0)
            denominator = tf + k1 * (1.0 - b + b * (dl / avg_dl))
            score += idf * (numerator / max(1e-6, denominator))
        scores.append((score, idx))

    scores.sort(key=lambda x: x[0], reverse=True)
    selected_indices = sorted([idx for _, idx in scores[:top_k]])
    return [sentences[i] for i in selected_indices]


class ArmBExtractiveExcerpts(BaseMemoryRepresentation):
    """Arm B: Implementable extractive sentence-ranking baseline."""

    def __init__(self, top_k: int = 2, task_conditioned: bool = True):
        super().__init__(
            arm_id="Arm_B_Extractive_Excerpts",
            description=f"Deterministic BM25 top-{top_k} sentence extraction (task_conditioned={task_conditioned})",
        )
        self.top_k = top_k
        self.task_conditioned = task_conditioned

    def build_reader_context(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> str:
        pub = self._ensure_public_input(source)
        # Split source into sentences
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", pub.content) if s.strip()]
        if self.task_conditioned and task and task.prompt:
            selected = _rank_sentences_bm25(sentences, task.prompt, top_k=self.top_k)
        else:
            selected = sentences[:self.top_k]

        excerpts_body = "\n".join(f"- {s}" for s in selected)
        return (
            f"=== EXTRACTIVE SOURCE EXCERPTS (Source: {pub.source_id}) ===\n"
            f"{excerpts_body}\n"
            f"=============================================================="
        )

    def estimate_token_cost(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> dict[str, int]:
        pub = self._ensure_public_input(source)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", pub.content) if s.strip()]
        if self.task_conditioned and task and task.prompt:
            selected = _rank_sentences_bm25(sentences, task.prompt, top_k=self.top_k)
        else:
            selected = sentences[:self.top_k]
        excerpts_text = " ".join(selected)
        return {
            "ingestion_tokens": max(1, len(pub.content) // 4),  # One pass over source
            "memory_carrier_tokens": max(1, len(excerpts_text) // 4),
            "reader_prompt_tokens": max(1, (len(excerpts_text) + len(task.prompt)) // 4),
        }


class ArmBOracleDiagnostic(BaseMemoryRepresentation):
    """Diagnostic upper bound: Extractor using hidden gold support spans."""

    def __init__(self):
        super().__init__(
            arm_id="Arm_B_Diagnostic_Oracle",
            description="Diagnostic upper bound extracting exact gold support spans",
            is_diagnostic_oracle=True,
        )

    def build_reader_context(self, source: AuthoritativeSource, task: DownstreamTask) -> str:
        # Diagnostic upper bound explicitly requires full AuthoritativeSource with spans
        if not hasattr(source, "spans"):
            raise ValueError("Diagnostic oracle requires AuthoritativeSource with spans")
        gold_spans = [span.text for span in source.spans.values()]
        body = "\n".join(f"- {s}" for s in gold_spans)
        return (
            f"=== ORACLE SOURCE EXCERPTS (DIAGNOSTIC UPPER BOUND: {source.source_id}) ===\n"
            f"{body}\n"
            f"=========================================================================="
        )

    def estimate_token_cost(self, source: AuthoritativeSource, task: DownstreamTask) -> dict[str, int]:
        gold_spans = [span.text for span in source.spans.values()]
        body = " ".join(gold_spans)
        return {
            "ingestion_tokens": max(1, len(source.content) // 4),
            "memory_carrier_tokens": max(1, len(body) // 4),
            "reader_prompt_tokens": max(1, (len(body) + len(task.prompt)) // 4),
        }
