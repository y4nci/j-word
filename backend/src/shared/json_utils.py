from __future__ import annotations

import json
import logging
import re
from typing import Any

from shared.llm import AsyncChatLLM

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMJSONError(ValueError):
    pass


def parse_json_object(text: str) -> dict[str, Any]:
    """
    Parse the first JSON object in an LLM reply.
    Tolerates code fences and leading/trailing prose.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMJSONError(f"No JSON object in LLM reply: {text[:200]!r}")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMJSONError(f"Invalid JSON in LLM reply: {exc}") from exc

    if not isinstance(value, dict):
        raise LLMJSONError("LLM reply is JSON but not an object")
    return value


async def chat_json(
    llm: AsyncChatLLM,
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    retries: int = 1,
) -> dict[str, Any]:
    """Run a chat call that must return a JSON object, retrying on malformed output."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        reply = await llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            json_mode=True,
        )
        try:
            return parse_json_object(reply)
        except LLMJSONError as exc:
            last_error = exc
            logger.warning("Malformed JSON from LLM (attempt %d): %s", attempt + 1, exc)
    raise LLMJSONError(str(last_error))
