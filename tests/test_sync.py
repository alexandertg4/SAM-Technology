from fastapi.testclient import TestClient

from sam_outbound.config import Config
from sam_outbound.server import create_app
from sam_outbound.sync import SyncSettings, handle_event, suppress_customers

from .fakes import FakeHubSpotAPI, FakeInstantlyAPI

SETTINGS = SyncSettings(pipeline="default", deal_stage="appointmentscheduled", owner_id="77")


def interested(email="dana@hartwellcpa.com", kind="lead_interested"):
    return {
        "event_type": kind, "lead_email": email, "campaign_name": "Busy season 2027",
        "reply_text": "Yes, we're short two preparers for January. Can we talk next week?",
        "unibox_url": "https://app.instantly.ai/unibox/1", "first_name": "Dana",
        "company_name": "Hartwell & Co. CPAs",
    }


def test_interested_creates_contact_company_deal_task_and_note():
    hs = FakeHubSpotAPI()
    result = handle_event(interested(), hs.client(), SETTINGS)
    assert result["status"] == "synced"
    contact = hs.of("contacts")[0]
    assert contact["email"] == "dana@hartwellcpa.com"
    assert contact["hs_lead_status"] == "IN_PROGRESS"
    assert hs.of("companies")[0]["domain"] == "hartwellcpa.com"
    deal = hs.of("deals")[0]
    assert deal["dealname"] == "Hartwell & Co. CPAs - Outbound"
    assert deal["hubspot_owner_id"] == "77"
    task = hs.of("tasks")[0]
    assert task["hs_task_subject"].startswith("Book the call") and task["hubspot_owner_id"] == "77"
    assert "short two preparers" in hs.of("notes")[0]["hs_note_body"]


def test_second_hot_event_does_not_duplicate_deal():
    hs = FakeHubSpotAPI()
    client = hs.client()
    handle_event(interested(), client, SETTINGS)
    handle_event(interested(kind="lead_meeting_booked"), client, SETTINGS)
    assert len(hs.of("deals")) == 1
    assert len(hs.of("contacts")) == 1
    assert len(hs.of("tasks")) == 2


def test_plain_reply_logs_note_only():
    hs = FakeHubSpotAPI()
    handle_event(interested(kind="reply_received"), hs.client(), SETTINGS)
    assert len(hs.of("notes")) == 1
    assert hs.of("deals") == [] and hs.of("tasks") == []
    assert "hs_lead_status" not in hs.of("contacts")[0]


def test_not_interested_marks_unqualified():
    hs = FakeHubSpotAPI()
    handle_event(interested(kind="lead_not_interested"), hs.client(), SETTINGS)
    assert hs.of("contacts")[0]["hs_lead_status"] == "UNQUALIFIED"
    assert hs.of("deals") == []


def test_free_mail_skips_company_and_unknown_events_ignored():
    hs = FakeHubSpotAPI()
    handle_event(interested(email="dana@gmail.com"), hs.client(), SETTINGS)
    assert hs.of("companies") == []
    assert handle_event({"event_type": "email_opened", "lead_email": "x@y.com"}, hs.client(), SETTINGS)["status"] == "ignored"


def test_suppress_blocks_customer_domains():
    hs, inst = FakeHubSpotAPI(), FakeInstantlyAPI()
    hs.seed("contacts", {"email": "a@clientfirm.com", "lifecyclestage": "customer"})
    hs.seed("contacts", {"email": "b@clientfirm.com", "lifecyclestage": "customer"})
    hs.seed("contacts", {"email": "solo@gmail.com", "lifecyclestage": "opportunity"})
    hs.seed("contacts", {"email": "lead@prospect.com", "lifecyclestage": "lead"})
    blocked = suppress_customers(hs.client(), inst.client())
    assert blocked == ["clientfirm.com", "solo@gmail.com"]
    assert inst.blocked == blocked


def _app(hs):
    config = Config("", "", "tok", "", "default", "appointmentscheduled", "s3cret", "")
    return TestClient(create_app(config, hs.client()))


def test_webhook_requires_token():
    hs = FakeHubSpotAPI()
    client = _app(hs)
    assert client.post("/webhooks/instantly", json=interested()).status_code == 401
    assert client.post("/webhooks/instantly?token=nope", json=interested()).status_code == 401
    resp = client.post("/webhooks/instantly?token=s3cret", json=interested())
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "synced"
    assert len(hs.of("deals")) == 1


def test_suppress_blocks_isp_addresses_individually():
    hs, inst = FakeHubSpotAPI(), FakeInstantlyAPI()
    for email in ["a@sbcglobal.net", "b@verizon.net", "c@proton.me", "d@att.net"]:
        hs.seed("contacts", {"email": email, "lifecyclestage": "customer"})
    blocked = suppress_customers(hs.client(), inst.client())
    assert blocked == ["a@sbcglobal.net", "b@verizon.net", "c@proton.me", "d@att.net"]
