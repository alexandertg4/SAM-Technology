"""Hiring signals: job postings that suggest an accounting firm is short on tax capacity.

Two sources:
- a CSV export (from Indeed, LinkedIn, ZipRecruiter or any job board), and
- Google Jobs via SerpAPI when SERPAPI_KEY is set.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx

DEFAULT_QUERIES = [
    "seasonal tax preparer CPA firm",
    "tax senior accountant CPA firm",
    "tax manager CPA firm",
    "enrolled agent tax preparer",
]


@dataclass
class JobPosting:
    company: str
    title: str
    location: str = ""
    posted_days_ago: int | None = None
    url: str = ""
    domain: str = ""
    description: str = ""
    extensions: list[str] = field(default_factory=list)


def _parse_posted(value: str, today: date | None = None) -> int | None:
    """Accept an ISO date ('2026-09-20') or relative text ('3 days ago', '1 week ago')."""
    value = (value or "").strip().lower()
    if not value:
        return None
    today = today or date.today()
    try:
        return max((today - datetime.fromisoformat(value).date()).days, 0)
    except ValueError:
        pass
    m = re.search(r"(\d+)\+?\s*(hour|day|week|month)", value)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return {"hour": 0, "day": n, "week": n * 7, "month": n * 30}[unit]
    if "today" in value or "just" in value:
        return 0
    return None


def load_csv(path: str, today: date | None = None) -> list[JobPosting]:
    """Columns (case-insensitive): company, title, location, posted, url, domain, description."""
    postings = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            if not row.get("company") or not row.get("title"):
                continue
            postings.append(JobPosting(
                company=row["company"],
                title=row["title"],
                location=row.get("location", ""),
                posted_days_ago=_parse_posted(row.get("posted") or row.get("posted_date", ""), today),
                url=row.get("url", ""),
                domain=row.get("domain", ""),
                description=row.get("description", ""),
            ))
    return postings


def fetch_google_jobs(api_key: str, queries: list[str] | None = None, location: str = "United States",
                      client: httpx.Client | None = None) -> list[JobPosting]:
    http = client or httpx.Client(timeout=30)
    postings = []
    for q in queries or DEFAULT_QUERIES:
        resp = http.get("https://serpapi.com/search.json",
                        params={"engine": "google_jobs", "q": q, "location": location, "api_key": api_key})
        resp.raise_for_status()
        for job in resp.json().get("jobs_results", []):
            ext = job.get("detected_extensions", {})
            postings.append(JobPosting(
                company=job.get("company_name", ""),
                title=job.get("title", ""),
                location=job.get("location", ""),
                posted_days_ago=_parse_posted(ext.get("posted_at", "")),
                url=job.get("share_link", ""),
                description=(job.get("description") or "")[:2000],
                extensions=[str(e) for e in job.get("extensions", [])],
            ))
    return [p for p in postings if p.company and p.title]
