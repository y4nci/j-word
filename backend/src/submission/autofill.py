# backend/src/submission/autofill.py
"""
Browser autofill for ATS application forms (Greenhouse, Lever, Ashby).

Opens a visible browser, fills in what it can and leaves the window open.
It NEVER clicks submit: the human reviews the form and submits it themselves,
then confirms in jword (POST /applications/{id}/mark-applied).

Selectors are best-effort; ATS markup changes over time and companies add
custom questions. Anything not filled is listed in the report.
"""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from applications.models import ApplicationPackage
from discovery.models import JobPosting
from onboarding.models import CandidateProfile
from shared.enums import SourceName

logger = logging.getLogger(__name__)


@dataclass
class FillStep:
    label: str
    value: Optional[str]
    selectors: list[str]
    kind: Literal["text", "file"] = "text"
    label_pattern: Optional[str] = None  # fallback: find the field by its visible label


@dataclass
class AutofillSession:
    """Handle to an open browser window. `wait_closed()` returns once the user closes it."""

    url: str
    report: list[str] = field(default_factory=list)
    _closed: asyncio.Event = field(default_factory=asyncio.Event)
    _task: Optional[asyncio.Task] = None  # keep a reference so the watcher isn't garbage-collected

    async def wait_closed(self) -> None:
        await self._closed.wait()


class AutofillSubmitter(ABC):
    name: str
    sources: set[SourceName]

    def can_handle(self, job: JobPosting) -> bool:
        return job.source in self.sources and bool(self.form_url(job))

    @abstractmethod
    def form_url(self, job: JobPosting) -> Optional[str]: ...

    @abstractmethod
    def steps(self, profile: CandidateProfile, package: ApplicationPackage, short_pitch: str) -> list[FillStep]: ...

    async def autofill(
        self,
        job: JobPosting,
        profile: CandidateProfile,
        package: ApplicationPackage,
        short_pitch: str,
    ) -> AutofillSession:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed: pip install playwright && playwright install chromium") from exc

        url = self.form_url(job)
        session = AutofillSession(url=url)
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)  # let client-side forms render

        for step in self.steps(profile, package, short_pitch):
            if not step.value:
                session.report.append(f"skipped {step.label}: no value in profile")
                continue
            filled = await _fill(page, step)
            session.report.append(f"{'filled' if filled else 'NOT FOUND'}: {step.label}")
        session.report.append("Review the form, answer any custom questions, then click submit yourself.")

        async def _wait_and_cleanup() -> None:
            try:
                await page.wait_for_event("close", timeout=0)
            finally:
                await browser.close()
                await pw.stop()
                session._closed.set()

        session._task = asyncio.get_running_loop().create_task(_wait_and_cleanup())
        return session


async def _fill(page, step: FillStep) -> bool:
    for selector in step.selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            if step.kind == "file":
                await locator.set_input_files(step.value)
            else:
                await locator.fill(step.value)
            return True
        except Exception as exc:
            logger.debug("Selector %s failed for %s: %s", selector, step.label, exc)
    if step.label_pattern and step.kind == "text":
        try:
            locator = page.get_by_label(re.compile(step.label_pattern, re.I)).first
            if await locator.count():
                await locator.fill(step.value)
                return True
        except Exception as exc:
            logger.debug("Label lookup failed for %s: %s", step.label, exc)
    return False


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (full_name, "")


def _link(profile: CandidateProfile, key: str) -> Optional[str]:
    return next((v for k, v in profile.links.items() if key in k.lower()), None)


class GreenhouseAutofill(AutofillSubmitter):
    name = "greenhouse"
    sources = {SourceName.GREENHOUSE}

    def form_url(self, job: JobPosting) -> Optional[str]:
        # The hosted board always contains the form; company career pages often embed it in an iframe.
        if job.board_token:
            return f"https://job-boards.greenhouse.io/{job.board_token}/jobs/{job.external_id}"
        return job.apply_url

    def steps(self, profile, package, short_pitch):
        first, last = _split_name(profile.full_name)
        return [
            FillStep("first name", first, ["#first_name", "input[name='first_name']"]),
            FillStep("last name", last, ["#last_name", "input[name='last_name']"]),
            FillStep("email", profile.email, ["#email", "input[name='email']"]),
            FillStep("phone", profile.phone, ["#phone", "input[name='phone']"]),
            FillStep("CV", package.cv_file, ["input#resume[type='file']", "#resume_fieldset input[type='file']"], "file"),
            FillStep("cover letter", package.cover_letter_pdf,
                     ["input#cover_letter[type='file']", "#cover_letter_fieldset input[type='file']"], "file"),
            FillStep("LinkedIn", _link(profile, "linkedin"), [], label_pattern="linkedin"),
            FillStep("GitHub / website", _link(profile, "github") or _link(profile, "website"), [],
                     label_pattern="github|website|portfolio"),
        ]


class LeverAutofill(AutofillSubmitter):
    name = "lever"
    sources = {SourceName.LEVER}

    def form_url(self, job: JobPosting) -> Optional[str]:
        return job.apply_url or (f"{job.url.rstrip('/')}/apply" if job.url else None)

    def steps(self, profile, package, short_pitch):
        return [
            FillStep("CV", package.cv_file, ["input[name='resume']"], "file"),
            FillStep("name", profile.full_name, ["input[name='name']"]),
            FillStep("email", profile.email, ["input[name='email']"]),
            FillStep("phone", profile.phone, ["input[name='phone']"]),
            FillStep("location", profile.location, ["input[name='location']"]),
            FillStep("LinkedIn", _link(profile, "linkedin"), ["input[name='urls[LinkedIn]']"]),
            FillStep("GitHub", _link(profile, "github"), ["input[name='urls[GitHub]']"]),
            FillStep("portfolio", _link(profile, "website") or _link(profile, "portfolio"),
                     ["input[name='urls[Portfolio]']", "input[name='urls[Other]']"]),
            FillStep("additional information", _read(package.cover_letter_txt) or short_pitch,
                     ["textarea[name='comments']"]),
        ]


class AshbyAutofill(AutofillSubmitter):
    name = "ashby"
    sources = {SourceName.ASHBY}

    def form_url(self, job: JobPosting) -> Optional[str]:
        return job.apply_url or (f"{job.url.rstrip('/')}/application" if job.url else None)

    def steps(self, profile, package, short_pitch):
        return [
            FillStep("name", profile.full_name, ["input[name='_systemfield_name']"], label_pattern="^name"),
            FillStep("email", profile.email, ["input[name='_systemfield_email']", "input[type='email']"]),
            FillStep("phone", profile.phone, ["input[type='tel']"], label_pattern="phone"),
            FillStep("CV", package.cv_file, ["input#_systemfield_resume", "input[type='file']"], "file"),
            FillStep("LinkedIn", _link(profile, "linkedin"), [], label_pattern="linkedin"),
            FillStep("GitHub / website", _link(profile, "github") or _link(profile, "website"), [],
                     label_pattern="github|website|portfolio"),
        ]


def _read(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


DEFAULT_SUBMITTERS: list[AutofillSubmitter] = [GreenhouseAutofill(), LeverAutofill(), AshbyAutofill()]
