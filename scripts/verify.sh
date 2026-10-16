#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence
# This quality gate executes BEFORE application runtime images are built.
(cd backend && python -m pip install -r requirements-dev.txt && \
  pytest -v && ruff check app tests && mypy app) 2>&1 | tee evidence/backend-tests.txt
(cd frontend && npm ci && npm test && npm run lint && npx tsc --noEmit && npm run build) \
  2>&1 | tee evidence/frontend-checks.txt
terraform -chdir=terraform init -backend=false -input=false
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform test
helm lint helm/knowops
docker compose build backend frontend next 2>&1 | tee evidence/docker-build.txt
bash scripts/scan-images.sh
