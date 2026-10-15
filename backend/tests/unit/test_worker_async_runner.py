"""Async resources must remain usable across consecutive Celery tasks."""

import asyncio

from app.services.queue.async_runner import close_runner, run_async


def test_consecutive_tasks_can_use_a_resource_bound_to_the_first_loop():
    async def create_resource():
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        return loop, future

    try:
        loop, future = run_async(create_resource())

        async def use_resource():
            loop.call_soon(future.set_result, "ready")
            return await future

        assert run_async(use_resource()) == "ready"
    finally:
        close_runner()
