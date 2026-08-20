# Weekly visibility report — Cursor Automation prompt

Copy everything below into your Cursor Automation prompt.

---

Run the weekly Connection Inc client visibility report job using the **existing v1 environment** and the committed implementation in the repository.

## IMPORTANT

- Use the **existing v1 environment only**. Do not create a new environment.
- Do not create a new repository.
- Do not create a new Python script or temporary replacement implementation.
- Do **not** recreate report logic in this prompt — logic lives in the `visibility_report/` package; `weekly_seo_report.py` is the entrypoint only.
- Run the committed job from the repository root: `python3 weekly_seo_report.py`
- Install dependencies using `requirements.txt` if needed.
- **Never print, expose, echo, or log any API keys, tokens, private keys, or other secrets.**
- Safe to log: presence flags (`set`/`MISSING`), `client_email` / `service_account_email` only (not the full JSON).

## Repository layout

```
weekly_seo_report.py          # thin entrypoint (run this)
visibility_report/
  config.py                   # pilots, dates, API base URL
  env.py                      # Runtime Secret name resolution
  portal.py                   # Connection Inc portal API + client fields
  crawl.py                    # fetch, HTML parse, robots, sitemap
  offers.py                   # real service/product discovery
  google_apis.py              # PageSpeed, Places, Geocoding, Gemini, GSC, GA4
  scoring.py                  # query builders + score helpers
  audit.py                    # full visibility audit orchestration
  report_html.py              # Oasbit-style RICH_TEXT HTML
  publish.py                  # POST/PATCH reports to portal
  main.py                     # pilot loop + summary JSON
requirements.txt
```

Do not modify package modules unless the run fails due to a committed bug.

## Runtime Secrets (v1 environment)

Confirm these are on **this same v1 environment**. Names must match exactly:

| Secret name | Purpose |
|---|---|
| `PORTAL_API_KEY` | Portal API (required) — used to resolve client + GA4/GSC fields |
| `gemini_api` | Gemini search + AI samples |
| `pagespeed_api` | PageSpeed Insights |
| `places_api` | Google Business Profile |
| `geocoding_api` | Geocoding |
| `search_console_api` | Search Console service-account **JSON** |
| `analytics_data_api` | GA4 Data API service-account **JSON** (same JSON is fine) |
| `GEMINI_MODEL` | Optional override (default `gemini-3.6-flash`) |

**Not required:** `analytics_property_id`. Per-client GA4 property and GSC site come from the portal client record (`GA4 URL` / `GSC URL` custom fields), resolved via `PORTAL_API_KEY`.

Unused (ignore if present): `custom_search_api`, `maps_javascript_api`.

**Pre-flight** (presence only — never print values):

```bash
python3 - <<'PY'
import os
for k in [
    "PORTAL_API_KEY", "gemini_api", "pagespeed_api", "places_api", "geocoding_api",
    "search_console_api", "analytics_data_api",
]:
    print(f"{k}={'set' if (os.environ.get(k) or '').strip() else 'MISSING'}")
PY
```

If `PORTAL_API_KEY` or core Google secrets show **MISSING**, report that Environment Runtime Secrets were not injected and stop unless the user accepts a crawl-only run.

## Pilot resolution (no hard-coded portal client id required)

`visibility_report/config.py` lists pilots. Current pilot is Amy DeBusk by **website host**:

- `website_host: amydebuskhomeloans.com`
- At runtime the job calls the portal API (`PORTAL_API_KEY`), finds the client whose Credentials → Website URL matches that host, then reads:
  - Website URL
  - `GA4 URL` / `GA4 Property ID` → Analytics property
  - `GSC URL` / Search Console Site URL → Search Console property

If `client_id` is set in config, that id is used directly. If only `website_host` is set, resolve via portal list — do **not** invent a client id in the prompt.

## Execution

1. `pip install -r requirements.txt`
2. Pre-flight check (above)
3. `git pull` on `cursor/setup-dev-environment-06c4` if behind remote
4. Confirm `visibility_report/` package exists next to `weekly_seo_report.py`
5. `python3 weekly_seo_report.py`
6. Pilot client only (Amy DeBusk). Creates a new RICH_TEXT report; do not overwrite prior reports.
7. Expect `apiNotes.service_account_email` like `seo-report-service@….iam.gserviceaccount.com`. That email must already have GSC + GA Viewer (or better) on the client’s properties.

## After execution

Summarize: pre-flight set/MISSING, client name + resolved `clientId`, report ID, HTML stored, portal enabled, assignment, overall scores, `apiNotes` (`pagespeed`, `gemini`, `places`, `gsc`, `gsc_ok`, `ga`, `ga_ok`, `ga_property`, `service_account_email`, `search_method`), and any errors. No secret values.
