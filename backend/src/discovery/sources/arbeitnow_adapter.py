# backend/src/discovery/sources/arbeitnow_adapter.py
"""
Arbeitnow public job board API (Germany-focused, no key, no server-side search).
https://www.arbeitnow.com/api/job-board-api
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from discovery.filters import matches_keywords
from discovery.inference import infer_employment_types, infer_work_mode
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from onboarding.models import JobFilters, SearchQuery
from shared.enums import SourceName, WorkMode
from shared.text import detect_language, html_to_text


class ArbeitnowAdapter(BaseSourceAdapter):
    source = SourceName.ARBEITNOW
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, client: httpx.AsyncClient, *, pages: int = 5) -> None:
        super().__init__(client)
        self._pages = pages
        self._cache: list[JobPosting] | None = None

    async def search(self, query: SearchQuery, filters: JobFilters) -> list[JobPosting]:
        jobs = await self._fetch_all()
        return [j for j in jobs if matches_keywords(j, query.keywords)][: query.max_results]

    async def _fetch_all(self) -> list[JobPosting]:
        # The API has no search; fetch the newest pages once per run and filter locally.
        if self._cache is None:
            jobs: list[JobPosting] = []
            for page in range(1, self._pages + 1):
                resp = await self._client.get(self.BASE_URL, params={"page": page})
                resp.raise_for_status()
                items = resp.json().get("data") or []
                if not items:
                    break
                jobs.extend(self._to_posting(item) for item in items)
            self._cache = jobs
        return self._cache

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
