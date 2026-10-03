"""Turn job postings into scored target firms.

The score estimates how likely a firm is to need SAM's on-demand U.S. tax capacity right now.
Weights are deliberately simple so they are easy to tune after the first campaign results.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .signals import JobPosting

TAX_ROLE = re.compile(r"\b(tax|enrolled agent|\bea\b|1040|1065|1120|preparer)", re.I)
SEASONAL = re.compile(r"\b(seasonal|temporary|temp|contract|part[- ]time|busy season|tax season)\b", re.I)
REVIEW_LEVEL = re.compile(r"\b(senior|manager|supervisor|reviewer|director)\b", re.I)
REMOTE = re.compile(r"\b(remote|work from home|hybrid)\b", re.I)
ACCOUNTING_FIRM = re.compile(r"\b(cpas?|accounting|accountants|tax|llp|& co\.?|and company)\b", re.I)

# Not prospects: national chains, the Big Four, and staffing firms (competitors).
EXCLUDE = re.compile(
    r"\b(deloitte|pwc|pricewaterhouse|ernst|\bey\b|kpmg|h&r block|h & r block|jackson hewitt|liberty tax|"
    r"robert half|staffing|recruit|talent|solutions group|intuit|turbotax)\b", re.I)

SUFFIXES = re.compile(r"[,.]|\b(llp|llc|pllc|pc|p\.c|inc|ltd|cpas?|co)\b", re.I)


def normalize_company(name: str) -> str:
    return re.sub(r"\s+", " ", SUFFIXES.sub(" ", name.replace("&", " and "))).strip().lower()


@dataclass
class Firm:
    name: str
    key: str
    domain: str = ""
    postings: list[JobPosting] = field(default_factory=list)
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def top_posting(self) -> JobPosting:
        return min(self.postings, key=lambda p: p.posted_days_ago if p.posted_days_ago is not None else 999)


def score_firm(firm: Firm) -> Firm:
    tax_posts = [p for p in firm.postings if TAX_ROLE.search(p.title)]
    score, reasons = 0, []

    if tax_posts:
        pts = min(len(tax_posts), 3) * 15
        score += pts
        reasons.append(f"{len(tax_posts)} open tax role(s)")

    def text(p: JobPosting) -> str:
        return " ".join([p.title, p.description, *p.extensions])

    if any(SEASONAL.search(text(p)) for p in firm.postings):
        score += 15
        reasons.append("seasonal or contract hiring")
    if any(REVIEW_LEVEL.search(p.title) for p in tax_posts):
        score += 10
        reasons.append("hiring at review level")
    if any(REMOTE.search(text(p)) or REMOTE.search(p.location) for p in firm.postings):
        score += 10
        reasons.append("open to remote staff")

    ages = [p.posted_days_ago for p in firm.postings if p.posted_days_ago is not None]
    if ages and min(ages) <= 14:
        score += 20
        reasons.append("posted in the last 2 weeks")
    elif ages and min(ages) <= 30:
        score += 10
        reasons.append("posted in the last 30 days")

    if ACCOUNTING_FIRM.search(firm.name):
        score += 10
        reasons.append("name looks like a CPA firm")

    firm.score, firm.reasons = score, reasons
    return firm


def build_firms(postings: list[JobPosting]) -> list[Firm]:
    firms: dict[str, Firm] = {}
    for p in postings:
        if EXCLUDE.search(p.company):
            continue
        key = normalize_company(p.company)
        if not key:
            continue
        firm = firms.setdefault(key, Firm(name=p.company, key=key))
        firm.postings.append(p)
        if p.domain and not firm.domain:
            firm.domain = p.domain.lower().removeprefix("www.")
    return sorted((score_firm(f) for f in firms.values()), key=lambda f: f.score, reverse=True)
