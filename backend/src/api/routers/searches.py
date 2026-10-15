# backend/src/api/routers/searches.py

from __future__ import annotations

from collections import Counter
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_pipeline, get_repository
from api.schemas import ApplicationView, CreateSearchRequest, DraftAllRequest, SearchSummary
from applications.models import Application
from db.repository import Repository
from discovery.models import JobPosting
from onboarding.models import JobSearch
from orchestration.job_pipeline import JobPipeline
from shared.enums import ApplicationStatus

router = APIRouter(prefix="/searches", tags=["searches"])


def _summary(search_id: UUID, rows: list[tuple[Application, JobPosting]]) -> SearchSummary:
    rows = sorted(rows, key=lambda r: -(r[0].latest_decision.fit_score if r[0].latest_decision else -1))
    return SearchSummary(
        search_id=search_id,
        counts=dict(Counter(a.status.value for a, _ in rows)),
        applications=[ApplicationView(application=a, job=j) for a, j in rows],
    )


@router.post("", response_model=JobSearch)
async def create_search(body: CreateSearchRequest, pipeline: JobPipeline = Depends(get_pipeline)) -> JobSearch:
    """Create a search and let the LLM plan queries + screening criteria."""
    return await pipeline.create_search(body.profile_id, body.prompt, body.filters)


@router.get("/{search_id}", response_model=JobSearch)
async def get_search(search_id: UUID, repo: Repository = Depends(get_repository)) -> JobSearch:
    search = await repo.get_search(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="search not found")
    return search


@router.post("/{search_id}/discover", response_model=SearchSummary)
async def discover(search_id: UUID, pipeline: JobPipeline = Depends(get_pipeline)) -> SearchSummary:
    return _summary(search_id, await pipeline.discover(search_id))


@router.post("/{search_id}/screen", response_model=SearchSummary)
async def screen(search_id: UUID, pipeline: JobPipeline = Depends(get_pipeline)) -> SearchSummary:
    return _summary(search_id, await pipeline.screen(search_id))


@router.post("/{search_id}/draft", response_model=list[Application])
async def draft_all(
    search_id: UUID,
    body: DraftAllRequest = DraftAllRequest(),
    pipeline: JobPipeline = Depends(get_pipeline),
) -> list[Application]:
    """Draft cover letters for every screened-in job (optionally above a fit threshold)."""
    return await pipeline.draft_all(search_id, min_fit=body.min_fit)


@router.get("/{search_id}/applications", response_model=SearchSummary)
async def list_applications(
    search_id: UUID,
    status: Optional[list[ApplicationStatus]] = Query(None),
    repo: Repository = Depends(get_repository),
) -> SearchSummary:
    return _summary(search_id, await repo.list_applications(search_id, status))
