# backend/src/onboarding/profile_service.py

from __future__ import annotations

import logging
from typing import Optional

from onboarding.models import CandidateProfile, Experience
from shared.json_utils import chat_json
from shared.llm import AsyncChatLLM

logger = logging.getLogger(__name__)

_PROFILE_SYSTEM_PROMPT = """You turn a candidate's CV and their "proto cover letter" into a structured profile.

The proto cover letter is the candidate's own description of what they did in each job/project.
It is the most detailed source: merge it into the matching experience's "summary" and "highlights".
It may consist of several documents (e.g. earlier cover letters), each starting with a
"--- filename ---" header. Combine what they say about the same experience into ONE experience;
don't create duplicates.

Rules:
- Use ONLY facts present in the inputs. Never invent employers, dates, numbers, tools or achievements.
- Keep the candidate's own wording for concrete achievements where possible.
- If the proto letter describes something not in the CV, add it as its own experience.
- "skills" are concrete technologies/methods (e.g. "Python", "FastAPI", "A/B testing"), deduplicated.

Return STRICT JSON only:
{
  "full_name": "...", "email": "...", "phone": "... or null", "location": "... or null",
  "links": {"linkedin": "...", "github": "..."},
  "headline": "one-line professional summary",
  "skills": ["..."],
  "languages": ["German (C1)", "..."],
  "experiences": [
    {"kind": "job|project|education|volunteering|other", "title": "...", "organization": "... or null",
     "start": "YYYY-MM or null", "end": "YYYY-MM, 'present' or null",
     "summary": "3-6 sentences on what the candidate actually did",
     "skills": ["..."], "highlights": ["concrete, verifiable outcomes"]}
  ]
}
"""


class ProfileService:
    def __init__(self, llm: AsyncChatLLM) -> None:
        self._llm = llm

    async def build_profile(
        self,
        *,
        cv_text: str,
        proto_cover_letter: str,
        cv_path: Optional[str] = None,
        overrides: Optional[dict] = None,
    ) -> CandidateProfile:
        """
        Extract a CandidateProfile with the LLM. `overrides` (name, email, phone, ...)
        typed in by the user always win over extracted values.
        """
        data = await chat_json(
            self._llm,
            system_prompt=_PROFILE_SYSTEM_PROMPT,
            user_prompt=f"CV:\n{cv_text}\n\nPROTO COVER LETTER:\n{proto_cover_letter}",
        )

        raw_experiences = data.get("experiences") if isinstance(data.get("experiences"), list) else []
        experiences = [
            _to_experience(f"exp-{i}", raw)
            for i, raw in enumerate((r for r in raw_experiences if isinstance(r, dict) and r.get("title")), start=1)
        ]

        fields = {
            "full_name": _text(data.get("full_name")) or "",
            "email": _text(data.get("email")) or "",
            "phone": _text(data.get("phone")),
            "location": _text(data.get("location")),
            "headline": _text(data.get("headline")) or "",
            "skills": _str_list(data.get("skills")),
            "languages": _str_list(data.get("languages")),
            "links": _links(data.get("links")),
        }
        fields.update({k: v for k, v in (overrides or {}).items() if v})

        profile = CandidateProfile(
            **fields,
            experiences=experiences,
            cv_text=cv_text,
            cv_path=cv_path,
            proto_cover_letter=proto_cover_letter,
        )
        logger.info("Built profile with %d experiences, %d skills", len(experiences), len(profile.skills))
        return profile


# ---------------------------------------------------------------------- #
# LLM output normalisation: the model doesn't always stick to the schema
# (e.g. kind="internship", skills as one comma-separated string). Coerce
# instead of failing the whole profile.
# ---------------------------------------------------------------------- #
_KINDS = {"job", "project", "education", "volunteering", "other"}
_KIND_ALIASES = {
    "internship": "job", "intern": "job", "work": "job", "employment": "job", "work experience": "job",
    "working student": "job", "werkstudent": "job", "freelance": "job", "part-time job": "job",
    "thesis": "project", "research": "project", "publication": "project", "side project": "project",
    "degree": "education", "course": "education", "certificate": "education", "certification": "education",
    "volunteer": "volunteering", "volunteer work": "volunteering",
}


def _to_experience(exp_id: str, raw: dict) -> Experience:
    kind = (_text(raw.get("kind")) or "other").lower()
    return Experience(
        id=exp_id,
        kind=kind if kind in _KINDS else _KIND_ALIASES.get(kind, "other"),
        title=_text(raw.get("title")) or "",
        organization=_text(raw.get("organization")),
        start=_text(raw.get("start")),
        end=_text(raw.get("end")),
        summary=_text(raw.get("summary")) or "",
        skills=_str_list(raw.get("skills")),
        highlights=_str_list(raw.get("highlights"), split=False),
    )


def _text(value) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "n/a"} else None


def _str_list(value, *, split: bool = True) -> list[str]:
    """List of non-empty strings. A plain string is split on commas (skills) or kept whole (sentences)."""
    if isinstance(value, str):
        value = value.split(",") if split else [value]
    if not isinstance(value, list):
        return []
    return [t for v in value if (t := _text(v))]


def _links(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): t for k, v in value.items() if (t := _text(v))}
