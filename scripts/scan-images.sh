#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence
status=0
for component in backend frontend next; do
  if ! docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    -v knowops_trivy_cache:/root/.cache/trivy \
    -v "$PWD/evidence:/results" aquasec/trivy:0.76.0@sha256:2416d1f74045b57274df1a340eee6b510cacd73c66a6ccb8da092b117eb7d222 image \
    --scanners vuln --severity HIGH,CRITICAL --exit-code 1 \
    --format table --output "/results/trivy-$component.txt" "knowops-$component:local"; then
    status=1
  fi
done
exit "$status"
