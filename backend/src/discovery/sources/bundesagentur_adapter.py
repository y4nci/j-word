# backend/src/discovery/sources/bundesagentur_adapter.py
"""
Bundesagentur für Arbeit Jobsuche API (largest German job database, public client key).
Docs: https://jobsuche.api.bund.dev/

Verified live 2026-10: search is served at /pc/v6/jobs (v4/v5 search return 403),
details are still at /pc/v4/jobdetails/{base64(referenznummer)}.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

import httpx

from discovery.inference import infer_employment_types, infer_work_mode
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from onboarding.models import JobFilters, SearchQuery
from shared.enums import EmploymentType, SourceName, WorkMode
from shared.text import detect_language, html_to_text

logger = logging.getLogger(__name__)

# 'arbeitszeit' codes accepted by the API.
_ARBEITSZEIT = {
    EmploymentType.FULL_TIME: "vz",
    EmploymentType.PART_TIME: "tz",
}
# ~40% of Werkstudent / Praktikum postings carry no 'tz' tag (checked live 2026-10), so a
# request that includes these types is not restricted by working time at all.
_UNTAGGED_TYPES = {EmploymentType.WORKING_STUDENT, EmploymentType.INTERNSHIP}


class BundesagenturAdapter(BaseSourceAdapter):
    source = SourceName.BUNDESAGENTUR
    BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
    SEARCH_PATH = "/pc/v6/jobs"
    DETAILS_PATH = "/pc/v4/jobdetails/{encoded}"
    HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # public client id from the official docs
    JOB_PAGE = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

    async def search(self, query: SearchQuery, filters: JobFilters) -> list[JobPosting]:
        size = min(query.max_results, 100)
        params: dict[str, str | int] = {
            "was": query.keywords,
            "size": size,
            "angebotsart": 1,  # 1 = Arbeit (not Ausbildung/Selbstständigkeit)
        }
        if query.location:
            params["wo"] = query.location
            params["umkreis"] = filters.radius_km
        if filters.max_age_days:
            params["veroeffentlichtseit"] = filters.max_age_days

        codes = set()
        if not _UNTAGGED_TYPES & set(filters.employment_types):
            codes = {_ARBEITSZEIT[e] for e in filters.employment_types if e in _ARBEITSZEIT}
        if WorkMode.REMOTE in filters.work_modes and len(filters.work_modes) == 1:
            codes.add("ho")
        if codes:
            params["arbeitszeit"] = ";".join(sorted(codes))

        jobs: list[JobPosting] = []
        page = 1
        while len(jobs) < query.max_results:
            resp = await self._client.get(
                f"{self.BASE_URL}{self.SEARCH_PATH}", params={**params, "page": page}, headers=self.HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("ergebnisliste") or []
            jobs.extend(self._to_posting(item) for item in items if item.get("referenznummer"))
            if len(items) < size or len(jobs) >= (data.get("maxErgebnisse") or 0):
                break
            page += 1
        return jobs[: query.max_results]

    async def fetch_details(self, job: JobPosting) -> JobPosting:
        """Search results carry no description; fetch it from the detail endpoint."""
        encoded = base64.b64encode(job.external_id.encode()).decode()
        try:
            resp = await self._client.get(
                f"{self.BASE_URL}{self.DETAILS_PATH.format(encoded=encoded)}", headers=self.HEADERS,
            )
            resp.raise_for_status()
            detail = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("No details for BA job %s: %s", job.external_id, exc)
            return job

        description = html_to_text(detail.get("stellenangebotsBeschreibung") or "")
        if description:
            job.description = description
            job.language = detect_language(description) or "de"
            if job.work_mode == WorkMode.UNKNOWN:
                job.work_mode = infer_work_mode(description, title=job.title)
            for etype in infer_employment_types(job.title, description[:1500]):
                if etype not in job.employment_types:
                    job.employment_types.append(etype)
        job.apply_url = job.apply_url or detail.get("allianzpartnerUrl")
        return job

    def _to_posting(self, item: dict) -> JobPosting:
        refnr = str(item["referenznummer"])
        title = item.get("stellenangebotsTitel") or item.get("hauptberuf") or ""
        place = ((item.get("stellenlokationen") or [{}])[0].get("adresse")) or {}

        employment = infer_employment_types(title)
        if item.get("arbeitszeitVollzeit"):
            employment.append(EmploymentType.FULL_TIME)
        if item.get("istGeringfuegigeBeschaeftigung") or any(
            v is True for k, v in item.items() if k.startswith("arbeitszeitTeilzeit")
        ):
            employment.append(EmploymentType.PART_TIME)

        return JobPosting(
            source=self.source,
            external_id=refnr,
            title=title,
            company=item.get("firma") or "",
            location=place.get("ort"),
            work_mode=infer_work_mode(title=title),
            employment_types=list(dict.fromkeys(employment)),
            description=f"{title}\nBerufe: {', '.join(item.get('alleBerufe') or [])}",
            url=self.JOB_PAGE.format(refnr=refnr),
            # Current publication period; datumErsteVeroeffentlichung is the first one for reposted jobs.
            posted_at=_parse_date((item.get("veroeffentlichungszeitraum") or {}).get("von")
                                  or item.get("datumErsteVeroeffentlichung")),
            language="de",
            raw=item,
        )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
