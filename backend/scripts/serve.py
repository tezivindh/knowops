"""Compose entrypoint: prepare the schema/storage, then replace this process with Uvicorn."""
import os
import subprocess
import sys

subprocess.run([sys.executable, "scripts/migrate.py"], check=True)
os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"])
