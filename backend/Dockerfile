# A patched Wolfi runtime avoids inheriting Debian's unfixed HIGH CVEs.
FROM cgr.dev/chainguard/wolfi-base@sha256:256c88bb066424045021090932d50be93c8e3f2ce3586707702a401b146f3e43 AS python-base
USER 0
RUN apk add --no-cache python-3.12 libgomp libstdc++ \
    && mkdir -p /home/knowops/.cache/fastembed \
    && chown -R 10001:10001 /home/knowops
ENV PATH="/opt/venv/bin:$PATH" HOME=/home/knowops \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    EMBEDDING_CACHE_DIR=/home/knowops/.cache/fastembed

FROM python-base AS builder
WORKDIR /build
RUN apk add --no-cache py3.12-pip build-base \
    && python3.12 -m venv /opt/venv
COPY pyproject.toml requirements.txt requirements-dev.txt ./
RUN python -c "import subprocess,tomllib; subprocess.check_call(['pip', 'install', '--no-cache-dir', *tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']])"
COPY . .
RUN pip install --no-cache-dir --no-deps -r requirements.txt

FROM builder AS test
RUN pip install --no-cache-dir -r requirements-dev.txt
USER 10001:10001
CMD ["pytest", "-v", "-p", "no:cacheprovider"]

FROM python-base AS runtime
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Package installation belongs in the builder, not the serving image.
RUN python -m pip uninstall --yes pip
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 scripts ./scripts
COPY --chown=10001:10001 alembic.ini pyproject.toml ./
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
