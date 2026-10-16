# backend/src/orchestration/search_runner.py
"""
Background "full search" jobs: discover -> screen in batches (-> draft good matches).

A run lives in an asyncio task inside the API process. Live progress is kept in
memory (cheap to poll); the run state and all results are committed to the DB
after each stage and each screening batch, so a crash or cancel keeps finished work.
A run that was still RUNNING in the DB when the process stopped is reported as
INTERRUPTED; start a new run to continue (already-screened jobs aren't redone).

Drafting never approves anything: drafts still wait for the human.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.repository import Repository
from onboarding.models import RunOptions, SearchRun
from orchestration.job_pipeline import JobPipeline, NotFound, PipelineDeps
from shared.enums import RunStatus

logger = logging.getLogger(__name__)

SCREENING_BATCH = 20  # jobs per committed screening batch


class RunConflict(RuntimeError):
    pass


class SearchRunner:
    def __init__(
        self,
        deps_factory: Callable[[], PipelineDeps],
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self._deps_factory = deps_factory
        self._session_factory = session_factory
        self._live: dict[str, tuple[asyncio.Task, SearchRun]] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def live(self, search_id: UUID) -> Optional[SearchRun]:
        entry = self._live.get(str(search_id))
        return entry[1] if entry else None

    async def status(self, search_id: UUID) -> Optional[SearchRun]:
        """Live run if one is in progress, else the last persisted run."""
        if (run := self.live(search_id)) is not None:
            return run
        async with self._session_factory() as session:
            search = await Repository(session).get_search(search_id)
        if search is None:
            raise NotFound(f"search {search_id}")
        run = search.run
        if run is not None and run.status == RunStatus.RUNNING:  # the process that ran it is gone
            run = run.model_copy(update={"status": RunStatus.INTERRUPTED})
        return run

    async def start(self, search_id: UUID, options: RunOptions) -> SearchRun:
        key = str(search_id)
        if key in self._live:
            raise RunConflict("A run is already in progress for this search")
        async with self._session_factory() as session:
            if await Repository(session).get_search(search_id) is None:
                raise NotFound(f"search {search_id}")

        run = SearchRun(options=options)
        run.note("run started")
        task = asyncio.get_running_loop().create_task(self._execute(search_id, run))
        self._live[key] = (task, run)
        task.add_done_callback(lambda _: self._live.pop(key, None))
        return run

    async def cancel(self, search_id: UUID) -> Optional[SearchRun]:
        entry = self._live.get(str(search_id))
        if entry is None:
            return None
        task, run = entry
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return run

    async def shutdown(self) -> None:
        for task, _ in list(self._live.values()):
            task.cancel()
        await asyncio.gather(*(t for t, _ in self._live.values()), return_exceptions=True)

    # ------------------------------------------------------------------ #
    # The job
    # ------------------------------------------------------------------ #
    async def _execute(self, search_id: UUID, run: SearchRun) -> None:
        session = self._session_factory()
        repo = Repository(session)
        pipeline = JobPipeline(self._deps_factory(), repo)

        def progress(stage: str):
            def update(done: int, total: int, message: str) -> None:
                run.stage, run.done, run.total = stage, done, total  # type: ignore[assignment]
                run.message = message
            return update

        async def checkpoint(message: str) -> None:
            run.note(message)
            await self._persist(repo, search_id, run)
            await session.commit()

        try:
            await checkpoint("saving run")

            # 1. Discover
            run.stage = "discovering"
            await checkpoint("discovering jobs across all sources")
            rows = await pipeline.discover(search_id, on_progress=progress("discovering"))
            await checkpoint(f"discovery done: {len(rows)} jobs in this search")

            # 2. Screen in committed batches
            run.stage = "screening"
            total = await pipeline.count_pending_screening(search_id)
            run.done, run.total = 0, total
            await checkpoint(f"screening {total} jobs that passed the filters")
            screened = 0
            while True:
                base = screened

                def batch_progress(done: int, _total: int, message: str) -> None:
                    run.stage, run.done, run.total, run.message = "screening", base + done, total, message

                n = await pipeline.screen_batch(search_id, limit=SCREENING_BATCH, on_progress=batch_progress)
                if n == 0:
                    break
                screened += n
                run.done = screened
                await checkpoint(f"screened {screened}/{total}")

            # 3. Draft (optional)
            if run.options.draft:
                run.stage = "drafting"
                await checkpoint(f"drafting letters for matches with fit >= {run.options.min_fit:.2f}")
                drafted = await pipeline.draft_all(
                    search_id, min_fit=run.options.min_fit, on_progress=progress("drafting"),
                )
                await checkpoint(f"drafted {len(drafted)} letters, waiting for your review")

            run.stage = "done"
            run.status = RunStatus.COMPLETED
            await self._finish(session, repo, search_id, run, "run completed")
        except asyncio.CancelledError:
            await session.rollback()  # drop the half-finished batch; finished batches are committed
            run.status = RunStatus.CANCELLED
            await self._finish(session, repo, search_id, run, "run cancelled")
            raise
        except Exception as exc:
            logger.exception("Search run %s failed", search_id)
            await session.rollback()
            run.status = RunStatus.FAILED
            run.error = str(exc)
            await self._finish(session, repo, search_id, run, f"run failed: {exc}")
        finally:
            await session.close()

    async def _finish(self, session: AsyncSession, repo: Repository, search_id: UUID, run: SearchRun, message: str) -> None:
        run.finished_at = datetime.now(timezone.utc)
        run.note(message)
        try:
            await self._persist(repo, search_id, run)
            await session.commit()
        except Exception:
            logger.exception("Could not persist final state of run for search %s", search_id)

    @staticmethod
    async def _persist(repo: Repository, search_id: UUID, run: SearchRun) -> None:
        search = await repo.get_search(search_id)
        if search is not None:
            search.run = run.model_copy(deep=True)
            await repo.save_search(search)
