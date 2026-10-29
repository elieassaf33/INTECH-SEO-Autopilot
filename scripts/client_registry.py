"""Validate central property identities without dropping unmapped clients."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def load_registry(path):
    sites = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(sites, list) or not sites:
        raise ValueError("Registry must be a nonempty list")
    seen = set()
    for site in sites:
        url = urlsplit(site["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.port not in (None, 443) or url.path not in ("", "/"):
            raise ValueError("Registry requires HTTPS website roots")
        prop = site.get("gsc_property")
        if prop:
            if prop in seen:
                raise ValueError("Duplicate GSC property")
            seen.add(prop)
            if prop.startswith("sc-domain:"):
                domain = prop.removeprefix("sc-domain:")
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or (url.hostname != domain and not url.hostname.endswith("." + domain)):
                    raise ValueError("Website is outside its GSC property")
            else:
                prefix = urlsplit(prop)
                if (prefix.scheme != url.scheme or prefix.netloc != url.netloc or
                        prefix.path not in ("", "/") or prefix.query or prefix.fragment):
                    raise ValueError("Website is outside its GSC URL prefix")
        repo = site.get("repository")
        if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository mapping")
        site.setdefault("client_id", url.hostname.removeprefix("www."))
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", site["client_id"]):
            raise ValueError("Invalid client identity")
    return sites
