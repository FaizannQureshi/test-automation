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

# Single active pilot while the new visibility template is verified in Admin → Reports.
PILOTS = [
    ("Adam Zeman", "cmkoitqae0001ib04j8hrefa9"),
]
