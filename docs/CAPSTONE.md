# DevOps capstone submission guide

Repository: https://github.com/tezivindh/knowops

This guide maps the implementation to the rubric. Evidence must be from an executed check; a mock Terraform plan is not evidence of AWS provisioning.

| Module | Implementation | Evidence / remaining external step |
|---|---|---|
| M1 | FastAPI, Next.js, PostgreSQL, Alembic; GET/POST/PUT/DELETE; `/health` | `evidence/backend-tests.txt`, browser screenshots |
| M2 | Isolated PostgreSQL test database, `backend/pytest.ini`, API/unit regressions, Ruff, strict mypy | `evidence/backend-tests.txt` (`pytest -v`) |
| M3 | Git repository, meaningful module commits, credential exclusions | Capture `git log`; GitHub publication requires authenticated Git access |
| M4 | Non-root multi-stage images; Node build, Nginx runtime, Next server sidecar; Compose port 3000 | `evidence/docker-build.txt`, Compose/browser evidence |
| M5 | `.github/workflows/action.yml`: push/main, tests before builds, frontend build, three image variants, GHCR SHA tags, gated EKS deployment | A green GitHub Actions URL and GHCR screenshot require an actual push/run |
| M6 | Trivy scans backend, Nginx and Next images; fails on HIGH/CRITICAL; no ignored CVEs | `evidence/trivy-*.txt`, `docs/SECURITY.md`; also capture CI scan output |
| M7 | `terraform/`: VPC, two public subnets, EKS/node group, EBS CSI, OIDC deployment identity | Init/validate/mock plan are local evidence only; real AWS plan/apply/destroy still require AWS credentials |
| M8 | `k8s/`, `helm/knowops/`; 2 backend and 2 frontend replicas, ClusterIP, Ingress | Local Minikube deployment evidence; repeat on EKS for AWS demonstration |
| M9 | `/metrics`, ServiceMonitor, kube-prometheus-stack, authenticated Grafana, provisioned dashboard | Metrics/targets/dashboard captures in `evidence/` |
| M10 | Root README, this guide, operational runbook and presentation steps | Live or recorded commit → pipeline → rollout demonstration remains a presentation activity |

## Required GitHub configuration

1. Authenticate Git and push `main`. Repository Actions builds/scans on every push. Publishing uses the scoped `GITHUB_TOKEN`; do not add a registry password to the repository.
2. Make the repository public or grant instructor access. GHCR packages may initially be private; set package visibility to public, or supply a Kubernetes image pull secret using a read-only package credential. The default chart assumes public images.
3. Bootstrap AWS/Kubernetes as described in `docs/OPERATIONS.md`.
4. Configure a dedicated Linux self-hosted runner with labels `self-hosted`, `linux`, `knowops-deploy`, and install AWS CLI v2, kubectl matching EKS, Helm 3, and Git. Its network must reach the EKS endpoint; include its egress IPv4 CIDR in Terraform `admin_cidrs` or run inside the VPC.
5. Create a GitHub environment named `capstone`, restrict it to `main`, and configure appropriate deployment protection. OIDC trust is restricted to this repository/environment. Apply `k8s/deployer-rbac.yaml` once as the cluster administrator.
6. Set repository/environment variables (not credentials): `CAPSTONE_DEPLOY_ENABLED=true`, `AWS_REGION=ap-south-1`, `EKS_CLUSTER_NAME=knowops`, `AWS_DEPLOY_ROLE_ARN` from Terraform output, `CAPSTONE_HOST` to the application hostname, `STORAGE_CLASS=gp3`.

The deployment job is intentionally inactive until `CAPSTONE_DEPLOY_ENABLED` is set. CI and image publication work without AWS. Never mark the deployment demo complete merely because that job was skipped.

## Presentation sequence (about 8–10 minutes)

1. Show the product at `http://localhost:3000` or the Ingress hostname. Register/sign in, create an organization, upload a sample policy and ask a cited question. Explain PostgreSQL, the asynchronous worker, object storage and vector search.
2. Show GET `/health`, authenticated CRUD requests and the isolated passing test suite.
3. Show non-root Docker image users and the multi-stage frontend build. Explain why Nginx proxies to a Next.js sidecar rather than discarding dynamic routes.
4. Show the repository commit history. Make a small visible change to the landing page, run local checks, commit it with a meaningful message and push to `main`.
5. Follow the Actions quality gates, image builds, Trivy gate, GHCR SHA tags, and EKS deploy job. Confirm the Deployment image tag equals that commit's SHA and show the visible change in the browser.
6. Show Terraform's real plan plus VPC/EKS in Mumbai, then the Helm release, two application replicas, Services and Ingress.
7. Generate read-only traffic with `scripts/generate-traffic.py`. Show both backend scrape targets UP and the populated Grafana dashboard.
8. After evaluation, run the documented AWS teardown and capture the successful destroy output. Keep the state until destroy succeeds.

## Evidence checklist

- [ ] Public repository URL or instructor access
- [ ] At least 10 meaningful commits and history screenshot
- [ ] Application screenshot at localhost:3000
- [ ] Verbose pytest screenshot
- [ ] Successful Compose startup screenshot
- [ ] Successful Actions run URL
- [ ] GHCR package page with SHA tags
- [ ] Trivy pipeline output and written explanation
- [ ] Real AWS Terraform plan screenshot
- [ ] VPC/EKS Console screenshot in ap-south-1
- [ ] Real Terraform destroy completion screenshot
- [ ] Pods, Services and Helm release screenshots
- [ ] Application through Ingress screenshot
- [ ] `/metrics` output screenshot
- [ ] Prometheus targets UP screenshot
- [ ] Grafana dashboard with live data screenshot
- [ ] Live or recorded deployment-update demonstration

Do not replace the AWS screenshots with local Minikube screenshots or the mock-provider plan. Local evidence validates the code but does not earn the real-provisioning criteria by itself.
