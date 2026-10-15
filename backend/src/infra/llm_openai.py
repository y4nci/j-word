from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from shared.llm import AsyncChatLLM


class AsyncOpenAIChatLLM(AsyncChatLLM):
    """
    OpenAI implementation of AsyncChatLLM.

    This is the *only* place that knows about:
      - OpenAI SDK
      - API keys / env vars
      - model names
    """

    def __init__(self, model: Optional[str] = None, *, api_key: Optional[str] = None, load_env: bool = True) -> None:
        if load_env:
            load_dotenv()

        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env")

        self._client = AsyncOpenAI(api_key=key)
        self.model = model or os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini")

    async def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            **kwargs,
        )
        return resp.choices[0].message.content or ""
