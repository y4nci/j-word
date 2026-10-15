# backend/src/onboarding/models.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from shared.enums import EmploymentType, SearchStatus, SourceName, WorkMode


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Experience(BaseModel):
    """
    One job / project / degree. `summary` merges the CV entry with what the
    user wrote about it in the proto-cover-letter; it is the *only* factual
    material the drafting step may use about this experience.
    """

    id: str  # "exp-1", stable within a profile so drafts can cite it
    kind: Literal["job", "project", "education", "volunteering", "other"] = "other"
    title: str
    organization: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    full_name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    links: dict[str, str] = Field(default_factory=dict)  # {"linkedin": "...", "github": "..."}
    headline: str = ""
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)  # ["German (C1)", "English (C2)"]
    experiences: list[Experience] = Field(default_factory=list)

    cv_text: str = ""
    cv_path: Optional[str] = None  # original CV file, attached as-is
    proto_cover_letter: str = ""
    created_at: datetime = Field(default_factory=_now)

    def experience(self, exp_id: str) -> Optional[Experience]:
        return next((e for e in self.experiences if e.id == exp_id), None)

    def compact(self) -> str:
        """Short text form used in screening prompts."""
        lines = [
            f"Headline: {self.headline}",
            f"Location: {self.location or 'n/a'}",
            f"Skills: {', '.join(self.skills)}",
            f"Languages: {', '.join(self.languages) or 'n/a'}",
            "Experiences:",
        ]
        for e in self.experiences:
            when = " - ".join(x for x in (e.start, e.end) if x)
            org = f" @ {e.organization}" if e.organization else ""
            lines.append(f"- [{e.id}] ({e.kind}) {e.title}{org} {when}: {e.summary[:300]}")
        return "\n".join(lines)


class CompanyBoard(BaseModel):
    """A company career page that exposes a public ATS API (Greenhouse / Lever / Ashby)."""

    source: SourceName
    token: str  # board token / site name / org slug, e.g. "n26"
    company_name: Optional[str] = None
    region: Optional[Literal["us", "eu"]] = None  # Lever only


class JobFilters(BaseModel):
    """Hard filters. Empty lists mean 'any'."""

    work_modes: list[WorkMode] = Field(default_factory=list)
    employment_types: list[EmploymentType] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    country: str = "de"  # ISO code used by Adzuna
    radius_km: int = 50
    max_age_days: Optional[int] = 30
    posting_languages: list[str] = Field(default_factory=list)  # ["en", "de"]
    exclude_companies: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    max_results_per_query: int = 50
    sources: list[SourceName] = Field(default_factory=list)  # empty = all configured
    company_boards: list[CompanyBoard] = Field(default_factory=list)


class SearchQuery(BaseModel):
    source: SourceName
    keywords: str
    location: Optional[str] = None
    max_results: int = 50


class SearchPlan(BaseModel):
    refined_goal: str
    target_titles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    screening_criteria: list[str] = Field(default_factory=list)
    queries: list[SearchQuery] = Field(default_factory=list)


class JobSearch(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    profile_id: UUID
    prompt: str
    filters: JobFilters = Field(default_factory=JobFilters)
    plan: Optional[SearchPlan] = None
    status: SearchStatus = SearchStatus.CREATED
    created_at: datetime = Field(default_factory=_now)
