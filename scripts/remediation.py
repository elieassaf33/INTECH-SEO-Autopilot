"""Conservative static-HTML adapter. No remote code execution, merge or deployment."""
import argparse
import datetime as dt
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from technical_audit import MetadataParser
from client_registry import load_registry

SUPPORTED = {"missing_description": "description", "missing_title": "title"}


def plan_proposals(report, sites):
    registry = {s.get("gsc_property"): s for s in sites}
    plans = []
    seen = set()
    for result in report["sites"]:
        site = registry.get(result.get("gsc_property"), {})
        for issue in result.get("findings", []):
            code = issue.get("code", "unknown")
            key = (site.get("client_id"), site.get("repository"), code, issue.get("url"))
            if key in seen:
                continue
            seen.add(key)
            blocked = ("repository_unmapped" if not site.get("repository") else
                       "manual_canonical_or_domain_decision" if "canonical" in code else
                       "repository_source_unverified" if site.get("repository_status") != "confirmed_by_owner" else
                       "remediation_disabled" if not site.get("remediation_enabled") else
                       "no_safe_adapter" if code not in SUPPORTED else "explicit_file_policy_required")
            plans.append({"client_id": site.get("client_id"), "gsc_property": result.get("gsc_property"),
                          "repository": site.get("repository"), "issue": code, "url": issue.get("url"),
                          "status": "blocked", "reason": blocked})
    return {"mode": "proposal_only", "auto_merge": False, "proposals": plans}


def static_patch(source, code, value):
    if code not in SUPPORTED or not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError("Unsupported issue or invalid approved metadata")
    if any(marker in source for marker in ("{%", "{{", "<?", "<%")):
        raise ValueError("Dynamic templates require a separately reviewed adapter")
    parser = MetadataParser()
    parser.feed(source)
    if len(re.findall(r"</head\s*>", source, re.I)) != 1 or len(re.findall(r"<head\b", source, re.I)) != 1:
        raise ValueError("Expected exactly one head element")
    if code == "missing_description":
        if parser.description or re.search(r'<meta\b[^>]*\bname\s*=\s*[\'\"]?description', source, re.I):
            raise ValueError("Existing or empty description requires manual review")
        tag = '<meta name="description" content="' + html.escape(value, quote=True) + '">'
    else:
        if re.search(r"<title\b", source, re.I):
            raise ValueError("Existing or empty title requires manual review")
        tag = "<title>" + html.escape(value) + "</title>"
    patched = re.sub(r"</head\s*>", lambda match: "    " + tag + "\n" + match[0], source, count=1, flags=re.I)
    # Controlled validation: never execute scripts, dependencies or tests from a client repository.
    parsed = MetadataParser()
    parsed.feed(patched)
    actual = parsed.description if code == "missing_description" else parsed.title
    if actual != value or patched.replace("    " + tag + "\n", "", 1) != source:
        raise ValueError("Patch validation failed")
    return patched


def validate_policy(policy, sites, report):
    site = next((s for s in sites if s.get("gsc_property") == policy.get("gsc_property")), None)
    if not site or not site.get("remediation_enabled") or site.get("repository_status") != "confirmed_by_owner":
        raise ValueError("Remediation requires an explicitly enabled, verified registry mapping")
    if policy.get("repository") != site["repository"] or policy.get("default_branch") != site.get("default_branch"):
        raise ValueError("Policy does not match registry repository and branch")
    if policy.get("issue") not in SUPPORTED or policy.get("branch_push_reviewed") is not True:
        raise ValueError("Unsupported adapter or branch deployment triggers not reviewed")
    file = PurePosixPath(policy["file"])
    if (file.is_absolute() or ".." in file.parts or "\\" in policy["file"] or
            any(part.startswith(".") for part in file.parts) or file.suffix.lower() not in (".html", ".htm")):
        raise ValueError("Only explicit public HTML target files are supported")
    generated = dt.datetime.fromisoformat(report["generated_at"])
    age = dt.datetime.now(dt.timezone.utc) - generated
    if not dt.timedelta(0) <= age <= dt.timedelta(days=7):
        raise ValueError("Evidence must be at most seven days old")
    match = any(s.get("gsc_property") == site["gsc_property"] and any(
        i.get("code") == policy["issue"] and i.get("url") == policy.get("url") for i in s.get("findings", [])) for s in report["sites"])
    if not match or not re.fullmatch(r"[0-9a-f]{64}", policy.get("source_sha256", "")):
        raise ValueError("Missing matching issue evidence or reviewed source hash")
    return site


