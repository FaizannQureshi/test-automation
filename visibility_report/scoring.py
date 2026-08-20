"""Search/AI query builders and score helpers."""

from __future__ import annotations

from .offers import looks_like_offer_name

def build_search_queries(business: str, host: str, offers: list[dict]) -> list[str]:
    brand = business.strip() or host.split(".")[0].replace("-", " ").title()
    host_label = host.split(".")[0].replace("-", " ")
    queries = [brand, f"{brand} {host_label}"]
    for o in offers:
        name = (o.get("name") or "").strip()
        if not looks_like_offer_name(name):
            continue
        queries.append(name)
        queries.append(f"{name} near me")
        if len(queries) >= 10:
            break
    # Category-style pads from remaining offer names
    for o in offers:
        if len(queries) >= 10:
            break
        name = (o.get("name") or "").strip()
        if name and f"best {name}" not in queries:
            queries.append(f"best {name}")
    while len(queries) < 10:
        queries.append(f"best {brand.split()[0]} services")
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out[:10]


def build_ai_prompts(business: str, host: str, queries: list[str]) -> list[str]:
    brand = business.strip() or host
    prompts = [
        f"What is {brand}?",
        f"Tell me about {brand} ({host}).",
    ]
    for q in queries[2:10]:
        prompts.append(f"Who is the best provider for: {q}?")
    return prompts[:10]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def clamp_score(n: float) -> int:
    return max(0, min(100, int(round(n))))


def metric_status(kind: str, value: float | None, *, good: float, warn: float | None = None) -> str:
    if value is None:
        return "Watch"
    if kind == "lower_is_better":
        if value <= good:
            return "On track"
        if warn is not None and value <= warn:
            return "Watch"
        return "Fix"
    # higher_is_better
    if value >= good:
        return "On track"
    if warn is not None and value >= warn:
        return "Watch"
    return "Fix"


def score_from_ratio(found: int, total: int) -> int:
    if total <= 0:
        return 0
    return clamp_score(found / total * 100)

