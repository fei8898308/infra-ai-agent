import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from api.config import Settings
from api.dedup import Deduplicator
from api.models import Notification
from integrations.flowise import FlowiseClient, FlowiseError

logger = logging.getLogger("infra_ai_agent")


def create_app(settings=None, transport=None):
    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        # Fail closed at startup. No token defaults and no secrets in tracebacks.
        try:
            config = settings or Settings.from_environment()
        except (ValueError, OSError):
            raise RuntimeError(
                "Invalid configuration; check required settings and secret files"
            ) from None
        app.state.settings = config
        app.state.dedup = Deduplicator(
            config.dedup_ttl_seconds, config.dedup_max_entries, config.max_inflight
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.flowise_timeout_seconds, connect=5),
            limits=httpx.Limits(
                max_connections=config.max_inflight, max_keepalive_connections=config.max_inflight
            ),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            app.state.flowise = FlowiseClient(config, client)
            yield

    app = FastAPI(
        title="Infrastructure AI Agent",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def health():
        return {
            "status": "ok",
            "mode": "dry_run" if app.state.settings.dry_run else "analysis_only",
            "remediation_enabled": False,
        }

    @app.post("/webhooks/alertmanager")
    async def webhook(request: Request):
        config = app.state.settings
        authorization = request.headers.getlist("authorization")
        expected = ("Bearer " + config.webhook_token.get_secret_value()).encode("ascii")
        if len(authorization) != 1 or not hmac.compare_digest(
            authorization[0].encode("utf-8"), expected
        ):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(415, "Content-Type must be application/json")
        if request.headers.get("content-encoding", "identity").lower() != "identity":
            raise HTTPException(415, "Compressed request bodies are not supported")
        lengths = request.headers.getlist("content-length")
        if lengths:
            if (
                len(lengths) != 1
                or not lengths[0].isascii()
                or not lengths[0].isdigit()
                or len(lengths[0]) > 10
            ):
                raise HTTPException(400, "Invalid Content-Length")
            if int(lengths[0]) > config.max_body_bytes:
                raise HTTPException(413, "Request body too large")
        raw = bytearray()
        try:
            async with asyncio.timeout(config.body_timeout_seconds):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > config.max_body_bytes:
                        raise HTTPException(413, "Request body too large")
                    raw.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Request body timed out") from None
        except ClientDisconnect:
            raise HTTPException(400, "Incomplete request body") from None
        try:
            notification = Notification.model_validate_json(bytes(raw))
        except (ValidationError, ValueError):
            # Pydantic's default errors echo input; do not return or log those.
            raise HTTPException(422, "Invalid Alertmanager v4 notification") from None
        event_id = notification.event_id()
        state = app.state.dedup.claim(event_id)
        base = {
            "event_id": event_id,
            "alert_count": len(notification.alerts),
            "alert_status": notification.status,
            "remediation_enabled": False,
        }
        if state == "duplicate":
            return {**base, "status": "duplicate"}
        if state == "busy":
            raise HTTPException(503, "Analysis busy; retry later", headers={"Retry-After": "5"})
        try:
            if config.dry_run:
                result = {**base, "status": "dry_run", "analysis": None}
            else:
                answer = await app.state.flowise.analyze(notification.normalized())
                result = {**base, "status": "analyzed", "analysis": answer}
            app.state.dedup.finish(event_id)
            logger.info(
                "webhook_completed event_id=%s status=%s alert_count=%d alert_status=%s",
                event_id,
                result["status"],
                len(notification.alerts),
                notification.status,
            )
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except FlowiseError as exc:
            logger.warning("webhook_failed event_id=%s code=%s", event_id, exc.code)
            # Alertmanager retries 5xx; never report success for lost analysis.
            raise HTTPException(503, exc.code, headers={"Retry-After": "5"}) from None
        finally:
            # Also release on cancellation; failures never poison deduplication.
            app.state.dedup.release(event_id)

    return app


app = create_app()
