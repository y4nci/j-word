# backend/src/discovery/filters.py
"""
Deterministic hard filters (the equivalent of autoreview's METADATA screening gate).

Only *clear* violations are filtered out. Unknown values (e.g. a posting that
doesn't say whether it's remote) pass, and the LLM screening step judges them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from discovery.models import JobPosting
from onboarding.models import JobFilters
from shared.enums import EmploymentType, SourceName, WorkMode
from shared.text import normalize_key, tokens

# Part-time-compatible types: asking for part time should not drop Werkstudent roles.
_PART_TIME_LIKE = {EmploymentType.PART_TIME, EmploymentType.WORKING_STUDENT, EmploymentType.INTERNSHIP}
# These sources already searched by location + radius; their location strings are not comparable.
_LOCATION_SEARCH_SOURCES = {SourceName.BUNDESAGENTUR, SourceName.ADZUNA}


def hard_filter(job: JobPosting, filters: JobFilters, *, now: Optional[datetime] = None) -> Optional[str]:
    """Return a human-readable reason if the job violates a filter, else None."""
    now = now or datetime.now(timezone.utc)

    if filters.work_modes and job.work_mode != WorkMode.UNKNOWN and job.work_mode not in filters.work_modes:
        return f"work mode is {job.work_mode.value}"

    if filters.employment_types and job.employment_types:
        wanted = set(filters.employment_types)
        if EmploymentType.PART_TIME in wanted:
            wanted |= _PART_TIME_LIKE
        if not wanted & set(job.employment_types):
            return f"employment type is {', '.join(e.value for e in job.employment_types)}"

    if filters.max_age_days and job.posted_at:
        posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
        if now - posted > timedelta(days=filters.max_age_days):
            return f"posted {(now - posted).days} days ago"

    if filters.posting_languages and job.language and job.language not in filters.posting_languages:
        return f"posting language is {job.language}"

    company_key = normalize_key(job.company)
    for excluded in filters.exclude_companies:
        if normalize_key(excluded) and normalize_key(excluded) in company_key:
            return f"company {job.company!r} is excluded"

    title_tokens = set(tokens(job.title))
    for keyword in filters.exclude_keywords:
        kw_tokens = tokens(keyword)
        if kw_tokens and set(kw_tokens) <= title_tokens:
            return f"title contains excluded keyword {keyword!r}"

    if (
        filters.locations
        and job.work_mode != WorkMode.REMOTE
        and job.location
        and not _location_matches(job.location, filters.locations)
        and job.source not in _LOCATION_SEARCH_SOURCES
    ):
        return f"location {job.location!r} not in {filters.locations}"

    return None


def matches_keywords(job: JobPosting, keywords: str) -> bool:
    """Local keyword gate for sources without server-side search: all words must appear in title/tags."""
    wanted = set(tokens(keywords))
    if not wanted:
        return True
    haystack = set(tokens(job.title)) | set(tokens(" ".join(job.tags)))
    return wanted <= haystack


def _location_matches(location: str, wanted: list[str]) -> bool:
    loc = normalize_key(location)
    return any(normalize_key(w) in loc for w in wanted if normalize_key(w))
