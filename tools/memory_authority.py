"""Canonical authority and provenance validation for GMS context records."""
from __future__ import annotations

from typing import Any

AUTHORITY_LABELS = {
    "user_instruction": "User stated",
    "verified_system_output": "System verified",
    "source_document": "Document extracted",
    "llm_inference": "AI inferred",
    "imported_legacy": "Legacy imported",
}

HUMAN_REVIEW_TYPES = {"decision", "policy"}


def authority_label(authority: str | None) -> str:
    return AUTHORITY_LABELS.get(str(authority or ""), "Unknown authority")


def validate_authority(record: dict[str, Any], authenticated_user: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    authority = record.get("authority")
    provenance = record.get("provenance") or {}
    record_type = record.get("record_type", "fact")
    if authority not in AUTHORITY_LABELS:
        errors.append("authority must be one of the five canonical authority classes")
    author = str(provenance.get("author") or "").strip().lower()
    extractor = str(provenance.get("extractor") or "").strip()
    if author == "mihir" and not authenticated_user:
        errors.append("author=mihir requires an authenticated user action")
    if author and extractor and author == extractor.lower():
        warnings.append("author and extractor are identical; verify they represent distinct roles")
    evidence = record.get("evidence") or []
    verification = str(record.get("verification") or "unverified")
    if authority == "imported_legacy" and verification == "verified" and not evidence:
        errors.append("imported legacy memory cannot be verified without evidence")
    requires_human = authority == "llm_inference" and record_type in HUMAN_REVIEW_TYPES
    if requires_human and (record.get("review") or {}).get("status") == "accepted":
        errors.append("AI-inferred decisions and policies require explicit human review")
    return {
        "valid": not errors,
        "authority": authority,
        "label": authority_label(authority),
        "requires_human_review": requires_human,
        "errors": errors,
        "warnings": warnings,
    }
