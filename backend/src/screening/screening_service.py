# backend/src/screening/screening_service.py

from __future__ import annotations

import asyncio
import logging

from applications.models import ScreeningDecision
from discovery.models import JobPosting
from onboarding.models import CandidateProfile, JobSearch
from shared.enums import ActorType, ScreeningOutcome
from shared.json_utils import chat_json
from shared.llm import AsyncChatLLM

logger = logging.getLogger(__name__)

_SCREENING_SYSTEM_PROMPT = """You are a careful career advisor screening job postings for one candidate.

Decide whether the candidate should apply: INCLUDE, EXCLUDE or UNSURE, based on
1) the candidate's request (what they are looking for),
2) the screening criteria derived from that request,
3) the hard filters (work mode, employment type, location) - the posting may not state them clearly,
4) the candidate's profile vs. the posting's requirements.

Guidance:
- EXCLUDE if the posting clearly contradicts the request or a hard filter, requires a language
  the candidate doesn't speak, or demands far more seniority/experience than the profile shows.
- INCLUDE if it clearly matches the request and the candidate meets most must-have requirements.
- UNSURE if it's plausible but key information is missing or the fit is borderline.
- Do not penalize missing nice-to-haves heavily.

fit_score: 1.0 = ideal match, ~0.7-0.9 strong, ~0.4-0.6 partial, near 0.0 irrelevant.

Return STRICT JSON only:
{
  "outcome": "include" | "exclude" | "unsure",
  "fit_score": <float 0..1>,
  "confidence": <float 0..1>,
  "reason": "1-2 concrete sentences",
  "matched_requirements": ["requirement the candidate clearly meets", "..."],
  "missing_requirements": ["must-have the candidate lacks or that is unclear", "..."],
  "dealbreakers": ["optional"]
}
"""


class ScreeningService:
    """LLM fit screening for jobs that passed the hard filters."""

    def __init__(self, llm: AsyncChatLLM, *, max_concurrency: int = 8) -> None:
        self._llm = llm
        self._max_concurrency = max_concurrency

    async def screen_many(
        self,
        search: JobSearch,
        profile: CandidateProfile,
        jobs: list[JobPosting],
    ) -> dict[str, ScreeningDecision]:
        """Return decisions keyed by str(job.id)."""
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def one(job: JobPosting) -> tuple[str, ScreeningDecision]:
            async with semaphore:
                return str(job.id), await self.screen(search, profile, job)

        return dict(await asyncio.gather(*(one(j) for j in jobs)))

    async def screen(self, search: JobSearch, profile: CandidateProfile, job: JobPosting) -> ScreeningDecision:
        plan = search.plan
        f = search.filters
        criteria = "\n".join(f"- {c}" for c in (plan.screening_criteria if plan else [])) or "(none)"
        user_prompt = (
            f"CANDIDATE REQUEST:\n{search.prompt}\n\n"
            f"REFINED GOAL: {plan.refined_goal if plan else search.prompt}\n\n"
            f"SCREENING CRITERIA:\n{criteria}\n\n"
            f"HARD FILTERS: work modes={[m.value for m in f.work_modes] or 'any'}, "
            f"employment={[e.value for e in f.employment_types] or 'any'}, locations={f.locations or 'any'}\n\n"
            f"CANDIDATE PROFILE:\n{profile.compact()}\n\n"
            f"JOB POSTING:\n{job.for_prompt()}"
        )
        try:
            data = await chat_json(self._llm, system_prompt=_SCREENING_SYSTEM_PROMPT, user_prompt=user_prompt)
        except Exception as exc:  # one bad job must not fail the batch
            logger.warning("Screening failed for job %s: %s", job.id, exc)
            return ScreeningDecision(
                outcome=ScreeningOutcome.UNSURE,
                reason=f"Automatic screening failed: {exc}",
                model_name=getattr(self._llm, "model", None),
            )
        return _to_decision(data, getattr(self._llm, "model", None))


def _to_decision(data: dict, model_name: str | None) -> ScreeningDecision:
    try:
        outcome = ScreeningOutcome(str(data.get("outcome", "unsure")).lower())
    except ValueError:
        outcome = ScreeningOutcome.UNSURE
    return ScreeningDecision(
        outcome=outcome,
        fit_score=_clamp(data.get("fit_score")),
        confidence=_clamp(data.get("confidence")),
        reason=str(data.get("reason") or ""),
        matched_requirements=[str(x) for x in data.get("matched_requirements") or []],
        missing_requirements=[str(x) for x in data.get("missing_requirements") or []],
        dealbreakers=[str(x) for x in data.get("dealbreakers") or []],
        actor_type=ActorType.AGENT,
        model_name=model_name,
    )


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
