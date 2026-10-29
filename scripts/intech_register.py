#!/usr/bin/env python3
"""Register a new client without changing audit code."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

path = Path(__file__).resolve().parents[1] / "seo-sites.json"
name = os.environ["CLIENT_NAME"].strip()
url = os.environ["CLIENT_URL"].strip().rstrip("/")
repo = os.environ.get("CLIENT_REPO", "").strip()
gsc = os.environ.get("CLIENT_GSC", "").strip()
parts = urlsplit(url)
if not name or parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
    raise SystemExit("Use a client name and an HTTPS website root, e.g. https://example.com")
if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
    raise SystemExit("GitHub repository must be owner/name")
sites = json.loads(path.read_text(encoding="utf-8"))
if any(urlsplit(s["url"]).hostname == parts.hostname for s in sites):
    raise SystemExit("This domain is already registered; edit seo-sites.json to update it")
sites.append({"name": name, "url": url, "repository": repo, "gsc_property": gsc})
path.write_text(json.dumps(sites, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("Registered", name, url)
