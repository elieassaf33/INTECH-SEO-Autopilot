import unittest
import csv
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts.intech_controller import _write_shared_reports
from scripts.keyword_discovery import discover


class KeywordDiscoveryTests(unittest.TestCase):
    def test_deduplicates_and_distinguishes_observed_queries(self):
        result = discover(
            {"keywords": ["electrician"], "languages": ["en-GB"], "country": "GB"},
            {"pages": [{"url": "https://example.test/", "headings": {
                "h1": ["Emergency electrician", "Electrical safety checks"]}}]},
            {"queries": {"current": [{"query": "emergency electrician"}]}},
            fetch=lambda *args: ["electrician", "emergency electrician", "Emergency electrician", "irrelevant stuff"],
        )
        self.assertEqual(len(result["ideas"]), 2)
        row = next(row for row in result["ideas"] if row["already_observed"])
        self.assertEqual(row["sources"], ["google_autocomplete", "site_heading"])
        self.assertIsNone(row["search_volume"])

    def test_failure_keeps_content_ideas_and_reports_partial(self):
        def fail(*args):
            raise TimeoutError("test outage")
        result = discover(
            {"keywords": ["electrician"], "languages": ["en"], "country": "GB"},
            {"pages": [{"headings": {"h1": ["Safety inspections"]}}]}, {}, fetch=fail,
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["ideas"][0]["sources"], ["site_heading"])

    def test_no_seeds_or_content_is_explicit(self):
        self.assertEqual(discover({"keywords": []}, {}, {})["status"], "no_seeds")

    def test_keyword_csv_preserves_sources_and_unknown_volume(self):
        idea = {"keyword": "electrician near me", "sources": ["google_autocomplete"],
                "seed": "electrician", "page": "", "already_observed": False,
                "search_volume": None}
        report = {"id": "test", "name": "Test", "domain": "example.test",
                  "country": "GB", "languages": ["en"], "business_type": "services",
                  "status": "insufficient_data", "technical_status": "success",
                  "gsc": {"status": "auth_unavailable"},
                  "keyword_discovery": {"ideas": [idea]}}
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.intech_controller.OUTPUT", Path(directory)):
                _write_shared_reports([report])
            with (Path(directory) / "keyword-ideas.csv").open(encoding="utf-8-sig", newline="") as file:
                row = next(csv.DictReader(file))
        self.assertEqual(row["keyword"], "electrician near me")
        self.assertEqual(row["search_volume"], "")
        self.assertEqual(row["sources"], "google_autocomplete")
