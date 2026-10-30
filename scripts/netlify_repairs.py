"""Recover approved Netlify deploys without rebuilding or losing functions/rewrites."""
import json
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler


class Netlify:
    def __init__(self, token_path):
        self.token = Path(token_path).read_text().strip()

    def api(self, path, method="GET"):
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("Unexpected Netlify API redirect")
        request = Request("https://api.netlify.com/api/v1/" + path,
                          headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
                          method=method, data=b"{}" if method == "POST" else None)
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            data = response.read(10_000_001)
            if len(data) > 10_000_000:
                raise ValueError("Oversized Netlify API response")
            return json.loads(data)


def validate_digest(current, policy):
    approved = policy["files"]
    if set(current) - set(approved):
        raise ValueError("Netlify deploy contains new files; refresh approved deployment")
    missing = set(approved) - set(current)
    if not missing <= set(policy.get("recoverable_files", [])):
        raise ValueError("Netlify deploy lost non-recoverable files")
    for path, sha in current.items():
        if sha != approved[path] and sha not in policy.get("metadata_variants", {}).get(path, []):
            raise ValueError("Netlify source changed beyond approved metadata: " + path)
    return current != approved


def apply_site(policy, client, verify, apply=False):
    prefix = "sites/" + policy["site_id"]
    site = client.api(prefix)
    current = site["published_deploy"]
    if current.get("locked"):
        raise ValueError("Netlify production deploy is locked")
    functions = {f["n"]: f["d"] for f in current.get("available_functions", [])}
    if (functions != policy.get("functions", {}) or current.get("edge_functions_present") or current.get("server")):
        raise ValueError("Netlify functions or server bundle changed; refresh approved deployment")
    files = {f["path"]: f["sha"] for f in client.api(prefix + "/files")}
    changed = validate_digest(files, policy)
    if not changed:
        return {"id": policy["id"], "status": "healthy", "provider": "netlify", "checks": verify(policy["checks"])}
    if not apply:
        return {"id": policy["id"], "status": "would_repair", "provider": "netlify"}
    # No new builds or digest deploys: restore the entire approved immutable release,
    # including functions, headers, rewrites, languages, and unchanged assets.
    if client.api(prefix)["published_deploy"]["id"] != current["id"]:
        raise ValueError("Netlify production advanced during repair")
    target = prefix + "/deploys/" + policy["deploy_id"] + "/restore"
    try:
        client.api(target, "POST")
        checks = verify(policy["checks"])
        restored = {f["path"]: f["sha"] for f in client.api(prefix + "/files")}
        if restored != policy["files"]:
            raise ValueError("Restored Netlify file digest differs from approved release")
        return {"id": policy["id"], "status": "repaired", "provider": "netlify",
                "deploy_id": policy["deploy_id"], "previous_deploy": current["id"], "checks": checks}
    except Exception as exc:
        # Avoid replacing an unrelated release that raced our verification.
        now = client.api(prefix)["published_deploy"]["id"]
        if now != policy["deploy_id"]:
            raise RuntimeError("Netlify changed during repair; manual release review required") from exc
        client.api(prefix + "/deploys/" + current["id"] + "/restore", "POST")
        raise RuntimeError("Netlify repair rolled back to " + current["id"]) from exc
