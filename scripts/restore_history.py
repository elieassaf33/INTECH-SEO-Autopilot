#!/usr/bin/env python3
"""Restore the latest successful weekly history artifact without unsafe ZIP extraction."""
from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "seo-reports" / "history"
LOGGER = logging.getLogger("intech_seo.history")
MAX_ARCHIVE_BYTES = 50_000_000
MAX_RECORDS_PER_FILE = 104
MAX_HISTORY_FILE_BYTES = 20_000_000


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        if urlparse(req.full_url).hostname != urlparse(newurl).hostname:
            redirected.remove_header("Authorization")
        return redirected


def _api_get(url: str, token: str) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with build_opener(SafeRedirectHandler()).open(request, timeout=30) as response:
        body = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(body) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("History artifact download exceeded the size limit")
    return body


def restore_history() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    current_run = os.environ.get("GITHUB_RUN_ID", "")
    token = os.environ.get("GH_TOKEN", "")
    workflow = os.environ.get("HISTORY_WORKFLOW", "intech-seo-controller.yml")
    if not repo or not current_run:
        LOGGER.info("No GitHub Actions run context; starting without prior artifact history")
        return 0
    if not token:
        LOGGER.warning("GH_TOKEN is unavailable; historical comparison baseline is missing")
        return 1
    workflow_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?status=success&per_page=20"
    try:
        runs = json.loads(_api_get(workflow_url, token)).get("workflow_runs", [])
        previous = next((run for run in runs if str(run.get("id")) != current_run), None)
        if not previous:
            LOGGER.info("No earlier successful weekly report run; starting history baseline")
            return 0
        artifact_url = (
            f"https://api.github.com/repos/{repo}/actions/runs/"
            f"{previous['id']}/artifacts?per_page=100"
        )
        artifacts = json.loads(_api_get(artifact_url, token)).get("artifacts", [])
        artifact = next((item for item in artifacts
                         if item.get("name") == "intech-seo-history"
                         and not item.get("expired")), None)
        if not artifact:
            LOGGER.warning("Prior workflow run has no retained SEO history artifact")
            return 0
        archive = _api_get(artifact["archive_download_url"], token)
        registry = json.loads((ROOT / "seo-sites.json").read_text(encoding="utf-8"))
        allowed_ids = {site["id"] for site in registry["sites"]}
        HISTORY.mkdir(parents=True, exist_ok=True)
        restored = 0
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for entry in bundle.infolist():
                filename = Path(entry.filename).name
                match = re.fullmatch(r"([a-z0-9][a-z0-9-]*)\.jsonl", filename)
                if not match or match.group(1) not in allowed_ids or entry.is_dir():
                    continue
                if entry.file_size > MAX_HISTORY_FILE_BYTES:
                    LOGGER.warning("Skipping oversized history file %s", filename)
                    continue
                valid_records = []
                for line in bundle.read(entry).decode("utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("Skipping malformed history line in %s", filename)
                        continue
                    if isinstance(record, dict):
                        valid_records.append(json.dumps(record, ensure_ascii=False))
                destination = HISTORY / filename
                destination.write_text(
                    "\n".join(valid_records[-MAX_RECORDS_PER_FILE:]) + "\n"
                    if valid_records else "",
                    encoding="utf-8",
                )
                restored += 1
        LOGGER.info("Restored historical data for %s website(s) from run %s",
                    restored, previous["id"])
        return 0
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        LOGGER.error("Unable to restore prior SEO history artifact: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(restore_history())
