#!/usr/bin/env python3
"""Generate independent weekly technical and Search Console reports for each client."""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.gsc_client import SearchConsoleClient, SearchConsoleError
from scripts.keyword_discovery import discover
from scripts.recommendations import recommendations
from scripts.seo_multisite import inspect


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "seo-sites.json"
OUTPUT = ROOT / "seo-reports" / "weekly"
HISTORY = ROOT / "seo-reports" / "history"
LOGGER = logging.getLogger("intech_seo")
MAX_HISTORY_SNAPSHOTS = 104
MAX_HISTORY_ROWS = 100


def load_sites(path: Path = REGISTRY) -> list[dict[str, Any]]:
    try:
        sites = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load website registry {path}: {exc}") from exc
    if not isinstance(sites, dict) or sites.get("schema_version") != 1:
        raise RuntimeError("Website registry must use schema_version 1")
    sites = sites.get("sites")
    if not isinstance(sites, list) or not sites:
        raise RuntimeError("Website registry must be a non-empty JSON list")
    seen: set[str] = set()
    required = {"id", "name", "url", "domain", "country", "languages",
                "business_type", "keywords", "gsc_property"}
    for site in sites:
        if not isinstance(site, dict) or not required.issubset(site):
            raise RuntimeError(f"Website entry is missing required fields: {site!r}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", site["id"]):
            raise RuntimeError(f"Invalid website id: {site['id']!r}")
        if site["id"] in seen:
            raise RuntimeError(f"Duplicate website id: {site['id']}")
        seen.add(site["id"])
        parsed_url = urlsplit(site["url"])
        if parsed_url.scheme != "https" or not parsed_url.hostname or not site["domain"]:
            raise RuntimeError(f"Website {site['id']} needs an HTTPS URL and domain")
        if parsed_url.hostname.lower().removeprefix("www.") != site["domain"].lower().removeprefix("www."):
            raise RuntimeError(f"Website {site['id']} URL and domain do not match")
        property_id = site.get("gsc_property", "")
        if property_id:
            if property_id.startswith("sc-domain:"):
                property_host = property_id.removeprefix("sc-domain:").lower()
            else:
                parsed_property = urlsplit(property_id)
                if (parsed_property.scheme != "https" or not parsed_property.hostname
                        or parsed_property.username or parsed_property.password
                        or parsed_property.path not in ("", "/")
                        or parsed_property.query or parsed_property.fragment):
                    raise RuntimeError(f"Website {site['id']} has an invalid Search Console property")
                property_host = parsed_property.hostname.lower()
            if property_host.removeprefix("www.") != site["domain"].lower().removeprefix("www."):
                raise RuntimeError(f"Website {site['id']} Search Console property belongs to another domain")
        if not isinstance(site["languages"], list) or not site["languages"]:
            raise RuntimeError(f"Website {site['id']} needs at least one language")
        if not isinstance(site["keywords"], list):
            raise RuntimeError(f"Website {site['id']} keywords must be a list")
    return sites


def _read_history(site_id: str) -> list[dict[str, Any]]:
    path = HISTORY / f"{site_id}.jsonl"
    if not path.exists():
        return []
    snapshots = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Ignoring invalid history record %s:%s: %s", path, line_number, exc)
            continue
        if isinstance(item, dict):
            snapshots.append(item)
    return snapshots[-MAX_HISTORY_SNAPSHOTS:]


def _save_history(site_id: str, snapshots: list[dict[str, Any]]) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    path = HISTORY / f"{site_id}.jsonl"
    serialized = "\n".join(json.dumps(item, ensure_ascii=False) for item in snapshots[-MAX_HISTORY_SNAPSHOTS:])
    path.write_text(serialized + ("\n" if serialized else ""), encoding="utf-8")


def _snapshot(gsc: dict[str, Any], generated_at: str,
              technical_findings: int) -> dict[str, Any]:
    run_date = dt.datetime.fromisoformat(generated_at).date()
    iso_week = run_date.isocalendar()
    periods = gsc.get("periods", {})
    queries = sorted(
        gsc.get("queries", {}).get("current", []),
        key=lambda row: row.get("impressions", 0), reverse=True,
    )[:MAX_HISTORY_ROWS]
    pages = sorted(
        gsc.get("pages", {}).get("current", []),
        key=lambda row: row.get("impressions", 0), reverse=True,
    )[:MAX_HISTORY_ROWS]
    return {
        "generated_at": generated_at,
        "week": f"{iso_week.year}-W{iso_week.week:02d}",
        "gsc_status": gsc.get("status", "not_configured"),
        "current": periods.get("current", {}),
        "previous": periods.get("previous", {}),
        "queries": queries,
        "pages": pages,
        "technical_findings": technical_findings,
    }


