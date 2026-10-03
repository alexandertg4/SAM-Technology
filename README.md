# SAM Technology outbound tools

Two tools for outbound to U.S. accounting firms, built on Instantly and HubSpot.

1. **Hiring-signal prospector.** Finds CPA firms posting tax roles (seasonal preparers, tax seniors, EAs),
   scores how much they likely need extra busy-season capacity, picks the best decision-maker, and loads
   them into an Instantly campaign with a personalized first line. Existing HubSpot customers, opportunities
   and contacts with open deals are skipped.
2. **Instantly to HubSpot sync.** A webhook receiver that turns Instantly events into CRM work:

   | Instantly event | HubSpot result |
   | --- | --- |
   | `lead_interested`, `lead_meeting_booked` | Contact + company, reply logged as a note, a deal (unless one is open), a high-priority task for the owner |
   | `reply_received` | Contact + reply logged as a note |
   | `lead_not_interested`, `lead_wrong_person`, `lead_unsubscribed`, `email_bounced` | Lead status set to Unqualified + note |

   It also has a `suppress` command that blocks every customer and open opportunity in Instantly.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in the keys; never commit .env
```

You need:
- **Instantly API v2 key** with lead, campaign and block list scopes, plus the ID of the campaign to fill.
- **HubSpot private app token** with read/write on contacts, companies and deals.
- Optional **SerpAPI key** to pull live Google Jobs postings instead of (or as well as) a CSV.

## Prospecting

Prepare two CSVs (see `examples/`):
- `jobs.csv`: `company, title, location, posted, url, domain`. Export from Indeed, LinkedIn, ZipRecruiter
  or a Google Jobs search. `posted` takes a date or text like `3 days ago`.
- `contacts.csv`: `email, first_name, last_name, title, company, domain` for people at those firms
  (from Apollo, ZoomInfo, Instantly SuperSearch or your own list).

```bash
# Score and match only, nothing is written. Review out/prospect_report.csv.
sam-outbound prospect --jobs jobs.csv --contacts contacts.csv --dry-run

# Live: add leads to Instantly and log them in HubSpot
sam-outbound prospect --jobs jobs.csv --contacts contacts.csv --campaign <campaign-id>

# Pull postings straight from Google Jobs
sam-outbound prospect --google-jobs --contacts contacts.csv --dry-run
```

Each lead gets these Instantly variables for your sequence copy:
`{{personalization}}` (e.g. "Saw Hartwell & Co. CPAs is hiring a Seasonal Tax Preparer in Denver ahead of busy season."),
`{{hiring_role}}`, `{{hiring_location}}`, `{{signal_score}}`, `{{signal_reasons}}`, `{{job_url}}`.

Scoring (in `sam_outbound/scoring.py`), out of 100: open tax roles (15 each, up to 3), seasonal or contract
wording (+15), review-level roles (+10), remote-friendly (+10), posted in the last 14 days (+20) or 30 days (+10),
CPA-firm name (+10). Big Four, national tax chains and staffing firms are excluded. The default cutoff is 40
(`--min-score`). The contact picked per firm is, in order: managing partner, founder or owner, partner,
COO or firm administrator, tax director, tax manager.

## Instantly to HubSpot sync

```bash
sam-outbound serve            # listens on $PORT or 8000
```

Deploy it anywhere that runs Python (Render, Railway, Fly.io, a small VM), then in Instantly go to
**Settings > Integrations > Webhooks** and add
`https://<your-host>/webhooks/instantly?token=<WEBHOOK_SECRET>` for all events.
Set `HUBSPOT_OWNER_ID` so follow-up tasks land with the right rep.

Run suppression before each new campaign, or on a schedule:

```bash
sam-outbound suppress --dry-run
sam-outbound suppress
```

## Tests

```bash
pytest
```

The tests run against in-memory fakes of the HubSpot and Instantly APIs and need no keys.
