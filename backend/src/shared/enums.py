# backend/src/shared/enums.py

from __future__ import annotations

import enum


class SearchStatus(str, enum.Enum):
    CREATED = "created"
    PLANNED = "planned"
    DISCOVERED = "discovered"
    SCREENED = "screened"
    DRAFTED = "drafted"
    FAILED = "failed"


class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    FILTERED_OUT = "filtered_out"   # failed a hard filter (remote, part time, ...)
    SCREENED_IN = "screened_in"
    SCREENED_OUT = "screened_out"
    UNSURE = "unsure"
    DRAFTED = "drafted"             # documents generated, waiting for the human
    APPROVED = "approved"           # human approved this exact draft
    REJECTED = "rejected"           # human decided not to apply
    PREPARED = "prepared"           # package written / form autofilled, waiting for final submit
    APPLIED = "applied"             # human confirmed the application went out
    FAILED = "failed"


class SourceName(str, enum.Enum):
    ARBEITNOW = "arbeitnow"
    BUNDESAGENTUR = "bundesagentur"
    ADZUNA = "adzuna"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    PERSONIO = "personio"
    SMARTRECRUITERS = "smartrecruiters"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # server stopped while the run was in progress


class WorkMode(str, enum.Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    WORKING_STUDENT = "working_student"
    INTERNSHIP = "internship"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class ScreeningOutcome(str, enum.Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    UNSURE = "unsure"


class ActorType(str, enum.Enum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"
