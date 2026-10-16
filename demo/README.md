# KnowOps — Demo Materials

This directory contains presentation and demonstration materials for the DevSecOps capstone.

## Live Demo Script (8–10 minutes)

### Step 1 — Product walkthrough (2 min)
1. Open `http://localhost:3000` in a browser
2. Register a new account → create an organization (e.g., "Acme Corp")
3. Upload a PDF policy document (e.g., an employee handbook)
4. Wait ~15 seconds for the Celery worker to index the document (embedding model downloads on first use)
5. Ask a question: *"How many days of annual leave do employees get?"*
6. Show the grounded answer with **clickable citation** links back to the exact page/section

### Step 2 — API & quality gates (1 min)
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```
Show the 200 response with all four backing services green.

### Step 3 — Docker multi-stage build (1 min)
```bash
docker compose ps
docker compose exec backend id   # uid=10001 (non-root)
docker compose exec frontend id  # uid=101 (nginx non-root)
```

### Step 4 — Make a visible change and push (2 min)
Edit `frontend/src/app/page.tsx` — change the hero tagline in `HEADLINE` or the CTA button text.
```bash
git add frontend/src/app/page.tsx
git commit -m "ui: update hero headline for demo presentation"
git push origin main
```
Watch GitHub Actions at `https://github.com/tezivindh/knowops/actions`.

### Step 5 — CI/CD pipeline (1 min)
Point at the running Actions workflow showing:
- `backend-tests` (pytest 91 tests + ruff + mypy + alembic check)
- `frontend-checks` (npm test + lint + tsc + build)
- `infrastructure-checks` (terraform validate + test + helm lint)
- `secret-scan` (gitleaks)
- `images` (backend + frontend + next built, Trivy scanned, pushed to GHCR with SHA tag)

### Step 6 — Kubernetes + Terraform (1 min)
Show:
```bash
kubectl get pods -n knowops       # all Running
kubectl get svc,ingress -n knowops
helm list -n knowops
```
Show AWS Console: VPC `knowops-vpc` and EKS cluster `knowops` in `ap-south-1`.

### Step 7 — Observability (1 min)
```bash
curl http://localhost:8000/metrics | grep knowops_http
```
Open Grafana dashboard — show HTTP request rate and latency panels with live data.

### Step 8 — Security cleanup
```bash
# After evaluation:
cd terraform && terraform destroy -auto-approve
```
Capture the "Destroy complete!" output as evidence.

---

## Key URLs

| Service | URL |
|---------|-----|
| Application | http://localhost:3000 |
| Backend API health | http://localhost:8000/health |
| Backend readiness | http://localhost:8000/ready |
| API docs (debug mode) | http://localhost:8000/api/docs |
| Prometheus metrics | http://localhost:8000/metrics |
| MinIO console | http://localhost:9001 |
| GitHub Actions | https://github.com/tezivindh/knowops/actions |
| GHCR packages | https://github.com/tezivindh/knowops/pkgs/container |

---

## Architecture Diagram

```
Browser
  │
  ▼
Nginx (port 3000) ──────── non-root, multi-stage build
  │        │
  │        ▼
  │     Next.js server (port 3001) ── dynamic SSR routes
  │
  ▼
FastAPI (port 8000) ── non-root Wolfi container
  │       │        │
  │       ▼        ▼
  │   PostgreSQL  Qdrant (vector search)
  │   (SQLAlchemy/Alembic)
  │
  ├── Redis ── Celery worker (ingestion, conflict scans)
  │
  └── MinIO (original file storage)

Prometheus ── scrapes /metrics every 15s
Grafana ──── reads Prometheus, shows HTTP request/latency panels
```

---

## Presentation Checklist

- [ ] Application running (`docker compose up -d` complete)
- [ ] Document uploaded and indexed (worker processed it)
- [ ] Q&A with citations demonstrated
- [ ] `/health` and `/ready` shown live
- [ ] Non-root user verified (`id` in container)
- [ ] Commit pushed, Actions pipeline shown running
- [ ] Trivy scan result explained (see `docs/SECURITY.md`)
- [ ] AWS Terraform plan output shared (`evidence/terraform-mock-plan.txt`)
- [ ] Kubernetes pods shown Running
- [ ] Grafana dashboard with live HTTP metrics
- [ ] Terraform destroy output saved as evidence
