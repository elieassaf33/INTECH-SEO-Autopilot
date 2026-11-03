"""Apply bounded metadata variants; never rewrite templates or visible page text."""
from __future__ import annotations

import argparse
import ast
import base64
import datetime as dt
import difflib
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from scripts.restore_history import SafeRedirectHandler

ROOT = Path(__file__).resolve().parents[1]


class GitHubContents:
    def __init__(self, token: str = "") -> None:
        self.token = token

    def request(self, method: str, path: str, payload=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "INTECH-SEO-Autopilot",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request("https://api.github.com" + path, data=data, headers=headers, method=method)
        try:
            with build_opener(SafeRedirectHandler()).open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"GitHub {method} returned HTTP {exc.code}") from None

    def read(self, repository, branch, path):
        endpoint = f"/repos/{repository}/contents/{quote(path, safe='/')}"
        result = self.request("GET", endpoint + "?" + urlencode({"ref": branch}))
        if result.get("type") != "file" or result.get("encoding") != "base64":
            raise ValueError("Expected a regular base64-encoded source file")
        return base64.b64decode(result["content"]).decode("utf-8"), result["sha"]

    def write(self, repository, branch, path, source, sha):
        # The source blob SHA is a compare-and-swap precondition. Never force or retry a write.
        result = self.request("PUT", f"/repos/{repository}/contents/{quote(path, safe='/')}", {
            "message": "SEO: update configured page title and description",
            "branch": branch, "sha": sha,
            "content": base64.b64encode(source.encode("utf-8")).decode("ascii"),
        })
        return result["commit"]["sha"]


def patch_metadata(source: str, target: dict, variant: dict) -> str:
    """Change exactly two allowlisted string leaves in one Python function."""
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == target["function"]]
    if len(functions) != 1:
        raise ValueError("Metadata function is missing or ambiguous")
    edits = []
    lines = source.encode("utf-8").splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for field in ("title", "description"):
        value = variant[field]
        limit = 70 if field == "title" else 170
        if not isinstance(value, str) or not 10 <= len(value) <= limit or any(c in value for c in '<>\r\n'):
            raise ValueError(f"Invalid {field} copy")
        allowed = {target["baseline"][field]} | {item[field] for item in target["variants"]}
        assignments = [node for node in ast.walk(functions[0])
                       if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == field]
        if len(assignments) != 1:
            raise ValueError(f"{field} assignment is missing or ambiguous")
        node = assignments[0].value
        if target.get("branch") == "else":
            if not isinstance(node, ast.IfExp):
                raise ValueError("Expected conditional metadata")
            node = node.orelse
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or node.value not in allowed:
            raise ValueError(f"{field} changed outside the configured variants")
        if node.value != value:
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            edits.append((start, end, repr(value).encode("utf-8")))
    result = source.encode("utf-8")
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    updated = result.decode("utf-8")
    compile(updated, "metadata.py", "exec")
    return updated


def choose_variant(target: dict, report: dict):
    ideas = {row["keyword"].casefold(): row for row in
             report.get("keyword_discovery", {}).get("ideas", [])
             if "google_autocomplete" in row.get("sources", [])}
    # Configuration order is priority; repeated runs select the same variant.
    for variant in target["variants"]:
        matched = [term for term in variant["keywords"] if term.casefold() in ideas]
        if matched:
            return variant, matched
    return None, []


