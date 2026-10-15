"""Keep application pods out of service until the release schema is ready."""

import asyncio

from alembic.config import Config
from alembic.script import ScriptDirectory
from migrate import connect


async def main():
    heads = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
    for _ in range(150):
        connection = None
        try:
            connection = await connect()
            rows = await connection.fetch("SELECT version_num FROM alembic_version")
            if {row["version_num"] for row in rows} == heads:
                return
        except Exception:
            pass
        finally:
            if connection is not None:
                await connection.close()
        await asyncio.sleep(2)
    raise RuntimeError("Migrations did not become ready within five minutes")


if __name__ == "__main__":
    asyncio.run(main())
