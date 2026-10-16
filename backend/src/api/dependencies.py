# backend/src/api/dependencies.py

from __future__ import annotations

from typing import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.repository import Repository
from orchestration.factory import build_deps
from orchestration.job_pipeline import JobPipeline, PipelineDeps
from orchestration.search_runner import SearchRunner


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def get_pipeline(
    request: Request,
    session: AsyncSession = Depends(get_session),
    http: httpx.AsyncClient = Depends(get_http_client),
) -> AsyncIterator[JobPipeline]:
    yield JobPipeline(pipeline_deps(request.app), Repository(session))


def pipeline_deps(app: FastAPI) -> PipelineDeps:
    """Fresh deps (adapters cache per search) around the app's shared HTTP and LLM clients."""
    llm, drafting_llm = app.state.llms
    return build_deps(app.state.http, llm=llm, drafting_llm=drafting_llm)


def get_runner(request: Request) -> SearchRunner:
    return request.app.state.runner


async def get_repository(session: AsyncSession = Depends(get_session)) -> Repository:
    return Repository(session)
