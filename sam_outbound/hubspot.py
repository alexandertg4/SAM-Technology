"""Thin HubSpot CRM v3 client covering what the outbound tools need."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

BASE_URL = "https://api.hubapi.com"

# HubSpot-defined association type ids (https://developers.hubspot.com/docs/api/crm/associations)
DEAL_TO_CONTACT = 3
DEAL_TO_COMPANY = 5
CONTACT_TO_COMPANY = 1
NOTE_TO_CONTACT = 202
TASK_TO_CONTACT = 204


def _assoc(object_id: str, type_id: int) -> dict:
    return {
        "to": {"id": object_id},
        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}],
    }


class HubSpot:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=BASE_URL, timeout=30)
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = self.http.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # --- search -----------------------------------------------------------
    def _search_one(self, object_type: str, prop: str, value: str, properties: list[str]) -> dict | None:
        body = {
            "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
            "properties": properties,
            "limit": 1,
        }
        results = self._request("POST", f"/crm/v3/objects/{object_type}/search", json=body).get("results", [])
        return results[0] if results else None

    def find_contact(self, email: str) -> dict | None:
        return self._search_one("contacts", "email", email.lower(), ["email", "lifecyclestage", "hubspot_owner_id"])

    def find_company(self, domain: str) -> dict | None:
        return self._search_one("companies", "domain", domain.lower(), ["domain", "name"])

    def iter_contacts(self, filter_groups: list[dict], properties: list[str]):
        """Yield every contact matching the filter groups, following pagination."""
        after = None
        while True:
            body = {"filterGroups": filter_groups, "properties": properties, "limit": 100}
            if after:
                body["after"] = after
            page = self._request("POST", "/crm/v3/objects/contacts/search", json=body)
            yield from page.get("results", [])
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                return

    # --- upserts ----------------------------------------------------------
    def upsert_company(self, domain: str, properties: dict) -> str:
        existing = self.find_company(domain)
        props = {"domain": domain.lower(), **{k: v for k, v in properties.items() if v not in (None, "")}}
        if existing:
            self._request("PATCH", f"/crm/v3/objects/companies/{existing['id']}", json={"properties": props})
            return existing["id"]
        return self._request("POST", "/crm/v3/objects/companies", json={"properties": props})["id"]

    def upsert_contact(self, email: str, properties: dict, company_id: str | None = None) -> str:
        existing = self.find_contact(email)
        props = {"email": email.lower(), **{k: v for k, v in properties.items() if v not in (None, "")}}
        if existing:
            contact_id = existing["id"]
            self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json={"properties": props})
        else:
            contact_id = self._request("POST", "/crm/v3/objects/contacts", json={"properties": props})["id"]
        if company_id:
            self._request(
                "PUT", f"/crm/v4/objects/contact/{contact_id}/associations/default/company/{company_id}"
            )
        return contact_id

    # --- engagement objects ----------------------------------------------
    def create_deal(self, name: str, pipeline: str, stage: str, contact_id: str,
                    company_id: str | None = None, owner_id: str = "") -> str:
        associations = [_assoc(contact_id, DEAL_TO_CONTACT)]
        if company_id:
            associations.append(_assoc(company_id, DEAL_TO_COMPANY))
        props = {"dealname": name, "pipeline": pipeline, "dealstage": stage}
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return self._request("POST", "/crm/v3/objects/deals",
                             json={"properties": props, "associations": associations})["id"]

    def open_deal_for_contact(self, contact_id: str) -> bool:
        """True if the contact already has a deal that is not closed."""
        resp = self._request("GET", f"/crm/v4/objects/contact/{contact_id}/associations/deal")
        for row in resp.get("results", []):
            deal = self._request("GET", f"/crm/v3/objects/deals/{row['toObjectId']}",
                                 params={"properties": "hs_is_closed"})
            if deal.get("properties", {}).get("hs_is_closed") != "true":
                return True
        return False

    def create_task(self, contact_id: str, subject: str, body: str, owner_id: str = "") -> str:
        props = {
            "hs_timestamp": datetime.now(timezone.utc).isoformat(),
            "hs_task_subject": subject,
            "hs_task_body": body,
            "hs_task_status": "NOT_STARTED",
            "hs_task_priority": "HIGH",
        }
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return self._request("POST", "/crm/v3/objects/tasks",
                             json={"properties": props, "associations": [_assoc(contact_id, TASK_TO_CONTACT)]})["id"]

    def add_note(self, contact_id: str, body: str) -> str:
        props = {"hs_timestamp": datetime.now(timezone.utc).isoformat(), "hs_note_body": body}
        return self._request("POST", "/crm/v3/objects/notes",
                             json={"properties": props, "associations": [_assoc(contact_id, NOTE_TO_CONTACT)]})["id"]
