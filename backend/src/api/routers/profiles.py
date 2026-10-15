# backend/src/api/routers/profiles.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_pipeline, get_repository
from db.repository import Repository
from infra.documents import combine_letters, extract_text
from onboarding.models import CandidateProfile, JobSearch
from orchestration.job_pipeline import JobPipeline

router = APIRouter(prefix="/profiles", tags=["profiles"])

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads"


@router.post("", response_model=CandidateProfile)
async def create_profile(
    cv: UploadFile = File(..., description="CV as PDF, TXT or MD"),
    proto_cover_letter: str = Form("", description="What you did in each job/project, in your own words"),
    proto_cover_letter_files: Optional[list[UploadFile]] = File(
        None, description="Any number of proto/previous cover letters (PDF, TXT, MD); combined with the text"
    ),
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    links: str = Form("{}", description='JSON, e.g. {"linkedin": "...", "github": "..."}'),
    pipeline: JobPipeline = Depends(get_pipeline),
) -> CandidateProfile:
    cv_bytes = await cv.read()
    try:
        cv_text = extract_text(cv.filename or "cv.pdf", cv_bytes)
        letters = [(f.filename or "letter.txt", extract_text(f.filename or "letter.txt", await f.read()))
                   for f in proto_cover_letter_files or []]
        parsed_links = json.loads(links or "{}")
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not cv_text:
        raise HTTPException(status_code=422, detail="Could not extract any text from the CV")
    proto_cover_letter = combine_letters(proto_cover_letter, letters)
    if not proto_cover_letter:
        raise HTTPException(status_code=422, detail="Provide a proto cover letter as text or at least one file")

    # Keep the original CV: it is attached to applications as-is.
    target = UPLOAD_DIR / str(uuid4()) / Path(cv.filename or "cv.pdf").name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(cv_bytes)

    return await pipeline.create_profile(
        cv_text=cv_text,
        proto_cover_letter=proto_cover_letter,
        cv_path=str(target),
        overrides={"full_name": full_name, "email": email, "phone": phone, "location": location,
                   "links": parsed_links},
    )


@router.get("", response_model=list[CandidateProfile])
async def list_profiles(repo: Repository = Depends(get_repository)) -> list[CandidateProfile]:
    return await repo.list_profiles()


@router.get("/{profile_id}/searches", response_model=list[JobSearch])
async def list_searches(profile_id: UUID, repo: Repository = Depends(get_repository)) -> list[JobSearch]:
    return await repo.list_searches(profile_id)


@router.get("/{profile_id}", response_model=CandidateProfile)
async def get_profile(profile_id: UUID, repo: Repository = Depends(get_repository)) -> CandidateProfile:
    profile = await repo.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@router.put("/{profile_id}", response_model=CandidateProfile)
async def update_profile(
    profile_id: UUID,
    profile: CandidateProfile,
    repo: Repository = Depends(get_repository),
) -> CandidateProfile:
    """Correct the extracted profile. Drafts only use facts from here, so it's worth reviewing once."""
    existing = await repo.get_profile(profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="profile not found")
    updated = profile.model_copy(update={"id": existing.id, "created_at": existing.created_at,
                                         "cv_path": existing.cv_path})
    await repo.save_profile(updated)
    return updated
