# backend/src/discovery/sources/company_boards.py
"""
Public ATS job-board APIs for a watchlist of companies: JobFilters.company_boards plus,
if enabled, the built-in DEFAULT_BOARDS.

  Greenhouse:      https://developers.greenhouse.io/job-board.html
  Lever:           https://github.com/lever/postings-api
  Ashby:           https://developers.ashbyhq.com/docs/public-job-posting-api
  Personio:        https://{company}.jobs.personio.de/xml  (public XML feed)
  SmartRecruiters: https://developers.smartrecruiters.com/docs/posting-api

Greenhouse, Lever and Ashby are also the ones the autofill submitters know how to fill in.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from datetime import datetime, timezone

import httpx

from discovery.filters import matches_keywords
from discovery.inference import infer_employment_types, infer_work_mode
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from discovery.sources.default_boards import effective_boards
from onboarding.models import CompanyBoard, JobFilters, SearchQuery
from shared.enums import SourceName, WorkMode
from shared.text import detect_language, html_to_text, truncate

logger = logging.getLogger(__name__)


class CompanyBoardAdapter(BaseSourceAdapter):
    """Fetches each configured board once per run, then filters by keywords locally."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(client)
        self._cache: dict[str, list[JobPosting]] = {}
        self._locks: dict[str, asyncio.Lock] = {}  # concurrent queries share one fetch per board

    async def search(self, query: SearchQuery, filters: JobFilters) -> list[JobPosting]:
        boards = [b for b in effective_boards(filters) if b.source == self.source]
        results = await asyncio.gather(*(self._board_jobs(b) for b in boards), return_exceptions=True)

        jobs: list[JobPosting] = []
        for board, result in zip(boards, results):
            if isinstance(result, Exception):
                logger.warning("%s board %r failed: %s", self.source.value, board.token, result)
                continue
            jobs.extend(j for j in result if matches_keywords(j, query.keywords))
        return jobs[: query.max_results]

    async def _board_jobs(self, board: CompanyBoard) -> list[JobPosting]:
        async with self._locks.setdefault(board.token, asyncio.Lock()):
            if board.token not in self._cache:
                self._cache[board.token] = await self._fetch_board(board)
        return self._cache[board.token]

    @abstractmethod
    async def _fetch_board(self, board: CompanyBoard) -> list[JobPosting]: ...


class GreenhouseAdapter(CompanyBoardAdapter):
    source = SourceName.GREENHOUSE
    URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    async def _fetch_board(self, board: CompanyBoard) -> list[JobPosting]:
        resp = await self._client.get(self.URL.format(token=board.token), params={"content": "true"})
        resp.raise_for_status()
        company = board.company_name or board.token
        jobs = []
        for item in resp.json().get("jobs") or []:
            description = html_to_text(item.get("content") or "")
            location = (item.get("location") or {}).get("name")
            jobs.append(JobPosting(
                source=self.source,
                external_id=str(item.get("id")),
                title=item.get("title") or "",
                company=company,
                location=location,
                work_mode=infer_work_mode(location, description, title=item.get("title") or ""),
                employment_types=infer_employment_types(item.get("title"), description[:1500]),
                description=description,
                url=item.get("absolute_url") or "",
                apply_url=item.get("absolute_url"),
                posted_at=_iso(item.get("first_published") or item.get("updated_at")),
                language=detect_language(description),
                board_token=board.token,
                raw=item,
            ))
        return jobs


