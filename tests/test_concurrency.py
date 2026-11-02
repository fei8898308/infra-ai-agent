import asyncio

import httpx
from conftest import AUTH, FLOWISE_KEY, TOKEN

from api.config import Settings
from api.main import create_app

PATH = "/webhooks/alertmanager"


async def test_inflight_duplicate_and_overload_are_retryable(payload):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def upstream(request):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return httpx.Response(200, json={"text": "Read-only checks"})

    settings = Settings(
        webhook_token=TOKEN,
        dry_run=False,
        flowise_api_key=FLOWISE_KEY,
        flowise_chatflow_id="test",
        flowise_read_only_confirmed=True,
        flowise_allow_insecure_http=True,
        max_inflight=1,
    )
    app = create_app(settings, httpx.MockTransport(upstream))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client,
    ):
        first = asyncio.create_task(client.post(PATH, json=payload, headers=AUTH))
        await asyncio.wait_for(started.wait(), timeout=2)
        assert (await client.post(PATH, json=payload, headers=AUTH)).status_code == 503
        payload["alerts"][0]["fingerprint"] = "1234567890abcdef"
        assert (await client.post(PATH, json=payload, headers=AUTH)).status_code == 503
        release.set()
        assert (await first).status_code == 200
        assert (await client.post(PATH, json=payload, headers=AUTH)).status_code == 200
        assert calls == 2


async def test_wall_clock_timeout_releases_claim(payload):
    calls = 0

    async def upstream(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(2)
        return httpx.Response(200, json={"text": "Recovered"})

    settings = Settings(
        webhook_token=TOKEN,
        dry_run=False,
        flowise_api_key=FLOWISE_KEY,
        flowise_chatflow_id="test",
        flowise_read_only_confirmed=True,
        flowise_allow_insecure_http=True,
        flowise_timeout_seconds=1,
    )
    app = create_app(settings, httpx.MockTransport(upstream))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client,
    ):
        response = await client.post(PATH, json=payload, headers=AUTH)
        assert response.status_code == 503
        assert response.json()["detail"] == "flowise_timeout"
        assert (await client.post(PATH, json=payload, headers=AUTH)).status_code == 200
