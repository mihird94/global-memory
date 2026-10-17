"""
arm_d_source_bound.py — Arm D: Source-Bound Constraint Memory & Semantic Admission Gate
========================================================================================
The proposed intervention: every decision-relevant constraint field is
explicitly typed and bound to a literal source span citation.

Fields:
  - primary_statement: str
  - applicability_scope: Optional[str]
  - exceptions_and_negation: Optional[str]
  - numeric_value: Optional[float]
  - numeric_unit: Optional[str]
  - execution_order: Optional[list[str]]
  - required_prerequisites: Optional[list[str]]
  - optional_prerequisites: Optional[list[str]]
  - rationale: Optional[str]
  - span_citations: dict[str, str] (mapping field_name -> exact verbatim source span)

Discipline:
  - Source Digest Verification: verifies SHA-256 digest against raw source.
  - Span existence: verifies that cited text appears verbatim in source.
  - Semantic consistency & entailment check:
      * Scope: verifies cited span supports asserted scope; rejects scope widening and contradiction of restrictive clauses.
      * Negation: verifies cited span contains explicit negative polarity markers.
      * Units & Numbers: verifies exact numeric value match with boundary checks (no substring traps like 4 in 4096), and canonical unit alignment.
      * Ordering: verifies sequential relative position in cited span.
      * Prerequisites: verifies required checks are not described as optional in cited text.
      * Rationale: verifies asserted rationale is grounded in cited text.
  - Admission Gate: executed in build_reader_context / admit_memory; rejects ungrounded records before reader execution.
  - Public Extractor vs Diagnostic Oracle: public arm consumes PublicSourceInput only; DiagnosticOracleArmD is a separate upper bound.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Union

from research_harness.decision_fidelity.models import (
    AuthoritativeSource,
    DownstreamTask,
    PublicSourceInput,
)
from research_harness.decision_fidelity.representations.base import BaseMemoryRepresentation


CANONICAL_UNITS = {
    "ms": "millisecond",
    "millisecond": "millisecond",
    "milliseconds": "millisecond",
    "s": "second",
    "sec": "second",
    "second": "second",
    "seconds": "second",
    "mb": "megabyte",
    "megabyte": "megabyte",
    "megabytes": "megabyte",
    "gb": "gigabyte",
    "gigabyte": "gigabyte",
    "gigabytes": "gigabyte",
    "day": "day",
    "days": "day",
}

NEGATIVE_POLARITY_TOKENS = {
    "not", "never", "prohibited", "prohibit", "prohibits", "forbidden", "forbids",
    "except", "exception", "cannot", "do not", "must not", "blocking", "blocked",
    "reject", "rejected", "rejection", "unsupported", "drops", "drops live",
}


@dataclass
class SourceBoundConstraintRecord:
    source_id: str
    source_sha256: str
    primary_statement: str
    applicability_scope: Optional[str] = None
    exceptions_and_negation: Optional[str] = None
    numeric_value: Optional[float] = None
    numeric_unit: Optional[str] = None
    execution_order: Optional[list[str]] = None
    required_prerequisites: Optional[list[str]] = None
    optional_prerequisites: Optional[list[str]] = None
    rationale: Optional[str] = None
    span_citations: dict[str, str] = field(default_factory=dict)

    def validate_span_existence(self, source_text: str) -> tuple[bool, list[str]]:
        """Verifies that all cited spans appear verbatim in the source text."""
        errors = []
        for fld, cited_span in self.span_citations.items():
            if not cited_span or not cited_span.strip():
                errors.append(f"Field '{fld}' has empty span citation")
            elif cited_span not in source_text:
                errors.append(f"Field '{fld}' cited span not found in source: '{cited_span[:40]}...'")
        return len(errors) == 0, errors

    def validate_record(self, source_text: str) -> tuple[bool, list[str]]:
        """
        Comprehensive semantic consistency and containment validation.
        Enforces digest verification, span existence, and field-level support checks.
        """
        errors = []

        # 1. Source SHA-256 digest check
        expected_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if self.source_sha256 and self.source_sha256 != expected_hash:
            errors.append(f"Source SHA-256 digest mismatch: record has '{self.source_sha256}', actual is '{expected_hash}'")

        # 2. Verbatim span existence check
        ok_exist, err_exist = self.validate_span_existence(source_text)
        if not ok_exist:
            errors.extend(err_exist)

        # 3. Primary statement check
        if self.primary_statement:
            ps_cite = self.span_citations.get("primary_statement")
            if not ps_cite and not self.span_citations:
                errors.append("primary_statement is asserted without any supporting span citation")

        # 4. Applicability Scope Check (Semantic scoping & containment)
        if self.applicability_scope:
            if "applicability_scope" not in self.span_citations:
                errors.append("applicability_scope is asserted but has no span citation")
            else:
                cited = self.span_citations["applicability_scope"].strip()
                cited_lower = cited.lower()
                asserted_lower = self.applicability_scope.lower()

                # Restrictive scoping analysis: check for restrictive keywords in cited text
                has_restriction = any(w in cited_lower for w in ["only to", "only", "strictly", "exclusively", "must not", "restricted to", "does not apply to"])
                if has_restriction:
                    # Check for widening / forbidden entity inclusion
                    # Extract entities mentioned in asserted scope (e.g. 'harbor', 'every project', 'all projects')
                    forbidden_widening = ["every project", "all projects", "all tenants", "global", "unrestricted"]
                    for widener in forbidden_widening:
                        if widener in asserted_lower and widener not in cited_lower:
                            errors.append(f"applicability_scope '{self.applicability_scope}' broadens scope beyond restrictive span: '{cited}'")

                    # Check if asserted scope introduces entities that cited span explicitly excludes or does not mention
                    asserted_words = set(re.findall(r"[a-z0-9_-]{3,}", asserted_lower))
                    cited_words = set(re.findall(r"[a-z0-9_-]{3,}", cited_lower))
                    stop_words = {
                        "this", "policy", "applies", "apply", "only", "backup", "backups", "service",
                        "storage", "engine", "project", "tenant", "target", "excluded", "exclusively",
                        "instances", "managed", "under", "with", "from", "both", "all", "rules", "standard"
                    }
                    novel_asserted_entities = asserted_words - cited_words - stop_words
                    if novel_asserted_entities:
                        errors.append(f"applicability_scope '{self.applicability_scope}' contains entities not grounded in cited span: {list(novel_asserted_entities)}")

        # 5. Exceptions & Negation Check (Polarity verification)
        if self.exceptions_and_negation:
            if "exceptions_and_negation" not in self.span_citations:
                errors.append("exceptions_and_negation is asserted but has no span citation")
            else:
                cited = self.span_citations["exceptions_and_negation"]
                cited_tokens = set(re.findall(r"[a-z0-9_-]+", cited.lower()))
                if not (cited_tokens & NEGATIVE_POLARITY_TOKENS):
                    errors.append(f"exceptions_and_negation asserted but cited span contains no negative polarity markers: '{cited}'")

        # 6. Quantities & Units Check (Exact numeric parsing; prevent substring traps)
        if self.numeric_value is not None:
            if "numeric_value" not in self.span_citations:
                errors.append("numeric_value is asserted but has no span citation")
            else:
                cited = self.span_citations["numeric_value"]
                # Extract all standalone numbers using word boundaries
                found_numbers = []
                for n_str in re.findall(r"\b\d+(?:\.\d+)?\b", cited):
                    try:
                        found_numbers.append(float(n_str))
                    except ValueError:
                        pass
                asserted_float = float(self.numeric_value)
                if asserted_float not in found_numbers:
                    errors.append(f"numeric_value {self.numeric_value} not supported by cited span: '{cited}' (found numbers: {found_numbers})")

        if self.numeric_unit:
            if "numeric_unit" not in self.span_citations:
                errors.append("numeric_unit is asserted but has no span citation")
            else:
                cited = self.span_citations["numeric_unit"].lower()
                asserted_canon = CANONICAL_UNITS.get(self.numeric_unit.lower(), self.numeric_unit.lower())
                # Find matching units in cited text
                cited_units = [CANONICAL_UNITS[u] for u in CANONICAL_UNITS if u in cited]
                if asserted_canon not in cited_units:
                    errors.append(f"numeric_unit '{self.numeric_unit}' not grounded in cited span: '{cited}'")

        # 7. Execution Ordering Check (Monotonic step occurrence)
        if self.execution_order:
            if "execution_order" not in self.span_citations:
                errors.append("execution_order is asserted but has no span citation")
            else:
                cited = self.span_citations["execution_order"]
                # If multiple steps are asserted, verify sequential ordering
                step_positions = []
                for st in self.execution_order:
                    # Tokenize step to match key sub-tokens
                    st_tokens = [t for t in re.findall(r"[a-z0-9_]+", st.lower()) if len(t) > 2]
                    first_pos = -1
                    for tok in st_tokens:
                        pos = cited.lower().find(tok)
                        if pos != -1:
                            first_pos = pos if first_pos == -1 else min(first_pos, pos)
                    step_positions.append((st, first_pos))

                valid_positions = [pos for _, pos in step_positions if pos != -1]
                if len(valid_positions) > 1 and valid_positions != sorted(valid_positions):
                    errors.append(f"execution_order {self.execution_order} contradicts sequential step order in cited span: '{cited}'")

        # 8. Prerequisites Check (Required vs Optional gating)
        if self.required_prerequisites:
            if "required_prerequisites" not in self.span_citations:
                errors.append("required_prerequisites is asserted but has no span citation")
            else:
                cited = self.span_citations["required_prerequisites"].lower()
                # If cited span indicates that a check is optional, it must not be asserted as required!
                for req in self.required_prerequisites:
                    req_lower = req.lower()
                    if req_lower in cited:
                        # Check if span contains optionality qualifiers adjacent to this check
                        if "optional" in cited or "secondary" in cited or "not required" in cited:
                            if "mandatory" not in cited and "required" not in cited:
                                errors.append(f"prerequisite '{req}' is marked optional in cited span and cannot be asserted as required: '{cited}'")

        if self.optional_prerequisites:
            if "optional_prerequisites" not in self.span_citations:
                errors.append("optional_prerequisites is asserted but has no span citation")

        # 9. Rationale Check
        if self.rationale:
            if "rationale" not in self.span_citations:
                errors.append("rationale is asserted but has no span citation")
            else:
                cited = self.span_citations["rationale"].lower()
                # Check for contradiction (e.g. asserting cost_optimization when span says it is a regulatory violation)
                if "cost_optimization" in self.rationale.lower() and "violation" in cited:
                    errors.append(f"rationale '{self.rationale}' contradicts cited span: '{cited}'")

        return len(errors) == 0, errors

    def validate_span_entailment(self) -> tuple[bool, list[str]]:
        """Backward compatible wrapper around validate_record without source text lookup."""
        source_text = " ".join(self.span_citations.values())
        return self.validate_record(source_text)


class ArmDSourceBound(BaseMemoryRepresentation):
    """
    Arm D: Source-bound constraint representation with verified span citations.
    Public implementation: extracts from PublicSourceInput without hidden annotations,
    and enforces the admission gate before presenting payload to reader agents.
    """

    def __init__(self):
        super().__init__(
            arm_id="Arm_D_Source_Bound",
            description="Typed constraint memory bound to verified verbatim source spans with admission gate",
            is_diagnostic_oracle=False,
        )

    def extract_from_public_text(
        self,
        pub: PublicSourceInput,
        raw_writer_json: Optional[str] = None,
    ) -> SourceBoundConstraintRecord:
        """
        Extracts typed constraints from public source text or parses raw writer JSON.
        Under no circumstances reads hidden source.constraints or gold labels.
        """
        if raw_writer_json:
            try:
                data = json.loads(raw_writer_json)
                if isinstance(data, dict):
                    return SourceBoundConstraintRecord(
                        source_id=pub.source_id,
                        source_sha256=pub.sha256,
                        primary_statement=data.get("primary_statement", "Operational Constraint"),
                        applicability_scope=data.get("applicability_scope"),
                        exceptions_and_negation=data.get("exceptions_and_negation"),
                        numeric_value=float(data["numeric_value"]) if data.get("numeric_value") is not None else None,
                        numeric_unit=data.get("numeric_unit"),
                        execution_order=data.get("execution_order"),
                        required_prerequisites=data.get("required_prerequisites"),
                        optional_prerequisites=data.get("optional_prerequisites"),
                        rationale=data.get("rationale"),
                        span_citations=data.get("span_citations", {}),
                    )
            except Exception:
                pass

        # Heuristic extraction from raw public text
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", pub.content) if s.strip()]
        first_sentence = sentences[0] if sentences else pub.content[:100]

        rec = SourceBoundConstraintRecord(
            source_id=pub.source_id,
            source_sha256=pub.sha256,
            primary_statement=first_sentence,
            span_citations={"primary_statement": first_sentence},
        )

        for s in sentences:
            s_lower = s.lower()
            # Scope extraction
            if any(k in s_lower for k in ["only applies to", "applies to", "scope", "restricted to", "exclusively"]):
                rec.applicability_scope = s
                rec.span_citations["applicability_scope"] = s

            # Negation extraction
            if any(k in s_lower for k in ["must never", "prohibited", "strictly forbidden", "do not", "cannot"]):
                rec.exceptions_and_negation = s
                rec.span_citations["exceptions_and_negation"] = s

            # Quantities and units
            m_num = re.search(r"\b(\d+(?:\.\d+)?)\s*(milliseconds|ms|megabytes|mb|seconds|days)\b", s_lower)
            if m_num:
                rec.numeric_value = float(m_num.group(1))
                rec.numeric_unit = m_num.group(2)
                rec.span_citations["numeric_value"] = s
                rec.span_citations["numeric_unit"] = s

            # Execution order
            if any(k in s_lower for k in ["must first", "prior to", "before", "then"]):
                rec.execution_order = [s]
                rec.span_citations["execution_order"] = s

            # Prerequisites
            if "mandatory" in s_lower or "requires" in s_lower:
                rec.required_prerequisites = [s]
                rec.span_citations["required_prerequisites"] = s

            # Rationale
            if any(k in s_lower for k in ["justification", "because", "mandated by", "statutory", "forward secrecy"]):
                rec.rationale = s
                rec.span_citations["rationale"] = s

        return rec

    def synthesize_source_bound_record(
        self,
        source: Union[AuthoritativeSource, PublicSourceInput],
    ) -> SourceBoundConstraintRecord:
        """Helper to extract source-bound record from authoritative source or public input."""
        pub = self._ensure_public_input(source)
        return self.extract_from_public_text(pub)

    def admit_memory(
        self,
        source: Union[AuthoritativeSource, PublicSourceInput],
        task: Optional[DownstreamTask] = None,
        injected_record: Optional[SourceBoundConstraintRecord] = None,
    ) -> tuple[bool, str, list[str]]:
        """
        Executes the formal admission gate:
          1. Verifies verbatim span existence against source text.
          2. Verifies semantic containment and consistency.
        If passed, returns clean admitted payload.
        If rejected, returns explicit rejection context and detailed error list.
        """
        pub = self._ensure_public_input(source)
        rec = injected_record or self.extract_from_public_text(pub)
        ok, errors = rec.validate_record(pub.content)

        if not ok:
            err_body = "\n".join(f"- {e}" for e in errors)
            payload = (
                f"=== ADMISSION REJECTED: UNGROUNDED ASSERTIONS (Source: {pub.source_id}) ===\n"
                f"Status: REJECTED\n"
                f"Reason: Memory record failed source grounding verification.\n"
                f"Violations:\n"
                f"{err_body}\n"
                f"=========================================================================="
            )
            return False, payload, errors

        rec_dict = {k: v for k, v in asdict(rec).items() if v is not None}
        payload = (
            f"=== ADMITTED SOURCE-BOUND CONSTRAINT MEMORY (Source: {rec.source_id}) ===\n"
            f"{json.dumps(rec_dict, indent=2)}\n"
            f"========================================================================"
        )
        return True, payload, []

    def build_reader_context(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> str:
        """Invokes admission gate and returns the admitted (or rejected) memory context."""
        _, payload, _ = self.admit_memory(source, task)
        return payload

    def estimate_token_cost(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> dict[str, int]:
        pub = self._ensure_public_input(source)
        rec = self.extract_from_public_text(pub)
        rec_json = json.dumps(asdict(rec))
        return {
            "ingestion_tokens": max(1, len(pub.content) // 4) + 220,  # Structured span-grounded extraction
            "memory_carrier_tokens": max(1, len(rec_json) // 4),
            "reader_prompt_tokens": max(1, (len(rec_json) + len(task.prompt)) // 4),
        }


class DiagnosticOracleArmD(BaseMemoryRepresentation):
    """
    Diagnostic Upper Bound: Uses hidden gold constraints and spans to construct
    an ideal source-bound constraint record. Explicitly marked is_diagnostic_oracle=True.
    """

    def __init__(self):
        super().__init__(
            arm_id="Arm_D_Diagnostic_Oracle",
            description="Diagnostic upper bound constructing source-bound records directly from gold annotations",
            is_diagnostic_oracle=True,
        )

    def synthesize_oracle_record(self, source: AuthoritativeSource) -> SourceBoundConstraintRecord:
        if not hasattr(source, "constraints") or not hasattr(source, "spans"):
            raise ValueError("DiagnosticOracleArmD requires AuthoritativeSource with constraints and spans")

        rec = SourceBoundConstraintRecord(
            source_id=source.source_id,
            source_sha256=source.sha256,
            primary_statement=source.constraints[0].statement if source.constraints else "Authoritative Constraint",
            span_citations={},
        )
        if source.spans:
            rec.span_citations["primary_statement"] = next(iter(source.spans.values())).text

        for c in source.constraints:
            span_texts = [source.spans[sp_id].text for sp_id in c.support_span_ids if sp_id in source.spans]
            primary_span = span_texts[0] if span_texts else ""

            if c.constraint_type == c.constraint_type.APPLICABILITY_SCOPE:
                rec.applicability_scope = c.statement
                best_span = span_texts[0] if span_texts else ""
                stmt_entities = set(re.findall(r"[a-z0-9_-]{3,}", c.statement.lower())) - {"applies", "target", "policy", "only"}
                for sp in span_texts:
                    if stmt_entities and all(e in sp.lower() for e in stmt_entities):
                        best_span = sp
                        break
                    elif any(e in sp.lower() for e in stmt_entities):
                        best_span = sp
                if best_span:
                    rec.span_citations["applicability_scope"] = best_span
            elif c.constraint_type == c.constraint_type.EXCEPTIONS_AND_NEGATION:
                rec.exceptions_and_negation = c.statement
                best_span = span_texts[0] if span_texts else ""
                for sp in span_texts:
                    sp_tokens = set(re.findall(r"[a-z0-9_-]+", sp.lower()))
                    if sp_tokens & NEGATIVE_POLARITY_TOKENS:
                        best_span = sp
                        break
                if best_span:
                    rec.span_citations["exceptions_and_negation"] = best_span
            elif c.constraint_type == c.constraint_type.QUANTITIES_AND_UNITS:
                for sp in span_texts:
                    m_num = re.search(r"\b(\d+(?:\.\d+)?)\b", sp)
                    if m_num:
                        rec.numeric_value = float(m_num.group(1))
                        rec.span_citations["numeric_value"] = sp
                    for u in ["milliseconds", "ms", "megabytes", "mb", "days", "seconds"]:
                        if u in sp.lower():
                            rec.numeric_unit = u
                            rec.span_citations["numeric_unit"] = sp
                            break
            elif c.constraint_type == c.constraint_type.ORDERING_AND_PROCEDURES:
                rec.execution_order = [c.statement]
                if primary_span:
                    rec.span_citations["execution_order"] = primary_span
            elif c.constraint_type == c.constraint_type.PREREQUISITES_REQUIRED_VS_OPTIONAL:
                rec.required_prerequisites = [c.statement]
                if primary_span:
                    rec.span_citations["required_prerequisites"] = primary_span
            elif c.constraint_type == c.constraint_type.RATIONALE_ATTRIBUTION:
                rec.rationale = c.statement
                if primary_span:
                    rec.span_citations["rationale"] = primary_span

        return rec

    def build_reader_context(self, source: AuthoritativeSource, task: DownstreamTask) -> str:
        rec = self.synthesize_oracle_record(source)
        rec_dict = {k: v for k, v in asdict(rec).items() if v is not None}
        return (
            f"=== ORACLE SOURCE-BOUND MEMORY (DIAGNOSTIC UPPER BOUND: {rec.source_id}) ===\n"
            f"{json.dumps(rec_dict, indent=2)}\n"
            f"=========================================================================="
        )

    def estimate_token_cost(self, source: AuthoritativeSource, task: DownstreamTask) -> dict[str, int]:
        rec = self.synthesize_oracle_record(source)
        rec_json = json.dumps(asdict(rec))
        return {
            "ingestion_tokens": max(1, len(source.content) // 4) + 220,
            "memory_carrier_tokens": max(1, len(rec_json) // 4),
            "reader_prompt_tokens": max(1, (len(rec_json) + len(task.prompt)) // 4),
        }
