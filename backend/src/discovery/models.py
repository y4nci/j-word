# backend/src/discovery/models.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from shared.enums import EmploymentType, SourceName, WorkMode
from shared.text import normalize_key, truncate


class JobPosting(BaseModel):
    """A job posting normalized across sources."""

    id: UUID = Field(default_factory=uuid4)  # internal, not the source's id
    source: SourceName
    external_id: str
    title: str
    company: str
    location: Optional[str] = None
    work_mode: WorkMode = WorkMode.UNKNOWN
    employment_types: list[EmploymentType] = Field(default_factory=list)
    description: str = ""  # plain text
    url: str  # posting page
    apply_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    salary: Optional[str] = None
    language: Optional[str] = None  # "de" / "en"
    tags: list[str] = Field(default_factory=list)
    board_token: Optional[str] = None  # Greenhouse/Lever/Ashby board, used by the autofill submitters
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("title", "company", mode="after")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def dedupe_key(self) -> str:
        """
        Same company + title + city counts as the same job across sources.
        City is the first segment of the location ("Berlin, Berlin" -> "berlin"), because
        companies post the same title in several cities and those are different jobs.
        """
        city = normalize_key((self.location or "").split(",")[0])
        return f"{normalize_key(self.company)}|{normalize_key(self.title)}|{city}"

    def for_prompt(self, max_description_chars: int = 6000) -> str:
        lines = [
            f"Title: {self.title}",
            f"Company: {self.company}",
            f"Location: {self.location or 'n/a'}",
            f"Work mode: {self.work_mode.value}",
            f"Employment: {', '.join(e.value for e in self.employment_types) or 'n/a'}",
        ]
        if self.salary:
            lines.append(f"Salary: {self.salary}")
        if self.tags:
            lines.append(f"Tags: {', '.join(self.tags)}")
        lines.append(f"Description:\n{truncate(self.description, max_description_chars)}")
        return "\n".join(lines)