class LeverAdapter(CompanyBoardAdapter):
    source = SourceName.LEVER
    URLS = {"us": "https://api.lever.co/v0/postings/{site}", "eu": "https://api.eu.lever.co/v0/postings/{site}"}
    _WORKPLACE = {"remote": WorkMode.REMOTE, "hybrid": WorkMode.HYBRID, "on-site": WorkMode.ONSITE}

    async def _fetch_board(self, board: CompanyBoard) -> list[JobPosting]:
        url = self.URLS[board.region or "us"].format(site=board.token)
        resp = await self._client.get(url, params={"mode": "json"})
        resp.raise_for_status()
        company = board.company_name or board.token
        jobs = []
        for item in resp.json():
            cats = item.get("categories") or {}
            sections = [item.get("descriptionPlain") or ""]
            for lst in item.get("lists") or []:
                sections.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content') or '')}")
            sections.append(item.get("additionalPlain") or "")
            description = "\n\n".join(s for s in sections if s.strip())
            created = item.get("createdAt")
            jobs.append(JobPosting(
                source=self.source,
                external_id=str(item.get("id")),
                title=item.get("text") or "",
                company=company,
                location=cats.get("location"),
                work_mode=self._WORKPLACE.get(item.get("workplaceType") or "")
                or infer_work_mode(cats.get("location"), title=item.get("text") or ""),
                employment_types=infer_employment_types(cats.get("commitment"), item.get("text")),
                description=description,
                url=item.get("hostedUrl") or "",
                apply_url=item.get("applyUrl"),
                posted_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None,
                language=detect_language(description),
                tags=[t for t in (cats.get("team"), cats.get("department")) if t],
                board_token=board.token,
                raw=item,
            ))
        return jobs


class AshbyAdapter(CompanyBoardAdapter):
    source = SourceName.ASHBY
    URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"
    _WORKPLACE = {"remote": WorkMode.REMOTE, "hybrid": WorkMode.HYBRID, "onsite": WorkMode.ONSITE}
    _EMPLOYMENT = {"fulltime": "full time", "parttime": "part time", "intern": "internship", "contract": "contract"}

    async def _fetch_board(self, board: CompanyBoard) -> list[JobPosting]:
        resp = await self._client.get(self.URL.format(org=board.token), params={"includeCompensation": "true"})
        resp.raise_for_status()
        company = board.company_name or board.token
        jobs = []
        for item in resp.json().get("jobs") or []:
            description = item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml") or "")
            workplace = (item.get("workplaceType") or "").lower().replace("-", "")
            # workplaceType is authoritative: boards set isRemote on hybrid roles too.
            mode = self._WORKPLACE.get(workplace) or (WorkMode.REMOTE if item.get("isRemote") else WorkMode.UNKNOWN)
            employment = self._EMPLOYMENT.get((item.get("employmentType") or "").lower(), "")
            jobs.append(JobPosting(
                source=self.source,
                external_id=str(item.get("id")),
                title=item.get("title") or "",
                company=company,
                location=item.get("location"),
                work_mode=mode,
                employment_types=infer_employment_types(employment, item.get("title")),
                description=description,
                url=item.get("jobUrl") or "",
                apply_url=item.get("applyUrl"),
                posted_at=_iso(item.get("publishedAt")),
                salary=(item.get("compensation") or {}).get("compensationTierSummary"),
                language=detect_language(description),
                tags=[t for t in (item.get("department"), item.get("team")) if t],
                board_token=board.token,
                raw=item,
            ))
        return jobs


