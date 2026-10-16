# backend/src/discovery/sources/arbeitnow_adapter.py
"""
Arbeitnow public job board API (Germany-focused, no key, no server-side search).
https://www.arbeitnow.com/api/job-board-api
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from discovery.depth import depth_settings
from discovery.filters import matches_keywords
from discovery.inference import infer_employment_types, infer_work_mode
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from onboarding.models import JobFilters, SearchQuery
from shared.enums import SourceName, WorkMode
from shared.text import detect_language, html_to_text

logger = logging.getLogger(__name__)


class ArbeitnowAdapter(BaseSourceAdapter):
    source = SourceName.ARBEITNOW
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(
        self, client: httpx.AsyncClient, *, pages: int | None = None, page_delay: float = 1.5, retry_wait: float = 20.0,
    ) -> None:
        super().__init__(client)
        self._pages = pages  # None = from the search depth
        self._page_delay = page_delay
        self._retry_wait = retry_wait
        self._cache: list[JobPosting] | None = None
        self._lock = asyncio.Lock()  # concurrent queries share one fetch

    async def search(self, query: SearchQuery, filters: JobFilters) -> list[JobPosting]:
        jobs = await self._fetch_all(self._pages or depth_settings(filters).arbeitnow_pages)
        return [j for j in jobs if matches_keywords(j, query.keywords)][: query.max_results]

    async def _fetch_all(self, pages: int) -> list[JobPosting]:
        # The API has no search; fetch the newest pages once per run and filter locally.
        async with self._lock:
            if self._cache is None:
                self._cache = await self._fetch_pages(pages)
        return self._cache

    async def _fetch_pages(self, pages: int) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for page in range(1, pages + 1):
            if page > 1:
                await asyncio.sleep(self._page_delay)  # the API rate-limits bursts (429)
            resp = await self._client.get(self.BASE_URL, params={"page": page})
            if resp.status_code == 429:
                # Back off once (Retry-After if given), then give up and keep what we have.
                await asyncio.sleep(_retry_after(resp, default=self._retry_wait))
                resp = await self._client.get(self.BASE_URL, params={"page": page})
            if resp.status_code == 429 and jobs:
                logger.warning("Arbeitnow rate limit at page %d; using the %d jobs fetched so far", page, len(jobs))
                break
            resp.raise_for_status()
            items = resp.json().get("data") or []
            if not items:
                break
            jobs.extend(self._to_posting(item) for item in items)
        return jobs

    def _to_posting(self, item: dict) -> JobPosting:
        description = html_to_text(item.get("description") or "")
        job_types = item.get("job_types") or []
        created = item.get("created_at")
        return JobPosting(
            source=self.source,
            external_id=str(item.get("slug")),
            title=item.get("title") or "",
            company=item.get("company_name") or "",
            location=item.get("location"),
            work_mode=WorkMode.REMOTE if item.get("remote") else infer_work_mode(description, title=item.get("title") or ""),
            employment_types=infer_employment_types(" ".join(job_types), item.get("title")),
            description=description,
            url=item.get("url") or "",
            posted_at=datetime.fromtimestamp(created, tz=timezone.utc) if created else None,
            language=detect_language(description),
            tags=list(item.get("tags") or []),
            raw=item,
        )


def _retry_after(resp: httpx.Response, *, default: float) -> float:
    try:
        return min(float(resp.headers.get("retry-after", default)), 60.0)
    except ValueError:
        return default
