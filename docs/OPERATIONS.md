# Deployment and teardown

## Local Docker

```bash
cp .env.example .env
# Replace SECRET_KEY/JWT_SECRET_KEY with different random strings and set LLM_API_KEY.
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

Open http://localhost:3000. Port 5173 is retained as a compatibility alias. API calls use `/api` on the same origin; Nginx forwards them to the API and forwards pages to the Next.js server. The API initializes the schema and storage before the worker/reconciler start. File/model data persists in Docker volumes. `docker compose down` stops services without deleting volumes.

For development outside Docker, install `backend/requirements-dev.txt`, start backing services with Compose, then run Uvicorn, Celery, the reconciler and `npm run dev` in separate terminals. The Next development server proxies `/api` to localhost:8000.

To rerun tests in Docker (uses only `knowops_test`):

```bash
docker compose --profile test run --rm test
```

The GitHub pipeline runs tests before building production images. Local `scripts/verify.sh` follows the same order; activate a Python 3.12+ virtual environment first and ensure the test PostgreSQL database exists. It never applies Terraform.

## Local Kubernetes

Requirements: Docker, Minikube, kubectl, Helm 3, Python 3, and the verified local images.

```bash
bash scripts/verify.sh
bash scripts/deploy-local.sh
kubectl get pods,svc,ingress -n knowops
helm list -n knowops
curl -H 'Host: knowops.local' "http://$(minikube ip):30080/"
```

On Linux, map `knowops.local` to `minikube ip` in your hosts file and open `http://knowops.local:30080`. Alternatively, forward the ingress controller locally:

```bash
kubectl port-forward -n traefik svc/traefik 8080:80
# Open http://localhost:8080 with Host: knowops.local, or use the hosts mapping.
```

Namespaces, secrets and Helm releases are separate bootstrap steps. `scripts/bootstrap-secrets.py` sends random secrets directly to kubectl, copies only the optional LLM key from `.env`, and preserves existing secrets. It prints no secret values. Never commit a rendered Secret or real kubeconfig.

The Helm migration Job runs once per release revision, waits for PostgreSQL, takes a PostgreSQL advisory lock, applies Alembic and initializes the MinIO bucket. Application init containers wait for the expected migration heads. Jobs remain for one day for inspection. Images are immutable by SHA in CI; `local` is used only for local development.

## AWS Mumbai

Real infrastructure incurs EKS, EC2, EBS, logging, public IPv4 and LoadBalancer charges. This repository does not automatically apply or destroy infrastructure.

```bash
aws sso login --profile capstone    # Or use your organization's normal credentials.
export AWS_PROFILE=capstone
aws sts get-caller-identity
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Set your public IP and deployment runner CIDR in admin_cidrs.
terraform -chdir=terraform init
terraform -chdir=terraform validate
terraform -chdir=terraform plan -out=capstone.tfplan
terraform -chdir=terraform apply capstone.tfplan
aws eks update-kubeconfig --region ap-south-1 --name knowops
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployer-rbac.yaml
kubectl apply -f k8s/storageclass-eks.yaml
python3 scripts/bootstrap-secrets.py
bash scripts/install-monitoring.sh
```

The initial administrator must apply the namespace/RBAC and bootstrap secrets before enabling CI deployment. The GitHub OIDC role gets EKS discovery permission and a namespace-scoped Kubernetes group; it cannot provision AWS infrastructure. It needs no long-lived AWS access key.

The small capstone cluster uses public worker subnets to avoid a NAT gateway. Nodes have no SSH rule; the Kubernetes API is restricted to explicit administrator/runner CIDRs. This is a cost-conscious teaching topology, not a complete enterprise network design. For production, move nodes into private subnets, use a controlled egress path, external managed data services, TLS and a remote encrypted/locked Terraform state backend.

EBS CSI is provisioned by Terraform; `gp3` StorageClass is provided separately. Set `persistence.storageClass=gp3` on EKS. Images must be pushed and publicly pullable (or configure `imagePullSecrets`).

Get the ingress controller's LoadBalancer hostname:

```bash
kubectl get svc traefik -n traefik
```

Point a hostname you control at that LoadBalancer, set `CAPSTONE_HOST` accordingly, and configure TLS through `ingress.tls` with an existing TLS Secret. Web Locks for cross-tab refresh require a secure browser context (HTTPS, or localhost).

## Monitoring

```bash
kubectl port-forward -n monitoring svc/monitoring-grafana 3002:80
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
kubectl port-forward -n knowops svc/knowops-backend 8001:8000
curl http://localhost:8001/metrics
python3 scripts/generate-traffic.py --url http://localhost:8001/health
```

Grafana: http://localhost:3002, user `admin`. Retrieve the generated password privately:

```bash
kubectl get secret grafana-admin -n monitoring -o jsonpath='{.data.admin-password}' | base64 --decode
```

Do not capture that command's output in submission screenshots. Dashboard: `/d/knowops-overview/knowops-application`. Prometheus targets: http://localhost:9090/targets. Query `sum(knowops_http_requests_total{namespace="knowops"})`. Both backend replicas should be UP through their ServiceMonitor endpoints. The ingress intentionally does not publish `/metrics`.

## AWS teardown — after the evaluation

Back up any data you need first. Helm uninstall removes the application's PVCs and can destroy uploaded documents and database contents.

1. Uninstall application and monitoring releases while the EKS API and nodes still work. This allows Kubernetes to delete LoadBalancers and EBS volumes rather than orphaning billable resources.
2. Check cloud-managed Services and PVCs are gone, then destroy Terraform-managed infrastructure.

```bash
helm uninstall knowops -n knowops
helm uninstall monitoring -n monitoring
helm uninstall traefik -n traefik
kubectl get svc,pvc -A
terraform -chdir=terraform plan -destroy -out=destroy.tfplan
terraform -chdir=terraform apply destroy.tfplan
# Capture the completion output and verify EC2/EKS/ELB/EBS in the AWS Console.
```

Keep `terraform.tfstate` until cleanup succeeds. State and plans can contain sensitive values and are gitignored. Never delete state to make resources appear destroyed. Do not delete existing unrelated AWS resources or Minikube workloads.
