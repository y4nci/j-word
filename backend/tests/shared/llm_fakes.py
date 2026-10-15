from __future__ import annotations

import json
from typing import Any

from shared.llm import AsyncChatLLM


class ScriptedLLM(AsyncChatLLM):
    """
    Fake LLM that picks a canned reply by matching a marker in the system prompt.
    `routes` maps marker -> reply (dict, str, or callable(user_prompt) -> dict|str).
    """

    model = "fake-llm"

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.3,
                   json_mode: bool = False) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        for marker, reply in self.routes.items():
            if marker in system_prompt:
                if callable(reply):
                    reply = reply(user_prompt)
                return reply if isinstance(reply, str) else json.dumps(reply)
        raise AssertionError(f"No scripted reply for prompt starting {system_prompt[:80]!r}")
