# backend/src/applications/models.py
"""
One Application per (search, job). It carries the screening decisions, the
generated draft and the submission package, plus an audit trail of every
status change.

Human-in-the-loop guarantees live here, not in the API layer:
  - only a HUMAN can move an application to APPROVED;
  - an approval is bound to the exact draft it was given for (draft hash);
  - editing or regenerating the draft drops the application back to DRAFTED;
  - nothing can be submitted unless it is APPROVED and the draft is unchanged.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from shared.enums import ActorType, ApplicationStatus as S, ScreeningOutcome


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ScreeningDecision(BaseModel):
    outcome: ScreeningOutcome
    fit_score: float = 0.0  # 0..1
    confidence: float = 0.0  # 0..1
    reason: str = ""
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    dealbreakers: list[str] = Field(default_factory=list)
    actor_type: ActorType = ActorType.AGENT
    model_name: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class RequirementMatch(BaseModel):
    requirement: str
    experience_ids: list[str] = Field(default_factory=list)
    evidence: str = ""


class UnsupportedClaim(BaseModel):
    claim: str
    why: str = ""


class ApplicationDraft(BaseModel):
    language: str = "en"
    subject: str
    cover_letter: str
    short_pitch: str = ""  # 2-3 sentences for "anything else?" form fields
    requirement_matches: list[RequirementMatch] = Field(default_factory=list)
    used_experience_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    model_name: Optional[str] = None
    edited_by_human: bool = False
    created_at: datetime = Field(default_factory=_now)

    def content_hash(self) -> str:
        payload = f"{self.subject}\n{self.cover_letter}\n{self.short_pitch}"
        return hashlib.sha256(payload.encode()).hexdigest()


class ApplicationPackage(BaseModel):
    directory: str
    cover_letter_pdf: str
    cover_letter_txt: str
    cv_file: Optional[str] = None
    summary_md: str
    autofill: Optional[str] = None  # which submitter was launched, if any
    autofill_report: list[str] = Field(default_factory=list)


class StatusEvent(BaseModel):
    from_status: Optional[S]
    to_status: S
    actor_type: ActorType
    note: str = ""
    at: datetime = Field(default_factory=_now)


class InvalidTransition(ValueError):
    pass


_SCREENABLE = {S.DISCOVERED, S.FILTERED_OUT, S.SCREENED_IN, S.SCREENED_OUT, S.UNSURE}

ALLOWED_TRANSITIONS: dict[S, set[S]] = {
    S.DISCOVERED: {S.FILTERED_OUT, S.SCREENED_IN, S.SCREENED_OUT, S.UNSURE},
    S.FILTERED_OUT: {S.SCREENED_IN, S.SCREENED_OUT, S.UNSURE},
    S.SCREENED_IN: {S.SCREENED_OUT, S.UNSURE, S.DRAFTED, S.REJECTED},
    S.SCREENED_OUT: {S.SCREENED_IN, S.UNSURE},
    S.UNSURE: {S.SCREENED_IN, S.SCREENED_OUT},
    S.DRAFTED: {S.DRAFTED, S.APPROVED, S.REJECTED},
    S.APPROVED: {S.DRAFTED, S.PREPARED, S.REJECTED},
    S.REJECTED: {S.DRAFTED, S.SCREENED_IN},
    S.PREPARED: {S.APPLIED, S.APPROVED, S.FAILED, S.DRAFTED},
    S.FAILED: {S.APPROVED, S.DRAFTED},
    S.APPLIED: set(),
}


class Application(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    search_id: UUID
    job_id: UUID
    status: S = S.DISCOVERED
    filter_reason: Optional[str] = None
    decisions: list[ScreeningDecision] = Field(default_factory=list)
    draft: Optional[ApplicationDraft] = None
    approved_draft_hash: Optional[str] = None
    package: Optional[ApplicationPackage] = None
    history: list[StatusEvent] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def latest_decision(self) -> Optional[ScreeningDecision]:
        return self.decisions[-1] if self.decisions else None

    # ------------------------------------------------------------------ #
    # Transitions
    # ------------------------------------------------------------------ #
    def transition(self, to: S, actor: ActorType, note: str = "") -> None:
        if to not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransition(f"Cannot go from {self.status.value} to {to.value}")
        if to == S.APPROVED and actor != ActorType.HUMAN:
            raise InvalidTransition("Only a human can approve an application")
        if to == S.APPLIED and actor != ActorType.HUMAN:
            raise InvalidTransition("Only a human can confirm an application was submitted")
        self.history.append(StatusEvent(from_status=self.status, to_status=to, actor_type=actor, note=note))
        self.status = to
        self.updated_at = _now()

    def record_screening(self, decision: ScreeningDecision) -> None:
        if self.status not in _SCREENABLE:
            raise InvalidTransition(f"Cannot re-screen an application in status {self.status.value}")
        target = {
            ScreeningOutcome.INCLUDE: S.SCREENED_IN,
            ScreeningOutcome.EXCLUDE: S.SCREENED_OUT,
            ScreeningOutcome.UNSURE: S.UNSURE,
        }[decision.outcome]
        self.decisions.append(decision)
        if target != self.status:
            self.transition(target, decision.actor_type, decision.reason)

    def set_draft(self, draft: ApplicationDraft, actor: ActorType) -> None:
        """New or edited draft. Any previous approval no longer applies."""
        self.transition(S.DRAFTED, actor, "draft edited" if actor == ActorType.HUMAN else "draft generated")
        self.draft = draft
        self.approved_draft_hash = None

    def approve(self, note: str = "") -> None:
        if self.draft is None:
            raise InvalidTransition("Nothing to approve: no draft yet")
        self.transition(S.APPROVED, ActorType.HUMAN, note)
        self.approved_draft_hash = self.draft.content_hash()

    def assert_submittable(self) -> None:
        if self.status != S.APPROVED:
            raise InvalidTransition(f"Application must be approved first (status: {self.status.value})")
        if self.draft is None or self.approved_draft_hash != self.draft.content_hash():
            raise InvalidTransition("Draft changed after approval; approve it again")
