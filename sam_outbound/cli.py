"""Command line entry point: sam-outbound {prospect,suppress,serve}."""
from __future__ import annotations

import argparse
import os
from collections import Counter

from .config import Config
from .hubspot import HubSpot
from .instantly import Instantly
from . import prospector, scoring, signals, sync


def cmd_prospect(args, config: Config) -> None:
    postings = []
    for path in args.jobs or []:
        postings += signals.load_csv(path)
    if args.google_jobs:
        config.require("serpapi_key")
        postings += signals.fetch_google_jobs(config.serpapi_key, args.query or None, args.location)
    if not postings:
        raise SystemExit("No job postings loaded. Pass --jobs file.csv and/or --google-jobs.")

    firms = scoring.build_firms(postings)
    contacts = prospector.load_contacts(args.contacts)

    live = not args.dry_run
    if live:
        config.require("instantly_api_key")
    campaign = args.campaign or config.instantly_campaign_id
    if live and not campaign:
        raise SystemExit("Missing campaign: pass --campaign or set INSTANTLY_CAMPAIGN_ID.")
    instantly = Instantly(config.instantly_api_key) if live else None
    hubspot = HubSpot(config.hubspot_token) if config.hubspot_token and not args.no_hubspot else None

    outcomes = prospector.run(firms, contacts, min_score=args.min_score, campaign_id=campaign,
                              instantly=instantly, hubspot=hubspot, dry_run=args.dry_run)
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    prospector.write_report(outcomes, args.report)

    counts = Counter(o.action for o in outcomes)
    print(f"{len(postings)} postings -> {len(firms)} firms. "
          f"added={counts['added']} queued={counts['queued']} skipped={counts['skipped']}")
    print(f"Report: {args.report}")


def cmd_suppress(args, config: Config) -> None:
    config.require("hubspot_token", *([] if args.dry_run else ["instantly_api_key"]))
    blocked = sync.suppress_customers(HubSpot(config.hubspot_token),
                                      Instantly(config.instantly_api_key), dry_run=args.dry_run)
    verb = "Would block" if args.dry_run else "Blocked"
    print(f"{verb} {len(blocked)} domains/emails in Instantly.")
    for value in blocked:
        print(f"  {value}")


def cmd_serve(args, config: Config) -> None:
    config.require("hubspot_token", "webhook_secret")
    import uvicorn
    from .server import create_app
    uvicorn.run(create_app(config), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sam-outbound")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prospect", help="Score firms from hiring signals and load the best contact into Instantly")
    p.add_argument("--jobs", action="append", help="Job postings CSV (repeatable)")
    p.add_argument("--google-jobs", action="store_true", help="Also pull postings from Google Jobs via SerpAPI")
    p.add_argument("--query", action="append", help="Google Jobs query (repeatable; defaults built in)")
    p.add_argument("--location", default="United States")
    p.add_argument("--contacts", required=True, help="Contacts CSV: email, first_name, last_name, title, company, domain")
    p.add_argument("--campaign", help="Instantly campaign id (defaults to INSTANTLY_CAMPAIGN_ID)")
    p.add_argument("--min-score", type=int, default=40)
    p.add_argument("--report", default="out/prospect_report.csv")
    p.add_argument("--no-hubspot", action="store_true", help="Skip HubSpot checks and writes")
    p.add_argument("--dry-run", action="store_true", help="Score and match only; write nothing to Instantly or HubSpot")
    p.set_defaults(func=cmd_prospect)

    s = sub.add_parser("suppress", help="Block HubSpot customers and open opportunities in Instantly")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_suppress)

    v = sub.add_parser("serve", help="Run the Instantly -> HubSpot webhook receiver")
    v.add_argument("--host", default="0.0.0.0")
    v.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    v.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args, Config.from_env())


if __name__ == "__main__":
    main()
