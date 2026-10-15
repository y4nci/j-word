# backend/src/discovery/sources/base_adapter.py

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from discovery.models import JobPosting
from onboarding.models import JobFilters, SearchQuery
from shared.enums import SourceName


class BaseSourceAdapter(ABC):
    """
    Fetches job postings from one external source and normalizes them into JobPosting.
    """

    source: SourceName

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @abstractmethod
    async def search(self, query: SearchQuery, filters: JobFilters) -> list[JobPosting]:
        """Run the query against the source and return normalized postings."""

    async def fetch_details(self, job: JobPosting) -> JobPosting:
        """
        Fill in the full description when the search result only has a snippet.
        Default: the search result is already complete.
        """
        return job
