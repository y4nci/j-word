import asyncio
import base64

import httpx

from discovery.sources.arbeitnow_adapter import ArbeitnowAdapter
from discovery.sources.bundesagentur_adapter import BundesagenturAdapter
from discovery.sources.company_boards import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    PersonioAdapter,
    SmartRecruitersAdapter,
)
from onboarding.models import CompanyBoard, JobFilters, SearchQuery
from shared.enums import EmploymentType, SourceName, WorkMode


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_arbeitnow_fetches_pages_once_and_filters_locally():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        calls.append(page)
        data = [] if page > 1 else [
            {"slug": "ml-eng", "company_name": "Acme", "title": "Machine Learning Engineer", "remote": True,
             "description": "<p>We build <b>models</b></p>", "url": "https://arbeitnow.com/ml-eng",
             "tags": ["Python"], "job_types": ["Werkstudent"], "location": "Berlin", "created_at": 1760000000},
            {"slug": "cook", "company_name": "Diner", "title": "Cook", "remote": False, "description": "",
             "url": "https://arbeitnow.com/cook", "tags": [], "job_types": [], "location": "Hamburg", "created_at": None},
        ]
        return httpx.Response(200, json={"data": data})

    async def run():
        adapter = ArbeitnowAdapter(client_for(handler), pages=3, page_delay=0)
        filters = JobFilters()
        first = await adapter.search(SearchQuery(source=SourceName.ARBEITNOW, keywords="machine learning"), filters)
        second = await adapter.search(SearchQuery(source=SourceName.ARBEITNOW, keywords="cook"), filters)
        return first, second

    first, second = asyncio.run(run())
    assert [j.title for j in first] == ["Machine Learning Engineer"]
    assert first[0].work_mode == WorkMode.REMOTE
    assert first[0].employment_types == [EmploymentType.WORKING_STUDENT]
    assert first[0].description == "We build models"
    assert [j.title for j in second] == ["Cook"]
    assert calls == [1, 2]  # second search served from cache


def test_greenhouse_unescapes_html_and_keeps_board_token():
    def handler(request):
        assert request.url.path == "/v1/boards/acme/jobs"
        return httpx.Response(200, json={"jobs": [{
            "id": 42, "title": "Backend Engineer", "absolute_url": "https://acme.com/jobs?gh_jid=42",
            "location": {"name": "Remote - Germany"}, "updated_at": "2026-10-01T10:00:00-04:00",
            "content": "&lt;p&gt;Python &amp;amp; Go&lt;/p&gt;&lt;ul&gt;&lt;li&gt;APIs&lt;/li&gt;&lt;/ul&gt;",
        }]})

    filters = JobFilters(use_default_boards=False, company_boards=[CompanyBoard(source=SourceName.GREENHOUSE, token="acme", company_name="Acme")])
    jobs = asyncio.run(GreenhouseAdapter(client_for(handler)).search(
        SearchQuery(source=SourceName.GREENHOUSE, keywords="engineer"), filters))
    assert len(jobs) == 1
    assert jobs[0].company == "Acme" and jobs[0].board_token == "acme"
    assert jobs[0].work_mode == WorkMode.REMOTE
    assert "Python & Go" in jobs[0].description and "- APIs" in jobs[0].description


def test_lever_uses_eu_endpoint_and_workplace_type():
    def handler(request):
        assert request.url.host == "api.eu.lever.co"
        return httpx.Response(200, json=[{
            "id": "abc", "text": "Data Scientist", "hostedUrl": "https://jobs.eu.lever.co/x/abc",
            "applyUrl": "https://jobs.eu.lever.co/x/abc/apply", "workplaceType": "hybrid",
            "categories": {"location": "Berlin", "commitment": "Part-time", "team": "Data"},
            "descriptionPlain": "About us", "lists": [{"text": "You bring", "content": "<li>SQL</li>"}],
            "createdAt": 1760000000000,
        }])

    filters = JobFilters(use_default_boards=False, company_boards=[CompanyBoard(source=SourceName.LEVER, token="x", region="eu")])
    [job] = asyncio.run(LeverAdapter(client_for(handler)).search(
        SearchQuery(source=SourceName.LEVER, keywords="data"), filters))
    assert job.work_mode == WorkMode.HYBRID
    assert job.employment_types == [EmploymentType.PART_TIME]
    assert "You bring" in job.description and "SQL" in job.description


