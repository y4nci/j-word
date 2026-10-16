# backend/src/screening/screening_service.py

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from applications.models import ScreeningDecision
from discovery.models import JobPosting, JobSummary
from onboarding.models import CandidateProfile, JobSearch
from shared.enums import ActorType, ScreeningOutcome
from shared.json_utils import chat_json
from shared.llm import AsyncChatLLM
from shared.progress import Progress, noop_progress

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
- Postings often offer several employment types (e.g. "Vollzeit / Teilzeit", "full time or part time").
  If ANY offered type fits the request, the employment type is compatible: never list the other
  option as a dealbreaker.
- Only list something as a dealbreaker if the posting REQUIRES it; "nice to have" German is not
  a dealbreaker for a candidate without fluent German.

fit_score: 1.0 = ideal match, ~0.7-0.9 strong, ~0.4-0.6 partial, near 0.0 irrelevant.

Return STRICT JSON only:
{
  "outcome": "include" | "exclude" | "unsure",
  "fit_score": <float 0..1>,
  "confidence": <float 0..1>,
  "reason": "1-2 concrete sentences",
  "matched_requirements": ["requirement the candidate clearly meets", "..."],
  "missing_requirements": ["must-have the candidate lacks or that is unclear", "..."],
  "dealbreakers": ["optional"],
  "summary": {
    "short_description": "1-2 plain sentences: what the person in this role actually does",
    "pay": "pay exactly as stated, e.g. '15 €/hour' or '48-55k €/year', else null",
    "hours": "working hours as stated, e.g. '20 h/week', else null",
    "employment": "e.g. 'Werkstudent (part time)', 'full time, permanent', else null",
    "work_mode": "e.g. 'remote', 'hybrid, 2 office days/week', 'on-site', else null",
    "location": "city/region as stated, else null",
    "start": "start date as stated, e.g. 'ASAP', else null",
    "duration": "contract length as stated, e.g. '6 months', 'permanent', else null",
    "languages": ["languages the role requires"],
    "key_requirements": ["the 3 most important must-haves"]
  }
}

The summary describes the POSTING, not the candidate. Only report what the posting states:
never estimate pay, hours or dates; use null when the posting doesn't say. Write the summary
in English even if the posting is in German.
"""


@dataclass
class ScreeningResult:
    decision: ScreeningDecision
    summary: Optional[JobSummary]  # None if the LLM call failed or returned no usable summary


class ScreeningService:
    """LLM fit screening for jobs that passed the hard filters. Also extracts a JobSummary per job."""

    def __init__(self, llm: AsyncChatLLM, *, max_concurrency: int = 8) -> None:
        self._llm = llm
        self._max_concurrency = max_concurrency

    async def screen_many(
        self,
        search: JobSearch,
        profile: CandidateProfile,
        jobs: list[JobPosting],
        on_progress: Progress = noop_progress,
    ) -> dict[str, ScreeningResult]:
        """Return results keyed by str(job.id)."""
        semaphore = asyncio.Semaphore(self._max_concurrency)
        done = 0

        async def one(job: JobPosting) -> tuple[str, ScreeningResult]:
            nonlocal done
            async with semaphore:
                result = await self.screen(search, profile, job)
            done += 1
            on_progress(done, len(jobs), f"screened {job.title[:60]!r}: {result.decision.outcome.value}")
            return str(job.id), result

        return dict(await asyncio.gather(*(one(j) for j in jobs)))

    async def screen(self, search: JobSearch, profile: CandidateProfile, job: JobPosting) -> ScreeningResult:
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
            return ScreeningResult(
                ScreeningDecision(
                    outcome=ScreeningOutcome.UNSURE,
                    reason=f"Automatic screening failed: {exc}",
                    model_name=getattr(self._llm, "model", None),
                ),
                summary=None,
            )
        return ScreeningResult(_to_decision(data, getattr(self._llm, "model", None)), _to_summary(data.get("summary")))


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


def _to_summary(raw) -> Optional[JobSummary]:
    if not isinstance(raw, dict):
        return None

    def text(key: str) -> Optional[str]:
        value = raw.get(key)
        if value is None or isinstance(value, (dict, list)):
            return None
        value = str(value).strip()
        return value if value and value.lower() not in {"null", "none", "n/a", "unknown", "not stated"} else None

    def items(key: str) -> list[str]:
        value = raw.get(key)
        value = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        return [str(v).strip() for v in value if v is not None and str(v).strip()]

    summary = JobSummary(
        short_description=text("short_description") or "",
        pay=text("pay"), hours=text("hours"), employment=text("employment"), work_mode=text("work_mode"),
        location=text("location"), start=text("start"), duration=text("duration"),
        languages=items("languages"), key_requirements=items("key_requirements")[:5],
    )
    return summary if summary.model_dump(exclude_defaults=True) else None


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
