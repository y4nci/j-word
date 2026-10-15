# backend/src/submission/package_builder.py

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from applications.models import Application, ApplicationPackage
from discovery.models import JobPosting
from infra.documents import render_letter_pdf
from onboarding.models import CandidateProfile
from shared.text import normalize_key

_EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]


class PackageBuilder:
    """Writes everything needed to apply into outputs/applications/<company>-<title>-<id>/."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def build(self, application: Application, job: JobPosting, profile: CandidateProfile) -> ApplicationPackage:
        draft = application.draft
        if draft is None:
            raise ValueError("Application has no draft")

        slug = "-".join(normalize_key(f"{job.company} {job.title}").split())[:60]
        directory = self._output_dir / f"{slug}-{str(application.id)[:8]}"
        directory.mkdir(parents=True, exist_ok=True)

        name_slug = "_".join(normalize_key(profile.full_name).split()) or "candidate"
        pdf_path = render_letter_pdf(
            directory / f"Cover_Letter_{name_slug}.pdf",
            sender_lines=[profile.full_name, profile.location or "", profile.email, profile.phone or ""],
            recipient_lines=[job.company, job.location or ""],
            date_line=_date_line(draft.language, profile.location),
            subject=draft.subject,
            body=draft.cover_letter,
        )
        txt_path = directory / "cover_letter.txt"
        txt_path.write_text(f"{draft.subject}\n\n{draft.cover_letter}\n", encoding="utf-8")

        cv_file = None
        if profile.cv_path and Path(profile.cv_path).exists():
            src = Path(profile.cv_path)
            cv_file = str(shutil.copy(src, directory / f"CV_{name_slug}{src.suffix}"))

        summary_path = directory / "application.md"
        summary_path.write_text(_summary_md(application, job), encoding="utf-8")

        return ApplicationPackage(
            directory=str(directory),
            cover_letter_pdf=str(pdf_path),
            cover_letter_txt=str(txt_path),
            cv_file=cv_file,
            summary_md=str(summary_path),
        )


def _date_line(language: str, location: str | None) -> str:
    today = date.today()
    if language == "de":
        city = (location or "").split(",")[0].strip()
        return f"{city + ', ' if city else ''}{today:%d.%m.%Y}"
    return f"{today.day} {_EN_MONTHS[today.month - 1]} {today.year}"


def _summary_md(application: Application, job: JobPosting) -> str:
    draft = application.draft
    decision = application.latest_decision
    lines = [
        f"# {job.title} - {job.company}",
        "",
        f"- Posting: {job.url}",
        f"- Apply: {job.apply_url or job.url}",
        f"- Location: {job.location or 'n/a'} ({job.work_mode.value})",
    ]
    if decision:
        lines.append(f"- Fit: {decision.fit_score:.2f} - {decision.reason}")
    lines += ["", "## Short pitch (for form fields)", "", draft.short_pitch or "-", "", "## Requirement coverage", ""]
    for m in draft.requirement_matches:
        lines.append(f"- **{m.requirement}** -> {', '.join(m.experience_ids) or 'not covered'}: {m.evidence}")
    if draft.unsupported_claims:
        lines += ["", "## Flagged by fact check", ""]
        lines += [f"- {c.claim} ({c.why})" for c in draft.unsupported_claims]
    return "\n".join(lines) + "\n"