def test_ashby_work_mode_prefers_workplace_type():
    def handler(request):
        return httpx.Response(200, json={"jobs": [{
            "id": "u1", "title": " ML Engineer", "isRemote": True, "employmentType": "FullTime",
            "descriptionPlain": "Train models", "jobUrl": "https://jobs.ashbyhq.com/o/u1",
            "applyUrl": "https://jobs.ashbyhq.com/o/u1/application", "location": "Europe",
        }, {
            "id": "u2", "title": "Engineer, Android", "isRemote": True, "workplaceType": "Hybrid",
            "employmentType": "FullTime", "descriptionPlain": "", "jobUrl": "https://jobs.ashbyhq.com/o/u2",
            "location": "New York, NY (HQ)",
        }]})

    filters = JobFilters(use_default_boards=False, company_boards=[CompanyBoard(source=SourceName.ASHBY, token="o")])
    remote, hybrid = asyncio.run(AshbyAdapter(client_for(handler)).search(
        SearchQuery(source=SourceName.ASHBY, keywords="engineer"), filters))
    assert remote.title == "ML Engineer" and remote.work_mode == WorkMode.REMOTE
    assert hybrid.work_mode == WorkMode.HYBRID  # workplaceType wins over isRemote
    job = remote
    assert job.employment_types == [EmploymentType.FULL_TIME]


def test_bundesagentur_builds_query_and_fetches_details():
    seen = {}

    def handler(request):
        assert request.headers["X-API-Key"] == "jobboerse-jobsuche"
        if request.url.path.endswith("/pc/v6/jobs"):
            seen["params"] = dict(request.url.params)
            # Shape copied from a live v6 response (trimmed).
            return httpx.Response(200, json={"ergebnisliste": [{
                "stellenangebotsart": "ARBEIT", "stellenangebotsTitel": "Werkstudent Data Science (m/w/d)",
                "arbeitszeitTeilzeitVormittag": True, "firma": "Beispiel AG", "referenznummer": "10000-1-S",
                "stellenlokationen": [{"adresse": {"plz": "10119", "ort": "Berlin", "region": "BERLIN"}}],
                "datumErsteVeroeffentlichung": "2026-10-10", "alleBerufe": ["Informatiker/in"],
            }]})
        assert request.url.path.endswith("/pc/v4/jobdetails/" + base64.b64encode(b"10000-1-S").decode())
        return httpx.Response(200, json={
            "stellenangebotsBeschreibung": "Ihre Aufgaben: Analysen mit Python. Homeoffice möglich.",
        })

    async def run():
        adapter = BundesagenturAdapter(client_for(handler))
        filters = JobFilters(employment_types=[EmploymentType.PART_TIME], max_age_days=14, radius_km=25)
        [job] = await adapter.search(SearchQuery(source=SourceName.BUNDESAGENTUR, keywords="data science",
                                                 location="Berlin"), filters)
        return await adapter.fetch_details(job)

    job = asyncio.run(run())
    assert seen["params"]["was"] == "data science"
    assert seen["params"]["wo"] == "Berlin" and seen["params"]["umkreis"] == "25"
    assert seen["params"]["arbeitszeit"] == "tz"
    assert job.company == "Beispiel AG" and job.location == "Berlin"
    assert job.employment_types == [EmploymentType.WORKING_STUDENT, EmploymentType.PART_TIME]
    assert "Python" in job.description and job.work_mode == WorkMode.REMOTE


def test_bundesagentur_does_not_restrict_working_time_for_werkstudent_searches():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"ergebnisliste": []})

    filters = JobFilters(employment_types=[EmploymentType.WORKING_STUDENT, EmploymentType.PART_TIME])
    asyncio.run(BundesagenturAdapter(client_for(handler)).search(
        SearchQuery(source=SourceName.BUNDESAGENTUR, keywords="Werkstudent"), filters))
    assert "arbeitszeit" not in seen  # many Werkstudent postings aren't tagged 'tz'


def test_arbeitnow_concurrent_queries_share_one_fetch_and_survive_429():
    calls = []

    def handler(request):
        page = int(request.url.params["page"])
        calls.append(page)
        if page == 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"data": [{
            "slug": f"job-{page}", "company_name": "Acme", "title": f"Werkstudent Software {page}",
            "description": "", "url": f"https://x/{page}", "tags": [], "job_types": [], "location": "Berlin",
        }]})

    async def run():
        adapter = ArbeitnowAdapter(client_for(handler), pages=5, page_delay=0, retry_wait=0)
        queries = [SearchQuery(source=SourceName.ARBEITNOW, keywords=k) for k in ("werkstudent", "software", "werkstudent software")]
        return await asyncio.gather(*(adapter.search(q, JobFilters()) for q in queries))

    results = asyncio.run(run())
    assert calls == [1, 2, 3, 3]  # fetched once despite three concurrent queries; retried page 3 once, then stopped
    assert all(len(r) == 2 for r in results)  # pages 1-2 kept