def publish(registry: dict, reports: dict, policy: dict, *, client=None,
            apply=False, now=None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    timestamp = dt.datetime.fromisoformat(reports["generated_at"])
    if timestamp.tzinfo is None or not dt.timedelta(0) <= now - timestamp <= dt.timedelta(days=8):
        raise ValueError("Audit report must be timezone-aware, not future-dated, and at most eight days old")
    targets = policy.get("targets", {})
    results = []
    report_by_id = {site["id"]: site for site in reports["sites"]}
    client = client or GitHubContents(os.environ.get("SEO_PUBLISH_TOKEN", ""))
    for site in registry["sites"]:
        result = {"site_id": site["id"], "status": "not_configured", "live_verified": False}
        results.append(result)
        target = targets.get(site["id"])
        if not target:
            result["reason"] = "No confirmed metadata source and deployment mapping"
            continue
        try:
            repository = target["repository"]
            if repository != site.get("repository") or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
                raise ValueError("Publisher repository does not match the confirmed registry")
            path = target["path"]
            if not path.endswith(".py") or path.startswith("/") or ".." in path.split("/") or "\\" in path:
                raise ValueError("Invalid metadata source path")
            report = report_by_id.get(site["id"], {})
            if report.get("technical_status") != "success":
                result.update(status="skipped", reason="Technical audit did not succeed")
                continue
            variant, matched = choose_variant(target, report)
            if not variant:
                result.update(status="no_matching_keyword", reason="No configured copy matches a discovered autocomplete keyword")
                continue
            result.update(keywords=matched, title=variant["title"], description=variant["description"],
                          repository=repository, path=path)
            if apply:
                missing = []
                if target.get("deployment_on_push_verified") is not True:
                    missing.append("Automatic deployment on this branch has not been verified")
                if not getattr(client, "token", ""):
                    missing.append("SEO_PUBLISH_TOKEN is unavailable")
                if missing:
                    result.update(status="blocked", reason="; ".join(missing))
                    continue
            source, sha = client.read(repository, target["git_branch"], path)
            updated = patch_metadata(source, target, variant)
            if source == updated:
                result.update(status="unchanged", reason="Selected metadata is already in source")
                continue
            result["diff"] = "".join(difflib.unified_diff(source.splitlines(True), updated.splitlines(True),
                                                       fromfile=path, tofile=path))
            result["source_sha"] = sha
            if not apply:
                result["status"] = "preview"
            else:
                result["commit"] = client.write(repository, target["git_branch"], path, updated, sha)
                # A successful commit is not evidence of successful deployment.
                result["status"] = "committed_pending_deployment"
        except Exception as exc:
            result.update(status="error", reason=f"{type(exc).__name__}: {exc}"[:300])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--local-site", help="Site ID for an offline source preview")
    parser.add_argument("--local-source", type=Path, help="Existing source file for that preview")
    args = parser.parse_args()
    if bool(args.local_site) != bool(args.local_source) or (args.apply and args.local_source):
        parser.error("Use --local-site with --local-source for previews only")
    output = ROOT / "seo-reports" / "weekly"
    try:
        registry = json.loads((ROOT / "seo-sites.json").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "seo-publishing.json").read_text(encoding="utf-8"))
        client = GitHubContents(os.environ.get("SEO_PUBLISH_TOKEN", ""))
        if args.local_source:
            import hashlib
            target = policy["targets"][args.local_site]
            remote_read = client.read
            def local_read(repository, branch, path):
                if (repository, path) != (target["repository"], target["path"]):
                    return remote_read(repository, branch, path)
                raw = args.local_source.read_bytes()
                blob = b"blob " + str(len(raw)).encode() + b"\0" + raw
                return raw.decode("utf-8"), hashlib.sha1(blob).hexdigest()
            client.read = local_read
        results = publish(registry,
                          json.loads((output / "report.json").read_text(encoding="utf-8")),
                          policy, client=client, apply=args.apply)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Metadata publishing could not start: {exc}")
        return 1
    output.mkdir(parents=True, exist_ok=True)
    (output / "publishing.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Automatic title and description updates", ""]
    lines.extend(f"- {row['site_id']}: **{row['status']}** — {row.get('reason', '')}" for row in results)
    (output / "publishing.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for row in results:
        print(f"{row['site_id']}: {row['status']} {row.get('reason', '')}")
    return int(any(row["status"] in ("error", "blocked") for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
