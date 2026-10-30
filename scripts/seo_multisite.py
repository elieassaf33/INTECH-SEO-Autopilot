#!/usr/bin/env python3
"""Compatibility CLI for the shared read-only technical checks."""
import datetime as dt
import json
from pathlib import Path
from client_registry import load_registry
from technical_audit import MetadataParser, fetch, inspect

ROOT = Path(__file__).resolve().parents[1]


def main():
    results = []
    for site in load_registry(ROOT / "seo-sites.json"):
        try:
            results.append(inspect(site))
        except Exception:
            results.append({"name": site["name"], "base_url": site["url"], "status": "error",
                            "findings": [{"severity": "high", "message": "Technical audit failed"}]})
    output = ROOT / "seo-reports" / "multisite"
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "sites": results}, indent=2), encoding="utf-8")
    lines = ["# INTECH multi-site SEO audit", "", f"Properties: {len(results)}", ""]
    for site in results:
        lines += [f"## {site['name']}", f"Status: {site['status']}"]
        lines += ["- " + issue["message"] for issue in site["findings"]]
        lines.append("")
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
