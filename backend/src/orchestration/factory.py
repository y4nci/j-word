# backend/src/orchestration/factory.py

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from discovery.discovery_service import DiscoveryService
from discovery.sources.adzuna_adapter import AdzunaAdapter
from discovery.sources.arbeitnow_adapter import ArbeitnowAdapter
from discovery.sources.base_adapter import BaseSourceAdapter
from discovery.sources.bundesagentur_adapter import BundesagenturAdapter
from discovery.sources.company_boards import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    PersonioAdapter,
    SmartRecruitersAdapter,
)
from drafting.drafting_service import DraftingService
from infra.llm_openai import AsyncOpenAIChatLLM
from onboarding.planning_service import PlanningService
from onboarding.profile_service import ProfileService
from orchestration.job_pipeline import PipelineDeps
from screening.screening_service import ScreeningService
from shared.enums import SourceName
from shared.llm import AsyncChatLLM
from submission.autofill import DEFAULT_SUBMITTERS
from submission.package_builder import PackageBuilder
from submission.submission_service import SubmissionService

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "outputs" / "applications"


def make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": "jword/0.1 (personal job search assistant)"},
        follow_redirects=True,
    )


def make_adapters(client: httpx.AsyncClient) -> dict[SourceName, BaseSourceAdapter]:
    """
    A fresh set of adapters per pipeline run: board/Arbeitnow adapters cache
    their fetched pages, which should not outlive one search.
    """
    adapters: dict[SourceName, BaseSourceAdapter] = {
        SourceName.ARBEITNOW: ArbeitnowAdapter(client),
        SourceName.BUNDESAGENTUR: BundesagenturAdapter(client),
        SourceName.GREENHOUSE: GreenhouseAdapter(client),
        SourceName.LEVER: LeverAdapter(client),
        SourceName.ASHBY: AshbyAdapter(client),
        SourceName.PERSONIO: PersonioAdapter(client),
        SourceName.SMARTRECRUITERS: SmartRecruitersAdapter(client),
    }
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if app_id and app_key:
        adapters[SourceName.ADZUNA] = AdzunaAdapter(client, app_id=app_id, app_key=app_key)
    return adapters


def make_llms() -> tuple[AsyncChatLLM, AsyncChatLLM]:
    """(general LLM, drafting LLM). Drafting benefits from a stronger model than bulk screening."""
    load_dotenv()
    llm = AsyncOpenAIChatLLM()
    drafting_model = os.getenv("OPENAI_MODEL_DRAFTING")
    return llm, (AsyncOpenAIChatLLM(drafting_model) if drafting_model else llm)


def build_deps(
    client: httpx.AsyncClient,
    *,
    llm: AsyncChatLLM | None = None,
    drafting_llm: AsyncChatLLM | None = None,
    output_dir: Path | None = None,
) -> PipelineDeps:
    """Cheap to call per request: adapters are fresh, LLM clients can be passed in and reused."""
    if llm is None:
        llm, drafting_llm = make_llms()
    drafting_llm = drafting_llm or llm
    return PipelineDeps(
        profiles=ProfileService(llm),
        planning=PlanningService(llm),
        discovery=DiscoveryService(make_adapters(client)),
        screening=ScreeningService(llm, max_concurrency=int(os.getenv("SCREENING_CONCURRENCY", "8"))),
        drafting=DraftingService(drafting_llm),
        submission=SubmissionService(PackageBuilder(output_dir or DEFAULT_OUTPUT_DIR), DEFAULT_SUBMITTERS),
    )

