#!/usr/bin/env bash
set -euo pipefail
# The images must have passed tests and scans first (scripts/verify.sh).
minikube start --driver=docker
kubectl apply -f k8s/namespace.yaml
python3 scripts/bootstrap-secrets.py
for image in knowops-backend:local knowops-frontend:local knowops-next:local; do
  minikube image load "$image"
done
INGRESS_SERVICE_TYPE=NodePort bash scripts/install-monitoring.sh
helm upgrade --install knowops helm/knowops --namespace knowops \
  --set metrics.serviceMonitor.enabled=true --wait --wait-for-jobs --timeout 15m
kubectl get pods,svc,ingress -n knowops
helm list -n knowops
printf 'Local Ingress: http://%s:30080 (send Host: knowops.local)\n' "$(minikube ip)"
