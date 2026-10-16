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
# These sources already filter server-side by location + radius and by publication age.
# Their location strings aren't comparable, and their posting dates can be the *first*
# publication of a reposted job, so neither is re-checked locally.
_SERVER_FILTERED_SOURCES = {SourceName.BUNDESAGENTUR, SourceName.ADZUNA}
# Company boards list only open jobs, but their dates can be years old for evergreen roles.
_NO_AGE_CHECK = _SERVER_FILTERED_SOURCES | {
    SourceName.GREENHOUSE, SourceName.LEVER, SourceName.ASHBY, SourceName.PERSONIO, SourceName.SMARTRECRUITERS,
}


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

    if filters.max_age_days and job.posted_at and job.source not in _NO_AGE_CHECK:
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
        and job.source not in _SERVER_FILTERED_SOURCES
    ):
        return f"location {job.location!r} not in {filters.locations}"

    return None


def matches_keywords(job: JobPosting, keywords: str) -> bool:
    """
    Local keyword gate for sources without server-side search. A posting matches when
    every keyword word appears in its title/tags, or when every word appears somewhere
    in the posting and at least one is in the title. Words match by shared stem, so
    "engineering" ~ "engineer" and "werkstudent" ~ "werkstudentin".
    """
    wanted = set(tokens(keywords))
    if not wanted:
        return True
    title = set(tokens(job.title)) | set(tokens(" ".join(job.tags)))
    if all(_has(word, title) for word in wanted):
        return True
    everything = title | set(tokens(job.description))
    return any(_has(word, title) for word in wanted) and all(_has(word, everything) for word in wanted)


def _has(word: str, vocabulary: set[str]) -> bool:
    if word in vocabulary:
        return True
    if len(word) < 4:  # short words ("ai", "ml", "c++") must match exactly
        return False
    return any(len(v) >= 4 and (v.startswith(word) or word.startswith(v)) for v in vocabulary)


def _location_matches(location: str, wanted: list[str]) -> bool:
    loc = normalize_key(location)
    return any(normalize_key(w) in loc for w in wanted if normalize_key(w))