PERSONIO_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>2834988</id>
    <subcompany>Ficus Health GmbH</subcompany>
    <office>Berlin</office>
    <department>Engineering</department>
    <name>Working Student Software Engineering (m/w/d)</name>
    <jobDescriptions>
        <jobDescription><name>Your role</name><value><![CDATA[<ul><li>Build APIs</li></ul>]]></value></jobDescription>
    </jobDescriptions>
    <employmentType>working_student</employmentType>
    <schedule>part-time</schedule>
    <keywords>Python,AI</keywords>
    <createdAt>2020-09-14T10:11:57+00:00</createdAt>
</position>
</workzag-jobs>"""


def test_personio_parses_xml_feed():
    def handler(request):
        assert request.url.host == "merantix.jobs.personio.de"
        return httpx.Response(200, content=PERSONIO_XML)

    filters = JobFilters(use_default_boards=False, company_boards=[CompanyBoard(source=SourceName.PERSONIO, token="merantix", company_name="Merantix")])
    [job] = asyncio.run(PersonioAdapter(client_for(handler)).search(
        SearchQuery(source=SourceName.PERSONIO, keywords="working student"), filters))
    assert job.company == "Ficus Health GmbH"  # subcompany wins over the board name
    assert job.url == "https://merantix.jobs.personio.de/job/2834988"
    assert set(job.employment_types) == {EmploymentType.WORKING_STUDENT, EmploymentType.PART_TIME}
    assert "- Build APIs" in job.description and "Python" in job.tags


def test_personio_old_evergreen_postings_are_not_age_filtered():
    from datetime import datetime, timezone
    from discovery.filters import hard_filter
    from discovery.models import JobPosting
    old = JobPosting(source=SourceName.PERSONIO, external_id="1", title="T", company="C", url="u",
                     posted_at=datetime(2020, 9, 14, tzinfo=timezone.utc))
    assert hard_filter(old, JobFilters(max_age_days=30)) is None


def test_smartrecruiters_paginates_and_fetches_details():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith("/postings"):
            offset = int(request.url.params["offset"])
            items = [{
                "id": str(offset + i), "name": f"Werkstudent Data {offset + i}", "company": {"name": "Omio"},
                "location": {"city": "Berlin", "fullLocation": "Berlin, Berlin, Germany", "remote": False, "hybrid": True},
                "typeOfEmployment": {"label": "Part-time"}, "releasedDate": "2019-06-24T13:36:25.000Z",
                "language": {"code": "en"}, "department": {"label": "Data"},
            } for i in range(100 if offset == 0 else 30)]
            return httpx.Response(200, json={"content": items, "totalFound": 130, "offset": offset, "limit": 100})
        return httpx.Response(200, json={
            "postingUrl": "https://jobs.smartrecruiters.com/Omio/5-werkstudent",
            "applyUrl": "https://jobs.smartrecruiters.com/Omio/5-werkstudent?oga=true",
            "jobAd": {"sections": {"jobDescription": {"title": "Job Description", "text": "<p>Analyse data</p>"},
                                   "videos": {"title": "Videos", "text": ""}}},
        })

    async def run():
        adapter = SmartRecruitersAdapter(client_for(handler))
        filters = JobFilters(use_default_boards=False, company_boards=[CompanyBoard(source=SourceName.SMARTRECRUITERS, token="omio")])
        jobs = await adapter.search(SearchQuery(source=SourceName.SMARTRECRUITERS, keywords="werkstudent", max_results=500), filters)
        return jobs, await adapter.fetch_details(jobs[5])

    jobs, detailed = asyncio.run(run())
    assert len(jobs) == 130 and sum("/postings?" in c for c in calls) == 2
    assert jobs[0].work_mode == WorkMode.HYBRID
    assert set(jobs[0].employment_types) == {EmploymentType.WORKING_STUDENT, EmploymentType.PART_TIME}
    assert detailed.description == "Job Description\nAnalyse data"
    assert detailed.apply_url.endswith("?oga=true")
