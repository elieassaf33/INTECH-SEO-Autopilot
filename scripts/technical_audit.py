"""Bounded public-page checks. Findings carry evidence, never production edits."""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser
from requests.utils import parse_header_links
import xml.etree.ElementTree as ET

LIMIT = 1_500_000


def public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.port not in (None, 80, 443):
        raise ValueError("Unsafe URL")
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Non-public address")


class Redirects(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if len(self.chain) >= 5:
            raise ValueError("Redirect limit reached")
        public_url(newurl)
        if urlsplit(newurl).hostname not in self.hosts:
            raise ValueError("Redirect to unapproved host; manual review required")
        self.chain.append({"from": req.full_url, "to": newurl, "status": code})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, hosts):
    redirects = Redirects(hosts)
    try:
        public_url(url)
        if urlsplit(url).hostname not in hosts:
            raise ValueError("Unapproved host")
        req = Request(url, headers={"User-Agent": "INTECH-SEO-Monitor/2.0"})
        with build_opener(redirects).open(req, timeout=15) as response:
            body = response.read(LIMIT + 1)
            return {"status": response.status, "final_url": response.url, "redirects": redirects.chain,
                    "content_type": response.headers.get("Content-Type", ""),
                    "x_robots_tag": response.headers.get("X-Robots-Tag", ""),
                    "link_header": ", ".join(response.headers.get_all("Link", [])),
                    "truncated": len(body) > LIMIT, "body": body[:LIMIT]}
    except HTTPError as exc:
        return {"status": exc.code, "final_url": exc.url, "redirects": redirects.chain, "body": b""}
    except (URLError, TimeoutError, OSError, ValueError):
        return {"status": None, "final_url": url, "redirects": redirects.chain,
                "error": "fetch_failed_or_redirect_requires_review", "body": b""}


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.in_title = False
        self.description = ""
        self.canonicals = []
        self.links = []
        self.robots = ""
        self.h1 = False
        self.in_body = False
        self.head_closed = False

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        if tag == "body":
            self.in_body = True
            self.in_title = False
        if tag == "title" and not self.in_body and not self.head_closed:
            self.in_title = True
        if tag == "h1":
            self.h1 = True
        if tag == "meta" and not self.in_body and not self.head_closed:
            name = attrs.get("name", "").lower()
            if name == "description":
                self.description = attrs.get("content", "").strip()
            if name in ("robots", "googlebot"):
                self.robots += "," + attrs.get("content", "").lower()
        if tag == "link" and not self.in_body and not self.head_closed and "canonical" in attrs.get("rel", "").lower().split():
            self.canonicals.append(attrs.get("href", "").strip())
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "head":
            self.head_closed = True
            self.in_title = False
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def header_canonicals(value):
    """HTTP canonical declarations are as relevant as HTML declarations."""
    return [link["url"].strip() for link in parse_header_links(value)
            if "canonical" in link.get("rel", "").lower().split() and link.get("url", "").strip()]


