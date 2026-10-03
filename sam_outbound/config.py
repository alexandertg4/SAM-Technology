import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    instantly_api_key: str
    instantly_campaign_id: str
    hubspot_token: str
    hubspot_owner_id: str
    hubspot_pipeline: str
    hubspot_deal_stage: str
    webhook_secret: str
    serpapi_key: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        get = lambda k, d="": os.environ.get(k, d).strip()
        return cls(
            instantly_api_key=get("INSTANTLY_API_KEY"),
            instantly_campaign_id=get("INSTANTLY_CAMPAIGN_ID"),
            hubspot_token=get("HUBSPOT_TOKEN"),
            hubspot_owner_id=get("HUBSPOT_OWNER_ID"),
            hubspot_pipeline=get("HUBSPOT_PIPELINE", "default"),
            hubspot_deal_stage=get("HUBSPOT_DEAL_STAGE", "appointmentscheduled"),
            webhook_secret=get("WEBHOOK_SECRET"),
            serpapi_key=get("SERPAPI_KEY"),
        )

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            env = ", ".join(n.upper() for n in missing)
            raise SystemExit(f"Missing required settings: {env} (see .env.example)")
