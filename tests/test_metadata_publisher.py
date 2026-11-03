import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts.metadata_publisher import patch_metadata, publish

ROOT = Path(__file__).resolve().parents[1]
TARGET = json.loads((ROOT / "seo-publishing.json").read_text())["targets"]["lb-electrical"]


def source():
    return ("# Preserve this comment and all visible copy\n"
            "def site_metadata(request):\n"
            "    title = 'Reviews' if request else " + repr(TARGET["baseline"]["title"]) + "\n"
            "    description = 'Review description' if request else " + repr(TARGET["baseline"]["description"]) + "\n"
            "    body = 'Visible page text stays unchanged'\n"
            "    return title, description, body\n")


class FakeClient:
    token = "test-token"

    def __init__(self, text=None):
        self.text = source() if text is None else text
        self.writes = []

    def read(self, *args):
        return self.text, "source-blob-sha"

    def write(self, *args):
        self.writes.append(args)
        self.text = args[3]
        return "commit-sha"


class MetadataPublishingTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc)
        self.registry = {"sites": [{"id": "lb-electrical", "repository": TARGET["repository"]},
                                    {"id": "unconnected", "repository": None}]}
        self.reports = {"generated_at": self.now.isoformat(), "sites": [{
            "id": "lb-electrical", "technical_status": "success", "keyword_discovery": {
                "ideas": [{"keyword": "electrical testing and inspection", "sources": ["google_autocomplete"]}]}}]}
        self.policy = {"targets": {"lb-electrical": copy.deepcopy(TARGET)}}
        self.client = FakeClient()

    def run_publish(self, **kwargs):
        return publish(self.registry, self.reports, self.policy, client=self.client, now=self.now, **kwargs)

    def test_changes_only_metadata_and_is_idempotent(self):
        updated = patch_metadata(source(), TARGET, TARGET["variants"][0])
        self.assertIn("body = 'Visible page text stays unchanged'", updated)
        self.assertIn("# Preserve this comment", updated)
        self.assertIn("'Reviews' if request", updated)
        self.assertEqual(patch_metadata(updated, TARGET, TARGET["variants"][0]), updated)

    def test_utf8_offsets_preserve_non_ascii_text(self):
        original = source().replace("    title =", "    label = 'Lietuvi\u0161ka'; title =")
        updated = patch_metadata(original, TARGET, TARGET["variants"][0])
        self.assertIn("label = 'Lietuvi\u0161ka'", updated)
        self.assertIn(repr(TARGET["variants"][0]["title"]), updated)
        self.assertIn("body = 'Visible page text stays unchanged'", updated)

    def test_refuses_unexpected_source_drift(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            patch_metadata(source().replace(TARGET["baseline"]["title"], "Unexpected edited title"), TARGET, TARGET["variants"][0])

    def test_refuses_overlong_and_markup_copy(self):
        for value in ('x' * 71, '<script>bad</script>'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                patch_metadata(source(), TARGET, {**TARGET["variants"][0], "title": value})

    def test_preview_never_writes(self):
        result = self.run_publish()
        self.assertEqual(result[0]["status"], "preview")
        self.assertIn("diff", result[0])
        self.assertEqual(result[1]["status"], "not_configured")
        self.assertFalse(self.client.writes)

    def test_blocks_unverified_deployment(self):
        self.assertEqual(self.run_publish(apply=True)[0]["status"], "blocked")
        self.assertFalse(self.client.writes)

    def test_publishes_with_sha_precondition_and_does_not_claim_live(self):
        self.policy["targets"]["lb-electrical"]["deployment_on_push_verified"] = True
        result = self.run_publish(apply=True)[0]
        self.assertEqual(result["status"], "committed_pending_deployment")
        self.assertFalse(result["live_verified"])
        self.assertEqual(self.client.writes[0][-1], "source-blob-sha")
        self.assertEqual(self.run_publish(apply=True)[0]["status"], "unchanged")
        self.assertEqual(len(self.client.writes), 1)

    def test_requires_token(self):
        self.client.token = ""
        self.policy["targets"]["lb-electrical"]["deployment_on_push_verified"] = True
        self.assertEqual(self.run_publish(apply=True)[0]["status"], "blocked")
        self.assertFalse(self.client.writes)

    def test_heading_ideas_do_not_trigger_publishing(self):
        self.reports["sites"][0]["keyword_discovery"]["ideas"][0]["sources"] = ["site_heading"]
        self.assertEqual(self.run_publish()[0]["status"], "no_matching_keyword")

    def test_blocks_mismatched_repository_and_isolates_error(self):
        self.policy["targets"]["lb-electrical"]["repository"] = "other/client"
        result = self.run_publish(apply=True)
        self.assertEqual(result[0]["status"], "error")
        self.assertEqual(result[1]["status"], "not_configured")
        self.assertFalse(self.client.writes)

    def test_rejects_stale_report(self):
        self.reports["generated_at"] = "2026-10-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "eight days"):
            self.run_publish(apply=True)

    def test_conflict_is_not_retried(self):
        self.policy["targets"]["lb-electrical"]["deployment_on_push_verified"] = True
        def fail(*args):
            self.client.writes.append(args)
            raise RuntimeError("GitHub PUT returned HTTP 409")
        self.client.write = fail
        self.assertEqual(self.run_publish(apply=True)[0]["status"], "error")
        self.assertEqual(len(self.client.writes), 1)
