"""Property access and bounded URL Inspection. Never submits indexing requests."""
from urllib.parse import quote
from gsc_api import request, error_status


def property_access(session, prop):
    try:
        data = request(session, "get", "https://searchconsole.googleapis.com/webmasters/v3/sites/" + quote(prop, safe=""))
        permission = data.get("permissionLevel", "unknown")
        return {"status": "ok" if permission not in ("siteUnverifiedUser", "unknown") else "unverified",
                "permission_level": permission}
    except Exception as exc:
        result = error_status(exc)
        if result["http_status"] == 403:
            result["required_action"] = "Grant the configured service account access in Search Console > Settings > Users and permissions for this exact property."
        return result


def indexing(session, prop, url):
    try:
        data = request(session, "post", "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                       json={"inspectionUrl": url, "siteUrl": prop, "languageCode": "en-US"})
        status = data.get("inspectionResult", {}).get("indexStatusResult", {})
        return {"status": "ok", "url": url,
                "source": "Google indexed version; not a live indexability test",
                **{k: status.get(k) for k in ("verdict", "coverageState", "robotsTxtState", "indexingState", "pageFetchState", "googleCanonical", "userCanonical", "lastCrawlTime")}}
    except Exception as exc:
        return {**error_status(exc), "url": url}
