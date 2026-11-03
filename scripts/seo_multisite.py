#!/usr/bin/env python3
"""Polite, bounded, read-only technical SEO crawl for one configured website."""
from __future__ import annotations

import json
import http.client
import time
import urllib.error
import urllib.parse
import urllib.robotparser
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any


USER_AGENT = "INTECH-SEO-Autopilot/1.0 (+https://getintech.eu)"
MAX_RESPONSE_BYTES = 2_000_000
MAX_SITEMAP_BYTES = 5_000_000
MAX_SITEMAP_DOCUMENTS = 5
MAX_SITEMAP_URLS = 5_000


class RedirectTracker(urllib.request.HTTPRedirectHandler):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.chain: list[str] = []
        self.base_url = base_url

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Any:
        if not _same_site(newurl, self.base_url):
            raise urllib.error.HTTPError(
                req.full_url, 310, "Redirect outside the configured website", headers, fp)
        self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.title_depth = 0
        self.title_count = 0
        self.description: list[str] = []
        self.canonicals: list[str] = []
        self.robots: list[str] = []
        self.headings: dict[str, list[str]] = {f"h{n}": [] for n in range(1, 7)}
        self.heading_stack: list[tuple[str, list[str]]] = []
        self.images_without_alt = 0
        self.images = 0
        self.links: list[tuple[str, str]] = []
        self.json_ld: list[str] = []
        self.json_ld_depth = 0
        self.viewport = False
        self._active_anchor: list[str] | None = None
        self._anchor_href = ""
        self._jsonld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self.title_depth += 1
            self.title_count += 1
        elif tag in self.headings:
            parts: list[str] = []
            self.headings[tag].append("")
            self.heading_stack.append((tag, parts))
        elif tag == "meta":
            name = (attributes.get("name") or "").strip().lower()
            content = (attributes.get("content") or "").strip()
            if name == "description":
                self.description.append(content)
            elif name == "robots" or name.startswith("googlebot"):
                self.robots.append(content.lower())
            elif name == "viewport":
                self.viewport = bool(content)
        elif tag == "link" and "canonical" in (attributes.get("rel") or "").lower().split():
            self.canonicals.append((attributes.get("href") or "").strip())
        elif tag == "img":
            self.images += 1
            if "alt" not in attributes:
                self.images_without_alt += 1
        elif tag == "a":
            self._active_anchor = []
            self._anchor_href = (attributes.get("href") or "").strip()
        elif tag == "script" and (attributes.get("type") or "").lower() == "application/ld+json":
            self.json_ld_depth += 1
            self._jsonld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        elif tag in self.headings and self.heading_stack:
            heading_tag, parts = self.heading_stack.pop()
            value = " ".join("".join(parts).split())
            if self.headings[heading_tag]:
                self.headings[heading_tag][-1] = value
        elif tag == "a" and self._active_anchor is not None:
            text = " ".join("".join(self._active_anchor).split())
            if self._anchor_href:
                self.links.append((self._anchor_href, text))
            self._active_anchor = None
            self._anchor_href = ""
        elif tag == "script" and self.json_ld_depth:
            self.json_ld_depth -= 1
            value = "".join(self._jsonld_parts).strip()
            if value:
                self.json_ld.append(value)

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_parts.append(data)
        for _, parts in self.heading_stack:
            parts.append(data)
        if self._active_anchor is not None:
            self._active_anchor.append(data)
        if self.json_ld_depth:
            self._jsonld_parts.append(data)


def _fetch(url: str, *, max_bytes: int = MAX_RESPONSE_BYTES,
           timeout: float = 15) -> dict[str, Any]:
    tracker = RedirectTracker(url)
    opener = urllib.request.build_opener(tracker)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                return {"status": response.status, "url": response.geturl(),
                        "chain": tracker.chain, "body": b"",
                        "error": f"Response exceeded {max_bytes} bytes"}
            return {"status": response.status, "url": response.geturl(),
                    "chain": tracker.chain, "body": body, "error": None,
                    "content_type": response.headers.get_content_type()}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "url": exc.geturl(), "chain": tracker.chain,
                "body": b"", "error": f"HTTP {exc.code}", "content_type": ""}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError,
            http.client.HTTPException) as exc:
        return {"status": None, "url": url, "chain": tracker.chain,
                "body": b"", "error": f"{type(exc).__name__}: {exc}"[:300],
                "content_type": ""}


def _finding(severity: str, evidence: str, message: str, url: str,
             *, confidence: str = "confirmed") -> dict[str, str]:
    return {"severity": severity, "confidence": confidence, "evidence": evidence,
            "message": message, "url": url}