def inspect(site):
    base = site["url"].rstrip("/") + "/"
    host = urlsplit(base).hostname.removeprefix("www.")
    hosts = {host, "www." + host}
    # Only explicit, registry-reviewed aliases can be followed. Shared client ID is not an alias policy.
    hosts.update(site.get("allowed_redirect_hosts", []))
    result = {"name": site["name"], "base_url": base, "status": "ok", "checks": {}, "findings": []}

    def finding(code, message, url, severity="medium", **evidence):
        result["findings"].append({"code": code, "severity": severity, "message": message,
                                   "url": url, "evidence": evidence, "requires_review": True})

    home = fetch(base, hosts)
    result["checks"]["homepage"] = {k: v for k, v in home.items() if k != "body"}
    final = home["final_url"]
    if home["status"] != 200:
        result["status"] = "partial"
        finding("homepage_unavailable", "Homepage fetch failed; do not infer missing SEO tags", final, "high", status=home["status"])
    robots_url = urljoin(final, "/robots.txt")
    robots = fetch(robots_url, hosts)
    if robots["status"] is None or robots["status"] in (401, 403, 429) or (robots["status"] or 0) >= 500:
        result["status"] = "partial"
    result["checks"]["robots"] = {k: v for k, v in robots.items() if k != "body"}
    robot = None
    sitemap_urls = []
    if robots["status"] == 200 and not robots.get("truncated"):
        text = robots["body"].decode("utf-8", "replace")
        if "<html" in text.lower() or "<!doctype html" in text.lower():
            finding("robots_invalid", "robots.txt returned HTML", robots_url)
        else:
            robot = RobotFileParser()
            robot.parse(text.splitlines())
            sitemap_urls = robot.site_maps() or []
            if not robot.can_fetch("Googlebot", final):
                finding("robots_blocks_homepage", "robots.txt disallows Googlebot at the final homepage", final, "high")
    elif robots.get("truncated"):
        result["status"] = "partial"
        result["checks"]["robots"]["note"] = "Body limit reached; robots rules were not evaluated"
    elif robots["status"] not in (404, 410):
        finding("robots_unavailable", "robots.txt unavailable; crawler behavior requires review", robots_url, status=robots["status"])
    else:
        result["checks"]["robots"]["note"] = "Absent robots.txt is allowed; not evidence of blocked indexing"

    sitemap_url = next((u for u in sitemap_urls if urlsplit(u).hostname in hosts and urlsplit(u).scheme == "https"), urljoin(final, "/sitemap.xml"))
    sitemap = fetch(sitemap_url, hosts)
    if sitemap["status"] is None or sitemap["status"] in (401, 403, 429) or (sitemap["status"] or 0) >= 500:
        result["status"] = "partial"
    result["checks"]["sitemap"] = {k: v for k, v in sitemap.items() if k != "body"}
    page_urls = []
    if sitemap["status"] == 200 and not sitemap.get("truncated"):
        try:
            root = ET.fromstring(sitemap["body"])
            kind = root.tag.rsplit("}", 1)[-1]
            if kind not in ("urlset", "sitemapindex"):
                raise ET.ParseError("Unexpected sitemap root")
            urls = [e.text.strip() for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "loc" and e.text]
            result["checks"]["sitemap"].update({"kind": kind, "url_count": len(urls)})
            foreign = [u for u in urls if urlsplit(u).hostname not in hosts]
            if foreign:
                finding("sitemap_foreign_urls", "Sitemap references another host; verify ownership and canonical policy", sitemap_url, examples=foreign[:5])
            if kind == "urlset":
                page_urls = [u for u in urls if urlsplit(u).hostname in hosts]
        except ET.ParseError:
            finding("sitemap_invalid", "Sitemap is not valid sitemap XML", sitemap_url)
    elif sitemap.get("truncated"):
        result["status"] = "partial"
        result["checks"]["sitemap"]["note"] = "Body limit reached; no XML validity verdict"
    else:
        finding("sitemap_unavailable", "Sitemap discovery failed; a sitemap is recommended, not required for indexing", sitemap_url, status=sitemap["status"])

    if home["status"] == 200 and not home.get("truncated"):
        if "html" not in home.get("content_type", "").lower():
            result["status"] = "partial"
            finding("homepage_not_html", "Homepage did not return HTML; metadata checks skipped", final)
            return result
        parser = MetadataParser()
        parser.feed(home["body"].decode("utf-8", "replace"))
        http_canonicals = header_canonicals(home.get("link_header", ""))
        canonicals = parser.canonicals + http_canonicals
        result["checks"]["metadata"] = {"title": parser.title.strip(), "description": parser.description,
                                          "canonicals": canonicals, "html_canonicals": parser.canonicals,
                                          "http_canonicals": http_canonicals, "h1": parser.h1}
        for code, present in (("missing_title", parser.title.strip()), ("missing_description", parser.description),
                              ("missing_canonical", any(canonicals))):
            if not present:
                message = ("No canonical declared in fetched HTML or HTTP Link headers" if code == "missing_canonical" else
                           code.replace("_", " ").capitalize() + " in fetched HTML (rendered JavaScript not evaluated)")
                finding(code, message, final)
        targets = {urljoin(final, c) for c in canonicals if c}
        if len(targets) > 1:
            finding("multiple_canonicals", "Conflicting HTML or HTTP canonical targets require review", final)
        for canonical in canonicals:
            resolved = urljoin(final, canonical)
            parts = urlsplit(resolved)
            if parts.scheme not in ("http", "https") or parts.hostname not in hosts or parts.fragment or parts.username or parts.password:
                finding("canonical_review", "Canonical has an unapproved host, fragment, credentials or invalid scheme", final, canonical=canonical)
        if "noindex" in parser.robots or "noindex" in home.get("x_robots_tag", "").lower():
            finding("noindex_review", "Homepage declares noindex; confirm whether intentional", final, "high")
        internal = sorted({urljoin(final, u).split("#")[0] for u in parser.links
                           if urlsplit(urljoin(final, u)).hostname == urlsplit(final).hostname
                           and urlsplit(urljoin(final, u)).scheme == "https"})
        result["checks"]["internal_links"] = {"count": len(internal), "sample": internal[:20],
                                                "note": "Homepage link discovery only; not an orphan-page verdict"}
        candidates = [u for u in page_urls if u.rstrip("/") != final.rstrip("/") and u not in internal]
        if candidates:
            finding("internal_link_opportunity", "Sitemap pages not directly linked from homepage; consider relevant internal links", final, examples=candidates[:5])
    elif home.get("truncated"):
        result["status"] = "partial"
        result["checks"]["homepage"]["note"] = "Body limit reached; metadata verdict skipped"
    return result
