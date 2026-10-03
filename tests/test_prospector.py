from datetime import date
from pathlib import Path

from sam_outbound import prospector, scoring, signals

from .fakes import FakeHubSpotAPI, FakeInstantlyAPI

EXAMPLES = Path(__file__).parent.parent / "examples"
TODAY = date(2026, 10, 3)


def firms():
    return scoring.build_firms(signals.load_csv(str(EXAMPLES / "jobs.csv"), today=TODAY))


def contacts():
    return prospector.load_contacts(str(EXAMPLES / "contacts.csv"))


def test_parse_posted():
    assert signals._parse_posted("3 days ago", TODAY) == 3
    assert signals._parse_posted("1 week ago", TODAY) == 7
    assert signals._parse_posted("2026-09-25", TODAY) == 8
    assert signals._parse_posted("Just posted", TODAY) == 0
    assert signals._parse_posted("", TODAY) is None


def test_scoring_ranks_seasonal_tax_hiring_and_excludes_staffing():
    ranked = firms()
    names = [f.name for f in ranked]
    assert "Robert Half" not in names
    assert names[0] == "Hartwell & Co. CPAs"
    top = ranked[0]
    assert len(top.postings) == 2
    assert "seasonal or contract hiring" in top.reasons
    assert "open to remote staff" in top.reasons
    dental = next(f for f in ranked if f.name == "Ridgeview Dental")
    assert dental.score < 40


def test_normalize_company_merges_variants():
    assert scoring.normalize_company("Hartwell & Co. CPAs") == scoring.normalize_company("Hartwell and Co, CPA")


def test_best_contact_prefers_managing_partner():
    top = firms()[0]
    assert prospector.best_contact(top, contacts()).email == "dana@hartwellcpa.com"


def test_first_line_uses_posting():
    line = prospector.first_line(firms()[0])
    assert line == "Saw Hartwell & Co. CPAs is hiring a Seasonal Tax Preparer (Remote) in Denver ahead of busy season."


def test_dry_run_writes_nothing():
    hs, inst = FakeHubSpotAPI(), FakeInstantlyAPI()
    out = prospector.run(firms(), contacts(), min_score=40, campaign_id="c1",
                         instantly=inst.client(), hubspot=hs.client(), dry_run=True)
    assert {o.firm.name for o in out if o.action == "queued"} == {"Hartwell & Co. CPAs", "Meadowbrook Accounting Group"}
    assert inst.leads == []
    assert all(m == "POST" and p.endswith("/search") for m, p, _ in hs.calls)


def test_live_run_adds_leads_and_logs_to_hubspot():
    hs, inst = FakeHubSpotAPI(), FakeInstantlyAPI()
    out = prospector.run(firms(), contacts(), min_score=40, campaign_id="c1",
                         instantly=inst.client(), hubspot=hs.client(), dry_run=False)
    assert [o.action for o in out].count("added") == 2
    lead = next(l for l in inst.leads if l["email"] == "dana@hartwellcpa.com")
    assert lead["campaign"] == "c1"
    assert lead["skip_if_in_workspace"] is True
    assert lead["custom_variables"]["hiring_role"] == "Seasonal Tax Preparer (Remote)"
    assert {c["email"] for c in hs.of("contacts")} == {"dana@hartwellcpa.com", "sam@meadowbrookaccounting.com"}
    assert {c["domain"] for c in hs.of("companies")} == {"hartwellcpa.com", "meadowbrookaccounting.com"}
    assert len(hs.of("notes")) == 2


def test_existing_customers_are_skipped():
    hs, inst = FakeHubSpotAPI(), FakeInstantlyAPI()
    hs.seed("contacts", {"email": "dana@hartwellcpa.com", "lifecyclestage": "customer"})
    out = prospector.run(firms(), contacts(), min_score=40, campaign_id="c1",
                         instantly=inst.client(), hubspot=hs.client(), dry_run=False)
    hartwell = next(o for o in out if o.firm.name == "Hartwell & Co. CPAs")
    assert hartwell.action == "skipped" and "customer" in hartwell.reason
    assert all(l["email"] != "dana@hartwellcpa.com" for l in inst.leads)


def test_report(tmp_path):
    out = prospector.run(firms(), contacts(), min_score=40, campaign_id="c1",
                         instantly=None, hubspot=None, dry_run=True)
    path = tmp_path / "r.csv"
    prospector.write_report(out, str(path))
    text = path.read_text()
    assert "dana@hartwellcpa.com" in text and "Ridgeview Dental" in text
