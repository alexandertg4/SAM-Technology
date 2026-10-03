"""In-memory fakes for the HubSpot and Instantly HTTP APIs, built on httpx.MockTransport."""
import json
import re

import httpx

from sam_outbound.hubspot import HubSpot
from sam_outbound.instantly import Instantly


class FakeHubSpotAPI:
    def __init__(self):
        self.objects = {"contacts": {}, "companies": {}, "deals": {}, "tasks": {}, "notes": {}}
        self.assocs = []  # (from_type, from_id, to_type, to_id)
        self.calls = []
        self._next = 100

    def _id(self):
        self._next += 1
        return str(self._next)

    def seed(self, kind, props):
        oid = self._id()
        self.objects[kind][oid] = dict(props)
        return oid

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        self.calls.append((method, path, body))

        if m := re.fullmatch(r"/crm/v3/objects/(\w+)/search", path):
            kind = m.group(1)
            f = body["filterGroups"][0]["filters"][0]
            if f["operator"] == "EQ":
                hits = [(i, p) for i, p in self.objects[kind].items() if p.get(f["propertyName"]) == f["value"]]
            else:
                hits = [(i, p) for i, p in self.objects[kind].items() if p.get(f["propertyName"]) in f["values"]]
            return httpx.Response(200, json={"results": [{"id": i, "properties": p} for i, p in hits]})

        if m := re.fullmatch(r"/crm/v3/objects/(\w+)", path):
            kind = m.group(1)
            oid = self._id()
            self.objects[kind][oid] = dict(body["properties"])
            for a in body.get("associations", []):
                self.assocs.append((kind, oid, a["types"][0]["associationTypeId"], a["to"]["id"]))
            return httpx.Response(201, json={"id": oid, "properties": body["properties"]})

        if m := re.fullmatch(r"/crm/v3/objects/(\w+)/(\d+)", path):
            kind, oid = m.groups()
            if method == "PATCH":
                self.objects[kind][oid].update(body["properties"])
            return httpx.Response(200, json={"id": oid, "properties": self.objects[kind][oid]})

        if m := re.fullmatch(r"/crm/v4/objects/contact/(\d+)/associations/default/company/(\d+)", path):
            self.assocs.append(("contact", m.group(1), "company", m.group(2)))
            return httpx.Response(200, json={})

        if m := re.fullmatch(r"/crm/v4/objects/contact/(\d+)/associations/deal", path):
            cid = m.group(1)
            deals = [{"toObjectId": did} for (k, did, _t, to) in self.assocs if k == "deals" and to == cid]
            return httpx.Response(200, json={"results": deals})

        return httpx.Response(404, json={"message": f"unhandled {method} {path}"})

    def client(self, token="test"):
        return HubSpot(token, httpx.Client(base_url="https://api.hubapi.com",
                                           transport=httpx.MockTransport(self.handler)))

    def of(self, kind):
        return list(self.objects[kind].values())


class FakeInstantlyAPI:
    def __init__(self):
        self.leads, self.blocked = [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/api/v2/leads":
            self.leads.append(body)
            return httpx.Response(200, json={"id": "lead", **body})
        if request.url.path == "/api/v2/block-lists-entries":
            self.blocked.append(body["bl_value"])
            return httpx.Response(200, json={"id": "bl", **body})
        return httpx.Response(404)

    def client(self):
        return Instantly("key", httpx.Client(base_url="https://api.instantly.ai",
                                             transport=httpx.MockTransport(self.handler)))
