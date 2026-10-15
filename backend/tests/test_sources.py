import asyncio
import base64

import httpx

from discovery.sources.arbeitnow_adapter import ArbeitnowAdapter
from discovery.sources.bundesagentur_adapter import BundesagenturAdapter
from discovery.sources.company_boards import AshbyAdapter, GreenhouseAdapter, LeverAdapter
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
        adapter = ArbeitnowAdapter(client_for(handler), pages=3)
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

    filters = JobFilters(company_boards=[CompanyBoard(source=SourceName.GREENHOUSE, token="acme", company_name="Acme")])
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

    filters = JobFilters(company_boards=[CompanyBoard(source=SourceName.LEVER, token="x", region="eu")])
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

    filters = JobFilters(company_boards=[CompanyBoard(source=SourceName.ASHBY, token="o")])
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
