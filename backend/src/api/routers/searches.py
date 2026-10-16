# backend/src/api/routers/searches.py

from __future__ import annotations

from collections import Counter
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_pipeline, get_repository, get_runner
from api.schemas import ApplicationView, CreateSearchRequest, DraftAllRequest, SearchSummary
from applications.models import Application
from db.repository import Repository
from discovery.models import JobPosting
from onboarding.models import JobSearch, RunOptions, SearchRun
from orchestration.job_pipeline import JobPipeline
from orchestration.search_runner import SearchRunner
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


# ---------------- background full-search runs ---------------- #
@router.post("/{search_id}/run", response_model=SearchRun, status_code=202)
async def start_run(
    search_id: UUID,
    options: RunOptions = RunOptions(),
    runner: SearchRunner = Depends(get_runner),
) -> SearchRun:
    """Start discover -> screen (-> draft) in the background. Poll GET /searches/{id}/run."""
    return await runner.start(search_id, options)


@router.get("/{search_id}/run", response_model=Optional[SearchRun])
async def run_status(search_id: UUID, runner: SearchRunner = Depends(get_runner)) -> Optional[SearchRun]:
    return await runner.status(search_id)


@router.post("/{search_id}/run/cancel", response_model=Optional[SearchRun])
async def cancel_run(search_id: UUID, runner: SearchRunner = Depends(get_runner)) -> Optional[SearchRun]:
    """Stop the running job. Everything screened so far is kept."""
    return await runner.cancel(search_id)
