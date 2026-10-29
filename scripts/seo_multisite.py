#!/usr/bin/env python3
"""Read-only multi-site SEO checks. No credentials, writes or deployments."""
import datetime as dt
import json
from pathlib import Path
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITES = json.loads((ROOT / "seo-sites.json").read_text(encoding="utf-8"))
OUT = ROOT / "seo-reports" / "multisite"
OUT.mkdir(parents=True, exist_ok=True)

def fetch(url):
    req = Request(url, headers={"User-Agent": "INTECH-Multisite-SEO-Audit/1.0"})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, response.geturl(), response.read(1_500_000)
    except HTTPError as exc:
        return exc.code, exc.geturl(), b""
    except (URLError, TimeoutError, ValueError) as exc:
        return None, url, str(exc).encode()

class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = False
        self.description = False
        self.canonical = False
        self.h1 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.title = True
        elif tag == "h1":
            self.h1 = True
        elif tag == "meta" and (attrs.get("name") or "").lower() == "description":
            self.description = True
        elif tag == "link" and "canonical" in (attrs.get("rel") or "").lower().split():
            self.canonical = True


def inspect(site):
    base = site["url"].rstrip("/") + "/"
    result = {"name": site["name"], "base_url": base, "checks": {}, "findings": []}
    for name, path in [("homepage", ""), ("robots", "robots.txt"), ("sitemap", "sitemap.xml")]:
        url = urljoin(base, path)
        status, final, body = fetch(url)
        result["checks"][name] = {"status": status, "final_url": final}
        if status != 200:
            result["findings"].append({"severity": "high" if name == "homepage" else "medium", "message": f"{name} returned {status}", "url": url})
        if name == "homepage" and status == 200:
            parser = MetadataParser()
            parser.feed(body.decode("utf-8", "replace"))
            for label, present in [("title", parser.title), ("meta description", parser.description), ("canonical", parser.canonical), ("h1", parser.h1)]:
                if not present:
                    result["findings"].append({"severity": "medium", "message": f"Homepage missing {label}", "url": final})
        if name == "sitemap" and status == 200:
            try:
                root = ET.fromstring(body)
                urls = [e.text.strip() for e in root.iter() if (e.tag.endswith("}loc") or e.tag == "loc") and e.text]
                result["checks"]["sitemap"]["urls"] = len(urls)
                # Compare to the actual sitemap host after HTTP redirects, not the configured alias.
                host = urlsplit(final).hostname
                for link in urls:
                    if urlsplit(link).hostname != host:
                        result["findings"].append({"severity": "medium", "message": "Sitemap contains off-host URL", "url": link})
            except ET.ParseError:
                result["findings"].append({"severity": "high", "message": "Invalid sitemap XML", "url": final})
    return result

def main():
    results = [inspect(site) for site in SITES]
    payload = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "sites": results}
    (OUT / "audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# INTECH multi-site SEO audit", "", f"Sites checked: {len(results)}", ""]
    for item in results:
        lines.extend([f"## {item['name']}", f"URL: {item['base_url']}", f"Findings: {len(item['findings'])}"])
        lines.extend(f"- [{x['severity']}] {x['message']}: {x['url']}" for x in item["findings"])
        lines.append("")
    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
