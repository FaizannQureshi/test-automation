"""Publish RICH_TEXT reports to the Connection Inc portal."""

from __future__ import annotations

from .config import REPORT_DATE, WEEK_OF
from .portal import api_get, api_send
from .report_html import build_html

def publish(client: dict, audit: dict) -> dict:
    cid = client["id"]
    name = client["name"]
    site = audit["site_url"]
    title = f"Weekly Visibility Report — {name} — {REPORT_DATE}"
    description = f"Visibility snapshot for {site} (week of {WEEK_OF})."
    html = build_html(name, client.get("businessName") or name, audit)
    payload = {
        "title": title,
        "reportSource": "RICH_TEXT",
        "content": html,
        "status": "DRAFT",
        "clientPortalEnabled": True,
        "description": description,
        "clientId": cid,
        "clientIds": [cid],
    }
    status, created = api_send("POST", "/reports", payload)
    result = {
        "client": name,
        "clientId": cid,
        "site": site,
        "createStatus": status,
        "reportId": None,
        "htmlStored": False,
        "htmlChars": len(html),
        "portalEnabled": False,
        "assignmentLanded": False,
        "assignmentNote": "",
        "overallScore": audit.get("overall_score"),
        "reachable": audit.get("reachable"),
        "apiNotes": audit.get("api_notes"),
    }
    if status not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
        result["assignmentNote"] = f"POST /reports failed HTTP {status}"
        return result
    rid = created["id"]
    result["reportId"] = rid
    stored = created.get("content") or ""
    result["htmlStored"] = bool(stored) and "<div" in stored
    result["portalEnabled"] = bool(created.get("clientPortalEnabled"))

    pstatus, patched = api_send(
        "PATCH",
        f"/reports/{rid}",
        {
            "clientPortalEnabled": True,
            "assignedClients": [cid],
            "assignmentNotes": f"Weekly visibility snapshot for {name}.",
        },
    )
    if pstatus in (200, 201) and isinstance(patched, dict):
        result["portalEnabled"] = bool(patched.get("clientPortalEnabled", True))
        if patched.get("content"):
            result["htmlStored"] = "<div" in patched["content"]

    gstatus, got = api_get(f"/reports/{rid}/assignments")
    assignments = got if isinstance(got, list) else (got.get("assignments") or got.get("data") or [])
    active = [
        a
        for a in assignments
        if isinstance(a, dict) and a.get("clientId") == cid and not a.get("disassociatedAt")
    ]
    result["assignmentLanded"] = bool(active)
    result["assignmentNote"] = (
        f"Assigned (PATCH HTTP {pstatus}, GET HTTP {gstatus})."
        if active
        else f"Created; verify assignment in Admin → Reports (PATCH HTTP {pstatus})."
    )
    return result
