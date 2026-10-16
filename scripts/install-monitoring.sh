#!/usr/bin/env bash
set -euo pipefail
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add traefik https://traefik.github.io/charts
helm repo update
ingress_type="${INGRESS_SERVICE_TYPE:-LoadBalancer}"
helm upgrade --install traefik traefik/traefik --version 39.0.3 \
  --namespace traefik --create-namespace -f monitoring/traefik-values.yaml --set service.type="$ingress_type" --wait --timeout 10m
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.10.0 \
  --namespace monitoring --create-namespace \
  -f monitoring/prometheus-values.yaml -f monitoring/grafana-values.yaml --wait --timeout 15m
kubectl create configmap knowops-dashboard -n monitoring \
  --from-file=knowops.json=monitoring/dashboards/knowops.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl label configmap knowops-dashboard -n monitoring grafana_dashboard=1 --overwrite
