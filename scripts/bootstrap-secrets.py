#!/usr/bin/env python3
"""Create cluster secrets without writing or printing credential values."""
import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import quote

parser = argparse.ArgumentParser()
parser.add_argument("--namespace", default="knowops")
parser.add_argument("--release", default="knowops")
args = parser.parse_args()


def create(namespace, name, values):
    exists = subprocess.run(
        ["kubectl", "get", "secret", name, "-n", namespace],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if exists:
        print(f"Keeping existing secret {namespace}/{name}")
        return
    manifest = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                "metadata": {"name": name, "namespace": namespace}, "stringData": values}
    subprocess.run(["kubectl", "create", "-f", "-"], input=json.dumps(manifest),
                   text=True, check=True, stdout=subprocess.DEVNULL)
    print(f"Created secret {namespace}/{name}; values were not written to disk")


# Only take the optional LLM key from .env; never execute the file as shell code.
llm_key = os.environ.get("LLM_API_KEY", "")
if not llm_key and Path(".env").exists():
    for line in Path(".env").read_text().splitlines():
        if line.startswith("LLM_API_KEY="):
            llm_key = line.split("=", 1)[1].strip().strip("\"'")
password = secrets.token_urlsafe(32)
create(args.namespace, f"{args.release}-secrets", {
    "SECRET_KEY": secrets.token_urlsafe(48),
    "JWT_SECRET_KEY": secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": password,
    "DATABASE_URL": f"postgresql+asyncpg://knowops:{quote(password, safe='')}@{args.release}-postgres:5432/knowops",
    "MINIO_ACCESS_KEY": "knowops",
    "MINIO_SECRET_KEY": secrets.token_urlsafe(48),
    "LLM_API_KEY": llm_key,
})
create("monitoring", "grafana-admin", {
    "admin-user": "admin", "admin-password": secrets.token_urlsafe(32),
})
