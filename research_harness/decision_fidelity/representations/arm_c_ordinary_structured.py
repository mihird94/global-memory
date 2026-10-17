"""
arm_c_ordinary_structured.py — Arm C: Ordinary Structured LLM Memory
====================================================================
Simulates conventional structured agent memory consolidation (e.g. Mem0,
standard GMS/MemGPT KV consolidation).
Extracts high-level key, title, summary, rules, and parameters directly
from raw public source text without:
  - Span-level citation binding
  - Typed constraint verification
  - Entailment gates

Provides:
  1. ArmCOrdinaryStructured: Public baseline consuming PublicSourceInput only.
     Strictly ignores and does not have access to hidden source.constraints or gold labels.
     Can also consume injected raw writer JSON output.
  2. DiagnosticOracleArmC: Separate diagnostic upper bound constructing structured
     records directly from gold constraint annotations (is_diagnostic_oracle=True).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Union
from research_harness.decision_fidelity.models import AuthoritativeSource, DownstreamTask, PublicSourceInput
from research_harness.decision_fidelity.representations.base import BaseMemoryRepresentation


class ArmCOrdinaryStructured(BaseMemoryRepresentation):
    """Arm C: Standard structured key-value memory object derived from public raw text."""

    def __init__(self):
        super().__init__(
            arm_id="Arm_C_Ordinary_Structured",
            description="Conventional structured JSON memory object extracted from raw public text without span citations",
            is_diagnostic_oracle=False,
        )

    def extract_from_public_text(self, pub: PublicSourceInput, raw_writer_json: Optional[str] = None) -> dict[str, Any]:
        """
        Extracts structured memory representation strictly from public source text.
        Under no circumstances reads hidden source.constraints or gold actions.
        """
        if raw_writer_json:
            try:
                parsed = json.loads(raw_writer_json)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        lines = [line.strip() for line in pub.content.splitlines() if line.strip()]
        title = lines[0] if lines else f"Policy {pub.source_id}"

        # Extract sentences as operational rules
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", pub.content) if s.strip()]
        # Standard ungrounded LLM consolidation summarizes key sentences into rule strings
        rules = [s for s in sentences[1:] if len(s) > 10][:4]

        # Extract numeric parameters if apparent
        param_candidates = {}
        for m in re.finditer(r"([A-Za-z0-9_]+)\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)['\"]?", pub.content):
            param_candidates[m.group(1)] = m.group(2)

        record = {
            "key": f"{pub.family_id}_{pub.variant_id}",
            "title": title,
            "source_id": pub.source_id,
            "operational_summary": "; ".join(rules[:2]) if rules else title,
            "extracted_rules": rules,
            "parameters": param_candidates,
            "status": "active",
        }
        return record

    def build_reader_context(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> str:
        pub = self._ensure_public_input(source)
        record = self.extract_from_public_text(pub)
        return (
            f"=== STRUCTURED MEMORY RECORD (Key: {record['key']}) ===\n"
            f"{json.dumps(record, indent=2)}\n"
            f"======================================================="
        )

    def estimate_token_cost(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> dict[str, int]:
        pub = self._ensure_public_input(source)
        record = self.extract_from_public_text(pub)
        record_json = json.dumps(record)
        return {
            "ingestion_tokens": max(1, len(pub.content) // 4) + 150,  # Extraction call overhead
            "memory_carrier_tokens": max(1, len(record_json) // 4),
            "reader_prompt_tokens": max(1, (len(record_json) + len(task.prompt)) // 4),
        }


class DiagnosticOracleArmC(BaseMemoryRepresentation):
    """Diagnostic upper bound: Structured memory constructed from hidden gold constraints."""

    def __init__(self):
        super().__init__(
            arm_id="Arm_C_Diagnostic_Oracle",
            description="Diagnostic upper bound structured memory constructed directly from gold constraints",
            is_diagnostic_oracle=True,
        )

    def synthesize_oracle_record(self, source: AuthoritativeSource) -> dict[str, Any]:
        if not hasattr(source, "constraints"):
            raise ValueError("DiagnosticOracleArmC requires AuthoritativeSource with constraints")
        first_line = source.content.splitlines()[0] if source.content.splitlines() else "Policy"
        summary_statements = [c.statement for c in source.constraints]
        record = {
            "key": f"{source.family_id}_{source.variant_id}",
            "title": first_line.strip(),
            "summary": "; ".join(summary_statements),
            "source_id": source.source_id,
            "status": "active",
        }
        return record

    def build_reader_context(self, source: AuthoritativeSource, task: DownstreamTask) -> str:
        record = self.synthesize_oracle_record(source)
        return (
            f"=== ORACLE STRUCTURED RECORD (DIAGNOSTIC UPPER BOUND: {record['key']}) ===\n"
            f"{json.dumps(record, indent=2)}\n"
            f"=========================================================================="
        )

    def estimate_token_cost(self, source: AuthoritativeSource, task: DownstreamTask) -> dict[str, int]:
        record = self.synthesize_oracle_record(source)
        record_json = json.dumps(record)
        return {
            "ingestion_tokens": max(1, len(source.content) // 4) + 150,
            "memory_carrier_tokens": max(1, len(record_json) // 4),
            "reader_prompt_tokens": max(1, (len(record_json) + len(task.prompt)) // 4),
        }
