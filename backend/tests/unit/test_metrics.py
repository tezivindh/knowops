from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_metrics_count_requests_and_bound_unknown_paths():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        await client.get("/unknown-a")
        await client.get("/unknown-b")
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert 'handler="/health",method="GET",status="200"} 1.0' in response.text
        assert 'handler="unmatched",method="GET",status="404"} 2.0' in response.text
        assert "knowops_http_request_duration_seconds_bucket" in response.text
        assert "/unknown-a" not in response.text


async def test_app_instances_have_independent_registries():
    for _ in range(2):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health")
            metrics = (await client.get("/metrics")).text
            assert 'handler="/health",method="GET",status="200"} 1.0' in metrics
