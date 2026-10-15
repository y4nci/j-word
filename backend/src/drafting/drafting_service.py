# backend/src/drafting/drafting_service.py
"""
Drafting = autoreview's RAG + synthesis, adapted:

  1. match   - extract the posting's key requirements and map each one to the
               candidate's experiences (by id). This is the retrieval step; a
               profile is small enough that the LLM can select from the whole
               list, so no vector DB is needed.
  2. write   - write the cover letter using ONLY the selected experiences, in
               the posting's language, in the candidate's own voice.
  3. verify  - a second pass lists every statement in the letter that the
               profile does not support. These are shown at approval time.
"""

from __future__ import annotations

import logging

from applications.models import ApplicationDraft, RequirementMatch, UnsupportedClaim
from discovery.models import JobPosting
from onboarding.models import CandidateProfile, Experience, JobSearch
from shared.json_utils import chat_json
from shared.llm import AsyncChatLLM
from shared.text import truncate

logger = logging.getLogger(__name__)

_MATCH_SYSTEM_PROMPT = """You prepare a job application. Map the posting's requirements to the candidate's experiences.

- key_requirements: the 4-8 most important requirements of the posting (must-haves first).
- For each, list the ids of experiences that give real evidence for it (may be empty) and
  quote/paraphrase that evidence from the experience text. Never stretch evidence.
- selected_experience_ids: the 2-4 experiences that make the strongest case for THIS job.
- company_hook: one specific, factual thing from the posting worth referring to
  (product, mission, tech, team). Empty string if nothing specific.
- language: "de" if the posting is written in German, otherwise "en".

Return STRICT JSON only:
{
  "language": "de" | "en",
  "key_requirements": ["..."],
  "requirement_matches": [{"requirement": "...", "experience_ids": ["exp-1"], "evidence": "..."}],
  "selected_experience_ids": ["exp-1", "exp-3"],
  "company_hook": "..."
}
"""

_WRITE_SYSTEM_PROMPT = """You write a cover letter for the candidate, in their voice.

Hard rules:
- Use ONLY facts from the SELECTED EXPERIENCES and the profile basics. Do not invent numbers,
  tools, employers, responsibilities, motivations or personal anecdotes.
- If a requirement is not covered by the experiences, do not claim it. You may express
  willingness to learn it, once, briefly.
- Write in the requested language. German letters use "Sie" unless the posting uses "du".
- Match the tone and phrasing of the candidate's own writing sample, but fix errors.
- 250-380 words, 3-5 paragraphs, no bullet points, no placeholders like [Company].
- Start with the salutation (e.g. "Dear Hiring Team," / "Sehr geehrte Damen und Herren,"),
  end with a closing and the candidate's full name.
- Be specific to this posting; avoid generic filler ("I am writing to express my interest").

Also produce:
- subject: the letter's subject line (e.g. "Application for <title>" / "Bewerbung als <title>").
- short_pitch: 2-3 sentences for an "anything else you want to tell us?" form field, same rules.

Return STRICT JSON only:
{"subject": "...", "cover_letter": "...", "short_pitch": "...", "used_experience_ids": ["exp-1"]}
"""

_VERIFY_SYSTEM_PROMPT = """You fact-check a cover letter against the candidate's profile.

List every statement about the candidate (skills, experience, achievements, numbers, roles, dates,
education, languages) that is NOT supported by the profile. Opinions, enthusiasm and statements
about the company are fine. Willingness to learn is fine.

Return STRICT JSON only:
{"unsupported_claims": [{"claim": "exact sentence or phrase", "why": "what is missing in the profile"}]}
"""


