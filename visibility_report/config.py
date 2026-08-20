"""Shared constants for the weekly visibility report."""

from __future__ import annotations

from datetime import date, timedelta

API = "https://seo.connectionincorporated.com/api/v1"
UA = (
    "Mozilla/5.0 (compatible; ConnectionIncWeeklySEO/2.0; "
    "+https://seo.connectionincorporated.com)"
)
TIMEOUT = 25
TODAY = date.today()
REPORT_DATE = TODAY.isoformat()
WEEK_OF = (TODAY - timedelta(days=TODAY.weekday())).isoformat()

# Active pilot(s). Prefer portal client id when known; otherwise set website_host
# and main.py will resolve the client by matching Credentials → Website URL.
PILOTS = [
    {
        "name": "Amy DeBusk",
        "client_id": None,  # resolved at runtime by website_host
        "website_host": "amydebuskhomeloans.com",
    },
]
