from uuid import uuid4

import pytest

from applications.models import Application, ApplicationDraft, InvalidTransition, ScreeningDecision
from shared.enums import ActorType, ApplicationStatus as S, ScreeningOutcome


def drafted_application() -> Application:
    app = Application(search_id=uuid4(), job_id=uuid4())
    app.record_screening(ScreeningDecision(outcome=ScreeningOutcome.INCLUDE, fit_score=0.8))
    app.set_draft(ApplicationDraft(subject="Application", cover_letter="Dear team, ..."), ActorType.AGENT)
    return app


def test_agent_cannot_approve():
    app = drafted_application()
    with pytest.raises(InvalidTransition):
        app.transition(S.APPROVED, ActorType.AGENT)


def test_cannot_submit_without_approval():
    app = drafted_application()
    with pytest.raises(InvalidTransition, match="approved first"):
        app.assert_submittable()


def test_editing_after_approval_requires_new_approval():
    app = drafted_application()
    app.approve()
    app.assert_submittable()

    edited = app.draft.model_copy(update={"cover_letter": "Dear team, changed"})
    app.set_draft(edited, ActorType.HUMAN)
    assert app.status == S.DRAFTED
    with pytest.raises(InvalidTransition):
        app.assert_submittable()


def test_draft_mutated_in_place_after_approval_is_caught():
    app = drafted_application()
    app.approve()
    app.draft.cover_letter = "sneaky change"
    with pytest.raises(InvalidTransition, match="changed after approval"):
        app.assert_submittable()


def test_only_human_marks_applied_and_history_is_recorded():
    app = drafted_application()
    app.approve()
    app.transition(S.PREPARED, ActorType.SYSTEM)
    with pytest.raises(InvalidTransition):
        app.transition(S.APPLIED, ActorType.AGENT)
    app.transition(S.APPLIED, ActorType.HUMAN)
    assert [e.to_status for e in app.history] == [S.SCREENED_IN, S.DRAFTED, S.APPROVED, S.PREPARED, S.APPLIED]


def test_cannot_rescreen_after_drafting():
    app = drafted_application()
    with pytest.raises(InvalidTransition):
        app.record_screening(ScreeningDecision(outcome=ScreeningOutcome.EXCLUDE))
