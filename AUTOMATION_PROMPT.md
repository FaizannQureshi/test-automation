# Weekly visibility report — Cursor Automation prompt

Copy everything below into your Cursor Automation prompt.

---

Run the weekly Connection Inc client visibility report job using the **existing v1 environment** and the committed implementation in the repository.

## IMPORTANT

- Use the **existing v1 environment only**. Do not create a new environment.
- Do not create a new repository.
- Do not create a new Python script.
- Do not create or use a temporary replacement implementation.
- Do not recreate the report logic in this prompt — all logic lives in `weekly_seo_report.py`.
- Run the committed `weekly_seo_report.py` from the repository root.
- Install dependencies using `requirements.txt` if needed.
- Use Runtime Secrets already configured in v1 (`PORTAL_API_KEY`, `pagespeed_api`, `gemini_api`, `places_api`, `geocoding_api`, etc.).
- **Never print, expose, echo, or log any API keys, tokens, or other secrets.**

## Execution

1. `pip install -r requirements.txt` (if not already installed).
2. `python3 weekly_seo_report.py`
3. The script authenticates to the portal with `PORTAL_API_KEY`.
4. The script audits **pilot clients only** (currently one client: Adam Zeman).
5. The script collects data via PageSpeed, Places, Geocoding, and Gemini (with Google Search grounding for ranking samples).
6. The script builds an Oasbit-style visibility HTML report and creates a new dated **RICH_TEXT** report per eligible pilot client.
7. The script enables client portal access and assigns the report to the client.
8. Do **not** overwrite or delete previous reports.
9. Do **not** modify existing PDF or iframe reports.
10. Do **not** modify `weekly_seo_report.py` unless the run fails due to a committed bug.

## After execution

Provide a concise summary containing:

- clients processed
- clients skipped and why
- report IDs created
- whether HTML was stored
- whether client portal access was enabled
- whether assignment succeeded
- overall visibility scores (if available)
- which APIs were used (from script JSON output — not secret values)
- any errors

Do not include API keys, passwords, tokens, or other secrets in the output.
