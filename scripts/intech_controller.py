#!/usr/bin/env python3
"""Reusable INTECH SEO controller. Read-only scans; never deploys."""
import datetime as dt
import json
import os
from pathlib import Path
from gsc_analysis import weekly_analysis
from technical_audit import inspect
from client_registry import load_registry
from gsc_diagnostics import property_access, indexing
from gsc_api import error_status

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "seo-sites.json"
OUT = ROOT / "seo-reports" / "controller"

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
            access = property_access(session, prop)
            if access["status"] != "ok":
                return {"status": "access_denied" if access.get("http_status") in (403, 404) else "error", "access": access, "queries": []}
            report = weekly_analysis(session, prop)
            report["access"] = access
            report["indexing"] = indexing(session, prop, site["url"].rstrip("/") + "/")
            if report["indexing"]["status"] != "ok" and report["status"] in ("ok", "no_data"):
                report["status"] = "partial"
            return report
    except Exception as exc:
        return {**error_status(exc), "queries": []}

def main():
    sites = load_registry(REGISTRY)
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for site in sites:
        try:
            audit = inspect(site)
        except Exception:
            audit = {"name": site["name"], "base_url": site["url"],
                     "status": "error",
                     "findings": [{"code": "technical_audit_failed", "severity": "high", "message": "Technical audit failed; no missing-tag verdict inferred"}]}
        audit["repository"] = site.get("repository", "")
        audit["client_id"] = site["client_id"]
        audit["gsc_property"] = site.get("gsc_property")
        audit["repository_status"] = site.get("repository_status", "unmapped")
        audit["default_branch"] = site.get("default_branch")
        audit["gsc"] = search_console(site)
        results.append(audit)
    report = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "property_count": len(results), "client_count": len({s["client_id"] for s in results}), "sites": results}
    report["clients"] = [{"client_id": client_id, "properties": [s["gsc_property"] for s in results if s["client_id"] == client_id]}
                         for client_id in sorted({s["client_id"] for s in results})]
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# INTECH weekly SEO report", "", f"Properties: {len(results)} | Clients: {report['client_count']}", ""]
    previous_client = None
    for site in sorted(results, key=lambda s: (s["client_id"], s["base_url"])):
        if previous_client != site["client_id"]:
            lines += [f"## Client: {site['client_id']}", ""]
            previous_client = site["client_id"]
        lines += [f"### {site['name']}", f"Website: {site['base_url']}",
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
        access = gsc.get("access", {})
        if access.get("required_action"):
            lines.append(access["required_action"] + " Property: " + str(site["gsc_property"]))
        for label, metrics in gsc.get("site_metrics", {}).items():
            lines.append(f"Property aggregate ({label}): {json.dumps(metrics, ensure_ascii=True)}")
        if "site_metric_changes" in gsc:
            lines.append("Aggregate changes: " + json.dumps(gsc["site_metric_changes"]))
        if "indexing" in gsc:
            lines.append("Index diagnostics: " + json.dumps(gsc["indexing"], ensure_ascii=True))
        if gsc.get("error"):
            lines.append("Search Console error: " + gsc["error"])
        for kw in gsc.get("recommendations", [])[:20]:
            keyword = kw['keyword'].replace("\n", " ").replace("\r", " ")
            lines.append(f"- [{kw['priority']}] {keyword} - {kw['page']}: {kw['action']} "
                         f"({kw['impressions']} impressions, {kw['clicks']} clicks, "
                         f"CTR {kw['ctr']:.1%}, click change {kw['click_change']:+g})")
        lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (OUT / f"snapshot-{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    from remediation import plan_proposals
    (OUT / "remediation-plan.json").write_text(json.dumps(plan_proposals(report, sites), indent=2), encoding="utf-8")
    (OUT / "health.json").write_text(json.dumps({"property_count": len(results),
        "unhealthy_properties": [s["gsc_property"] for s in results if s["gsc"]["status"] not in ("ok", "no_data") or s.get("status") != "ok"]}, indent=2), encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
