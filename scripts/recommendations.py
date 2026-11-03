#!/usr/bin/env python3
"""Evidence-based, deterministic SEO recommendations (no generated metrics)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urldefrag


MIN_QUERY_IMPRESSIONS = 20
MIN_PAGE_IMPRESSIONS = 20
MAX_RECOMMENDATIONS = 100


def _recommendation(priority: int, impact: str, confidence: str, effort: str,
                    evidence: str, title: str, action: str,
                    url: str = "") -> dict[str, Any]:
    return {
        "priority": priority,
        "impact": impact,
        "confidence": confidence,
        "effort": effort,
        "evidence": evidence,
        "title": title,
        "action": action,
        "url": url,
    }


def _keyed(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(key, "")).casefold(): row for row in rows if row.get(key)}


def recommendations(site: dict[str, Any], gsc: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings = site.get("findings", [])
    output: list[dict[str, Any]] = []
    for finding in findings:
        severity = finding.get("severity", "low")
        rank = {"high": 1, "medium": 2, "low": 3}.get(severity, 3)
        confidence = finding.get("confidence", "confirmed")
        output.append(_recommendation(
            rank,
            "high" if severity == "high" else "medium" if severity == "medium" else "low",
            confidence,
            "low" if finding.get("evidence") else "medium",
            finding.get("evidence", finding.get("message", "Technical audit evidence")),
            finding.get("message", "Review technical audit finding"),
            "Manually verify the observation before deciding whether a change is needed."
            if confidence == "potential"
            else "Review the affected page and correct the confirmed issue before deployment.",
            finding.get("url", ""),
        ))

    if not gsc or gsc.get("status") not in ("ok", "insufficient_data"):
        return sorted(output, key=lambda item: (item["priority"], item["title"]))[:MAX_RECOMMENDATIONS]

    current_queries = _keyed(gsc.get("queries", {}).get("current", []), "query")
    previous_queries = _keyed(gsc.get("queries", {}).get("previous", []), "query")
    for key, current in current_queries.items():
        impressions = int(current.get("impressions", 0))
        position = float(current.get("position", 0))
        previous = previous_queries.get(key)
        if impressions >= MIN_QUERY_IMPRESSIONS and 8 <= position <= 20:
            output.append(_recommendation(
                2, "medium", "high", "medium",
                f"Search Console: {impressions} impressions; average position {position:.1f}",
                f"Improve the page matching “{current['query']}”",
                "Review the relevant landing page for search intent coverage, useful content, "
                "and internal links. Position is an average, not a guarantee of rank.",
            ))
        if previous:
            old_impressions = int(previous.get("impressions", 0))
            decline = old_impressions - impressions
            if old_impressions >= MIN_QUERY_IMPRESSIONS and decline >= 10 and decline / old_impressions >= 0.2:
                output.append(_recommendation(
                    1, "high", "high", "medium",
                    f"Search Console: impressions fell from {old_impressions} to {impressions} "
                    f"({decline / old_impressions:.0%}) across adjacent 28-day periods",
                    f"Investigate declining query “{current['query']}”",
                    "Compare the affected landing page and search intent across both periods; "
                    "check for recent content, canonical, or availability changes.",
                ))
            old_position = float(previous.get("position", 0))
            if old_position and position and position - old_position >= 2:
                output.append(_recommendation(
                    2, "medium", "medium", "medium",
                    f"Search Console average position moved from {old_position:.1f} "
                    f"to {position:.1f}",
                    f"Review ranking decline for “{current['query']}”",
                    "Inspect the associated landing page and current search results before making changes.",
                ))

    current_total = gsc.get("periods", {}).get("current", {}).get("metrics", {})
    current_total_impressions = current_total.get("impressions")
    for key, previous in previous_queries.items():
        if key in current_queries:
            continue
        impressions = int(previous.get("impressions", 0))
        if impressions >= MIN_QUERY_IMPRESSIONS:
            no_property_impressions = current_total_impressions == 0
            current_total_evidence = (
                "the current property total has no impressions"
                if no_property_impressions
                else f"the current property total has {current_total_impressions} impressions"
                if current_total_impressions is not None
                else "the current property total is unavailable"
            )
            output.append(_recommendation(
                1 if no_property_impressions else 2,
                "high" if no_property_impressions else "medium",
                "medium", "medium",
                f"Search Console returned {impressions} impressions for this query "
                f"in the previous 28 days, but no current query row; {current_total_evidence}",
                f"Investigate query disappearance: {previous['query']}",
                "Check the landing page and Search Console again. A missing row can "
                "reflect privacy thresholds or sparse data and is not assumed to be "
                "exactly zero query impressions.",
            ))

    by_band: dict[str, list[dict[str, Any]]] = {}
    for row in current_queries.values():
        impressions = int(row.get("impressions", 0))
        position = float(row.get("position", 0))
        if impressions < MIN_QUERY_IMPRESSIONS or not position:
            continue
        band = "1-3" if position <= 3 else "4-10" if position <= 10 else "11-20" if position <= 20 else "21+"
        by_band.setdefault(band, []).append(row)
    for key, current in current_queries.items():
        impressions = int(current.get("impressions", 0))
        position = float(current.get("position", 0))
        if impressions < MIN_QUERY_IMPRESSIONS or not 1 <= position <= 10:
            continue
        band = "1-3" if position <= 3 else "4-10"
        cohort = by_band.get(band, [])
        if len(cohort) < 3:
            continue
        cohort_clicks = sum(float(row.get("clicks", 0)) for row in cohort)
        cohort_impressions = sum(float(row.get("impressions", 0)) for row in cohort)
        if not cohort_impressions:
            continue
        cohort_ctr = cohort_clicks / cohort_impressions
        ctr = float(current.get("ctr", 0))
        if ctr < cohort_ctr * 0.5 and ctr < cohort_ctr:
            output.append(_recommendation(
                2, "medium", "medium", "low",
                f"Search Console CTR {ctr:.1%} is below this site's observed "
                f"position-{band} cohort CTR of {cohort_ctr:.1%} "
                f"({impressions} impressions)",
                f"Review the search result snippet for “{current['query']}”",
                "Check whether the page title and description accurately communicate the page's "
                "value and intent; avoid changing them based on CTR alone.",
            ))

    current_pages = gsc.get("pages", {}).get("current", [])
    output.extend(
        _recommendation(
            3, "medium", "high", "low",
            f"Search Console: {row.get('clicks', 0)} clicks, "
            f"{row.get('impressions', 0)} impressions; average position "
            f"{float(row.get('position', 0)):.1f}",
            "Review top landing page performance",
            "Compare this landing page's search intent and snippet against its Search Console queries.",
            str(row.get("page", "")),
        )
        for row in sorted(current_pages, key=lambda item: int(item.get("clicks", 0)), reverse=True)[:3]
        if int(row.get("impressions", 0)) >= MIN_PAGE_IMPRESSIONS
    )
    crawled_pages = {
        urldefrag(str(page.get("final_url") or page.get("url", "")))[0]: page
        for page in site.get("pages", [])
    }
    for row in current_queries.values():
        impressions = int(row.get("impressions", 0))
        position = float(row.get("position", 0))
        if impressions < MIN_QUERY_IMPRESSIONS or not 8 <= position <= 20:
            continue
        matching_pages = sorted(
            (page for page in gsc.get("query_pages", {}).get("current", [])
             if str(page.get("query", "")).casefold() == row["query"].casefold()
             and int(page.get("impressions", 0)) >= MIN_PAGE_IMPRESSIONS),
            key=lambda page: int(page.get("impressions", 0)), reverse=True,
        )
        target_url = (urldefrag(str(matching_pages[0]["page"]))[0]
                      if matching_pages else "")
        if not target_url:
            continue
        target = crawled_pages.get(target_url)
        if not target:
            continue
        terms = {term for term in re.findall(
            r"[\w]+", row.get("query", "").casefold()) if len(term) > 2}
        candidates = []
        for source_url, source in crawled_pages.items():
            if source_url == target_url or target_url in source.get("internal_links", []):
                continue
            text = " ".join(
                [str(source.get("title", ""))]
                + [str(value) for values in source.get("headings", {}).values()
                   for value in values]
            ).casefold()
            overlap = terms & set(re.findall(r"[\w]+", text))
            if overlap:
                candidates.append((source_url, sorted(overlap)))
        for source_url, overlap in candidates[:2]:
            output.append(_recommendation(
                3, "medium", "potential", "low",
                f"Search Console query “{row['query']}” has {impressions} impressions "
                f"at average position {position:.1f}; crawled source page shares terms "
                f"{', '.join(overlap)} and has no observed link to the landing page",
                "Review a contextual internal link",
                "Manually confirm the pages are relevant, then consider adding a useful "
                "contextual link. Crawl coverage is limited and this is not an automatic fix.",
                target_url,
            ))
    return sorted(
        output,
        key=lambda item: (item["priority"], -len(item["evidence"]), item["title"]),
    )[:MAX_RECOMMENDATIONS]
