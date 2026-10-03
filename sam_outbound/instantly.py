"""Thin Instantly API v2 client covering what the outbound tools need."""
from __future__ import annotations

import httpx

BASE_URL = "https://api.instantly.ai"


class Instantly:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=BASE_URL, timeout=30)
        self.http.headers["Authorization"] = f"Bearer {api_key}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = self.http.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def add_lead(self, campaign_id: str, lead: dict) -> dict:
        """Add one lead to a campaign. Leads already in the workspace are skipped, not duplicated."""
        body = {"campaign": campaign_id, "skip_if_in_workspace": True, **lead}
        return self._request("POST", "/api/v2/leads", json=body)

    def block(self, value: str) -> dict:
        """Add an email or domain to the workspace block list so no campaign emails it."""
        return self._request("POST", "/api/v2/block-lists-entries", json={"bl_value": value.lower()})
