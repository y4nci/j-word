# backend/src/db/repository.py

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from applications.models import Application
from db.models import ApplicationRow, JobRow, ProfileRow, SearchRow
from discovery.models import JobPosting
from onboarding.models import CandidateProfile, JobSearch
from shared.enums import ApplicationStatus


class Repository:
    """All persistence for jword. Takes and returns domain models only."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ---------------- profiles ---------------- #
    async def save_profile(self, profile: CandidateProfile) -> None:
        await self._s.merge(ProfileRow(
            id=str(profile.id), data=profile.model_dump(mode="json"), created_at=profile.created_at,
        ))

    async def get_profile(self, profile_id: UUID) -> Optional[CandidateProfile]:
        row = await self._s.get(ProfileRow, str(profile_id))
        return CandidateProfile.model_validate(row.data) if row else None

    async def list_profiles(self) -> list[CandidateProfile]:
        rows = await self._s.scalars(select(ProfileRow).order_by(ProfileRow.created_at.desc()))
        return [CandidateProfile.model_validate(r.data) for r in rows]

    # ---------------- searches ---------------- #
    async def save_search(self, search: JobSearch) -> None:
        await self._s.merge(SearchRow(
            id=str(search.id), profile_id=str(search.profile_id), status=search.status.value,
            data=search.model_dump(mode="json"), created_at=search.created_at,
        ))

    async def get_search(self, search_id: UUID) -> Optional[JobSearch]:
        row = await self._s.get(SearchRow, str(search_id))
        return JobSearch.model_validate(row.data) if row else None

    async def list_searches(self, profile_id: UUID) -> list[JobSearch]:
        stmt = (
            select(SearchRow)
            .where(SearchRow.profile_id == str(profile_id))
            .order_by(SearchRow.created_at.desc())
        )
        return [JobSearch.model_validate(r.data) for r in await self._s.scalars(stmt)]

    async def known_dedupe_keys(self, profile_id: UUID) -> set[str]:
        """Jobs already seen in any earlier search for this profile."""
        stmt = (
            select(JobRow.dedupe_key)
            .join(SearchRow, SearchRow.id == JobRow.search_id)
            .where(SearchRow.profile_id == str(profile_id))
        )
        return set((await self._s.scalars(stmt)).all())

    # ---------------- jobs + applications ---------------- #
    async def add_job_with_application(self, search_id: UUID, job: JobPosting, application: Application) -> None:
        self._s.add(JobRow(
            id=str(job.id), search_id=str(search_id), source=job.source.value,
            dedupe_key=job.dedupe_key, data=job.model_dump(mode="json"),
        ))
        await self._s.flush()  # job row must exist before the application's FK
        await self.save_application(application)

    async def get_job(self, job_id: UUID) -> Optional[JobPosting]:
        row = await self._s.get(JobRow, str(job_id))
        return JobPosting.model_validate(row.data) if row else None

    async def save_job(self, job: JobPosting) -> None:
        row = await self._s.get(JobRow, str(job.id))
        if row is None:
            raise KeyError(job.id)
        row.data = job.model_dump(mode="json")

    async def save_application(self, application: Application) -> None:
        await self._s.merge(ApplicationRow(
            id=str(application.id), search_id=str(application.search_id), job_id=str(application.job_id),
            status=application.status.value, data=application.model_dump(mode="json"),
            updated_at=application.updated_at,
        ))

    async def get_application(self, application_id: UUID) -> Optional[Application]:
        row = await self._s.get(ApplicationRow, str(application_id))
        return Application.model_validate(row.data) if row else None

    async def list_applications(
        self,
        search_id: UUID,
        statuses: Optional[list[ApplicationStatus]] = None,
    ) -> list[tuple[Application, JobPosting]]:
        stmt = (
            select(ApplicationRow, JobRow)
            .join(JobRow, JobRow.id == ApplicationRow.job_id)
            .where(ApplicationRow.search_id == str(search_id))
        )
        if statuses:
            stmt = stmt.where(ApplicationRow.status.in_([s.value for s in statuses]))
        rows = (await self._s.execute(stmt)).all()
        return [(Application.model_validate(a.data), JobPosting.model_validate(j.data)) for a, j in rows]
