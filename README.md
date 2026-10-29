# INTECH SEO Autopilot

Central, read-only weekly SEO monitoring for all clients in `seo-sites.json`.

The Monday workflow audits websites and compares two seven-day Search Console
windows, producing JSON and Markdown reports with page-specific recommendations.
New clients only need a registry entry and Search Console access.

See [setup and report interpretation](docs/INTECH-SEO-AUTOPILOT.md).

Run offline tests: `python -m unittest discover -s tests -v`.
