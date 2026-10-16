"""HTTP-level test of the endpoints the frontend uses (fake LLM, fake source, temp DB)."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import api.dependencies as api_deps
import api.main as api_main
from db import database
from db.database import create_tables, make_engine
from discovery.discovery_service import DiscoveryService
from drafting.drafting_service import DraftingService
from onboarding.planning_service import PlanningService
from onboarding.profile_service import ProfileService
from orchestration.job_pipeline import PipelineDeps
from screening.screening_service import ScreeningService
from shared.enums import SourceName
from submission.package_builder import PackageBuilder
from submission.submission_service import SubmissionService
from tests.test_pipeline import FakeSource, scripted_llm


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    llm = scripted_llm()

    async def get_test_session():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def fake_build_deps(http, **_):
        return PipelineDeps(
            profiles=ProfileService(llm), planning=PlanningService(llm),
            discovery=DiscoveryService({SourceName.ARBEITNOW: FakeSource()}),
            screening=ScreeningService(llm), drafting=DraftingService(llm),
            submission=SubmissionService(PackageBuilder(tmp_path / "out"), submitters=[]),
        )

    monkeypatch.setattr(api_main, "create_tables", lambda: create_tables(engine))
    monkeypatch.setattr(api_main, "make_llms", lambda: (llm, llm))
    monkeypatch.setattr(api_deps, "build_deps", fake_build_deps)
    monkeypatch.setattr("api.routers.profiles.UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(database, "SessionLocal", Session)  # used by the background runner
    api_main.app.dependency_overrides[database.get_session] = get_test_session
    with TestClient(api_main.app) as c:
        c.llm = llm
        yield c
    api_main.app.dependency_overrides.clear()


def test_frontend_flow_endpoints(client: TestClient):
    resp = client.post(
        "/profiles",
        files=[
            ("cv", ("cv.txt", b"My CV text", "text/plain")),
            ("proto_cover_letter_files", ("letter_a.md", b"At Shop GmbH I maintained APIs.", "text/markdown")),
            ("proto_cover_letter_files", ("letter_b.txt", b"In AutoReview I built a pipeline.", "text/plain")),
        ],
        data={"proto_cover_letter": "Pasted notes.", "full_name": "Real Name", "links": "{}"},
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()
    letter = profile["proto_cover_letter"]
    assert letter.startswith("Pasted notes.")
    assert "--- letter_a.md ---\nAt Shop GmbH" in letter and "--- letter_b.txt ---\nIn AutoReview" in letter

    # Neither text nor files -> 422
    resp = client.post("/profiles", files={"cv": ("cv.txt", b"CV", "text/plain")}, data={"links": "{}"})
    assert resp.status_code == 422
    assert [p["id"] for p in client.get("/profiles").json()] == [profile["id"]]

    search = client.post("/searches", json={"profile_id": profile["id"], "prompt": "python backend"}).json()
    assert [s["id"] for s in client.get(f"/profiles/{profile['id']}/searches").json()] == [search["id"]]

    assert client.post(f"/searches/{search['id']}/discover").json()["counts"] == {"discovered": 3}
    summary = client.post(f"/searches/{search['id']}/screen").json()
    first = summary["applications"][0]["application"]  # sorted by fit, Python Developer first
    assert first["status"] == "screened_in"

    # Approving without a draft is refused by the domain model -> 409.
    resp = client.post(f"/applications/{first['id']}/approve", json={})
    assert resp.status_code == 409 and "no draft" in resp.json()["detail"].lower()
    assert client.get(f"/applications/{first['id']}/cover-letter.pdf").status_code == 404

    client.post(f"/applications/{first['id']}/draft")
    assert client.post(f"/applications/{first['id']}/approve", json={}).json()["status"] == "approved"
    prepared = client.post(f"/applications/{first['id']}/prepare", json={"autofill": False}).json()
    assert prepared["status"] == "prepared"
    pdf = client.get(f"/applications/{first['id']}/cover-letter.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def _new_search(client: TestClient) -> str:
    profile = client.post(
        "/profiles", files={"cv": ("cv.txt", b"CV", "text/plain")},
        data={"proto_cover_letter": "In AutoReview I built...", "links": "{}"},
    ).json()
    search = client.post("/searches", json={"profile_id": profile["id"], "prompt": "python backend"}).json()
    return search["id"]


def _wait_for_run(client: TestClient, search_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/searches/{search_id}/run").json()
        if run and run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_background_run_discovers_screens_and_drafts(client: TestClient):
    search_id = _new_search(client)
    assert client.get(f"/searches/{search_id}/run").json() is None

    resp = client.post(f"/searches/{search_id}/run", json={"draft": True, "min_fit": 0.6})
    assert resp.status_code == 202 and resp.json()["status"] == "running"

    run = _wait_for_run(client, search_id)
    assert run["status"] == "completed" and run["stage"] == "done", run
    assert any("screened 3/3" in line for line in run["log"])
    assert any("drafted 1 letters" in line for line in run["log"])

    counts = client.get(f"/searches/{search_id}/applications").json()["counts"]
    assert counts == {"drafted": 1, "unsure": 2}  # no hard filters set, so all three jobs were screened
    # Persisted: the stored search carries the finished run.
    assert client.get(f"/searches/{search_id}").json()["run"]["status"] == "completed"


def test_run_conflict_and_cancel_keep_finished_work(client: TestClient):
    search_id = _new_search(client)
    client.llm.delay = 2.0  # screening is slow, so the run is still going when we cancel
    assert client.post(f"/searches/{search_id}/run", json={}).status_code == 202
    assert client.post(f"/searches/{search_id}/run", json={}).status_code == 409

    time.sleep(0.3)  # let discovery finish and screening start
    cancelled = client.post(f"/searches/{search_id}/run/cancel").json()
    assert cancelled["status"] == "cancelled"
    stored = client.get(f"/searches/{search_id}/run").json()
    assert stored["status"] == "cancelled" and stored["stage"] == "screening"
    # Discovery was committed before the cancel; nothing was screened.
    counts = client.get(f"/searches/{search_id}/applications").json()["counts"]
    assert counts.get("discovered", 0) >= 1 and "screened_in" not in counts

    # A new run can start afterwards and finishes the remaining work.
    client.llm.delay = 0.0
    assert client.post(f"/searches/{search_id}/run", json={}).status_code == 202
    assert _wait_for_run(client, search_id)["status"] == "completed"
    assert "discovered" not in client.get(f"/searches/{search_id}/applications").json()["counts"]