def gh(*args, payload=None):
    command = ["gh", *args]
    if payload is not None:
        command += ["--input", "-"]
    completed = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                               text=True, capture_output=True)
    if completed.returncode:
        # CLI errors can include raw URLs/headers; never put them in shared reports.
        raise RuntimeError("GitHub CLI operation failed; check scoped authentication and repository permissions")
    return json.loads(completed.stdout) if completed.stdout.strip() else None


def propose(policy, sites, report, publish=False):
    import base64
    site = validate_policy(policy, sites, report)
    repo = site["repository"]
    metadata = gh("api", f"repos/{repo}")
    if metadata["default_branch"] != site["default_branch"] or metadata.get("archived"):
        raise ValueError("Repository default branch changed or repository archived")
    from urllib.parse import quote
    base = gh("api", f"repos/{repo}/commits/{quote(site['default_branch'], safe='')}")["sha"]
    target = gh("api", f"repos/{repo}/contents/{quote(policy['file'], safe='/')}?ref={base}")
    if target.get("type") != "file" or target.get("encoding") != "base64":
        raise ValueError("Target must be a regular UTF-8 HTML file")
    raw = base64.b64decode(target["content"])
    if hashlib.sha256(raw).hexdigest() != policy["source_sha256"]:
        raise ValueError("Source changed since policy review; refresh evidence")
    source = raw.decode("utf-8")
    patch = static_patch(source, policy["issue"], policy["approved_value"])
    identity = json.dumps([site["client_id"], repo, policy["file"], policy["issue"], policy["approved_value"]])
    branch = "seo/proposal-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    existing = gh("api", f"repos/{repo}/pulls?state=all&head={repo.split('/')[0]}:{branch}&per_page=100")
    if existing:
        return {"status": "existing_pr", "url": existing[0]["html_url"]}
    result = {"status": "validated", "repository": repo, "file": policy["file"], "branch": branch,
              "validation": "Controlled HTML parse, exact approved value and single insertion invariant passed; client application CI remains required"}
    if not publish:
        import difflib
        result["diff"] = "".join(difflib.unified_diff(source.splitlines(True), patch.splitlines(True), fromfile=policy["file"], tofile=policy["file"]))
        return result
    # An existing branch (including a failed earlier publication) fails closed. Never reset or overwrite it.
    gh("api", f"repos/{repo}/git/refs", payload={"ref": "refs/heads/" + branch, "sha": base})
    gh("api", "--method", "PUT", f"repos/{repo}/contents/{quote(policy['file'], safe='/')}", payload={
        "message": "SEO: propose reviewed missing metadata", "branch": branch, "sha": target["sha"],
        "content": base64.b64encode(patch.encode()).decode()})
    pr = gh("api", f"repos/{repo}/pulls", payload={"title": "SEO: propose reviewed missing metadata",
        "head": branch, "base": site["default_branch"], "draft": True,
        "body": f"Evidence: {policy['url']} ({report['generated_at']}).\n\nIssue: {policy['issue']}. File: {policy['file']}.\n\n{result['validation']}.\n\nHuman review required. No canonical, redirects, domain, database or deployment changes. No automatic merge."})
    return {**result, "status": "draft_pr_created", "url": pr["html_url"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="seo-sites.json")
    parser.add_argument("--report", required=True)
    parser.add_argument("--policies", default="remediation-policies.json")
    parser.add_argument("--output", default="seo-reports/remediation/results.json")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    sites = load_registry(args.registry)
    results = []
    for policy in json.loads(Path(args.policies).read_text(encoding="utf-8")):
        try:
            results.append(propose(policy, sites, report, args.publish))
        except Exception as exc:
            results.append({"status": "blocked", "gsc_property": policy.get("gsc_property"),
                            "reason": str(exc) if isinstance(exc, ValueError) else "github_operation_failed"})
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if any(r["status"] == "blocked" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
