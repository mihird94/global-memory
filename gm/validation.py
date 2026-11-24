"""Input checks shared by Brain's MCP, CLI, and desktop entry points."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

FACT_HEADLINE_THRESHOLD = 400
HEADLINE_REQUIRED = (
    f"Add a one-line headline for this fact. A headline is required above {FACT_HEADLINE_THRESHOLD} characters."
)
VALID_KINDS = ("profile", "project", "decision", "lesson", "fact", "journal", "episode")
WRITABLE_KINDS = tuple(kind for kind in VALID_KINDS if kind != "profile")
VALID_EPISTEMIC = ("", "verified", "decision", "lesson", "hypothesis")


def validation_message(error: ValidationError) -> str:
    return " ".join(item["msg"] for item in error.errors(include_input=False, include_url=False))


def needs_headline(error: ValidationError) -> bool:
    return any(item["type"] == "fact_headline_required" for item in error.errors(include_input=False))


class HeadlineAnswer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)

    headline: str = Field(min_length=1, description="One line that states the main verified fact.")


def normalize_project_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:48].strip("-")


class MemoryDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)

    content: str
    kind: str = "fact"
    title: str = ""
    project: str = ""
    headline: str = ""
    subject: str = ""
    predicate: str = ""
    source: str = ""
    epistemic: str = ""
    author: str = ""

    @field_validator("content")
    @classmethod
    def check_content(cls, value: str) -> str:
        if not value:
            raise PydanticCustomError("empty_memory", "Add the verified fact, decision, lesson, or milestone to content.")
        return value

    @field_validator("kind")
    @classmethod
    def check_kind(cls, value: str) -> str:
        kind = value.lower()
        if kind not in WRITABLE_KINDS:
            raise PydanticCustomError("memory_kind", "Choose kind fact, decision, lesson, project, journal, or episode.")
        return kind

    @field_validator("title", "headline", "subject", "predicate", "source", "author")
    @classmethod
    def single_line(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("project")
    @classmethod
    def check_project(cls, value: str) -> str:
        return normalize_project_slug(value) if value.strip() else ""

    @field_validator("epistemic")
    @classmethod
    def check_epistemic(cls, value: str) -> str:
        val = value.lower().strip()
        if val not in VALID_EPISTEMIC:
            raise PydanticCustomError("memory_epistemic", "Choose epistemic verified, decision, lesson, or hypothesis.")
        return val

    @model_validator(mode="after")
    def check_kind_and_headline(self) -> MemoryDraft:
        if (self.subject or self.predicate) and self.kind != "fact":
            raise PydanticCustomError("fact_identity_kind", "Use kind='fact' for a subject and predicate.")
        if bool(self.subject) != bool(self.predicate):
            raise PydanticCustomError("fact_identity_pair", "Provide both subject and predicate to identify a mutable fact.")
        if self.kind == "project" and not (self.project or self.title):
            raise PydanticCustomError("project_name_required", "Provide a project name in project or title.")
        if self.kind in ("fact", "decision", "lesson", "project") and (
            self.epistemic == "hypothesis"
            or re.match(r"^(?:#{1,6}[^\n]*\n\s*)?(?:#{1,6}[ \t]+)?\[hypothesis\]", self.content, re.IGNORECASE)
        ):
            raise PydanticCustomError(
                "unverified_memory", "Save a worthwhile hypothesis as kind='episode' and keep the [hypothesis] prefix."
            )
        if self.kind == "fact" and len(self.content) > FACT_HEADLINE_THRESHOLD and not self.headline:
            raise PydanticCustomError("fact_headline_required", HEADLINE_REQUIRED)
        return self


class SearchFilters(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)

    kind: str = ""
    bucket: str = ""
    project: str = ""
    since: str = ""
    until: str = ""

    @field_validator("kind")
    @classmethod
    def check_kind(cls, value: str) -> str:
        kind = value.lower()
        if kind and kind not in VALID_KINDS:
            raise PydanticCustomError("search_kind", "Choose kind fact, decision, lesson, project, profile, journal, or episode.")
        return kind

    @field_validator("bucket")
    @classmethod
    def check_bucket(cls, value: str) -> str:
        bucket = value.lower()
        if bucket not in ("", "fact", "episode"):
            raise PydanticCustomError("search_bucket", "Choose bucket='fact' for durable knowledge or bucket='episode' for journal entries.")
        return bucket

    @field_validator("project")
    @classmethod
    def check_project(cls, value: str) -> str:
        return normalize_project_slug(value) if value.strip() else ""

    @field_validator("since", "until")
    @classmethod
    def check_date(cls, value: str) -> str:
        if not value:
            return value
        try:
            if date.fromisoformat(value).isoformat() == value:
                return value
        except ValueError:
            pass
        raise PydanticCustomError("search_date", "Use YYYY-MM-DD for since and until.")

    @model_validator(mode="after")
    def check_filters(self) -> SearchFilters:
        if self.since and self.until and self.since > self.until:
            raise PydanticCustomError("search_date_range", "Set since on or before until.")
        expected = "episode" if self.kind in ("journal", "episode") else "fact"
        if self.kind and self.bucket and self.bucket != expected:
            raise PydanticCustomError("search_scope", "Use bucket='{bucket}' with kind='{kind}'.", {"bucket": expected, "kind": self.kind})
        return self


class SearchRequest(SearchFilters):
    query: str
    limit: int = 8

    @field_validator("query")
    @classmethod
    def check_query(cls, value: str) -> str:
        if not value:
            raise PydanticCustomError("search_query", "Enter a search query with a topic, symbol, or error code.")
        return value

    @field_validator("limit")
    @classmethod
    def check_limit(cls, value: int) -> int:
        if value < 1:
            raise PydanticCustomError("search_limit", "Set limit to a positive whole number.")
        return value
