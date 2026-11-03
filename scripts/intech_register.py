#!/usr/bin/env python3
"""Register a client using the same structured schema as existing sites."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


path = Path(__file__).resolve().parents[1] / "seo-sites.json"
name = os.environ.get("CLIENT_NAME", "").strip()
url = os.environ.get("CLIENT_URL", "").strip().rstrip("/")
repo = os.environ.get("CLIENT_REPO", "").strip()
gsc = os.environ.get("CLIENT_GSC", "").strip()
country = os.environ.get("CLIENT_COUNTRY", "").strip().upper()
languages = [item.strip() for item in os.environ.get("CLIENT_LANGUAGES", "").split(",")
             if item.strip()]
business_type = os.environ.get("CLIENT_BUSINESS_TYPE", "").strip()
keywords = [item.strip() for item in os.environ.get("CLIENT_KEYWORDS", "").split(",")
            if item.strip()]
parts = urlsplit(url)
if (not name or parts.scheme != "https" or not parts.hostname or parts.username
        or parts.password or parts.query or parts.fragment or parts.path not in ("", "/")):
    raise SystemExit("Use a client name and HTTPS website root, e.g. https://example.com")
if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
    raise SystemExit("GitHub repository must be owner/name")
if not re.fullmatch(r"[A-Z]{2}", country):
    raise SystemExit("Set the ISO 3166-1 alpha-2 country code or EU")
if not languages or not business_type:
    raise SystemExit("Set at least one language and a business type")
if gsc:
    if re.fullmatch(r"sc-domain:[A-Za-z0-9.-]+", gsc):
        property_host = gsc.removeprefix("sc-domain:").lower()
    else:
        property_url = urlsplit(gsc)
        if (property_url.scheme != "https" or not property_url.hostname
                or property_url.username or property_url.password
                or property_url.path not in ("", "/")
                or property_url.query or property_url.fragment):
            raise SystemExit("Search Console property must be an exact domain or HTTPS URL-prefix identifier")
        property_host = property_url.hostname.lower()
    if property_host.removeprefix("www.") != parts.hostname.lower().removeprefix("www."):
        raise SystemExit("Search Console property host must match the configured website")
registry = json.loads(path.read_text(encoding="utf-8"))
sites = registry.get("sites", [])
if any(urlsplit(site["url"]).hostname == parts.hostname for site in sites):
    raise SystemExit("This domain is already registered; edit seo-sites.json to update it")
site_id = re.sub(r"[^a-z0-9]+", "-", parts.hostname.lower().removeprefix("www.")).strip("-")
if any(site["id"] == site_id for site in sites):
    raise SystemExit(f"Generated site id {site_id!r} already exists")
sites.append({
    "id": site_id,
    "name": name,
    "url": url,
    "domain": parts.hostname.lower().removeprefix("www."),
    "country": country,
    "languages": languages,
    "business_type": business_type,
    "keywords": keywords,
    "gsc_property": gsc,
    "repository": repo or None,
})
path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("Registered", name, url, "as", site_id)
