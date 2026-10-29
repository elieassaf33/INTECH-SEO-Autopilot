#!/usr/bin/env python3
"""Reusable INTECH SEO controller. Read-only scans; never deploys."""
import datetime as dt
import json
import os
from pathlib import Path
from gsc_analysis import weekly_analysis
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
        with session:
            return weekly_analysis(session, prop)
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300], "queries": []}

def main():
    sites = json.loads(REGISTRY.read_text(encoding="utf-8"))
    results = []
    for site in sites:
        try:
            audit = inspect(site)
        except Exception as exc:
            audit = {"name": site["name"], "base_url": site["url"],
                     "findings": [{"severity": "high", "message": "Audit failed: " + str(exc)[:200]}]}
        audit["repository"] = site.get("repository", "")
        audit["gsc"] = search_console(site)
        results.append(audit)
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
        gsc = site["gsc"]
        if "period" in gsc:
            lines.append(f"Period: {gsc['period']} vs {gsc['previous_period']}")
            lines.append(gsc["coverage_note"])
            if gsc["row_cap_reached"]:
                lines.append("WARNING: configured row cap reached; analysis is truncated.")
        if gsc.get("error"):
            lines.append("Search Console error: " + gsc["error"])
        for kw in gsc.get("recommendations", [])[:20]:
            keyword = kw['keyword'].replace("\n", " ").replace("\r", " ")
            lines.append(f"- [{kw['priority']}] {keyword} - {kw['page']}: {kw['action']} "
                         f"({kw['impressions']} impressions, {kw['clicks']} clicks, "
                         f"CTR {kw['ctr']:.1%}, click change {kw['click_change']:+g})")
        lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
