from __future__ import annotations

from typing import Protocol


class AsyncChatLLM(Protocol):
    """
    Minimal interface for a chat-style LLM that returns a single assistant
    message as plain text.

    Domain code (onboarding, screening, drafting) depends on *this*,
    not on any concrete provider.
    """

    model: str

    async def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str: ...