class PersonioAdapter(CompanyBoardAdapter):
    """Personio's public XML feed: widespread among German startups and SMEs."""

    source = SourceName.PERSONIO
    URL = "https://{token}.jobs.personio.de/xml"
    JOB_URL = "https://{token}.jobs.personio.de/job/{id}"
    _EMPLOYMENT = {"working_student": "working student", "intern": "internship", "trainee": "internship",
                   "freelance": "freelance", "temporary": "befristet"}

    async def _fetch_board(self, board: CompanyBoard) -> list[JobPosting]:
        from defusedxml.ElementTree import fromstring  # untrusted XML

        resp = await self._client.get(self.URL.format(token=board.token), params={"language": "en"})
        resp.raise_for_status()
        root = fromstring(resp.content)
        jobs = []
        for pos in root.iter("position"):
            def text(tag: str) -> str:
                return (pos.findtext(tag) or "").strip()

            sections = [
                f"{d.findtext('name') or ''}\n{html_to_text(d.findtext('value') or '')}"
                for d in pos.iter("jobDescription")
            ]
            description = "\n\n".join(x.strip() for x in sections if x.strip())
            title, office, schedule = text("name"), text("office"), text("schedule")
            employment = " ".join(x for x in (self._EMPLOYMENT.get(text("employmentType"), ""), schedule.replace("-", " ")) if x)
            job_id = text("id")
            jobs.append(JobPosting(
                source=self.source,
                external_id=job_id,
                title=title,
                company=text("subcompany") or board.company_name or board.token,
                location=office or None,
                work_mode=infer_work_mode(office, title=title),
                employment_types=infer_employment_types(employment, title),
                description=description,
                url=self.JOB_URL.format(token=board.token, id=job_id),
                apply_url=self.JOB_URL.format(token=board.token, id=job_id),
                posted_at=_iso(text("createdAt")),
                language=detect_language(description),
                tags=[t for t in (text("department"), *text("keywords").split(",")) if t.strip()][:10],
                board_token=board.token,
            ))
        return jobs


class SmartRecruitersAdapter(CompanyBoardAdapter):
    """SmartRecruiters Posting API. Lists are paginated and carry no description; see fetch_details."""

    source = SourceName.SMARTRECRUITERS
    URL = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
    PAGE_SIZE = 100
    MAX_POSTINGS = 2000  # big employers list thousands of jobs worldwide

    async def _fetch_board(self, board: CompanyBoard) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        offset = 0
        while offset < self.MAX_POSTINGS:
            resp = await self._client.get(
                self.URL.format(token=board.token), params={"limit": self.PAGE_SIZE, "offset": offset},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("content") or []
            jobs.extend(self._to_posting(board, item) for item in items)
            offset += self.PAGE_SIZE
            if not items or offset >= (data.get("totalFound") or 0):
                break
        return jobs

    def _to_posting(self, board: CompanyBoard, item: dict) -> JobPosting:
        loc = item.get("location") or {}
        title = item.get("name") or ""
        mode = WorkMode.REMOTE if loc.get("remote") else WorkMode.HYBRID if loc.get("hybrid") else WorkMode.UNKNOWN
        employment = (item.get("typeOfEmployment") or {}).get("label") or ""
        return JobPosting(
            source=self.source,
            external_id=str(item.get("id")),
            title=title,
            company=(item.get("company") or {}).get("name") or board.company_name or board.token,
            location=loc.get("fullLocation") or loc.get("city"),
            work_mode=mode if mode != WorkMode.UNKNOWN else infer_work_mode(title=title),
            employment_types=infer_employment_types(employment, title),
            description="",  # filled by fetch_details for jobs that pass the hard filters
            url=f"https://jobs.smartrecruiters.com/{board.token}/{item.get('id')}",
            posted_at=_iso(item.get("releasedDate")),
            language=(item.get("language") or {}).get("code"),
            tags=[t for t in ((item.get("department") or {}).get("label"), (item.get("function") or {}).get("label")) if t],
            board_token=board.token,
            raw=item,
        )

    async def fetch_details(self, job: JobPosting) -> JobPosting:
        resp = await self._client.get(f"{self.URL.format(token=job.board_token)}/{job.external_id}")
        resp.raise_for_status()
        detail = resp.json()
        sections = ((detail.get("jobAd") or {}).get("sections") or {})
        parts = [
            f"{sec.get('title') or ''}\n{html_to_text(sec.get('text') or '')}"
            for key, sec in sections.items()
            if key != "videos" and isinstance(sec, dict) and sec.get("text")
        ]
        description = "\n\n".join(parts)
        if description:
            job.description = truncate(description, 20000)
            job.language = job.language or detect_language(description)
            if job.work_mode == WorkMode.UNKNOWN:
                job.work_mode = infer_work_mode(description, title=job.title)
        job.url = detail.get("postingUrl") or job.url
        job.apply_url = detail.get("applyUrl") or job.apply_url
        return job


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
