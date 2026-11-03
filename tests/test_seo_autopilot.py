from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request
from unittest.mock import patch

import google.auth

from scripts import gsc_client, recommendations, restore_history, seo_multisite
from scripts.intech_controller import load_sites, run


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


class FakeGscSession:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url: str, *, json: dict, timeout: int) -> FakeResponse:
        self.calls.append((url, json, timeout))
        dimension = json.get("dimensions", [])
        if not dimension:
            return FakeResponse(200, {"rows": [{
                "clicks": 15, "impressions": 125, "ctr": 0.12, "position": 8.5,
            }]})
        if dimension == ["query", "page"]:
            return FakeResponse(200, {"rows": [{
                "keys": ["sample query", "https://example.test/page"],
                "clicks": 5, "impressions": 50,
                "ctr": 0.1, "position": 7.0,
            }]})
        return FakeResponse(200, {"rows": [{
            "keys": ["mobile"], "clicks": 5, "impressions": 50,
            "ctr": 0.1, "position": 7.0,
        }]})


class SeoAutopilotTests(unittest.TestCase):
    def test_registry_contains_eight_independent_sites(self) -> None:
        sites = load_sites(ROOT / "seo-sites.json")
        self.assertEqual(len(sites), 8)
        self.assertEqual(len({site["id"] for site in sites}), 8)
        self.assertEqual(
            {site["domain"] for site in sites},
            {
                "lbelectrical.uk", "alisosfotografija.lt", "jegaainis.lt",
                "klaipedosaliejus.lt", "teslaeu.eu", "cardbrostcg.com",
                "getintech.lt", "getintech.eu",
            },
        )
        self.assertTrue(all(isinstance(site["keywords"], list) for site in sites))
        self.assertEqual(
            {site["gsc_property"] for site in sites},
            {
                "sc-domain:lbelectrical.uk", "sc-domain:alisosfotografija.lt",
                "sc-domain:jegaainis.lt", "sc-domain:klaipedosaliejus.lt",
                "sc-domain:teslaeu.eu", "sc-domain:cardbrostcg.com",
                "sc-domain:getintech.lt", "sc-domain:getintech.eu",
            },
        )

    def test_registry_rejects_property_for_another_client(self) -> None:
        registry = json.loads((ROOT / "seo-sites.json").read_text(encoding="utf-8"))
        registry["sites"][0]["gsc_property"] = "sc-domain:someone-elses-site.example"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seo-sites.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "belongs to another domain"):
                load_sites(path)

    def test_gsc_fetches_adjacent_28_day_periods_and_breakdowns(self) -> None:
        session = FakeGscSession()
        client = gsc_client.SearchConsoleClient(session)
        today = dt.date(2026, 10, 29)

        result = client.collect("sc-domain:example.test", today)

        self.assertEqual(result["query_pages"]["current"][0]["query"], "sample query")
        self.assertEqual(result["query_pages"]["current"][0]["page"], "https://example.test/page")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(session.calls), 6)
        current = result["periods"]["current"]
        previous = result["periods"]["previous"]
        self.assertEqual(current["start_date"], "2026-09-28")
        self.assertEqual(current["end_date"], "2026-10-25")
        self.assertEqual(previous["start_date"], "2026-08-31")
        self.assertEqual(previous["end_date"], "2026-09-27")
        self.assertEqual(current["metrics"]["clicks"], 15)
        self.assertEqual(current["metrics"]["impressions"], 125)
        self.assertEqual(result["queries"]["current"][0]["query"], "sample query")
        self.assertEqual(result["pages"]["current"][0]["page"], "https://example.test/page")

    def test_gsc_rejects_permission_errors_explicitly(self) -> None:
        class DeniedSession:
            def post(self, *args, **kwargs):
                return FakeResponse(403, {"error": "forbidden"})

        client = gsc_client.SearchConsoleClient(DeniedSession())
        with self.assertRaisesRegex(gsc_client.SearchConsoleError, "permission denied"):
            client.collect("sc-domain:example.test", dt.date(2026, 10, 29))

    def test_gsc_surfaces_missing_application_default_credentials(self) -> None:
        error = google.auth.exceptions.DefaultCredentialsError("no test credentials")
        with patch.dict("os.environ", {"GCP_USE_ADC": "true"}), \
                patch("google.auth.default", side_effect=error):
            with self.assertRaisesRegex(
                gsc_client.SearchConsoleError, "credentials are unavailable",
            ):
                gsc_client.SearchConsoleClient.from_application_default_credentials()

    def test_gsc_paginates_full_result_pages(self) -> None:
        class PaginatedSession:
            def __init__(self) -> None:
                self.offsets = []

            def post(self, url: str, *, json: dict, timeout: int) -> FakeResponse:
                self.offsets.append(json["startRow"])
                rows = [{"keys": ["sample"], "clicks": 1, "impressions": 2,
                         "position": 3}] * 25000 if json["startRow"] == 0 else []
                return FakeResponse(200, {"rows": rows})

        session = PaginatedSession()
        client = gsc_client.SearchConsoleClient(session)
        rows = client._query(
            "sc-domain:example.test", dt.date(2026, 10, 1),
            dt.date(2026, 10, 28), ["query"],
        )
        self.assertEqual(len(rows), 25000)
        self.assertEqual(session.offsets, [0, 25000])

    def test_history_download_sends_github_api_authorization(self) -> None:
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size: int) -> bytes:
                return b"{}"

        class FakeOpener:
            def open(self, request, timeout: int):
                captured["request"] = request
                return FakeResponse()

        with patch("scripts.restore_history.build_opener", return_value=FakeOpener()):
            restore_history._api_get("https://api.github.com/repos/example/repo", "test-token")
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer test-token")

    def test_history_download_strips_authorization_on_cross_host_redirect(self) -> None:
        request = Request(
            "https://api.github.com/repos/example/repo",
            headers={"Authorization": "Bearer test-token"},
        )
        redirected = restore_history.SafeRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://artifact-storage.example/download",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_technical_crawl_respects_robots_and_reports_evidence(self) -> None:
        site = {
            "id": "test", "name": "Test", "domain": "example.test",
            "url": "https://example.test", "country": "GB",
            "languages": ["en-GB"], "business_type": "test",
        }
        html = (
            '<html><head><title>Test</title><meta name="description" content="Description">'
            '<meta name="robots" content="noindex"><meta name="viewport" content="width=device-width">'
            '<link rel="canonical" href="https://example.test/"></head>'
            '<body><h1>Test</h1><img src="/image.jpg"><a href="/broken/">Broken page</a>'
            '<script type="application/ld+json">{"@type":"Organization"}</script></body></html>'
        ).encode()
        sitemap = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://example.test/broken/</loc></url></urlset>'
        ).encode()

        def fake_fetch(url: str, **kwargs):
            if url.endswith("/robots.txt"):
                return {"status": 200, "url": url, "chain": [], "body":
                        b"User-agent: *\nDisallow: /private\nSitemap: https://example.test/sitemap.xml",
                        "error": None, "content_type": "text/plain"}
            if url.endswith("/sitemap.xml"):
                return {"status": 200, "url": url, "chain": [], "body": sitemap,
                        "error": None, "content_type": "application/xml"}
            if url.endswith("/broken/"):
                return {"status": 404, "url": url, "chain": [], "body": b"",
                        "error": "HTTP 404", "content_type": ""}
            return {"status": 200, "url": url, "chain": [], "body": html, "error": None,
                    "content_type": "text/html"}

        with patch("scripts.seo_multisite._fetch", side_effect=fake_fetch):
            result = seo_multisite.inspect(site, max_pages=10, delay_seconds=0)

        messages = [finding["message"] for finding in result["findings"]]
        self.assertTrue(any("noindex" in finding["evidence"]
                            for finding in result["findings"]))
        self.assertTrue(any("Broken internal link" in message for message in messages))
        self.assertTrue(any("alt attribute" in message for message in messages))
        self.assertEqual(result["sitemap_urls"], 1)
        self.assertTrue(result["checks"]["crawl"]["sitemap_is_not_indexing_evidence"])
        self.assertFalse(any("/private" in page["url"] for page in result["pages"]))
        self.assertEqual(
            seo_multisite._normalize_url("https://example.test/a page/"),
            "https://example.test/a%20page/",
        )

    def test_controller_isolates_failures_and_writes_reports(self) -> None:
        sites = [
            {
                "id": "first", "name": "First", "url": "https://first.test",
                "domain": "first.test", "country": "GB", "languages": ["en-GB"],
                "business_type": "services", "keywords": ["sample"],
                "gsc_property": "sc-domain:first.test", "repository": None,
            },
            {
                "id": "second", "name": "Second", "url": "https://second.test",
                "domain": "second.test", "country": "LT", "languages": ["lt-LT"],
                "business_type": "retail", "keywords": ["sample"],
                "gsc_property": "", "repository": None,
            },
        ]

        def audit(site):
            if site["id"] == "first":
                raise OSError("test outage")
            return {"findings": [], "pages_crawled": 1, "checks": {}}

        class Client:
            def collect(self, property_id):
                return {"status": "insufficient_data", "error": None}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("scripts.intech_controller.OUTPUT", root / "weekly"), \
                    patch("scripts.intech_controller.HISTORY", root / "history"):
                results = run(
                    sites, audit_fn=audit, gsc_client=Client(),
                    discovery_fn=lambda *args: {"status": "ok", "ideas": []},
                    generated_at=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc),
                )
                payload = json.loads((root / "weekly" / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(len(results), 2)
                self.assertEqual(results[0]["status"], "failed")
                self.assertEqual(results[1]["status"], "insufficient_data")
                self.assertEqual(payload["summary"]["failed"], 1)
                self.assertEqual(payload["summary"]["insufficient_data"], 1)
                self.assertTrue((root / "weekly" / "first" / "report.md").exists())
                self.assertTrue((root / "weekly" / "summary.csv").exists())
                self.assertEqual(
                    (root / "weekly" / "query-pages.csv").read_text(encoding="utf-8-sig").strip(),
                    "site_id,period,query,page,clicks,impressions,ctr,position",
                )
                self.assertTrue((root / "history" / "first.jsonl").exists())

    def test_controller_labels_missing_local_oidc_as_auth_unavailable(self) -> None:
        site = {
            "id": "local-auth", "name": "Local auth", "url": "https://local-auth.test",
            "domain": "local-auth.test", "country": "GB", "languages": ["en-GB"],
            "business_type": "services", "keywords": [],
            "gsc_property": "sc-domain:local-auth.test", "repository": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("scripts.intech_controller.OUTPUT", root / "weekly"), \
                    patch("scripts.intech_controller.HISTORY", root / "history"), \
                    patch.dict("os.environ", {"GCP_USE_ADC": "false"}):
                result = run(
                    [site],
                    audit_fn=lambda _: {"findings": [], "pages_crawled": 0, "checks": {}},
                    discovery_fn=lambda *args: {"status": "ok", "ideas": []},
                    generated_at=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc),
                )[0]
        self.assertEqual(result["gsc"]["status"], "auth_unavailable")
        self.assertEqual(result["status"], "insufficient_data")

    def test_controller_restores_weekly_metric_baseline(self) -> None:
        site = {
            "id": "history", "name": "History", "url": "https://history.test",
            "domain": "history.test", "country": "GB", "languages": ["en-GB"],
            "business_type": "services", "keywords": [],
            "gsc_property": "sc-domain:history.test", "repository": None,
        }

        class Client:
            def __init__(self) -> None:
                self.clicks = 10

            def collect(self, property_id):
                clicks = self.clicks
                self.clicks += 5
                return {
                    "status": "ok",
                    "periods": {
                        "current": {"metrics": {
                            "clicks": clicks, "impressions": 100,
                            "ctr": clicks / 100, "position": 8.0,
                        }},
                        "previous": {"metrics": {
                            "clicks": clicks - 1, "impressions": 90,
                            "ctr": (clicks - 1) / 90, "position": 9.0,
                        }},
                    },
                    "queries": {"current": [], "previous": []},
                    "pages": {"current": [], "previous": []},
                    "countries": [], "devices": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("scripts.intech_controller.OUTPUT", root / "weekly"), \
                    patch("scripts.intech_controller.HISTORY", root / "history"):
                client = Client()
                audit = lambda _: {"findings": [], "pages_crawled": 1, "checks": {}}
                first = run(
                    [site], audit_fn=audit, gsc_client=client,
                    discovery_fn=lambda *args: {"status": "ok", "ideas": []},
                    generated_at=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc),
                )[0]
                second = run(
                    [site], audit_fn=audit, gsc_client=client,
                    discovery_fn=lambda *args: {"status": "ok", "ideas": []},
                    generated_at=dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc),
                )[0]
                self.assertEqual(first["history_snapshots"], 1)
                self.assertEqual(second["history_snapshots"], 2)
                self.assertEqual(second["history_comparison"]["metrics"]["clicks"], 5)
                markdown = (root / "weekly" / "history" / "report.md").read_text(
                    encoding="utf-8")
                self.assertIn("Since prior report", markdown)

    def test_recommendations_use_observed_evidence_not_estimates(self) -> None:
        result = recommendations.recommendations(
            {"findings": []},
            {
                "status": "ok",
                "queries": {
                    "current": [
                        {"query": "declining term", "clicks": 2, "impressions": 30,
                         "ctr": 0.066, "position": 12},
                    ],
                    "previous": [
                        {"query": "declining term", "clicks": 10, "impressions": 50,
                         "ctr": 0.2, "position": 10},
                    ],
                },
                "pages": {"current": []},
            },
        )
        decline = next(item for item in result if "declining query" in item["title"])
        self.assertIn("50 to 30", decline["evidence"])
        self.assertTrue(all("search volume" not in item["evidence"].lower() for item in result))

    def test_ranking_decline_means_a_larger_position_number(self) -> None:
        for position, expected in ((12, True), (8, False)):
            with self.subTest(position=position):
                result = recommendations.recommendations({"findings": []}, {
                    "status": "ok",
                    "queries": {
                        "current": [{"query": "sample", "impressions": 50,
                                     "position": position}],
                        "previous": [{"query": "sample", "impressions": 50,
                                      "position": 10}],
                    },
                })
                self.assertEqual(any("ranking decline" in item["title"]
                                     for item in result), expected)

    def test_internal_link_uses_observed_query_page_relationship(self) -> None:
        target = "https://example.test/services"
        site = {"findings": [], "pages": [
            {"url": target},
            {"url": "https://example.test/about", "title": "Sample advice"},
        ]}
        gsc = {"status": "ok", "queries": {"current": [
            {"query": "sample", "impressions": 50, "position": 12},
        ]}, "query_pages": {"current": [
            {"query": "sample", "page": target, "impressions": 50},
        ]}}
        result = recommendations.recommendations(site, gsc)
        link = next(item for item in result if item["title"] == "Review a contextual internal link")
        self.assertEqual(link["url"], target)
        del gsc["query_pages"]
        self.assertFalse(any(item["title"] == "Review a contextual internal link"
                             for item in recommendations.recommendations(site, gsc)))

    def test_recommendations_preserve_declines_when_current_period_has_no_rows(self) -> None:
        result = recommendations.recommendations(
            {"findings": []},
            {
                "status": "insufficient_data",
                "queries": {
                    "current": [],
                    "previous": [
                        {"query": "previously visible term", "clicks": 2,
                         "impressions": 30, "ctr": 0.06, "position": 11},
                    ],
                },
                "pages": {"current": []},
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["confidence"], "medium")
        self.assertIn("not assumed", result[0]["action"])


if __name__ == "__main__":
    unittest.main()
