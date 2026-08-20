"""CLI entry for the weekly visibility report job."""

from __future__ import annotations

import json
import sys

from .audit import audit_visibility
from .config import PILOTS
from .portal import (
    api_get,
    find_client_by_website_host,
    ga_property_from_client,
    gsc_site_from_client,
    normalize_site_url,
    website_url_from_client,
)
from .publish import publish


def resolve_pilot(pilot: dict | tuple) -> tuple[str, dict | None, str | None]:
    """Return (label, client_or_none, skip_reason)."""
    if isinstance(pilot, tuple):
        label, cid = pilot
        status, client = api_get(f"/clients/{cid}")
        if status != 200 or not isinstance(client, dict):
            return label, None, f"GET /clients/{{id}} HTTP {status}"
        return label, client, None

    label = pilot.get("name") or "pilot"
    cid = pilot.get("client_id")
    host = (pilot.get("website_host") or "").strip().lower().removeprefix("www.")

    if cid:
        status, client = api_get(f"/clients/{cid}")
        if status != 200 or not isinstance(client, dict):
            return label, None, f"GET /clients/{{id}} HTTP {status}"
        return label, client, None

    if host:
        client = find_client_by_website_host(host)
        if not client:
            return label, None, f"no portal client with Website URL host {host}"
        return label, client, None

    return label, None, "pilot missing client_id and website_host"


def main() -> int:
    summaries = []
    for pilot in PILOTS:
        label, client, skip_reason = resolve_pilot(pilot)
        if skip_reason or not client:
            summaries.append(
                {
                    "client": label,
                    "clientId": (pilot.get("client_id") if isinstance(pilot, dict) else pilot[1])
                    if isinstance(pilot, (dict, tuple))
                    else None,
                    "skipped": True,
                    "reason": skip_reason or "client not found",
                    "reportId": None,
                }
            )
            print(json.dumps(summaries[-1]))
            continue

        cid = client.get("id")
        name = client.get("name") or label
        if client.get("archivedAt"):
            summaries.append(
                {"client": name, "clientId": cid, "skipped": True, "reason": "archived", "reportId": None}
            )
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
                    "clientId": cid,
                    "site": site,
                    "gaPropertyConfigured": bool(ga_prop),
                    "gaProperty": ga_prop or None,
                    "gscSiteOverride": bool(gsc_site),
                    "gscSite": gsc_site or None,
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