def _same_site(url: str, base: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        origin = urllib.parse.urlsplit(base)
    except ValueError:
        return False
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password):
        return False
    expected = (origin.hostname or "").lower().removeprefix("www.")
    actual = parsed.hostname.lower().removeprefix("www.")
    expected_port = origin.port or (443 if origin.scheme == "https" else 80)
    actual_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return actual == expected and actual_port == expected_port


def _normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="=&/?@:!$'()*+,;%-._~")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def _is_email_protection_url(url: str) -> bool:
    return urllib.parse.urlsplit(url).path.startswith("/cdn-cgi/l/email-protection")


def _parse_sitemap(body: bytes, source_url: str, base: str,
                   findings: list[dict[str, str]], depth: int = 0,
                   budget: list[int] | None = None) -> list[str]:
    budget = budget if budget is not None else [MAX_SITEMAP_DOCUMENTS, MAX_SITEMAP_URLS]
    if depth > 2:
        findings.append(_finding("low", "sitemap depth limit", "Sitemap index nesting exceeds the crawl limit",
                                 source_url, confidence="potential"))
        return []
    budget[0] -= 1
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        findings.append(_finding("high", str(exc), "Sitemap XML is invalid", source_url))
        return []
    tag = root.tag.rsplit("}", 1)[-1].lower()
    locations = [element.text.strip() for element in root.iter()
                 if element.tag.rsplit("}", 1)[-1].lower() == "loc" and element.text]
    pages: list[str] = []
    for location in locations:
        if budget[1] <= 0:
            break
        budget[1] -= 1
        try:
            absolute = _normalize_url(urllib.parse.urljoin(source_url, location))
        except ValueError as exc:
            findings.append(_finding("medium", f"invalid sitemap URL: {exc}",
                                     "Sitemap contains a malformed URL", source_url))
            continue
        if not _same_site(absolute, base):
            findings.append(_finding("medium", "off-site sitemap location",
                                     "Sitemap references a URL outside the configured website", absolute))
            continue
        if tag == "sitemapindex":
            if budget[0] <= 0:
                findings.append(_finding(
                    "low", "sitemap document limit reached",
                    "Additional nested sitemaps were not fetched due to the audit limit",
                    absolute, confidence="potential"))
                break
            child = _fetch(absolute, max_bytes=MAX_SITEMAP_BYTES)
            if child["status"] == 200:
                pages.extend(_parse_sitemap(
                    child["body"], child["url"], base, findings, depth + 1, budget))
            else:
                findings.append(_finding("medium", child["error"] or f"HTTP {child['status']}",
                                         "Nested sitemap could not be fetched", absolute))
        else:
            pages.append(absolute)
    return pages


