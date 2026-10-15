"""End-to-end pipeline run with a scripted LLM, a fake job source and a temp SQLite DB."""

import asyncio
from pathlib import Path

import pytest

from applications.models import InvalidTransition
from db.database import create_tables, make_engine
from db.repository import Repository
from discovery.discovery_service import DiscoveryService
from discovery.models import JobPosting
from discovery.sources.base_adapter import BaseSourceAdapter
from drafting.drafting_service import DraftingService
from onboarding.models import JobFilters
from onboarding.planning_service import PlanningService
from onboarding.profile_service import ProfileService
from orchestration.job_pipeline import JobPipeline, PipelineDeps
from screening.screening_service import ScreeningService
from shared.enums import ApplicationStatus as S, ScreeningOutcome, SourceName, WorkMode
from sqlalchemy.ext.asyncio import async_sessionmaker
from submission.package_builder import PackageBuilder
from submission.submission_service import SubmissionService
from tests.shared.llm_fakes import ScriptedLLM

LONG = " Python FastAPI PostgreSQL Docker. " * 20


class FakeSource(BaseSourceAdapter):
    source = SourceName.ARBEITNOW

    def __init__(self):
        super().__init__(client=None)
        self.queries = []

    async def search(self, query, filters):
        self.queries.append(query.keywords)
        return [
            JobPosting(source=self.source, external_id="1", title="Python Developer", company="Good Co",
                       location="Berlin", work_mode=WorkMode.REMOTE, description=LONG, url="https://x/1"),
            JobPosting(source=self.source, external_id="2", title="Backend Engineer", company="Maybe Co",
                       location="Berlin", description=LONG, url="https://x/2"),
            JobPosting(source=self.source, external_id="3", title="Office Python Dev", company="Onsite Co",
                       location="Berlin", work_mode=WorkMode.ONSITE, description=LONG, url="https://x/3"),
        ]


def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM({
        "into a structured profile": {
            "full_name": "Extracted Name", "email": "x@example.com", "headline": "CS student, backend focus",
            "skills": ["Python", "FastAPI"], "languages": ["English (C1)"],
            "experiences": [
                {"kind": "project", "title": "AutoReview", "organization": "TU Berlin",
                 "summary": "Built an LLM pipeline for literature reviews with FastAPI.", "skills": ["Python"]},
                {"kind": "job", "title": "Working student", "organization": "Shop GmbH", "summary": "Maintained APIs."},
                {"title": None},
            ],
        },
        "You plan a job search": {
            "refined_goal": "Remote junior Python backend roles", "target_titles": ["Python Developer"],
            "keywords": ["python developer", "backend engineer"], "screening_criteria": ["Python is core"],
        },
        "screening job postings": lambda prompt: (
            {"outcome": "include", "fit_score": 0.9, "confidence": 0.8, "reason": "Python backend match"}
            if "Title: Python Developer" in prompt else
            {"outcome": "unsure", "fit_score": 0.5, "confidence": 0.4, "reason": "Stack unclear"}
        ),
        "Map the posting's requirements": {
            "language": "en", "key_requirements": ["Python"],
            "requirement_matches": [{"requirement": "Python", "experience_ids": ["exp-1"], "evidence": "AutoReview"}],
            "selected_experience_ids": ["exp-1", "exp-99"], "company_hook": "",
        },
        "You write a cover letter": {
            "subject": "Application: Python Developer", "cover_letter": "Dear Hiring Team,\n\nI built AutoReview.",
            "short_pitch": "I build LLM pipelines.", "used_experience_ids": ["exp-1", "exp-404"],
        },
        "You fact-check a cover letter": {"unsupported_claims": []},
    })


def test_full_pipeline_with_human_gate(tmp_path: Path):
    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        await create_tables(engine)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF-fake")
        llm = scripted_llm()
        source = FakeSource()
        deps = PipelineDeps(
            profiles=ProfileService(llm), planning=PlanningService(llm),
            discovery=DiscoveryService({SourceName.ARBEITNOW: source}),
            screening=ScreeningService(llm), drafting=DraftingService(llm),
            submission=SubmissionService(PackageBuilder(tmp_path / "out"), submitters=[]),
        )

        async with Session() as session:
            pipeline = JobPipeline(deps, Repository(session))
            profile = await pipeline.create_profile(
                cv_text="CV text", proto_cover_letter="In AutoReview I built...", cv_path=str(cv),
                overrides={"full_name": "Real Name", "email": ""},
            )
            assert profile.full_name == "Real Name"          # user override wins
            assert profile.email == "x@example.com"          # empty override doesn't erase
            assert [e.id for e in profile.experiences] == ["exp-1", "exp-2"]

            search = await pipeline.create_search(profile.id, "remote python backend",
                                                  JobFilters(work_modes=[WorkMode.REMOTE]))
            assert len(search.plan.queries) == 2

            rows = await pipeline.discover(search.id)
            by_title = {j.title: a for a, j in rows}
            assert len(rows) == 3  # deduped across the two queries
            assert by_title["Office Python Dev"].status == S.FILTERED_OUT

            rows = await pipeline.screen(search.id)
            by_title = {j.title: a for a, j in rows}
            assert by_title["Python Developer"].status == S.SCREENED_IN
            assert by_title["Backend Engineer"].status == S.UNSURE

            # A human include overrides the fit threshold (Backend Engineer has fit 0.5).
            maybe = by_title["Backend Engineer"]
            await pipeline.override_screening(maybe.id, ScreeningOutcome.INCLUDE)

            drafted = await pipeline.draft_all(search.id, min_fit=0.6)
            assert {a.id for a in drafted} == {by_title["Python Developer"].id, maybe.id}
            app = next(a for a in drafted if a.id == by_title["Python Developer"].id)
            assert app.status == S.DRAFTED
            assert app.draft.used_experience_ids == ["exp-1"]  # unknown ids dropped

            with pytest.raises(InvalidTransition):
                await pipeline.prepare(app.id)               # not approved yet

            await pipeline.approve(app.id)
            app, browser = await pipeline.prepare(app.id, autofill=False)
            assert browser is None and app.status == S.PREPARED
            assert Path(app.package.cover_letter_pdf).read_bytes().startswith(b"%PDF")
            assert Path(app.package.cv_file).exists()

            app = await pipeline.mark_applied(app.id)
            await session.commit()

        async with Session() as session:
            stored = await Repository(session).get_application(app.id)
            assert stored.status == S.APPLIED

            # A second search for the same profile skips jobs already seen.
            pipeline = JobPipeline(deps, Repository(session))
            search2 = await pipeline.create_search(profile.id, "again", JobFilters())
            assert await pipeline.discover(search2.id) == []

        await engine.dispose()

    asyncio.run(run())
