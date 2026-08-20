"""CLI entry for the weekly visibility report job."""

from __future__ import annotations

import json
import sys

from .audit import audit_visibility
from .config import PILOTS
from .portal import (
    api_get,
    ga_property_from_client,
    gsc_site_from_client,
    normalize_site_url,
    website_url_from_client,
)
from .publish import publish

def main() -> int:
    summaries = []
    for _label, cid in PILOTS:
        status, client = api_get(f"/clients/{cid}")
        if status != 200 or not isinstance(client, dict):
            summaries.append(
                {
                    "client": _label,
                    "clientId": cid,
                    "skipped": True,
                    "reason": f"GET /clients/{{id}} HTTP {status}",
                    "reportId": None,
                }
            )
            print(json.dumps(summaries[-1]))
            continue
        name = client.get("name") or _label
        if client.get("archivedAt"):
            summaries.append({"client": name, "clientId": cid, "skipped": True, "reason": "archived", "reportId": None})
            print(json.dumps(summaries[-1]))
            continue
        site = website_url_from_client(client)
        if not site:
            summaries.append(
                {
                    "client": name,
                    "clientId": cid,
                    "skipped": True,
                    "reason": "missing Credentials → Website URL",
                    "reportId": None,
                }
            )
            print(json.dumps(summaries[-1]))
            continue
        site = normalize_site_url(site)
        business = client.get("businessName") or name
        ga_prop = ga_property_from_client(client)
        gsc_site = gsc_site_from_client(client)
        print(
            json.dumps(
                {
                    "event": "audit_start",
                    "client": name,
                    "site": site,
                    "gaPropertyConfigured": bool(ga_prop),
                    "gscSiteOverride": bool(gsc_site),
                }
            )
        )
        audit = audit_visibility(
            site,
            business,
            ga_property=ga_prop,
            gsc_site=gsc_site,
            client=client,
        )
        print(
            json.dumps(
                {
                    "event": "audit_done",
                    "client": name,
                    "reachable": audit["reachable"],
                    "overallScore": audit["overall_score"],
                    "scores": audit["scores"],
                    "apiNotes": audit["api_notes"],
                }
            )
        )
        pub = publish(client, audit)
        summaries.append(pub)
        print(json.dumps({k: v for k, v in pub.items()}))

    out_path = "/tmp/weekly_seo_results.json"
    with open(out_path, "w") as f:
        json.dump(summaries, f, indent=2)
    print(json.dumps({"event": "complete", "resultsPath": out_path, "count": len(summaries)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
