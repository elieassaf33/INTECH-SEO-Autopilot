#!/usr/bin/env python3
"""Reusable INTECH SEO controller. Read-only scans; never deploys."""
import datetime as dt
import json
import os
from pathlib import Path
from urllib.parse import quote
from seo_multisite import inspect

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "seo-sites.json"
OUT = ROOT / "seo-reports" / "controller"
OUT.mkdir(parents=True, exist_ok=True)

def search_console(site):
    """Returns explicit setup status when GSC access has not been configured."""
    prop = site.get("gsc_property", "")
    if not prop or os.environ.get("GCP_USE_ADC") != "true":
        return {"status": "not_configured", "queries": []}
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
        )
        session = AuthorizedSession(credentials)
        end = dt.date.today() - dt.timedelta(days=3)
        start = end - dt.timedelta(days=27)
        url = "https://searchconsole.googleapis.com/webmasters/v3/sites/" + quote(prop, safe="") + "/searchAnalytics/query"
        response = session.post(url, json={
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["query"], "rowLimit": 100,
        }, timeout=30)
        response.raise_for_status()
        rows = response.json().get("rows", [])
        queries = [{
            "keyword": row["keys"][0], "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0), "position": row.get("position", 0),
        } for row in rows]
        opportunities = sorted(
            (q for q in queries if q["impressions"] >= 10 and q["position"] >= 5),
            key=lambda q: (-q["impressions"], q["position"]),
        )[:20]
        return {"status": "ok", "queries": queries, "opportunities": opportunities,
                "period": [start.isoformat(), end.isoformat()]}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300], "queries": []}

def main():
    sites = json.loads(REGISTRY.read_text(encoding="utf-8"))
    results = []
    for site in sites:
        try:
            audit = inspect(site)
            audit["repository"] = site.get("repository", "")
            audit["gsc"] = search_console(site)
            results.append(audit)
        except Exception as exc:
            results.append({"name": site["name"], "base_url": site["url"],
                            "repository": site.get("repository", ""),
                            "findings": [{"severity": "high", "message": "Audit failed: " + str(exc)[:200]}],
                            "gsc": {"status": "not_run"}})
    report = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "client_count": len(results), "sites": results}
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# INTECH weekly SEO report", "", f"Clients: {len(results)}", ""]
    for site in results:
        lines += [f"## {site['name']}", f"Website: {site['base_url']}",
                  f"GitHub: {site.get('repository') or 'not configured'}",
                  f"Technical findings: {len(site.get('findings', []))}",
                  f"Search Console: {site['gsc']['status']}"]
        for issue in site.get("findings", [])[:25]:
            lines.append("- " + issue["severity"] + ": " + issue["message"])
        for kw in site["gsc"].get("opportunities", [])[:10]:
            lines.append(f"- Keyword opportunity: {kw['keyword']} ({kw['impressions']} impressions, position {kw['position']:.1f})")
        lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