def _change(current: dict[str, Any], previous: dict[str, Any], field: str) -> int | float | None:
    if not current or not previous:
        return None
    new_value = current.get(field)
    old_value = previous.get(field)
    if new_value is None or old_value is None:
        return None
    return new_value - old_value


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "not available"
    return f"{value}{suffix}"


def _signed(value: Any, number_format: str) -> str:
    if value is None:
        return "not available"
    return format(value, f"+{number_format}")


def _write_site_report(site: dict[str, Any], report: dict[str, Any]) -> Path:
    directory = OUTPUT / site["id"]
    directory.mkdir(parents=True, exist_ok=True)
    gsc = report["gsc"]
    lines = [
        f"# Weekly SEO report — {site['name']}", "",
        f"- Domain: {site['url']}",
        f"- Country / language: {site['country']} / {', '.join(site['languages'])}",
        f"- Business type: {site['business_type']}",
        f"- Run status: **{report['status']}**",
        f"- Technical audit: **{report['technical_status']}** "
        f"({report.get('pages_crawled', 0)} pages sampled)",
        f"- Search Console: **{gsc['status']}**",
        f"- Search Console property: `{site.get('gsc_property') or 'not configured'}`",
        f"- Generated (UTC): {report['generated_at']}",
        "",
        "## Executive summary",
    ]
    current_period = gsc.get("periods", {}).get("current", {})
    previous_period = gsc.get("periods", {}).get("previous", {})
    current = current_period.get("metrics", {})
    previous = previous_period.get("metrics", {})
    if current:
        lines += [
            f"- Clicks: {current.get('clicks', 0)} "
            f"({_fmt(_change(current, previous, 'clicks'), ' vs prior 28 days')})",
            f"- Impressions: {current.get('impressions', 0)} "
            f"({_fmt(_change(current, previous, 'impressions'), ' vs prior 28 days')})",
            f"- CTR: {current.get('ctr', 0):.2%} "
            f"({_fmt(_change(current, previous, 'ctr'), ' vs prior 28 days')})",
            f"- Average position: {current.get('position', 0):.1f} "
            f"({_fmt(_change(current, previous, 'position'), ' vs prior 28 days')})",
            f"- Period: {current_period.get('start_date')} to {current_period.get('end_date')}",
        ]
    historical = report.get("history_comparison")
    if historical and historical.get("status") == "ok":
        metrics = historical["metrics"]
        lines += [
            f"- Since prior report ({historical['generated_at']}): "
            f"{_signed(metrics.get('clicks'), '.0f')} clicks, "
            f"{_signed(metrics.get('impressions'), '.0f')} impressions, "
            f"{_signed(metrics.get('ctr'), '.2%')} CTR, "
            f"{_signed(metrics.get('position'), '.1f')} average position",
        ]
    else:
        lines.append("- Search performance metrics are unavailable; no values have been inferred.")
    if gsc.get("error"):
        lines.append(f"- Search Console detail: {gsc['error']}")
    discovery = report.get("keyword_discovery", {})
    lines += ["", "## New keyword ideas", "", f"Discovery: {discovery.get('status', 'unavailable')}",
              discovery.get("note", "")]
    for idea in discovery.get("ideas", []):
        lines.append(f"- {idea['keyword']} ? {', '.join(idea['sources'])}; "
                     f"{'already observed in GSC' if idea['already_observed'] else 'not observed in returned GSC rows'}")
    if discovery.get("errors"):
        lines.append(f"- {len(discovery['errors'])} autocomplete requests failed; see JSON for details.")
    lines += ["", "## Top queries"]
    queries = sorted(gsc.get("queries", {}).get("current", []),
                     key=lambda row: row.get("clicks", 0), reverse=True)[:10]
    lines.extend(
        f"- {row['query']}: {row['clicks']} clicks, {row['impressions']} impressions, "
        f"{row['ctr']:.2%} CTR, position {row['position']:.1f}"
        for row in queries
    )
    if not queries:
        lines.append("- No query rows returned for this period.")
    lines += ["", "## Top landing pages"]
    pages = sorted(gsc.get("pages", {}).get("current", []),
                   key=lambda row: row.get("clicks", 0), reverse=True)[:10]
    lines.extend(
        f"- [{row['page']}]({row['page']}): {row['clicks']} clicks, "
        f"{row['impressions']} impressions, position {row['position']:.1f}"
        for row in pages
    )
    if not pages:
        lines.append("- No landing-page rows returned for this period.")
    lines += ["", "## Country and device breakdown"]
    for label, key, rows in (("Countries", "country", gsc.get("countries", [])),
                             ("Devices", "device", gsc.get("devices", []))):
        lines.append(f"### {label}")
        leaders = sorted(rows, key=lambda row: row.get("impressions", 0), reverse=True)[:5]
        if leaders:
            lines.extend(
                f"- {row[key]}: {row['clicks']} clicks, "
                f"{row['impressions']} impressions"
                for row in leaders
            )
        else:
            lines.append("- No breakdown rows returned.")
    lines += ["", "## Keyword movement"]
    previous_queries = {
        row.get("query", "").casefold(): row
        for row in gsc.get("queries", {}).get("previous", [])
    }
    movements = []
    new_queries = []
    for row in gsc.get("queries", {}).get("current", []):
        old = previous_queries.get(row.get("query", "").casefold())
        if old:
            movement = float(old.get("position", 0)) - float(row.get("position", 0))
            if abs(movement) >= 1:
                movements.append((movement, row, old))
        elif int(row.get("impressions", 0)) >= 10:
            new_queries.append(row)
    for movement, row, old in sorted(movements, key=lambda item: item[0], reverse=True)[:10]:
        direction = "improved" if movement > 0 else "declined"
        lines.append(
            f"- {row['query']}: {direction} by {abs(movement):.1f} average positions "
            f"({old['position']:.1f} → {row['position']:.1f})"
        )
    if not movements:
        lines.append("- No query ranking changes of at least one average position were measured.")
    for row in sorted(new_queries, key=lambda item: int(item.get("impressions", 0)), reverse=True)[:10]:
        lines.append(
            f"- Newly observed query: {row['query']} "
            f"({row['impressions']} impressions, position {row['position']:.1f})"
        )
    lines += ["", "## Technical SEO findings"]
    for finding in report.get("findings", []):
        lines.append(
            f"- **{finding['severity'].upper()} / {finding.get('confidence', 'confirmed')}** — "
            f"{finding['message']} ([page]({finding['url']})); evidence: {finding.get('evidence', 'audit')}"
        )
    if not report.get("findings"):
        lines.append("- No issues were confirmed in the crawled sample.")
    lines += ["", "## Prioritized action plan"]
    for index, item in enumerate(report.get("recommendations", [])[:20], start=1):
        lines.append(
            f"{index}. **P{item['priority']} — {item['title']}** "
            f"(impact: {item['impact']}; confidence: {item['confidence']}; effort: {item['effort']}). "
            f"{item['action']} Evidence: {item['evidence']} "
            + (f"[Page]({item['url']})" if item.get("url") else "")
        )
    if not report.get("recommendations"):
        lines.append("- No evidence-based actions met the current thresholds.")
    lines += [
        "", "## Reporting notes",
        "- Search Console measurements are API data for the exact periods shown; missing rows are not estimated.",
        "- A sitemap is discovery input only and is not evidence that a URL is indexed.",
        "- Technical results cover a bounded, robots-respecting crawl sample; potential findings require review.",
        "- Historical average-position deltas below zero indicate improved average position.",
        "- Recommendations are not ranking or traffic guarantees.",
    ]
    path = directory / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe_row = {
                key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
                else value
                for key, value in row.items()
            }
            writer.writerow(safe_row)


