# Weekly visibility report — Cursor Automation prompt

Copy everything below into your Cursor Automation prompt.

---

Run the weekly Connection Inc client visibility report job using the **existing v1 environment** and the committed implementation in the repository.

## IMPORTANT

- Use the **existing v1 environment only**. Do not create a new environment.
- Do not create a new repository.
- Do not create a new Python script.
- Do not recreate the report logic in this prompt — all logic lives in `weekly_seo_report.py`.
- Run the committed `weekly_seo_report.py` from the repository root.
- Install dependencies using `requirements.txt` if needed.
- **Never print, expose, echo, or log any API keys, tokens, or other secrets.**

## Runtime Secrets (v1 environment)

Confirm these are on **this same v1 environment** before running. Names must match exactly:

| Secret name | Purpose |
|---|---|
| `PORTAL_API_KEY` | Portal API (required) |
| `gemini_api` | Gemini search + AI samples |
| `pagespeed_api` | PageSpeed Insights |
| `places_api` | Google Business Profile |
| `geocoding_api` | Geocoding |
| `search_console_api` | Search Console API credentials |
| `analytics_data_api` | Google Analytics Data API credentials |
| `analytics_property_id` | GA4 property ID, e.g. `123456789` or `properties/123456789` |
| `GEMINI_MODEL` | Optional override (default `gemini-3.6-flash`) |

**Pre-flight** (presence only — never print values):

```bash
python3 - <<'PY'
import os
for k in [
    "PORTAL_API_KEY", "gemini_api", "pagespeed_api", "places_api", "geocoding_api",
    "search_console_api", "analytics_data_api", "analytics_property_id",
]:
    print(f"{k}={'set' if (os.environ.get(k) or '').strip() else 'MISSING'}")
PY
```

If core Google secrets show **MISSING**, report that Environment Runtime Secrets were not injected and stop unless the user accepts a crawl-only run.

## Execution

1. `pip install -r requirements.txt`
2. Pre-flight check (above)
3. `git pull` on `cursor/setup-dev-environment-06c4` if behind remote
4. `python3 weekly_seo_report.py`
5. Pilot client only (Adam Zeman). Creates new RICH_TEXT report; do not overwrite prior reports.

## After execution

Summarize: pre-flight set/MISSING, clients processed/skipped, report ID, HTML stored, portal enabled, assignment, overall scores, `apiNotes` (`pagespeed`, `gemini`, `places`, `gsc`, `gsc_ok`, `ga`, `ga_ok`, `search_method`), and any errors. No secret values.
