from datetime import datetime, timedelta, timezone

from discovery.filters import hard_filter, matches_keywords
from discovery.inference import infer_employment_types, infer_work_mode
from discovery.models import JobPosting
from onboarding.models import JobFilters
from shared.enums import EmploymentType, SourceName, WorkMode

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def job(**overrides) -> JobPosting:
    base = dict(source=SourceName.ARBEITNOW, external_id="1", title="Data Engineer", company="Acme GmbH",
                location="Berlin", url="https://example.com/1", posted_at=NOW - timedelta(days=2))
    return JobPosting(**(base | overrides))


def test_unknown_work_mode_passes_remote_filter():
    assert hard_filter(job(), JobFilters(work_modes=[WorkMode.REMOTE]), now=NOW) is None


def test_onsite_job_fails_remote_filter():
    reason = hard_filter(job(work_mode=WorkMode.ONSITE), JobFilters(work_modes=[WorkMode.REMOTE]), now=NOW)
    assert reason == "work mode is onsite"


def test_part_time_filter_keeps_working_student_roles():
    j = job(employment_types=[EmploymentType.WORKING_STUDENT])
    assert hard_filter(j, JobFilters(employment_types=[EmploymentType.PART_TIME]), now=NOW) is None
    j = job(employment_types=[EmploymentType.FULL_TIME])
    assert hard_filter(j, JobFilters(employment_types=[EmploymentType.PART_TIME]), now=NOW) is not None


def test_old_postings_and_excluded_companies_are_filtered():
    assert "days ago" in hard_filter(job(posted_at=NOW - timedelta(days=60)), JobFilters(max_age_days=30), now=NOW)
    assert "excluded" in hard_filter(job(), JobFilters(exclude_companies=["acme"]), now=NOW)
    assert "excluded keyword" in hard_filter(job(title="Senior Data Engineer"),
                                              JobFilters(exclude_keywords=["senior"]), now=NOW)


def test_location_filter_skips_remote_jobs():
    filters = JobFilters(locations=["Munich"])
    assert hard_filter(job(), filters, now=NOW) is not None
    assert hard_filter(job(work_mode=WorkMode.REMOTE), filters, now=NOW) is None


def test_keyword_gate_needs_all_words_in_title_or_tags():
    assert matches_keywords(job(), "data engineer")
    assert not matches_keywords(job(), "machine learning")
    assert matches_keywords(job(tags=["Python"]), "python")


def test_dedupe_key_separates_cities_but_matches_across_sources():
    berlin = job(location="Berlin, Berlin")
    assert berlin.dedupe_key == job(source=SourceName.BUNDESAGENTUR, location="Berlin").dedupe_key
    assert berlin.dedupe_key != job(location="London, United Kingdom").dedupe_key


def test_inference_heuristics():
    assert infer_work_mode("Hybrid (2 days in office)") == WorkMode.HYBRID
    assert infer_work_mode("Wir bieten Homeoffice") == WorkMode.REMOTE
    assert EmploymentType.WORKING_STUDENT in infer_employment_types("Werkstudent (m/w/d) Data Science")
    assert EmploymentType.PART_TIME in infer_employment_types("Teilzeit, 20h")
