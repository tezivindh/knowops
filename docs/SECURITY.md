# Security gate and scan interpretation

The pipeline scans the final backend, Nginx and Next.js server images with Trivy before pushing them to GHCR. It selects vulnerability scanning and HIGH/CRITICAL severity with `--exit-code 1`; a finding blocks image publication and therefore deployment. It does not use `--ignore-unfixed`, a CVE allowlist or `continue-on-error`.

Trivy is pinned to release 0.76.0 and its verified container digest in the workflow and local scan script. The gate applies to operating-system and application dependencies, including the extra Next.js runtime image. A clean scan is a point-in-time database result, not proof that the application has no vulnerabilities.

## Finding investigated during implementation

The initial Debian runtime scan reported 48 HIGH findings, including unfixed OS issues; the runtime was replaced with a patched Wolfi/Python 3.12 base. The first Wolfi scan also detected **CVE-2025-47273** in setuptools 70.3.0 referenced by pip's vendored dependency inventory. This vulnerability permits path traversal during PackageIndex downloads, leading to arbitrary file writes; fixed versions start at 78.1.1. Package-management tools are unnecessary for serving requests, so pip and its vendored code/inventory were removed from the final backend image while updated installed setuptools remained.

The Next.js runtime initially inherited vulnerable npm package-management dependencies. npm, Corepack and Yarn were removed from that runtime; builds still install dependencies in the isolated Node build stage. This removes unused software rather than disabling scanner rules.

Reference: [setuptools security advisory](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf).

## Secret handling

- Real `.env`, `.aws`, kubeconfigs, Terraform variable/state/plan files and rendered cluster Secrets are excluded from Git.
- Secrets are created directly in Kubernetes by `scripts/bootstrap-secrets.py`; it preserves existing values and never prints them.
- GitHub deploys through short-lived AWS OIDC credentials restricted to the repository's `capstone` environment, with namespace-scoped Kubernetes permissions. Bootstrap/infrastructure administration remains separate.
- Gitleaks checks history. Its only explicit exceptions are the two exact synthetic authentication keys used in the original test fixtures; it does not exempt an entire file or commit.
- Metrics labels use bounded route templates rather than user IDs, raw URLs or question text. `/metrics` is available on the internal backend Service and intentionally blocked at the frontend ingress path.
- The local `braces` guard applies only to development lint tooling. Its upstream advisory metadata remains visible; it is not shipped in the production frontend image.

Do not include Grafana passwords, registration tokens, API keys, real Terraform variable values or kubeconfig contents in screenshots. Keep Actions/package links and actual scan outputs as submission evidence.
