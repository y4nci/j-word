# backend/src/api/main.py
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.dependencies import pipeline_deps
from api.routers import applications, meta, profiles, searches
from applications.models import InvalidTransition
from db import database
from db.database import create_tables, engine
from orchestration.factory import make_http_client, make_llms
from orchestration.job_pipeline import NotFound
from orchestration.search_runner import RunConflict, SearchRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    app.state.http = make_http_client()
    app.state.llms = make_llms()
    app.state.autofill_sessions = {}
    app.state.runner = SearchRunner(lambda: pipeline_deps(app), lambda: database.SessionLocal())
    yield
    await app.state.runner.shutdown()
    await app.state.http.aclose()
    await engine.dispose()


app = FastAPI(
    title="jword API",
    description="""
    Job search and application assistant with a human in the loop.

    ## Workflow

    1. **Profile**: upload CV + proto cover letter, review the extracted profile
    2. **Search**: prompt + filters -> LLM search plan
    3. **Discover**: fetch postings (Arbeitnow, Bundesagentur, Adzuna, Greenhouse/Lever/Ashby boards), hard filters
    4. **Screen**: LLM fit screening, human override
    5. **Draft**: requirement matching -> cover letter -> fact check
    6. **Approve**: human edits/approves each application
    7. **Prepare**: package + browser autofill; the human clicks submit and marks it applied
    """,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": f"{exc} not found"})


@app.exception_handler(RunConflict)
async def _run_conflict(_: Request, exc: RunConflict):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InvalidTransition)
async def _invalid_transition(_: Request, exc: InvalidTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(profiles.router)
app.include_router(searches.router)
app.include_router(applications.router)
app.include_router(meta.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
