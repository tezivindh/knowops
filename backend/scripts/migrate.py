"""Serialize release migrations and initialize object storage before serving traffic."""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.storage.client import StorageService  # noqa: E402


async def connect():
    url = make_url(get_settings().database_url)
    return await asyncpg.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, database=url.database, timeout=5,
    )


async def main():
    for attempt in range(90):
        try:
            connection = await connect()
            break
        except (OSError, asyncpg.PostgresError):
            if attempt == 89:
                raise
            await asyncio.sleep(2)
    try:
        await connection.execute("SELECT pg_advisory_lock(846305170)")
        await asyncio.to_thread(
            subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "head"], check=True
        )
    finally:
        await connection.close()
    for attempt in range(60):
        try:
            await asyncio.to_thread(StorageService().ensure_bucket)
            return
        except Exception:
            if attempt == 59:
                raise
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
