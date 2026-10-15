# backend/src/api/routers/applications.py
"""
Human-in-the-loop endpoints. The approval rules themselves are enforced in
applications.models.Application; these routes only expose them.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from api.dependencies import get_pipeline, get_repository
from api.schemas import ApplicationView, DraftEditRequest, NoteRequest, PrepareRequest, ScreeningOverrideRequest
from applications.models import Application
from db.repository import Repository
from orchestration.job_pipeline import JobPipeline

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/{application_id}", response_model=ApplicationView)
async def get_application(application_id: UUID, repo: Repository = Depends(get_repository)) -> ApplicationView:
    app = await repo.get_application(application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="application not found")
    return ApplicationView(application=app, job=await repo.get_job(app.job_id))


@router.get("/{application_id}/cover-letter.pdf", response_class=FileResponse)
async def cover_letter_pdf(application_id: UUID, repo: Repository = Depends(get_repository)) -> FileResponse:
    """Serve the generated PDF. Only the path stored on the application is ever served."""
    app = await repo.get_application(application_id)
    if app is None or app.package is None or not Path(app.package.cover_letter_pdf).exists():
        raise HTTPException(status_code=404, detail="no cover letter PDF yet; prepare the application first")
    return FileResponse(app.package.cover_letter_pdf, media_type="application/pdf")


@router.post("/{application_id}/screening", response_model=Application)
async def override_screening(application_id: UUID, body: ScreeningOverrideRequest,
                             pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    return await pipeline.override_screening(application_id, body.outcome, body.reason)


@router.post("/{application_id}/draft", response_model=Application)
async def draft(application_id: UUID, pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    """(Re)generate the draft for one application."""
    return await pipeline.draft_one(application_id)


@router.patch("/{application_id}/draft", response_model=Application)
async def edit_draft(application_id: UUID, body: DraftEditRequest,
                     pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    """Edit the draft. Re-runs the fact check and clears any previous approval."""
    return await pipeline.edit_draft(application_id, **body.model_dump())


@router.post("/{application_id}/approve", response_model=Application)
async def approve(application_id: UUID, body: NoteRequest = NoteRequest(),
                  pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    return await pipeline.approve(application_id, body.note)


@router.post("/{application_id}/reject", response_model=Application)
async def reject(application_id: UUID, body: NoteRequest = NoteRequest(),
                 pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    return await pipeline.reject(application_id, body.note)


@router.post("/{application_id}/prepare", response_model=Application)
async def prepare(application_id: UUID, request: Request, body: PrepareRequest = PrepareRequest(),
                  pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    """
    Approved applications only: write the package and, for Greenhouse/Lever/Ashby,
    open a browser window with the form filled in. You submit it yourself.
    """
    app, session = await pipeline.prepare(application_id, autofill=body.autofill)
    if session is not None:
        request.app.state.autofill_sessions[str(application_id)] = session
    return app


@router.post("/{application_id}/mark-applied", response_model=Application)
async def mark_applied(application_id: UUID, body: NoteRequest = NoteRequest(),
                       pipeline: JobPipeline = Depends(get_pipeline)) -> Application:
    return await pipeline.mark_applied(application_id, body.note)
