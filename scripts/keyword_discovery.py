"""Free, best-effort keyword ideas; never invent search volume or demand."""
from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def autocomplete(seed: str, language: str, country: str) -> list[str]:
    # Public, undocumented endpoint: failures are reported, never bypassed.
    params = {"client": "firefox", "q": seed, "hl": language}
    if country != "EU":
        params["gl"] = country.lower()
    url = "https://suggestqueries.google.com/complete/search?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "INTECH-SEO-Autopilot/1.0"})
    time.sleep(0.2)
    with urlopen(request, timeout=5) as response:
        body = json.loads(response.read(262144).decode("utf-8"))
    if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
        raise ValueError("Unexpected autocomplete response")
    return [value for value in body[1] if isinstance(value, str)][:10]


def discover(site: dict[str, Any], technical: dict[str, Any],
             gsc: dict[str, Any], *, fetch=autocomplete) -> dict[str, Any]:
    seeds = list(dict.fromkeys(str(value).strip() for value in site.get("keywords", [])
                               if str(value).strip()))[:4]
    known = {seed.casefold() for seed in seeds}
    observed = {str(row.get("query", "")).casefold()
                for period in ("current", "previous")
                for row in gsc.get("queries", {}).get(period, [])}
    ideas: dict[str, dict[str, Any]] = {}
    errors = []
    successful = 0

    def add(term: str, source: str, seed: str = "", url: str = "") -> None:
        term = " ".join(term.split())
        key = term.casefold()
        if key in known or not 2 <= len(term.split()) <= 12 or len(term) > 120:
            return
        row = ideas.setdefault(key, {"keyword": term, "sources": [], "seed": seed,
                                    "page": url, "already_observed": key in observed,
                                    "search_volume": None})
        if source not in row["sources"]:
            row["sources"].append(source)
        if url and not row["page"]:
            row["page"] = url

    languages = list(dict.fromkeys(value.split("-")[0]
                                   for value in site.get("languages", ["en"])))[:2]
    for language in languages:
        for seed in seeds:
            try:
                terms = fetch(seed, language, site.get("country", "EU"))
                successful += 1
                for term in terms:
                    # Keep expansions related to the configured business topics.
                    if set(re.findall(r"\w+", seed.casefold())) & set(re.findall(r"\w+", term.casefold())):
                        add(term, "google_autocomplete", seed)
            except Exception as exc:
                errors.append({"seed": seed, "language": language,
                               "error": f"{type(exc).__name__}: {exc}"[:200]})
    for page in technical.get("pages", []):
        for values in page.get("headings", {}).values():
            for heading in values:
                add(str(heading), "site_heading", url=page.get("final_url") or page.get("url", ""))
    rows = sorted(ideas.values(), key=lambda row: (
        row["already_observed"], "google_autocomplete" not in row["sources"], row["keyword"]))[:100]
    return {"status": "partial" if errors and (successful or rows) else
            "unavailable" if errors else "ok" if seeds or rows else "no_seeds",
            "ideas": rows, "errors": errors,
            "note": "Suggestions require relevance review. Autocomplete is not search volume; "
                    "site headings are content-derived ideas, not evidence of demand. "
                    "Already observed means present in returned Search Console rows only."}