def _write_shared_reports(reports: list[dict[str, Any]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_csv(
        OUTPUT / "summary.csv",
        ["id", "name", "domain", "country", "languages", "business_type", "status",
         "technical_status", "gsc_status", "clicks_current_28d", "clicks_previous_28d",
         "impressions_current_28d", "impressions_previous_28d", "ctr_current_28d",
         "position_current_28d", "pages_crawled", "technical_findings"],
        [{
            "id": report["id"], "name": report["name"], "domain": report["domain"],
            "country": report["country"], "languages": ",".join(report["languages"]),
            "business_type": report["business_type"], "status": report["status"],
            "technical_status": report["technical_status"],
            "gsc_status": report["gsc"]["status"],
            "clicks_current_28d": report["gsc"].get("periods", {}).get("current", {}).get("metrics", {}).get("clicks"),
            "clicks_previous_28d": report["gsc"].get("periods", {}).get("previous", {}).get("metrics", {}).get("clicks"),
            "impressions_current_28d": report["gsc"].get("periods", {}).get("current", {}).get("metrics", {}).get("impressions"),
            "impressions_previous_28d": report["gsc"].get("periods", {}).get("previous", {}).get("metrics", {}).get("impressions"),
            "ctr_current_28d": report["gsc"].get("periods", {}).get("current", {}).get("metrics", {}).get("ctr"),
            "position_current_28d": report["gsc"].get("periods", {}).get("current", {}).get("metrics", {}).get("position"),
            "pages_crawled": report.get("pages_crawled", 0),
            "technical_findings": len(report.get("findings", [])),
        } for report in reports],
    )
    _write_csv(OUTPUT / "keyword-ideas.csv",
               ["site_id", "keyword", "sources", "seed", "page", "already_observed", "search_volume"],
               [{"site_id": report["id"], **idea, "sources": ",".join(idea["sources"])}
                for report in reports
                for idea in report.get("keyword_discovery", {}).get("ideas", [])])
    query_rows = []
    query_page_rows = []
    finding_rows = []
    recommendation_rows = []
    breakdown_rows = []
    for report in reports:
        for period in ("current", "previous"):
            for row in report["gsc"].get("queries", {}).get(period, []):
                query_rows.append({"site_id": report["id"], "period": period, **row})
            for row in report["gsc"].get("query_pages", {}).get(period, []):
                query_page_rows.append({"site_id": report["id"], "period": period, **row})
        for finding in report.get("findings", []):
            finding_rows.append({"site_id": report["id"], **finding})
        for item in report.get("recommendations", []):
            recommendation_rows.append({"site_id": report["id"], **item})
        for dimension, rows in (("country", report["gsc"].get("countries", [])),
                                ("device", report["gsc"].get("devices", []))):
            breakdown_rows.extend(
                {"site_id": report["id"], "dimension": dimension, **row}
                for row in rows
            )
    _write_csv(OUTPUT / "queries.csv",
               ["site_id", "period", "query", "clicks", "impressions", "ctr", "position"],
               query_rows)
    _write_csv(OUTPUT / "query-pages.csv",
               ["site_id", "period", "query", "page", "clicks", "impressions", "ctr", "position"],
               query_page_rows)
    _write_csv(OUTPUT / "technical-findings.csv",
               ["site_id", "severity", "confidence", "evidence", "message", "url"],
               finding_rows)
    _write_csv(OUTPUT / "recommendations.csv",
               ["site_id", "priority", "impact", "confidence", "effort", "evidence",
                "title", "action", "url"],
               recommendation_rows)
    _write_csv(OUTPUT / "country-device-breakdown.csv",
               ["site_id", "dimension", "country", "device", "clicks", "impressions",
                "ctr", "position"],
               breakdown_rows)


def run(sites: list[dict[str, Any]] | None = None,
        audit_fn=inspect, gsc_client: Any = None,
        generated_at: dt.datetime | None = None,
        discovery_fn=discover) -> list[dict[str, Any]]:
    sites = sites or load_sites()
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc)
    generated_string = timestamp.astimezone(dt.timezone.utc).isoformat()
    needs_gsc = any(site.get("gsc_property") for site in sites)
    if needs_gsc and gsc_client is None:
        try:
            gsc_client = SearchConsoleClient.from_application_default_credentials()
        except (SearchConsoleError, OSError, RuntimeError) as exc:
            LOGGER.error("Search Console client initialization failed: %s", exc)
            gsc_client = exc

    reports = []
    for site in sites:
        technical: dict[str, Any]
        try:
            technical = audit_fn(site)
            technical_status = "success"
        except Exception as exc:
            LOGGER.exception("Technical audit failed for %s", site["id"])
            technical = {"findings": [{
                "severity": "high", "confidence": "confirmed",
                "evidence": f"{type(exc).__name__}: {exc}",
                "message": "Technical audit failed before completing",
                "url": site["url"],
            }], "pages_crawled": 0}
            technical_status = "failed"

        property_id = site.get("gsc_property", "").strip()
        if not property_id:
            gsc = {"status": "not_configured", "error": None}
        elif isinstance(gsc_client, Exception):
            auth_status = "auth_unavailable" if os.environ.get("GCP_USE_ADC") != "true" else "error"
            gsc = {"status": auth_status, "error": str(gsc_client)[:300]}
        else:
            try:
                gsc = gsc_client.collect(property_id)
            except SearchConsoleError as exc:
                LOGGER.error("Search Console failed for %s: %s", site["id"], exc)
                gsc = {"status": "error", "error": str(exc)[:300]}
            except Exception as exc:
                LOGGER.exception("Unexpected Search Console failure for %s", site["id"])
                gsc = {"status": "error",
                       "error": f"{type(exc).__name__}: {exc}"[:300]}
        keyword_discovery = discovery_fn(site, technical, gsc)
        technical["gsc"] = gsc
        technical["recommendations"] = recommendations(technical, gsc)
        history = _read_history(site["id"])
        snapshot = _snapshot(
            gsc, generated_string, len(technical.get("findings", [])))
        current_week = snapshot["week"]
        prior = next(
            (item for item in reversed(history)
             if item.get("week") != current_week
             and item.get("generated_at") != generated_string
             and item.get("gsc_status") == "ok"
             and item.get("current", {}).get("metrics")),
            None,
        )
        history_comparison = {"status": "not_available"}
        if prior and gsc.get("status") == "ok":
            prior_metrics = prior["current"]["metrics"]
            current_metrics = snapshot.get("current", {}).get("metrics", {})
            history_comparison = {
                "status": "ok",
                "generated_at": prior["generated_at"],
                "metrics": {
                    field: _change(current_metrics, prior_metrics, field)
                    for field in ("clicks", "impressions", "ctr", "position")
                },
            }
        same_week = next(
            (index for index, item in enumerate(history)
             if item.get("week") == current_week),
            None,
        )
        if same_week is None:
            history.append(snapshot)
        else:
            history[same_week] = snapshot
        if history:
            _save_history(site["id"], history)
        status = "failed" if technical_status == "failed" or gsc.get("status") == "error" else (
            "success" if gsc.get("status") == "ok" else "insufficient_data"
        )
        report = {
            "id": site["id"], "name": site["name"], "domain": site["domain"],
            "url": site["url"], "country": site["country"],
            "languages": site["languages"], "business_type": site["business_type"],
            "keyword_discovery": keyword_discovery,
            "keywords": site["keywords"], "repository": site.get("repository"),
            "gsc_property": property_id, "status": status,
            "technical_status": technical_status, "pages_crawled": technical.get("pages_crawled", 0),
            "generated_at": generated_string, "checks": technical.get("checks", {}),
            "findings": technical.get("findings", []), "gsc": gsc,
            "recommendations": technical["recommendations"],
            "history_comparison": history_comparison,
            "history_snapshots": len(history),
        }
        reports.append(report)
        _write_site_report(site, report)

    payload = {
        "generated_at": generated_string,
        "website_count": len(reports),
        "summary": {
            "succeeded": sum(row["status"] == "success" for row in reports),
            "failed": sum(row["status"] == "failed" for row in reports),
            "insufficient_data": sum(row["status"] == "insufficient_data" for row in reports),
        },
        "sites": reports,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    lines = [
        "# INTECH weekly SEO status",
        f"Generated: {generated_string}",
        f"Websites: {len(reports)} — succeeded {payload['summary']['succeeded']}, "
        f"failed {payload['summary']['failed']}, insufficient data {payload['summary']['insufficient_data']}",
        "",
    ]
    lines.extend(
        f"- **{row['status'].upper()}** — {row['name']} (`{row['domain']}`): "
        f"technical {row['technical_status']}; Search Console {row['gsc']['status']}"
        for row in reports
    )
    (OUTPUT / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_shared_reports(reports)
    for row in reports:
        LOGGER.info("%s: status=%s technical=%s gsc=%s",
                    row["id"], row["status"], row["technical_status"], row["gsc"]["status"])
    return reports


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        sites = load_sites()
        reports = run(sites)
    except (RuntimeError, OSError) as exc:
        LOGGER.error("Report generation failed: %s", exc)
        return 1
    return 1 if reports and all(row["status"] == "failed" for row in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