def inspect(site: dict[str, Any], *, max_pages: int = 50,
            delay_seconds: float = 0.2) -> dict[str, Any]:
    """Inspect a bounded sample of same-site URLs; sitemap presence is not indexing evidence."""
    base = site["url"].rstrip("/") + "/"
    findings: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "id": site["id"], "name": site["name"], "domain": site["domain"],
        "base_url": base, "country": site["country"], "languages": site["languages"],
        "business_type": site["business_type"], "checks": {}, "pages_crawled": 0,
        "findings": findings, "sitemap_urls": 0,
    }

    robots_url = urllib.parse.urljoin(base, "robots.txt")
    robots_response = _fetch(robots_url)
    result["checks"]["robots"] = {
        "status": robots_response["status"], "url": robots_response["url"],
        "error": robots_response["error"],
    }
    if robots_response["status"] != 200:
        findings.append(_finding("medium", robots_response["error"] or
                                 f"HTTP {robots_response['status']}",
                                 "robots.txt was unavailable", robots_url,
                                 confidence="potential" if robots_response["status"] is None else "confirmed"))

    parser_robots = urllib.robotparser.RobotFileParser()
    parser_robots.set_url(robots_url)
    robots_sitemaps: list[str] = []
    if robots_response["status"] == 200:
        robot_text = robots_response["body"].decode("utf-8", "replace")
        parser_robots.parse(robot_text.splitlines())
        robots_sitemaps = [line.split(":", 1)[1].strip()
                           for line in robot_text.splitlines()
                           if line.lower().startswith("sitemap:") and ":" in line]

    sitemap_candidates = (robots_sitemaps or [
        urllib.parse.urljoin(base, "sitemap.xml"),
        urllib.parse.urljoin(base, "sitemap_index.xml"),
    ])[:10]
    sitemap_pages: list[str] = []
    sitemap_urls_checked: set[str] = set()
    for candidate in dict.fromkeys(sitemap_candidates):
        if not _same_site(candidate, base):
            findings.append(_finding("medium", "off-site Sitemap directive in robots.txt",
                                     "Sitemap directive points outside the configured website",
                                     candidate, confidence="potential"))
            continue
        response = _fetch(candidate, max_bytes=MAX_SITEMAP_BYTES)
        sitemap_urls_checked.add(candidate)
        if response["status"] == 200:
            sitemap_pages.extend(_parse_sitemap(
                response["body"], response["url"], base, findings))
            break
    else:
        findings.append(_finding("medium", "No configured sitemap URL returned HTTP 200",
                                 "A public XML sitemap could not be confirmed", sitemap_candidates[0],
                                 confidence="potential"))

    pages: dict[str, dict[str, Any]] = {}
    queue = [base]
    queue.extend(sitemap_pages)
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        normalized = _normalize_url(urllib.parse.urldefrag(url)[0])
        if normalized in pages or not _same_site(normalized, base):
            continue
        if robots_response["status"] == 200 and not parser_robots.can_fetch(USER_AGENT, normalized):
            continue
        if delay_seconds and pages:
            time.sleep(delay_seconds)
        response = _fetch(normalized)
        page_record: dict[str, Any] = {
            "url": normalized, "status": response["status"], "final_url": response["url"],
            "redirect_chain": [normalized, *response["chain"]] if response["chain"] else [],
            "error": response["error"],
        }
        pages[normalized] = page_record
        if len(response["chain"]) > 1:
            findings.append(_finding(
                "low", "redirect chain: " + " -> ".join(response["chain"]),
                "URL passes through multiple redirects before its final destination",
                normalized, confidence="confirmed"))
        if response["status"] != 200:
            if normalized == base or normalized in sitemap_pages:
                findings.append(_finding(
                    "high" if normalized == base else "medium",
                    response["error"] or f"HTTP {response['status']}",
                    "Homepage or sitemap URL returned an unsuccessful response",
                    normalized,
                    confidence="potential" if response["status"] is None else "confirmed"))
            continue
        if response.get("content_type") not in ("text/html", "application/xhtml+xml"):
            page_record["content_type"] = response.get("content_type", "")
            continue
        page_parser = PageParser()
        try:
            page_parser.feed(response["body"].decode("utf-8", "replace"))
        except (ValueError, AssertionError) as exc:
            findings.append(_finding("low", f"HTML parse error: {exc}",
                                     "Page markup could not be fully analyzed", normalized,
                                     confidence="potential"))
            continue
        title = " ".join("".join(page_parser.title_parts).split())
        descriptions = [item for item in page_parser.description if item]
        canonicals = page_parser.canonicals
        headings = {key: [item for item in value if item]
                    for key, value in page_parser.headings.items()}
        robots_meta = page_parser.robots
        page_record.update({
            "title": title, "description": descriptions[0] if descriptions else "",
            "canonical": canonicals[0] if canonicals else "",
            "title_elements": page_parser.title_count,
            "h1": headings["h1"], "headings": headings,
            "robots_meta": robots_meta, "images": page_parser.images,
            "images_without_alt": page_parser.images_without_alt,
            "json_ld": [], "viewport": page_parser.viewport,
        })
        if not title:
            findings.append(_finding("medium", "no non-empty <title> element",
                                     "Page is missing a title", normalized))
        elif page_parser.title_count > 1:
            findings.append(_finding("medium", f"{page_parser.title_count} title elements",
                                     "Page has duplicate title elements", normalized))
        elif len(title) > 60:
            findings.append(_finding("low", f"title is {len(title)} characters",
                                     "Page title is longer than 60 characters; review for truncation",
                                     normalized, confidence="potential"))
        if len(descriptions) > 1:
            findings.append(_finding("medium", f"{len(descriptions)} meta descriptions",
                                     "Page has duplicate meta description elements", normalized))
        elif not descriptions:
            findings.append(_finding("medium", "no non-empty meta description",
                                     "Page is missing a meta description", normalized))
        elif len(descriptions[0]) > 160:
            findings.append(_finding("low", f"description is {len(descriptions[0])} characters",
                                     "Meta description is longer than 160 characters; review for truncation",
                                     normalized, confidence="potential"))
        if len(canonicals) > 1:
            findings.append(_finding("high", f"{len(canonicals)} canonical link elements",
                                     "Page declares multiple canonical URLs", normalized))
        elif not canonicals:
            findings.append(_finding("medium", "no canonical link element",
                                     "Page has no explicit canonical URL", normalized))
        else:
            canonical_url = _normalize_url(
                urllib.parse.urljoin(response["url"], canonicals[0]))
            if not _same_site(canonical_url, base):
                findings.append(_finding("high", "canonical points off the configured site",
                                         "Canonical URL points outside the configured website",
                                         canonical_url))
            page_record["canonical"] = canonical_url
        if len(headings["h1"]) == 0:
            findings.append(_finding("medium", "no H1 heading",
                                     "Page has no H1 heading", normalized))
        elif len(headings["h1"]) > 1:
            findings.append(_finding("low", f"{len(headings['h1'])} H1 headings",
                                     "Page has multiple H1 headings; review the page outline",
                                     normalized, confidence="potential"))
        if page_parser.images_without_alt:
            findings.append(_finding(
                "medium", f"{page_parser.images_without_alt} of {page_parser.images} images lack an alt attribute",
                "Images are missing alt text; decorative images may use an empty alt attribute",
                normalized))
        if any("noindex" in directive for directive in robots_meta):
            findings.append(_finding("high", "robots meta contains noindex",
                                     "Page explicitly requests exclusion from search indexing",
                                     normalized))
        if not page_parser.viewport:
            findings.append(_finding("low", "no viewport meta tag",
                                     "Mobile viewport declaration was not found",
                                     normalized, confidence="potential"))
        valid_json_ld = []
        for block in page_parser.json_ld:
            try:
                decoded = json.loads(block)
                if isinstance(decoded, (dict, list)):
                    valid_json_ld.append(decoded)
                else:
                    raise ValueError("JSON-LD root must be an object or array")
            except (json.JSONDecodeError, ValueError) as exc:
                findings.append(_finding("medium", f"invalid JSON-LD: {exc}",
                                         "Structured data block is not valid JSON",
                                         normalized))
        page_record["json_ld"] = valid_json_ld
        internal_links = []
        for href, text in page_parser.links:
            try:
                absolute = _normalize_url(urllib.parse.urljoin(response["url"], href))
            except ValueError as exc:
                findings.append(_finding("low", f"malformed internal-link URL: {exc}",
                                         "Link target could not be parsed", normalized,
                                         confidence="potential"))
                continue
            if _same_site(absolute, base) and not _is_email_protection_url(absolute):
                internal_links.append({"url": absolute, "text": text})
                if absolute not in pages and absolute not in queue:
                    queue.append(absolute)
        page_record["_links"] = internal_links

    for field in ("title", "description", "canonical"):
        seen: dict[str, list[str]] = {}
        seen_final_urls: set[str] = set()
        for page in pages.values():
            identity = page.get("final_url") or page["url"]
            if identity in seen_final_urls:
                continue
            seen_final_urls.add(identity)
            value = str(page.get(field) or "").strip().casefold()
            if value:
                seen.setdefault(value, []).append(identity)
        for duplicate_urls in seen.values():
            if len(duplicate_urls) > 1:
                findings.append(_finding(
                    "medium", f"duplicate {field} across {len(duplicate_urls)} crawled pages",
                    f"Multiple pages share the same {field}", duplicate_urls[0],
                    confidence="potential"))

    known_urls = set(pages)
    inbound_links: dict[str, int] = {}
    checked_broken_links: set[tuple[str, str]] = set()
    for source in pages.values():
        source_links = source.pop("_links", [])
        source["internal_links"] = sorted({link["url"] for link in source_links})
        for destination in source["internal_links"]:
            destination = urllib.parse.urldefrag(destination)[0]
            inbound_links[destination] = inbound_links.get(destination, 0) + 1
            if destination not in known_urls:
                continue
            target = pages[destination]
            broken_link = (source["url"], destination)
            if (broken_link not in checked_broken_links
                    and target["status"] is not None and target["status"] >= 400):
                checked_broken_links.add(broken_link)
                findings.append(_finding(
                    "medium", f"linked from {source['url']}; HTTP {target['status']}",
                    "Broken internal link points to an unsuccessful URL",
                    destination))
    for page in pages.values():
        page["inbound_internal_links"] = inbound_links.get(page["url"], 0)
    result["pages_crawled"] = len(pages)
    result["sitemap_urls"] = len(sitemap_pages)
    result["checks"]["crawl"] = {
        "max_pages": max_pages, "pages_crawled": len(pages),
        "robots_respected": robots_response["status"] == 200,
        "sitemap_checked": sorted(sitemap_urls_checked),
        "sitemap_url_count": len(sitemap_pages),
        "sitemap_is_not_indexing_evidence": True,
    }
    result["pages"] = list(pages.values())
    return result
