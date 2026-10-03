"""Hiring-signal prospector: scored firms + decision-maker contacts -> Instantly campaign + HubSpot."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass

from .hubspot import HubSpot
from .instantly import Instantly
from .scoring import Firm, normalize_company

# Higher is better: who signs off on outsourcing busy-season capacity at a CPA firm.
TITLE_RANK = [
    (re.compile(r"managing (partner|director|member)", re.I), 100),
    (re.compile(r"\b(founder|owner|president|ceo)\b", re.I), 90),
    (re.compile(r"\b(tax partner|partner|principal|shareholder)\b", re.I), 80),
    (re.compile(r"\b(coo|chief operating|director of operations|firm administrator)\b", re.I), 70),
    (re.compile(r"\btax director\b|\bdirector of tax\b", re.I), 60),
    (re.compile(r"\btax manager\b", re.I), 40),
]


def title_rank(title: str) -> int:
    for pattern, rank in TITLE_RANK:
        if pattern.search(title or ""):
            return rank
    return 0


@dataclass
class Contact:
    email: str
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company: str = ""
    domain: str = ""


def load_contacts(path: str) -> list[Contact]:
    """Columns (case-insensitive): email, first_name, last_name, title, company, domain."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            email = row.get("email", "").lower()
            if "@" not in email:
                continue
            domain = (row.get("domain") or email.split("@", 1)[1]).lower().removeprefix("www.")
            out.append(Contact(email=email, first_name=row.get("first_name", ""), last_name=row.get("last_name", ""),
                               title=row.get("title", ""), company=row.get("company", ""), domain=domain))
    return out


def best_contact(firm: Firm, contacts: list[Contact]) -> Contact | None:
    matches = [c for c in contacts
               if (firm.domain and c.domain == firm.domain)
               or (c.company and normalize_company(c.company) == firm.key)]
    return max(matches, key=lambda c: title_rank(c.title), default=None)


def first_line(firm: Firm) -> str:
    p = firm.top_posting
    where = f" in {p.location.split(',')[0]}" if p.location else ""
    article = "an" if p.title[:1].lower() in "aeiou" else "a"
    return f"Saw {firm.name} is hiring {article} {p.title}{where} ahead of busy season."


@dataclass
class Outcome:
    firm: Firm
    contact: Contact | None
    action: str  # queued | added | skipped
    reason: str = ""


def run(firms: list[Firm], contacts: list[Contact], *, min_score: int, campaign_id: str,
        instantly: Instantly | None, hubspot: HubSpot | None, dry_run: bool) -> list[Outcome]:
    outcomes = []
    for firm in firms:
        if firm.score < min_score:
            outcomes.append(Outcome(firm, None, "skipped", f"score {firm.score} below {min_score}"))
            continue
        contact = best_contact(firm, contacts)
        if not contact:
            outcomes.append(Outcome(firm, None, "skipped", "no decision-maker contact found"))
            continue
        if not firm.domain:
            firm.domain = contact.domain

        if hubspot:
            existing = hubspot.find_contact(contact.email)
            if existing:
                stage = existing.get("properties", {}).get("lifecyclestage") or ""
                if stage in ("customer", "evangelist", "opportunity"):
                    outcomes.append(Outcome(firm, contact, "skipped", f"already a HubSpot {stage}"))
                    continue
                if hubspot.open_deal_for_contact(existing["id"]):
                    outcomes.append(Outcome(firm, contact, "skipped", "has an open HubSpot deal"))
                    continue

        if dry_run:
            outcomes.append(Outcome(firm, contact, "queued", "dry run"))
            continue

        p = firm.top_posting
        instantly.add_lead(campaign_id, {
            "email": contact.email,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "company_name": firm.name,
            "job_title": contact.title,
            "website": firm.domain,
            "personalization": first_line(firm),
            "custom_variables": {
                "hiring_role": p.title,
                "hiring_location": p.location,
                "signal_score": firm.score,
                "signal_reasons": "; ".join(firm.reasons),
                "job_url": p.url,
            },
        })
        if hubspot:
            company_id = hubspot.upsert_company(firm.domain, {"name": firm.name}) if firm.domain else None
            contact_id = hubspot.upsert_contact(contact.email, {
                "firstname": contact.first_name,
                "lastname": contact.last_name,
                "jobtitle": contact.title,
                "company": firm.name,
                "hs_lead_status": "NEW",
            }, company_id)
            hubspot.add_note(contact_id, (
                f"Added to Instantly outbound (hiring signal, score {firm.score}).<br>"
                f"Signals: {'; '.join(firm.reasons)}.<br>"
                f"Posting: {p.title} {('- ' + p.url) if p.url else ''}"
            ))
        outcomes.append(Outcome(firm, contact, "added"))
    return outcomes


def write_report(outcomes: list[Outcome], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["action", "reason", "firm", "score", "signals", "top_posting", "posting_url",
                    "contact_email", "contact_name", "contact_title", "first_line"])
        for o in outcomes:
            p = o.firm.top_posting
            c = o.contact
            w.writerow([o.action, o.reason, o.firm.name, o.firm.score, "; ".join(o.firm.reasons), p.title, p.url,
                        c.email if c else "", f"{c.first_name} {c.last_name}".strip() if c else "",
                        c.title if c else "", first_line(o.firm)])
