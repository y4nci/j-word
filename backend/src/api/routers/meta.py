# backend/src/api/routers/meta.py

from __future__ import annotations

from fastapi import APIRouter

from discovery.sources.default_boards import DEFAULT_BOARDS
from onboarding.models import CompanyBoard

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/default-boards", response_model=list[CompanyBoard])
async def default_boards() -> list[CompanyBoard]:
    """The built-in company boards searched when `use_default_boards` is on."""
    return DEFAULT_BOARDS
