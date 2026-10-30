# INTECH SEO Autopilot

Weekly monitoring of 13 Google Search Console properties, grouped into 11
clients, followed by automatic production metadata recovery for nine VPS clients
(ten properties). The production worker restores only approved missing metadata
against pinned template snapshots, backs up changes, checks live pages and rolls
back failed repairs. Netlify's two INTECH properties and Tvari Kirpeja still need
deployment integration. Other SEO findings remain recommendations.

The separate static-HTML draft-PR adapter remains disabled. Production recovery
uses its own restricted SSH worker, not the draft-PR credential path.

See [setup, safeguards and limits](docs/INTECH-SEO-AUTOPILOT.md) and
[verified status and blockers](docs/VERIFICATION-2026-10-30.md).

Tests: `python -m unittest discover -s tests -v`.
