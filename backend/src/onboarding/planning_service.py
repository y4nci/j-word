# backend/src/onboarding/planning_service.py

from __future__ import annotations

import logging
from collections.abc import Iterable

from discovery.depth import depth_settings
from discovery.sources.default_boards import effective_boards
from onboarding.models import CandidateProfile, JobFilters, JobSearch, SearchPlan, SearchQuery
from shared.enums import EmploymentType, SearchStatus, SourceName, WorkMode
from shared.json_utils import chat_json
from shared.llm import AsyncChatLLM

logger = logging.getLogger(__name__)

# Sources whose API accepts a keyword query. The others return a full board
# and are filtered locally by the same keywords.
KEYWORD_SOURCES = {SourceName.BUNDESAGENTUR, SourceName.ADZUNA}
BOARD_SOURCES = {
    SourceName.GREENHOUSE, SourceName.LEVER, SourceName.ASHBY, SourceName.PERSONIO, SourceName.SMARTRECRUITERS,
}

_PLAN_SYSTEM_PROMPT = """You plan a job search for a candidate.

Inputs: the candidate's request (free text), their profile and their hard filters.

Produce:
- refined_goal: one precise sentence describing the jobs to look for.
- target_titles: 3-8 realistic job titles, in the languages of the target market
  (for Germany include German titles too, e.g. "Werkstudent Data Science").
- keywords: up to {max_keywords} SHORT search phrases (1-3 words each) for job-board keyword search.
  Cover the whole request: each target area, synonyms, and German + English variants.
  If the request targets working-student / part-time / internship roles, EVERY keyword must
  include that qualifier, mixing German and English for the German market
  (e.g. "Werkstudent Software", "working student backend", "Werkstudent Data").
  Keyword search ANDs every word against job titles, so use words that appear in titles,
  not topics, and keep phrases short. In that case also include the bare qualifier on its own
  (e.g. "Werkstudent") as one keyword: German boards list few such roles, and a broad query
  finds the ones whose titles don't contain your other words.
- screening_criteria: 3-8 concrete criteria a posting should satisfy, derived from the request
  (e.g. "Python is a core part of the role", "no more than 2 years experience required").
  Do not repeat the hard filters (remote/part-time/location); they are checked separately.
- suggested_filters: hard filters the request states EXPLICITLY. Leave a list empty if the
  request doesn't clearly restrict it.
  - employment_types: any of "full_time", "part_time", "working_student", "internship", "contract"
  - work_modes: any of "remote", "hybrid", "onsite"; only if the request rules a mode OUT
    (e.g. "remote only"). "Berlin, hybrid ok" does not rule out on-site Berlin jobs.
  - locations: cities the candidate wants to work in (remote jobs elsewhere still pass)

Return STRICT JSON only:
{"refined_goal": "...", "target_titles": ["..."], "keywords": ["..."], "screening_criteria": ["..."],
 "suggested_filters": {"employment_types": [], "work_modes": [], "locations": []}}
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
        depth = depth_settings(f)
        system_prompt = _PLAN_SYSTEM_PROMPT.replace("{max_keywords}", str(depth.max_keywords))
        data = await chat_json(self._llm, system_prompt=system_prompt, user_prompt=user_prompt)

        plan = SearchPlan(
            refined_goal=str(data.get("refined_goal") or search.prompt),
            target_titles=_str_list(data.get("target_titles")),
            keywords=_str_list(data.get("keywords"))[: depth.max_keywords],
            screening_criteria=_str_list(data.get("screening_criteria")),
        )
        plan.inferred_filters = apply_suggested_filters(search.filters, data.get("suggested_filters"))
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
    depth = depth_settings(f)
    sources = [s for s in available_sources if not f.sources or s in f.sources]
    boards = effective_boards(f)
    # Without explicit locations, keyword sources search nationwide (location=None).
    locations: list[str | None] = list(f.locations) or [None]
    phrases = plan.keywords or plan.target_titles[:3]
    if depth.title_queries:
        phrases = phrases + plan.target_titles
    phrases = list({p.lower(): p for p in reversed(phrases)}.values())[::-1]  # dedupe, keep first spelling

    queries: list[SearchQuery] = []
    for source in sources:
        if source in BOARD_SOURCES and not any(b.source == source for b in boards):
            continue
        for phrase in phrases:
            if source in KEYWORD_SOURCES:
                queries.extend(
                    SearchQuery(source=source, keywords=phrase, location=loc, max_results=depth.per_query_cap)
                    for loc in locations
                )
            else:
                queries.append(SearchQuery(source=source, keywords=phrase, max_results=depth.per_query_cap))
    return queries


def apply_suggested_filters(filters: JobFilters, suggested) -> dict[str, list[str]]:
    """
    Fill hard filters the user left empty with what the planner read from the prompt.
    Filters the user set are never touched. Returns what was applied, for display.
    """
    if not isinstance(suggested, dict):
        return {}
    applied: dict[str, list[str]] = {}

    def enum_values(key: str, enum_cls) -> list:
        allowed = {e.value: e for e in enum_cls if e.value != "unknown"}
        return list(dict.fromkeys(allowed[v] for v in _str_list(suggested.get(key)) if v in allowed))

    if not filters.employment_types and (types := enum_values("employment_types", EmploymentType)):
        filters.employment_types = types
        applied["employment_types"] = [t.value for t in types]
    if not filters.work_modes and (modes := enum_values("work_modes", WorkMode)):
        filters.work_modes = modes
        applied["work_modes"] = [m.value for m in modes]
    if not filters.locations and (locations := _str_list(suggested.get("locations"))[:3]):
        filters.locations = locations
        applied["locations"] = locations
    return applied


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]
