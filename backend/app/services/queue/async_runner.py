"""Keep async clients on one event loop for the lifetime of a worker process."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from celery.signals import worker_process_shutdown, worker_shutdown

T = TypeVar("T")
_runner: asyncio.Runner | None = None


def run_async(coroutine: Coroutine[Any, Any, T]) -> T:
    # Initialize after Celery forks so no event loop is inherited from the parent.
    global _runner
    if _runner is None:
        _runner = asyncio.Runner()
    return _runner.run(coroutine)


@worker_process_shutdown.connect
@worker_shutdown.connect
def close_runner(**kwargs: Any) -> None:
    global _runner
    if _runner is not None:
        _runner.close()
        _runner = None
