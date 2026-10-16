# backend/src/discovery/sources/default_boards.py
"""
Built-in company boards searched when JobFilters.use_default_boards is on.

Companies with a Berlin or Germany presence whose public ATS board was checked live
on 2026-10-16 (it returned open jobs, a meaningful share of them in Germany). Boards
change: a board that later 404s is skipped with a warning, it doesn't fail the search.
The hard filters (location, employment type, ...) and the LLM screener still apply.
"""

from __future__ import annotations

from onboarding.models import CompanyBoard, JobFilters
from shared.enums import SourceName as S


def _b(source: S, token: str, name: str, region: str | None = None) -> CompanyBoard:
    return CompanyBoard(source=source, token=token, company_name=name, region=region)


DEFAULT_BOARDS: list[CompanyBoard] = [
    # Greenhouse
    _b(S.GREENHOUSE, "helsing", "Helsing"),
    _b(S.GREENHOUSE, "hellofresh", "HelloFresh"),
    _b(S.GREENHOUSE, "doctolib", "Doctolib"),
    _b(S.GREENHOUSE, "celonis", "Celonis"),
    _b(S.GREENHOUSE, "getyourguide", "GetYourGuide"),
    _b(S.GREENHOUSE, "sumup", "SumUp"),
    _b(S.GREENHOUSE, "parloa", "Parloa"),
    _b(S.GREENHOUSE, "wolt", "Wolt"),
    _b(S.GREENHOUSE, "raisin", "Raisin"),
    _b(S.GREENHOUSE, "avimedical", "Avi Medical"),
    _b(S.GREENHOUSE, "n26", "N26"),
    _b(S.GREENHOUSE, "solarisbank", "Solaris"),
    _b(S.GREENHOUSE, "staffbase", "Staffbase"),
    _b(S.GREENHOUSE, "traderepublicbank", "Trade Republic"),
    _b(S.GREENHOUSE, "grover", "Grover"),
    _b(S.GREENHOUSE, "wunderflats", "Wunderflats"),
    # Ashby
    _b(S.ASHBY, "enpal", "Enpal"),
    _b(S.ASHBY, "pliant", "Pliant"),
    _b(S.ASHBY, "n8n", "n8n"),
    _b(S.ASHBY, "moss", "Moss"),
    _b(S.ASHBY, "upvest", "Upvest"),
    _b(S.ASHBY, "dataguard", "DataGuard"),
    _b(S.ASHBY, "taktile", "Taktile"),
    _b(S.ASHBY, "babbel", "Babbel"),
    _b(S.ASHBY, "forto", "Forto"),
    _b(S.ASHBY, "qonto", "Qonto"),
    _b(S.ASHBY, "billie", "Billie"),
    # Lever
    _b(S.LEVER, "researchgate", "ResearchGate"),
    # Personio
    _b(S.PERSONIO, "thermondo", "Thermondo"),
    _b(S.PERSONIO, "merantix", "Merantix"),
    _b(S.PERSONIO, "ottonova", "ottonova"),
    _b(S.PERSONIO, "clark", "CLARK"),
    # SmartRecruiters
    _b(S.SMARTRECRUITERS, "deliveryhero", "Delivery Hero"),
    _b(S.SMARTRECRUITERS, "auto1", "AUTO1 Group"),
    _b(S.SMARTRECRUITERS, "home24", "home24"),
    _b(S.SMARTRECRUITERS, "omio", "Omio"),
]


def effective_boards(filters: JobFilters) -> list[CompanyBoard]:
    """The user's boards plus, if enabled, the built-in ones (user entries win on duplicates)."""
    boards = list(filters.company_boards)
    if filters.use_default_boards:
        seen = {(b.source, b.token.lower()) for b in boards}
        boards += [b for b in DEFAULT_BOARDS if (b.source, b.token.lower()) not in seen]
    return boards
