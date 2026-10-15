# backend/src/api/dependencies.py

from __future__ import annotations

from typing import AsyncIterator

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.repository import Repository
from orchestration.factory import build_deps
from orchestration.job_pipeline import JobPipeline


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def get_pipeline(
    request: Request,
    session: AsyncSession = Depends(get_session),
    http: httpx.AsyncClient = Depends(get_http_client),
) -> AsyncIterator[JobPipeline]:
    llm, drafting_llm = request.app.state.llms
    deps = build_deps(http, llm=llm, drafting_llm=drafting_llm)
    yield JobPipeline(deps, Repository(session))


async def get_repository(session: AsyncSession = Depends(get_session)) -> Repository:
    return Repository(session)
