# backend/src/discovery/depth.py
"""How far a search reaches, per JobFilters.depth. One place to tune breadth vs. runtime/LLM cost."""

from __future__ import annotations

from dataclasses import dataclass

from onboarding.models import JobFilters


@dataclass(frozen=True)
class DepthSettings:
    max_keywords: int  # keyword phrases the planner may produce
    title_queries: bool  # also run each planned job title as its own query
    arbeitnow_pages: int  # ~100 newest jobs per page; fetching stops early when pages run out
    per_query_cap: int  # max results kept per query (Bundesagentur pages through up to this)


_STANDARD = DepthSettings(max_keywords=6, title_queries=False, arbeitnow_pages=5, per_query_cap=50)
_DEEP = DepthSettings(max_keywords=12, title_queries=True, arbeitnow_pages=30, per_query_cap=400)


def depth_settings(filters: JobFilters) -> DepthSettings:
    if filters.depth == "deep":
        return DepthSettings(
            max_keywords=_DEEP.max_keywords,
            title_queries=_DEEP.title_queries,
            arbeitnow_pages=_DEEP.arbeitnow_pages,
            per_query_cap=max(_DEEP.per_query_cap, filters.max_results_per_query),
        )
    return DepthSettings(
        max_keywords=_STANDARD.max_keywords,
        title_queries=_STANDARD.title_queries,
        arbeitnow_pages=_STANDARD.arbeitnow_pages,
        per_query_cap=filters.max_results_per_query,
    )
