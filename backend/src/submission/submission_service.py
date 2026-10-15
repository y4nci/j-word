# backend/src/submission/submission_service.py

from __future__ import annotations

import logging
from typing import Optional

from applications.models import Application
from discovery.models import JobPosting
from onboarding.models import CandidateProfile
from shared.enums import ActorType, ApplicationStatus
from submission.autofill import AutofillSession, AutofillSubmitter
from submission.package_builder import PackageBuilder

logger = logging.getLogger(__name__)


class SubmissionService:
    def __init__(self, packages: PackageBuilder, submitters: list[AutofillSubmitter]) -> None:
        self._packages = packages
        self._submitters = submitters

    async def prepare(
        self,
        application: Application,
        job: JobPosting,
        profile: CandidateProfile,
        *,
        autofill: bool = True,
    ) -> Optional[AutofillSession]:
        """
        Build the application package and, where the ATS is supported, open a
        browser with the form filled in. Requires a human-approved, unchanged draft.
        """
        application.assert_submittable()

        package = self._packages.build(application, job, profile)
        application.package = package

        session = None
        submitter = next((s for s in self._submitters if s.can_handle(job)), None)
        if autofill and submitter:
            package.autofill = submitter.name
            try:
                session = await submitter.autofill(job, profile, package, application.draft.short_pitch)
                package.autofill_report = session.report
            except Exception as exc:
                logger.exception("Autofill failed for %s", job.url)
                package.autofill_report = [f"Autofill failed: {exc}. Apply manually with the package."]
        else:
            package.autofill_report = [f"No autofill for this site. Apply at {job.apply_url or job.url} using the package."]

        application.transition(ApplicationStatus.PREPARED, ActorType.SYSTEM, f"package at {package.directory}")
        return session
