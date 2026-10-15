# backend/src/api/schemas.py

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from applications.models import Application
from discovery.models import JobPosting
from onboarding.models import JobFilters
from shared.enums import ScreeningOutcome


class CreateSearchRequest(BaseModel):
    profile_id: UUID
    prompt: str
    filters: JobFilters = JobFilters()


class ScreeningOverrideRequest(BaseModel):
    outcome: ScreeningOutcome
    reason: str = ""


class DraftEditRequest(BaseModel):
    subject: Optional[str] = None
    cover_letter: Optional[str] = None
    short_pitch: Optional[str] = None


class NoteRequest(BaseModel):
    note: str = ""


class DraftAllRequest(BaseModel):
    min_fit: float = 0.0


class PrepareRequest(BaseModel):
    autofill: bool = True


class ApplicationView(BaseModel):
    application: Application
    job: JobPosting


class SearchSummary(BaseModel):
    search_id: UUID
    counts: dict[str, int]
    applications: list[ApplicationView]
