# backend/src/discovery/sources/adzuna_adapter.py
"""
Adzuna job search API (optional aggregator, paid key: https://developer.adzuna.com/).
Descriptions are truncated snippets; screening works on those, drafting uses what's there.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from discovery.inference import infer_employment_types, infer_work_mode
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from onboarding.models import JobFilters, SearchQuery
from shared.enums import EmploymentType, SourceName
from shared.text import detect_language, html_to_text


class AdzunaAdapter(BaseSourceAdapter):
    source = SourceName.ADZUNA
    BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

    def __init__(self, client: httpx.AsyncClient, *, app_id: str, app_key: str) -> None:
        super().__init__(client)
        self._app_id = app_id
        self._app_key = app_key

    async def search(self, query: SearchQuery, filters: JobFilters) -> list[JobPosting]:
        params: dict[str, str | int] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "what": query.keywords,
            "results_per_page": min(query.max_results, 50),
            "sort_by": "date",
            "content-type": "application/json",
        }
        if query.location:
            params["where"] = query.location
            params["distance"] = filters.radius_km
        if filters.max_age_days:
            params["max_days_old"] = filters.max_age_days

        types = set(filters.employment_types)
        if types and types <= {EmploymentType.PART_TIME, EmploymentType.WORKING_STUDENT}:
            params["part_time"] = 1
        elif types == {EmploymentType.FULL_TIME}:
            params["full_time"] = 1

        resp = await self._client.get(self.BASE_URL.format(country=filters.country.lower()), params=params)
        resp.raise_for_status()
        return [self._to_posting(item) for item in resp.json().get("results") or []]

    def _to_posting(self, item: dict) -> JobPosting:
        description = html_to_text(item.get("description") or "")
        title = html_to_text(item.get("title") or "")
        salary = None
        if item.get("salary_min"):
            salary = f"{int(item['salary_min'])}-{int(item.get('salary_max') or item['salary_min'])} (Adzuna estimate)"
        employment = infer_employment_types(title, (item.get("contract_time") or "").replace("_", " "))
        return JobPosting(
            source=self.source,
            external_id=str(item.get("id")),
            title=title,
            company=(item.get("company") or {}).get("display_name") or "",
            location=(item.get("location") or {}).get("display_name"),
            work_mode=infer_work_mode(description, title=title),
            employment_types=employment,
            description=description,
            url=item.get("redirect_url") or "",
            posted_at=datetime.fromisoformat(item["created"].replace("Z", "+00:00")) if item.get("created") else None,
            salary=salary,
            language=detect_language(description),
            raw=item,
        )
