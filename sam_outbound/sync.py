"""Instantly -> HubSpot sync.

Turns Instantly webhook events into HubSpot records so sales works every reply from the CRM:
- interested / meeting booked: contact + company, reply logged as a note, a deal (unless one is open)
  and a high-priority follow-up task for the owner.
- any other reply: contact + note.
- not interested / wrong person / unsubscribed / bounced: lead status updated + note.
Event names follow https://developer.instantly.ai/guides/webhook-events.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from .hubspot import HubSpot
from .instantly import Instantly

HOT = {"lead_interested", "lead_meeting_booked"}
REPLY = {"reply_received"}
COLD = {
    "lead_not_interested": "UNQUALIFIED",
    "lead_wrong_person": "UNQUALIFIED",
    "lead_unsubscribed": "UNQUALIFIED",
    "email_bounced": "UNQUALIFIED",
}
FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com", "outlook.com", "hotmail.com",
    "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "mail.com", "gmx.com", "zoho.com",
    "proton.me", "protonmail.com", "pm.me", "fastmail.com", "comcast.net", "sbcglobal.net", "att.net",
    "bellsouth.net", "verizon.net", "optonline.net", "cox.net", "charter.net", "earthlink.net", "frontier.com",
    "frontiernet.net", "windstream.net", "centurylink.net", "roadrunner.com", "twc.com", "rr.com", "juno.com",
    "netzero.net", "q.com", "embarqmail.com", "suddenlink.net", "mediacombb.net", "hughes.net", "aim.com",
}


@dataclass
class SyncSettings:
    pipeline: str = "default"
    deal_stage: str = "appointmentscheduled"
    owner_id: str = ""


def _field(event: dict, *names: str) -> str:
    for n in names:
        if event.get(n):
            return str(event[n]).strip()
    return ""


def handle_event(event: dict, hubspot: HubSpot, settings: SyncSettings) -> dict:
    kind = event.get("event_type", "")
    email = _field(event, "lead_email", "email").lower()
    if kind not in HOT | REPLY | set(COLD) or "@" not in email:
        return {"status": "ignored", "event_type": kind}

    domain = email.split("@", 1)[1]
    company_name = _field(event, "company_name", "companyName")
    company_id = None
    if domain not in FREE_MAIL:
        company_id = hubspot.upsert_company(domain, {"name": company_name})

    props = {
        "firstname": _field(event, "first_name", "firstName"),
        "lastname": _field(event, "last_name", "lastName"),
        "company": company_name,
    }
    if kind in HOT:
        props["hs_lead_status"] = "IN_PROGRESS"
    elif kind in COLD:
        props["hs_lead_status"] = COLD[kind]
    contact_id = hubspot.upsert_contact(email, props, company_id)

    reply = _field(event, "reply_text", "reply_text_snippet")
    campaign = _field(event, "campaign_name", "campaign_id")
    label = kind.replace("lead_", "").replace("_", " ")
    note = f"<b>Instantly: {html.escape(label)}</b> (campaign: {html.escape(campaign)})"
    if reply:
        note += "<br><br>" + html.escape(reply[:4000]).replace("\n", "<br>")
    if event.get("unibox_url"):
        note += f"<br><br><a href=\"{html.escape(event['unibox_url'])}\">Open in Instantly Unibox</a>"
    hubspot.add_note(contact_id, note)

    result = {"status": "synced", "event_type": kind, "contact_id": contact_id, "company_id": company_id}
    if kind in HOT:
        if not hubspot.open_deal_for_contact(contact_id):
            name = company_name or domain
            result["deal_id"] = hubspot.create_deal(f"{name} - Outbound", settings.pipeline, settings.deal_stage,
                                                    contact_id, company_id, settings.owner_id)
        subject = "Book the call" if kind == "lead_interested" else "Prep for booked meeting"
        result["task_id"] = hubspot.create_task(
            contact_id, f"{subject}: {email}",
            f"Instantly marked this lead {label}. Reply:\n\n{reply[:1000]}", settings.owner_id)
    return result


def suppress_customers(hubspot: HubSpot, instantly: Instantly, dry_run: bool = False) -> list[str]:
    """Block every current customer and open opportunity in Instantly so outbound never hits them.

    Business domains are blocked as a whole (covers everyone at the firm); free-mail addresses individually.
    """
    groups = [{"filters": [{"propertyName": "lifecyclestage", "operator": "IN",
                            "values": ["customer", "opportunity", "evangelist"]}]}]
    blocked: list[str] = []
    for contact in hubspot.iter_contacts(groups, ["email"]):
        email = (contact.get("properties", {}).get("email") or "").lower()
        if "@" not in email:
            continue
        domain = email.split("@", 1)[1]
        value = email if domain in FREE_MAIL else domain
        if value in blocked:
            continue
        if not dry_run:
            instantly.block(value)
        blocked.append(value)
    return blocked
