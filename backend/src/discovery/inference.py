# backend/src/discovery/inference.py
"""Heuristics for fields that sources don't report in a structured way."""

from __future__ import annotations

import re

from shared.enums import EmploymentType, WorkMode

_REMOTE_RE = re.compile(r"\b(remote|fully remote|100\s?% remote|work from home|homeoffice|home office|mobiles arbeiten)\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)

_EMPLOYMENT_PATTERNS = [
    (EmploymentType.WORKING_STUDENT, re.compile(r"\b(werkstudent\w*|working student|student assistant|studentische)", re.I)),
    (EmploymentType.INTERNSHIP, re.compile(r"\b(intern|internship|praktikum|praktikant\w*)\b", re.I)),
    (EmploymentType.PART_TIME, re.compile(r"\b(part[- ]time|teilzeit|minijob)\b", re.I)),
    (EmploymentType.CONTRACT, re.compile(r"\b(contract|contractor|freelance|freiberuf\w*|befristet)\b", re.I)),
    (EmploymentType.FULL_TIME, re.compile(r"\b(full[- ]time|vollzeit|permanent|festanstellung)\b", re.I)),
]


def infer_work_mode(*texts: str | None, title: str = "") -> WorkMode:
    """Check structured/short fields first, then fall back to the description."""
    for text in (title, *texts):
        if not text:
            continue
        if _HYBRID_RE.search(text):
            return WorkMode.HYBRID
        if _REMOTE_RE.search(text):
            return WorkMode.REMOTE
    return WorkMode.UNKNOWN


def infer_employment_types(*texts: str | None) -> list[EmploymentType]:
    joined = " ".join(t for t in texts if t)
    found = [etype for etype, pattern in _EMPLOYMENT_PATTERNS if pattern.search(joined)]
    return found
