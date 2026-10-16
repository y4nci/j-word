from __future__ import annotations

from typing import Callable

# on_progress(done, total, message): called by long-running steps; must be cheap and non-blocking.
Progress = Callable[[int, int, str], None]


def noop_progress(done: int, total: int, message: str) -> None:
    pass
