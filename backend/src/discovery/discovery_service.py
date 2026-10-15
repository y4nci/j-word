# backend/src/discovery/discovery_service.py

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from discovery.filters import hard_filter
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from onboarding.models import JobSearch
from shared.enums import SourceName

logger = logging.getLogger(__name__)

# Descriptions shorter than this are probably snippets; try the source's detail endpoint.
_MIN_DESCRIPTION_CHARS = 400


@dataclass
class DiscoveredJob:
    job: JobPosting
    filter_reason: Optional[str]  # None = passed the hard filters


class DiscoveryService:
    def __init__(self, adapters: dict[SourceName, BaseSourceAdapter], *, max_concurrency: int = 8) -> None:
        self._adapters = adapters
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def sources(self) -> list[SourceName]:
        return list(self._adapters)

    async def run(self, search: JobSearch, *, skip_keys: set[str] = frozenset()) -> list[DiscoveredJob]:
        """
        Run every planned query, dedupe across queries/sources, apply hard filters,
        and fetch full descriptions for the jobs that passed.

        `skip_keys`: dedupe keys already seen in earlier searches of this profile.
        """
        if not search.plan or not search.plan.queries:
            return []

        queries = [q for q in search.plan.queries if q.source in self._adapters]
        results = await asyncio.gather(
            *(self._run_query(q, search) for q in queries),
            return_exceptions=True,
        )

        unique: dict[str, JobPosting] = {}
        for query, result in zip(queries, results):
            if isinstance(result, Exception):
                logger.warning("Query %s/%r failed: %s", query.source.value, query.keywords, result)
                continue
            for job in result:
                key = job.dedupe_key
                if not job.title or not job.company or key in skip_keys:
                    continue
                current = unique.get(key)
                if current is None or len(job.description) > len(current.description):
                    unique[key] = job

        discovered = [DiscoveredJob(job, hard_filter(job, search.filters)) for job in unique.values()]
        await asyncio.gather(*(self._ensure_details(d) for d in discovered if d.filter_reason is None))

        # Re-check filters that depend on the full description (language, work mode).
        for d in discovered:
            if d.filter_reason is None:
                d.filter_reason = hard_filter(d.job, search.filters)

        kept = sum(d.filter_reason is None for d in discovered)
        logger.info("Discovery for search %s: %d unique jobs, %d passed filters", search.id, len(discovered), kept)
        return discovered

    async def _run_query(self, query, search: JobSearch) -> list[JobPosting]:
        async with self._semaphore:
            return await self._adapters[query.source].search(query, search.filters)

    async def _ensure_details(self, discovered: DiscoveredJob) -> None:
        job = discovered.job
        if len(job.description) >= _MIN_DESCRIPTION_CHARS:
            return
        async with self._semaphore:
            try:
                discovered.job = await self._adapters[job.source].fetch_details(job)
            except Exception as exc:  # details are optional; never fail discovery on them
                logger.info("fetch_details failed for %s: %s", job.url, exc)
