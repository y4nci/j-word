# backend/src/orchestration/job_pipeline.py
"""
Step-by-step pipeline, called by both the API routers and the CLI:

    create_profile -> create_search (plan) -> discover -> screen -> draft
        -> [human: edit / approve / reject] -> prepare (package + autofill)
        -> [human submits the form] -> mark_applied

Each step loads what it needs from the Repository and saves its results.
The caller owns the DB transaction (commit after each step).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from applications.models import Application, ApplicationDraft, InvalidTransition, ScreeningDecision
from db.repository import Repository
from discovery.discovery_service import DiscoveryService
from discovery.models import JobPosting
from drafting.drafting_service import DraftingService
from onboarding.models import CandidateProfile, JobFilters, JobSearch
from onboarding.planning_service import PlanningService
from onboarding.profile_service import ProfileService
from screening.screening_service import ScreeningService
from shared.enums import ActorType, ApplicationStatus as S, ScreeningOutcome, SearchStatus
from submission.autofill import AutofillSession
from shared.progress import Progress, noop_progress
from submission.submission_service import SubmissionService

logger = logging.getLogger(__name__)


class NotFound(LookupError):
    pass


@dataclass
class PipelineDeps:
    profiles: ProfileService
    planning: PlanningService
    discovery: DiscoveryService
    screening: ScreeningService
    drafting: DraftingService
    submission: SubmissionService


class JobPipeline:
    def __init__(self, deps: PipelineDeps, repo: Repository) -> None:
        self._d = deps
        self._repo = repo

    # ------------------------------------------------------------------ #
    # Onboarding
    # ------------------------------------------------------------------ #
    async def create_profile(self, *, cv_text: str, proto_cover_letter: str,
                             cv_path: Optional[str] = None, overrides: Optional[dict] = None) -> CandidateProfile:
        profile = await self._d.profiles.build_profile(
            cv_text=cv_text, proto_cover_letter=proto_cover_letter, cv_path=cv_path, overrides=overrides,
        )
        await self._repo.save_profile(profile)
        return profile

    async def create_search(self, profile_id: UUID, prompt: str, filters: JobFilters) -> JobSearch:
        profile = await self._profile(profile_id)
        search = JobSearch(profile_id=profile.id, prompt=prompt, filters=filters)
        search = await self._d.planning.build_plan(search, profile, self._d.discovery.sources)
        await self._repo.save_search(search)
        return search

    # ------------------------------------------------------------------ #
    # Discovery + screening
    # ------------------------------------------------------------------ #
    async def discover(
        self, search_id: UUID, *, on_progress: Progress = noop_progress,
    ) -> list[tuple[Application, JobPosting]]:
        search = await self._search(search_id)
        skip = await self._repo.known_dedupe_keys(search.profile_id)
        discovered = await self._d.discovery.run(search, skip_keys=skip, on_progress=on_progress)

        for d in discovered:
            app = Application(search_id=search.id, job_id=d.job.id)
            if d.filter_reason:
                app.filter_reason = d.filter_reason
                app.transition(S.FILTERED_OUT, ActorType.SYSTEM, d.filter_reason)
            await self._repo.add_job_with_application(search.id, d.job, app)

        search.status = SearchStatus.DISCOVERED
        await self._repo.save_search(search)
        return await self._repo.list_applications(search.id)

    async def screen(self, search_id: UUID) -> list[tuple[Application, JobPosting]]:
        await self.screen_batch(search_id)
        return await self._repo.list_applications(search_id)

    async def count_pending_screening(self, search_id: UUID) -> int:
        return len(await self._repo.list_applications(search_id, [S.DISCOVERED]))

    async def screen_batch(
        self, search_id: UUID, *, limit: Optional[int] = None, on_progress: Progress = noop_progress,
    ) -> int:
        """Screen up to `limit` not-yet-screened jobs (all if None). Returns how many were screened."""
        search = await self._search(search_id)
        profile = await self._profile(search.profile_id)
        pending = (await self._repo.list_applications(search.id, [S.DISCOVERED]))[:limit]
        if not pending:
            return 0

        results = await self._d.screening.screen_many(search, profile, [job for _, job in pending], on_progress)
        for app, job in pending:
            result = results[str(job.id)]
            app.record_screening(result.decision)
            await self._repo.save_application(app)
            if result.summary:
                job.summary = result.summary
                await self._repo.save_job(job)

        search.status = SearchStatus.SCREENED
        await self._repo.save_search(search)
        return len(pending)

    async def override_screening(self, application_id: UUID, outcome: ScreeningOutcome, reason: str = "") -> Application:
        app = await self._application(application_id)
        app.record_screening(ScreeningDecision(
            outcome=outcome, fit_score=app.latest_decision.fit_score if app.latest_decision else 0.0,
            confidence=1.0, reason=reason or "manual decision", actor_type=ActorType.HUMAN,
        ))
        await self._repo.save_application(app)
        return app

    # ------------------------------------------------------------------ #
    # Drafting + human review
    # ------------------------------------------------------------------ #
    async def draft_all(
        self, search_id: UUID, *, min_fit: float = 0.0, max_concurrency: int = 4, on_progress: Progress = noop_progress,
    ) -> list[Application]:
        search = await self._search(search_id)
        candidates = [
            (app, job) for app, job in await self._repo.list_applications(search.id, [S.SCREENED_IN])
            if app.latest_decision
            and (app.latest_decision.actor_type == ActorType.HUMAN or app.latest_decision.fit_score >= min_fit)
        ]
        profile = await self._profile(search.profile_id)
        semaphore = asyncio.Semaphore(max_concurrency)

        # LLM calls run concurrently; DB writes stay sequential (one AsyncSession).
        finished = 0

        async def one(job: JobPosting) -> ApplicationDraft | Exception:
            nonlocal finished
            async with semaphore:
                try:
                    return await self._d.drafting.draft(search, profile, job)
                except Exception as exc:
                    logger.warning("Drafting failed for %s: %s", job.url, exc)
                    return exc
                finally:
                    finished += 1
                    on_progress(finished, len(candidates), f"drafted letter for {job.title[:60]!r}")

        drafts = await asyncio.gather(*(one(job) for _, job in candidates))
        drafted = []
        for (app, _), draft in zip(candidates, drafts):
            if isinstance(draft, Exception):
                continue
            app.set_draft(draft, ActorType.AGENT)
            await self._repo.save_application(app)
            drafted.append(app)

        search.status = SearchStatus.DRAFTED
        await self._repo.save_search(search)
        return drafted

    async def draft_one(self, application_id: UUID) -> Application:
        app = await self._application(application_id)
        search = await self._search(app.search_id)
        profile = await self._profile(search.profile_id)
        draft = await self._d.drafting.draft(search, profile, await self._job(app.job_id))
        app.set_draft(draft, ActorType.AGENT)
        await self._repo.save_application(app)
        return app

    async def edit_draft(self, application_id: UUID, *, subject: Optional[str] = None,
                         cover_letter: Optional[str] = None, short_pitch: Optional[str] = None) -> Application:
        app = await self._application(application_id)
        if app.draft is None:
            raise InvalidTransition("No draft to edit")
        search = await self._search(app.search_id)
        profile = await self._profile(search.profile_id)

        edited = app.draft.model_copy(update={
            k: v for k, v in {"subject": subject, "cover_letter": cover_letter, "short_pitch": short_pitch}.items()
            if v is not None
        } | {"edited_by_human": True})
        edited.unsupported_claims = await self._d.drafting.recheck(profile, edited)
        app.set_draft(edited, ActorType.HUMAN)
        await self._repo.save_application(app)
        return app

    async def approve(self, application_id: UUID, note: str = "") -> Application:
        app = await self._application(application_id)
        app.approve(note)
        await self._repo.save_application(app)
        return app

    async def reject(self, application_id: UUID, note: str = "") -> Application:
        app = await self._application(application_id)
        app.transition(S.REJECTED, ActorType.HUMAN, note)
        await self._repo.save_application(app)
        return app

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    async def prepare(self, application_id: UUID, *, autofill: bool = True) -> tuple[Application, Optional[AutofillSession]]:
        app = await self._application(application_id)
        job = await self._job(app.job_id)
        profile = await self._profile((await self._search(app.search_id)).profile_id)
        session = await self._d.submission.prepare(app, job, profile, autofill=autofill)
        await self._repo.save_application(app)
        return app, session

    async def mark_applied(self, application_id: UUID, note: str = "") -> Application:
        app = await self._application(application_id)
        app.transition(S.APPLIED, ActorType.HUMAN, note)
        await self._repo.save_application(app)
        return app

    # ------------------------------------------------------------------ #
    # Loaders
    # ------------------------------------------------------------------ #
    async def _profile(self, profile_id: UUID) -> CandidateProfile:
        if (p := await self._repo.get_profile(profile_id)) is None:
            raise NotFound(f"profile {profile_id}")
        return p

    async def _search(self, search_id: UUID) -> JobSearch:
        if (s := await self._repo.get_search(search_id)) is None:
            raise NotFound(f"search {search_id}")
        return s

    async def _application(self, application_id: UUID) -> Application:
        if (a := await self._repo.get_application(application_id)) is None:
            raise NotFound(f"application {application_id}")
        return a

    async def _job(self, job_id: UUID) -> JobPosting:
        if (j := await self._repo.get_job(job_id)) is None:
            raise NotFound(f"job {job_id}")
        return j
