"""HTTP metrics with bounded route labels and a registry per app instance."""

from time import perf_counter

from prometheus_client import CollectorRegistry, Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class MetricsMiddleware:
    def __init__(self, app: ASGIApp, registry: CollectorRegistry) -> None:
        self.app = app
        self.requests = Counter(
            "knowops_http_requests_total", "HTTP requests", ["method", "handler", "status"],
            registry=registry,
        )
        self.duration = Histogram(
            "knowops_http_request_duration_seconds", "HTTP request duration",
            ["method", "handler"], registry=registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") == "/metrics":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        status = 500

        async def record_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, record_status)
        finally:
            route = scope.get("route")
            handler = getattr(route, "path", "unmatched")
            method = scope.get("method", "UNKNOWN")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                method = "OTHER"
            self.requests.labels(method, handler, str(status)).inc()
            self.duration.labels(method, handler).observe(perf_counter() - started)
