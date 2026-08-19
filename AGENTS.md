# test-automation

Weekly Connection Inc client visibility reports via `weekly_seo_report.py`.

## Run (Cloud Agent / automation)

```bash
pip install -r requirements.txt
python3 weekly_seo_report.py
```

Requires `PORTAL_API_KEY` (Runtime Secret). Never log or print secret values.

## Runtime secrets — name your API keys exactly like this

| Secret name | Used for | Required now? |
|---|---|---|
| `PORTAL_API_KEY` | Connection Inc portal API auth | **Yes** |
| `GOOGLE_API_KEY` | Shared fallback for Google APIs below | **Yes** (or use per-service keys) |
| `GOOGLE_CSE_ID` | Custom Search Engine ID (`cx`) | **Yes** (search ranking sample) |
| `GEMINI_API_KEY` | Gemini AI answer sampling | **Yes** |
| `GOOGLE_PAGESPEED_API_KEY` | PageSpeed Insights (optional override) | Optional — falls back to `GOOGLE_API_KEY` |
| `GOOGLE_CUSTOM_SEARCH_API_KEY` | Custom Search (optional override) | Optional — falls back to `GOOGLE_API_KEY` |
| `GOOGLE_PLACES_API_KEY` | Places API (New) for GBP/listings | Optional — falls back to `GOOGLE_API_KEY` |
| `GOOGLE_GEOCODING_API_KEY` | Geocoding API | Optional — falls back to `GOOGLE_API_KEY` |
| `GOOGLE_SEARCH_CONSOLE_CREDENTIALS_JSON` | Search Console (service account JSON) | **Not yet** — script notes when missing |
| `GOOGLE_ANALYTICS_PROPERTY_ID` | GA4 property ID | **Not yet** — script notes when missing |
| `GOOGLE_ANALYTICS_CREDENTIALS_JSON` | GA4 service account JSON | **Not yet** |

`Maps JavaScript API` is a browser-only key — not used by this Python job.

Optional: `GEMINI_MODEL` (default `gemini-2.0-flash`).

## Google Cloud APIs to enable

- Custom Search API
- PageSpeed Insights API
- Places API (New)
- Geocoding API
- Generative Language API (Gemini)

Later: Search Console API, Google Analytics Data API.

## Custom Search setup

1. Create a Programmable Search Engine at [programmablesearchengine.google.com](https://programmablesearchengine.google.com/) (search the entire web).
2. Copy the **Search engine ID** into `GOOGLE_CSE_ID`.

Ranking logic: for each of 10 queries, the script checks whether the client domain appears in the **first 2 pages** (20 results) of Custom Search results and assigns a score.

## Pilot clients

Only clients listed in `PILOTS` inside `weekly_seo_report.py` are processed. Expand that list after verifying the template in Admin → Reports.

## Report template

Reports follow the Oasbit visibility layout: Scores, Facts, Offers, Search, Improve, Compare, Next — published as `RICH_TEXT` to the client portal.

Reference: [Oasbit visibility report sample](https://oasbit.com/114/4757a659-1a96-4425-947d-4ffae49f87c2)
