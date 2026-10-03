"""Webhook receiver for Instantly. Run with: sam-outbound serve"""
from __future__ import annotations

import hmac
import logging

from fastapi import FastAPI, HTTPException, Request

from .config import Config
from .hubspot import HubSpot
from .sync import SyncSettings, handle_event

log = logging.getLogger("sam_outbound")


def create_app(config: Config | None = None, hubspot: HubSpot | None = None) -> FastAPI:
    config = config or Config.from_env()
    hubspot = hubspot or HubSpot(config.hubspot_token)
    settings = SyncSettings(config.hubspot_pipeline, config.hubspot_deal_stage, config.hubspot_owner_id)
    app = FastAPI(title="SAM outbound sync")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/webhooks/instantly")
    async def instantly_webhook(request: Request, token: str = ""):
        if not config.webhook_secret or not hmac.compare_digest(token, config.webhook_secret):
            raise HTTPException(status_code=401, detail="bad token")
        event = await request.json()
        events = event if isinstance(event, list) else [event]
        results = []
        for e in events:
            try:
                results.append(handle_event(e, hubspot, settings))
            except Exception as exc:  # surface to Instantly as a 500 so it retries
                log.exception("sync failed for %s", e.get("lead_email"))
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"results": results}

    return app
