# backend/src/onboarding/planning_service.py

from __future__ import annotations

import logging
from collections.abc import Iterable

from onboarding.models import CandidateProfile, JobSearch, SearchPlan, SearchQuery
from shared.enums import SearchStatus, SourceName
from shared.json_utils import chat_json
from shared.llm import AsyncChatLLM

logger = logging.getLogger(__name__)

# Sources whose API accepts a keyword query. The others return a full board
# and are filtered locally by the same keywords.
KEYWORD_SOURCES = {SourceName.BUNDESAGENTUR, SourceName.ADZUNA}
BOARD_SOURCES = {SourceName.GREENHOUSE, SourceName.LEVER, SourceName.ASHBY}

_PLAN_SYSTEM_PROMPT = """You plan a job search for a candidate.

Inputs: the candidate's request (free text), their profile and their hard filters.

Produce:
- refined_goal: one precise sentence describing the jobs to look for.
- target_titles: 3-8 realistic job titles, in the languages of the target market
  (for Germany include German titles too, e.g. "Werkstudent Data Science").
- keywords: 3-6 SHORT search phrases (1-3 words each) for job-board keyword search.
- screening_criteria: 3-8 concrete criteria a posting should satisfy, derived from the request
  (e.g. "Python is a core part of the role", "no more than 2 years experience required").
  Do not repeat the hard filters (remote/part-time/location); they are checked separately.

Return STRICT JSON only:
{"refined_goal": "...", "target_titles": ["..."], "keywords": ["..."], "screening_criteria": ["..."]}
"""


class PlanningService:
    def __init__(self, llm: AsyncChatLLM) -> None:
        self._llm = llm

    async def build_plan(
        self,
        search: JobSearch,
        profile: CandidateProfile,
        available_sources: Iterable[SourceName],
    ) -> JobSearch:
        f = search.filters
        user_prompt = (
            f"REQUEST:\n{search.prompt}\n\n"
            f"PROFILE:\n{profile.compact()}\n\n"
            f"HARD FILTERS: work modes={[m.value for m in f.work_modes] or 'any'}, "
            f"employment={[e.value for e in f.employment_types] or 'any'}, "
            f"locations={f.locations or 'any'}, country={f.country}"
        )
        data = await chat_json(self._llm, system_prompt=_PLAN_SYSTEM_PROMPT, user_prompt=user_prompt)

        plan = SearchPlan(
            refined_goal=str(data.get("refined_goal") or search.prompt),
            target_titles=_str_list(data.get("target_titles")),
            keywords=_str_list(data.get("keywords"))[:6],
            screening_criteria=_str_list(data.get("screening_criteria")),
        )
        plan.queries = build_queries(plan, search, available_sources)

        search.plan = plan
        search.status = SearchStatus.PLANNED
        logger.info("Search %s planned with %d queries", search.id, len(plan.queries))
        return search


def build_queries(
    plan: SearchPlan,
    search: JobSearch,
    available_sources: Iterable[SourceName],
) -> list[SearchQuery]:
    f = search.filters
    sources = [s for s in available_sources if not f.sources or s in f.sources]
    # Without explicit locations, keyword sources search nationwide (location=None).
    locations: list[str | None] = list(f.locations) or [None]
    phrases = plan.keywords or plan.target_titles[:3]

    queries: list[SearchQuery] = []
    for source in sources:
        if source in BOARD_SOURCES and not any(b.source == source for b in f.company_boards):
            continue
        for phrase in phrases:
            if source in KEYWORD_SOURCES:
                queries.extend(
                    SearchQuery(source=source, keywords=phrase, location=loc, max_results=f.max_results_per_query)
                    for loc in locations
                )
            else:
                queries.append(SearchQuery(source=source, keywords=phrase, max_results=f.max_results_per_query))
    return queries


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]
