# INTECH SEO Autopilot — all clients

This dedicated INTECH repository hosts the central controller; the registry is `seo-sites.json`. No per-client workflow installation is needed.

## Onboard any future client
Actions → **INTECH SEO - onboard client** → Run workflow. Enter the name, HTTPS domain, optional GitHub owner/repo, and optional Search Console property (`sc-domain:example.com` or exact URL prefix). Review and merge the generated onboarding PR. The next weekly audit automatically includes the client.

## Every Monday
**INTECH SEO Autopilot - all clients** runs and produces one JSON/Markdown report for all registered domains. The existing multi-site checks cover homepage, robots.txt and sitemap. This does not guarantee indexing or ranking.

## Search Console setup (one-time credentials)
Create a Google Cloud service account, enable Google Search Console API, grant its email access to each client Search Console property, then store the service account JSON as GitHub Actions secret `GSC_SERVICE_ACCOUNT_JSON`. Set each client's `gsc_property` in the registry. The weekly report then includes actual query impressions, clicks, CTR, position and opportunity candidates. Without permission, it explicitly reports an error or not_configured. This is not Google Ads Keyword Planner: it finds opportunities from existing Search Console queries, not market-wide search volumes.

## Safety and boundaries
Read-only monitoring; never changes client code or deploys. The existing Codex workflow is an issue-driven **manual PR proposal**, not automatic client optimization. Automated cross-repository PR routing, per-page deep crawling, competitor research, Keyword Planner integration, and automatic production deployment are **not implemented yet**. Do not assume that an API connection to OpenAI grants write permissions to every client's GitHub repository. All proposed changes should be reviewed and tested before merge.
