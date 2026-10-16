#!/usr/bin/env python
"""
Interactive end-to-end run in the terminal (no frontend needed).

    python scripts/run_pipeline.py --cv ~/cv.pdf --letter ~/proto_letter.md --letter ~/old_letter.pdf \
        --prompt "Werkstudent or junior roles in ML engineering, ideally NLP" \
        --part-time --remote --hybrid --location Berlin \
        --board greenhouse:n26 --board lever:eu:mistral

Nothing is submitted without you: every application is shown for approval,
and the browser autofill never clicks submit.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from db.database import SessionLocal, create_tables  # noqa: E402
from db.repository import Repository  # noqa: E402
from infra.documents import combine_letters, extract_text  # noqa: E402
from onboarding.models import CandidateProfile, CompanyBoard, JobFilters  # noqa: E402
from orchestration.factory import build_deps, make_http_client  # noqa: E402
from orchestration.job_pipeline import JobPipeline  # noqa: E402
from shared.enums import ApplicationStatus as S, EmploymentType, ScreeningOutcome, SourceName, WorkMode  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = p.add_argument_group("profile")
    who.add_argument("--profile-id", type=UUID, help="reuse a stored profile instead of --cv/--letter")
    who.add_argument("--cv", type=Path)
    who.add_argument("--letter", type=Path, action="append", default=[],
                     help="proto cover letter (.md/.txt/.pdf); repeat for several files")
    for field in ("name", "email", "phone", "city", "linkedin", "github", "website"):
        who.add_argument(f"--{field}", default="")

    search = p.add_argument_group("search")
    search.add_argument("--prompt", required=True)
    search.add_argument("--remote", action="store_true")
    search.add_argument("--hybrid", action="store_true")
    search.add_argument("--onsite", action="store_true")
    search.add_argument("--full-time", action="store_true")
    search.add_argument("--part-time", action="store_true")
    search.add_argument("--working-student", action="store_true")
    search.add_argument("--internship", action="store_true")
    search.add_argument("--location", action="append", default=[])
    search.add_argument("--lang", action="append", default=[], help="accepted posting languages, e.g. en, de")
    search.add_argument("--max-age-days", type=int, default=30)
    search.add_argument("--exclude-company", action="append", default=[])
    search.add_argument("--exclude-keyword", action="append", default=[])
    search.add_argument("--board", action="append", default=[],
                        help="company board: greenhouse:<token>, lever:<site>, lever:eu:<site>, ashby:<org>")

    run = p.add_argument_group("run")
    run.add_argument("--min-fit", type=float, default=0.6, help="only draft jobs with at least this fit score")
    run.add_argument("--no-autofill", action="store_true")
    return p.parse_args()


def build_filters(args: argparse.Namespace) -> JobFilters:
    modes = [m for flag, m in ((args.remote, WorkMode.REMOTE), (args.hybrid, WorkMode.HYBRID),
                               (args.onsite, WorkMode.ONSITE)) if flag]
    types = [t for flag, t in ((args.full_time, EmploymentType.FULL_TIME), (args.part_time, EmploymentType.PART_TIME),
                               (args.working_student, EmploymentType.WORKING_STUDENT),
                               (args.internship, EmploymentType.INTERNSHIP)) if flag]
    boards = []
    for spec in args.board:
        parts = spec.split(":")
        source = SourceName(parts[0])
        region = parts[1] if len(parts) == 3 else None
        boards.append(CompanyBoard(source=source, token=parts[-1], region=region))
    return JobFilters(
        work_modes=modes, employment_types=types, locations=args.location, posting_languages=args.lang,
        max_age_days=args.max_age_days, exclude_companies=args.exclude_company,
        exclude_keywords=args.exclude_keyword, company_boards=boards,
    )


# ---------------------------------------------------------------------- #
# Terminal helpers
# ---------------------------------------------------------------------- #
def ask(prompt: str, choices: str) -> str:
    while True:
        answer = input(f"{prompt} [{'/'.join(choices)}] ").strip().lower()
        if answer in choices:
            return answer


def edit_in_editor(text: str, suffix: str = ".txt") -> str:
    editor = os.environ.get("EDITOR", "nano")
    with tempfile.NamedTemporaryFile("w+", suffix=suffix, delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    subprocess.call([editor, path])
    edited = Path(path).read_text(encoding="utf-8")
    os.unlink(path)
    return edited


def header(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------------- #
# Steps
# ---------------------------------------------------------------------- #
async def get_profile(args, pipeline: JobPipeline, repo: Repository) -> CandidateProfile:
    if args.profile_id:
        profile = await repo.get_profile(args.profile_id)
        if profile is None:
            sys.exit(f"Profile {args.profile_id} not found")
        return profile
    if not args.cv or not args.letter:
        sys.exit("--cv and --letter are required unless --profile-id is given")

    links = {k: getattr(args, k) for k in ("linkedin", "github", "website") if getattr(args, k)}
    profile = await pipeline.create_profile(
        cv_text=extract_text(args.cv.name, args.cv.read_bytes()),
        proto_cover_letter=combine_letters("", [(f.name, extract_text(f.name, f.read_bytes())) for f in args.letter]),
        cv_path=str(args.cv.resolve()),
        overrides={"full_name": args.name, "email": args.email, "phone": args.phone,
                   "location": args.city, "links": links},
    )
    header(f"Profile {profile.id}")
    print(profile.compact())
    if ask("Drafts may only use facts from this profile. Edit it now?", "yn") == "y":
        edited = edit_in_editor(profile.model_dump_json(indent=2, exclude={"cv_text"}), ".json")
        profile = CandidateProfile.model_validate_json(edited).model_copy(update={"cv_text": profile.cv_text})
        await repo.save_profile(profile)
    return profile


async def review_unsure(pipeline: JobPipeline, rows) -> None:
    unsure = [(a, j) for a, j in rows if a.status == S.UNSURE]
    if not unsure:
        return
    header(f"{len(unsure)} jobs the screener was unsure about")
    for app, job in unsure:
        d = app.latest_decision
        print(f"\n{job.title} @ {job.company} ({job.location or 'n/a'}, {job.work_mode.value})\n  {job.url}")
        print(f"  fit {d.fit_score:.2f}: {d.reason}")
        choice = ask("  include / exclude / skip?", "ies")
        if choice != "s":
            outcome = ScreeningOutcome.INCLUDE if choice == "i" else ScreeningOutcome.EXCLUDE
            await pipeline.override_screening(app.id, outcome)


async def review_drafts(pipeline: JobPipeline, drafted, repo: Repository) -> list[UUID]:
    approved: list[UUID] = []
    for i, app in enumerate(drafted, start=1):
        job = await repo.get_job(app.job_id)
        while True:
            d = app.draft
            header(f"[{i}/{len(drafted)}] {job.title} @ {job.company}\n{job.url}")
            print(f"Fit {app.latest_decision.fit_score:.2f}: {app.latest_decision.reason}\n")
            print(f"Subject: {d.subject}\n")
            print(d.cover_letter)
            print(f"\nShort pitch: {d.short_pitch}")
            if d.unsupported_claims:
                print("\n!! Fact check flagged:")
                for c in d.unsupported_claims:
                    print(textwrap.indent(f"- {c.claim}\n  ({c.why})", "   "))

            choice = ask("\n(a)pprove, (e)dit, (g)enerate again, (r)eject, (s)kip for now?", "aegrs")
            if choice == "a":
                app = await pipeline.approve(app.id)
                approved.append(app.id)
            elif choice == "e":
                edited = edit_in_editor(f"{d.subject}\n\n{d.cover_letter}")
                subject, _, body = edited.partition("\n\n")
                app = await pipeline.edit_draft(app.id, subject=subject.strip(), cover_letter=body.strip())
                continue
            elif choice == "g":
                app = await pipeline.draft_one(app.id)
                continue
            elif choice == "r":
                await pipeline.reject(app.id)
            break
    return approved


async def main() -> None:
    args = parse_args()
    await create_tables()

    async with make_http_client() as http, SessionLocal() as session:
        repo = Repository(session)
        pipeline = JobPipeline(build_deps(http), repo)

        profile = await get_profile(args, pipeline, repo)
        await session.commit()

        search = await pipeline.create_search(profile.id, args.prompt, build_filters(args))
        await session.commit()
        header("Search plan")
        print(f"Goal: {search.plan.refined_goal}")
        print(f"Titles: {', '.join(search.plan.target_titles)}")
        print(f"Keywords: {', '.join(search.plan.keywords)}")
        print("Criteria:\n" + "\n".join(f"  - {c}" for c in search.plan.screening_criteria))
        print(f"{len(search.plan.queries)} queries over {sorted({q.source.value for q in search.plan.queries})}")

        print("\nDiscovering...")
        rows = await pipeline.discover(search.id)
        await session.commit()
        print(f"{len(rows)} new jobs, {sum(a.status == S.DISCOVERED for a, _ in rows)} passed the hard filters")

        print("Screening...")
        rows = await pipeline.screen(search.id)
        await session.commit()
        screened = sorted((r for r in rows if r[0].latest_decision), key=lambda r: -r[0].latest_decision.fit_score)
        header("Screening results")
        for app, job in screened:
            d = app.latest_decision
            print(f"{d.fit_score:.2f}  {app.status.value:<12} {job.title[:45]:<45} {job.company[:25]}")
            if job.summary:
                facts = [job.summary.pay, job.summary.hours, job.summary.employment, job.summary.work_mode]
                print(f"      {' · '.join(f for f in facts if f) or ''}  {job.summary.short_description[:90]}")

        await review_unsure(pipeline, rows)
        await session.commit()

        print(f"\nDrafting applications with fit >= {args.min_fit}...")
        drafted = await pipeline.draft_all(search.id, min_fit=args.min_fit)
        await session.commit()
        if not drafted:
            print("Nothing to draft. Lower --min-fit or broaden the search.")
            return

        approved = await review_drafts(pipeline, drafted, repo)
        await session.commit()

        for app_id in approved:
            app, browser = await pipeline.prepare(app_id, autofill=not args.no_autofill)
            await session.commit()
            job = await repo.get_job(app.job_id)
            header(f"Prepared: {job.title} @ {job.company}")
            print(f"Package: {app.package.directory}")
            print("\n".join(app.package.autofill_report))
            if browser is not None:
                print("\nThe form is open in the browser. Submit it there, then close the window.")
                await browser.wait_closed()
            if ask("Did you submit this application?", "yn") == "y":
                await pipeline.mark_applied(app_id)
                await session.commit()

        print(f"\nDone. Search id: {search.id}, profile id: {profile.id}")


if __name__ == "__main__":
    asyncio.run(main())
