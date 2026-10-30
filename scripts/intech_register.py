#!/usr/bin/env python3
"""Register a client without enabling remediation or guessing a default branch."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from client_registry import load_registry


def register(path, name, url, repo="", gsc="", client_id=""):
    name, url, repo, gsc = name.strip(), url.strip().rstrip("/"), repo.strip(), gsc.strip()
    if not name:
        raise ValueError("Client name is required")
    sites = load_registry(path)
    if any(urlsplit(s["url"]).hostname == urlsplit(url).hostname for s in sites):
        raise ValueError("This domain is already registered; update it through review")
    entry = {"name": name, "url": url, "repository": repo, "gsc_property": gsc,
             "client_id": client_id.strip() or (urlsplit(url).hostname or "").removeprefix("www."),
             "repository_status": "pending_verification" if repo else "unmapped", "remediation_enabled": False}
    # Validate before replacing the registry; errors never leave a partial write.
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        candidate = Path(temp) / "sites.json"
        candidate.write_text(json.dumps(sites + [entry]), encoding="utf-8")
        load_registry(candidate)
    Path(path).write_text(json.dumps(sites + [entry], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry


def main():
    path = Path(__file__).resolve().parents[1] / "seo-sites.json"
    try:
        entry = register(path, os.environ["CLIENT_NAME"], os.environ["CLIENT_URL"],
                         os.environ.get("CLIENT_REPO", ""), os.environ.get("CLIENT_GSC", ""),
                         os.environ.get("CLIENT_ID", ""))
    except (ValueError, KeyError) as exc:
        raise SystemExit(str(exc))
    print("Registered", entry["name"], entry["url"])


if __name__ == "__main__":
    main()