class DraftingService:
    def __init__(self, llm: AsyncChatLLM) -> None:
        self._llm = llm

    async def draft(self, search: JobSearch, profile: CandidateProfile, job: JobPosting) -> ApplicationDraft:
        match = await self._match(profile, job)
        selected = [e for eid in match["selected_experience_ids"] if (e := profile.experience(eid))]
        if not selected:  # fall back to the most recent experiences rather than writing from nothing
            selected = profile.experiences[:3]

        written = await self._write(search, profile, job, match, selected)
        unsupported = await self._verify(profile, written["cover_letter"] + "\n\n" + written["short_pitch"])

        known_ids = {e.id for e in profile.experiences}
        return ApplicationDraft(
            language=match["language"],
            subject=written["subject"],
            cover_letter=written["cover_letter"],
            short_pitch=written["short_pitch"],
            requirement_matches=match["requirement_matches"],
            used_experience_ids=[i for i in written["used_experience_ids"] if i in known_ids],
            unsupported_claims=unsupported,
            model_name=getattr(self._llm, "model", None),
        )

    async def recheck(self, profile: CandidateProfile, draft: ApplicationDraft) -> list[UnsupportedClaim]:
        """Re-run the fact check after a human edit."""
        return await self._verify(profile, draft.cover_letter + "\n\n" + draft.short_pitch)

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #
    async def _match(self, profile: CandidateProfile, job: JobPosting) -> dict:
        user_prompt = f"JOB POSTING:\n{job.for_prompt()}\n\nCANDIDATE EXPERIENCES:\n{_experiences_block(profile.experiences)}"
        data = await chat_json(self._llm, system_prompt=_MATCH_SYSTEM_PROMPT, user_prompt=user_prompt)

        language = data.get("language") if data.get("language") in {"de", "en"} else (job.language or "en")
        matches = [
            RequirementMatch(
                requirement=str(m.get("requirement") or ""),
                experience_ids=[str(i) for i in m.get("experience_ids") or []],
                evidence=str(m.get("evidence") or ""),
            )
            for m in data.get("requirement_matches") or []
            if isinstance(m, dict) and m.get("requirement")
        ]
        return {
            "language": language,
            "requirement_matches": matches,
            "selected_experience_ids": [str(i) for i in data.get("selected_experience_ids") or []],
            "company_hook": str(data.get("company_hook") or ""),
        }

    async def _write(
        self,
        search: JobSearch,
        profile: CandidateProfile,
        job: JobPosting,
        match: dict,
        selected: list[Experience],
    ) -> dict:
        coverage = "\n".join(
            f"- {m.requirement}: {', '.join(m.experience_ids) or 'NOT COVERED'}" for m in match["requirement_matches"]
        )
        user_prompt = (
            f"LANGUAGE: {'German' if match['language'] == 'de' else 'English'}\n\n"
            f"CANDIDATE: {profile.full_name}, {profile.headline}\n"
            f"Languages: {', '.join(profile.languages) or 'n/a'}\n\n"
            f"WHAT THE CANDIDATE IS LOOKING FOR:\n{search.prompt}\n\n"
            f"JOB POSTING:\n{job.for_prompt(max_description_chars=5000)}\n\n"
            f"COMPANY HOOK: {match['company_hook'] or '(none)'}\n\n"
            f"REQUIREMENT COVERAGE:\n{coverage or '(none)'}\n\n"
            f"SELECTED EXPERIENCES (the only facts you may use):\n{_experiences_block(selected)}\n\n"
            f"CANDIDATE'S OWN WRITING SAMPLE (for tone only):\n{truncate(profile.proto_cover_letter, 2500)}"
        )
        data = await chat_json(self._llm, system_prompt=_WRITE_SYSTEM_PROMPT, user_prompt=user_prompt, temperature=0.5)
        return {
            "subject": str(data.get("subject") or f"Application: {job.title}"),
            "cover_letter": str(data.get("cover_letter") or "").strip(),
            "short_pitch": str(data.get("short_pitch") or "").strip(),
            "used_experience_ids": [str(i) for i in data.get("used_experience_ids") or []],
        }

    async def _verify(self, profile: CandidateProfile, text: str) -> list[UnsupportedClaim]:
        user_prompt = (
            f"PROFILE:\n{profile.compact()}\n\nFULL EXPERIENCE DETAILS:\n{_experiences_block(profile.experiences)}"
            f"\n\nCOVER LETTER:\n{text}"
        )
        try:
            data = await chat_json(self._llm, system_prompt=_VERIFY_SYSTEM_PROMPT, user_prompt=user_prompt, temperature=0.0)
        except Exception as exc:
            logger.warning("Fact check failed: %s", exc)
            return [UnsupportedClaim(claim="(fact check did not run)", why=str(exc))]
        return [
            UnsupportedClaim(claim=str(c.get("claim") or ""), why=str(c.get("why") or ""))
            for c in data.get("unsupported_claims") or []
            if isinstance(c, dict) and c.get("claim")
        ]


def _experiences_block(experiences: list[Experience]) -> str:
    parts = []
    for e in experiences:
        when = " - ".join(x for x in (e.start, e.end) if x)
        header = f"[{e.id}] {e.title}" + (f" @ {e.organization}" if e.organization else "") + (f" ({when})" if when else "")
        body = e.summary
        if e.highlights:
            body += "\nHighlights: " + "; ".join(e.highlights)
        if e.skills:
            body += "\nSkills: " + ", ".join(e.skills)
        parts.append(f"{header}\n{body}")
    return "\n\n".join(parts) or "(none)"
