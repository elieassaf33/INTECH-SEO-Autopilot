"""Apply root-owned, source-pinned metadata repair bundles; never accept remote code."""
import argparse
import base64
import datetime as dt
import hashlib
from html.parser import HTMLParser
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.head = False
        self.title = False
        self.values = {"title": "", "description": [], "canonical": []}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "head":
            self.head = True
        if not self.head:
            return
        if tag == "title":
            self.title = True
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.values["description"].append(attrs.get("content", "").strip())
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.values["canonical"].append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "title":
            self.title = False
        if tag == "head":
            self.head = self.title = False

    def handle_data(self, data):
        if self.head and self.title:
            self.values["title"] += data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def approved_bytes(file):
    desired = base64.b64decode(file["content_base64"], validate=True)
    if digest(desired) != file["sha256"]:
        raise ValueError("Corrupt approved snapshot")
    return desired


def repair_bytes(current, file):
    """Only recover a missing approved snippet, or apply an exact approved predecessor."""
    desired = approved_bytes(file)
    if current == desired:
        return None
    if digest(current) in file.get("approved_predecessors", []):
        return desired
    snippets = [s.encode("utf-8") for s in file.get("recoverable_snippets", [])]
    if len(snippets) > 3 or any(desired.count(s) != 1 for s in snippets):
        raise ValueError("Invalid recovery snippets")
    for count in range(1, len(snippets) + 1):
        for removed in itertools.combinations(snippets, count):
            variant = desired
            for snippet in removed:
                variant = variant.replace(snippet, b"", 1)
            if current == variant:
                return desired
    raise ValueError("Source changed beyond approved metadata; refresh source baseline")


def atomic_write(path, data):
    stat = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=".seo-repair-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.st_mode & 0o777)
        if hasattr(os, "chown"):
            os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def probe(check):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("Live verification redirected unexpectedly")
    request = Request(check["url"], headers={"User-Agent": "INTECH-SEO-Repair/1.0", "Cache-Control": "no-cache"})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status != 200 or response.url.split("?", 1)[0] != check["url"]:
            raise ValueError("Live page failed or redirected unexpectedly")
        data = response.read(1_500_001)
        if len(data) > 1_500_000 or "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("Live page is truncated or not HTML")
    parser = Metadata()
    parser.feed(data.decode("utf-8"))
    for name, expected in check["expected"].items():
        actual = parser.values[name]
        if expected is True:
            if (not actual or isinstance(actual, str) and not actual.strip() or
                    isinstance(actual, list) and (len(actual) != 1 or not actual[0])):
                raise ValueError("Live metadata missing or ambiguous: " + name)
        elif actual != expected:
            raise ValueError("Live metadata mismatch: " + name)
    return {"url": check["url"], "status": "verified"}


def reload_services(services):
    for service in services:
        subprocess.run(["systemctl", "restart", service], check=True,
                       capture_output=True, timeout=30)


def verify(checks, attempts=6):
    for attempt in range(attempts):
        try:
            return [probe(check) for check in checks]
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(5)


def apply_bundle(bundle, state, apply=False):
    root = Path(bundle["root"]).resolve(strict=True)
    changes = []
    for file in bundle["files"]:
        path = root / file["path"]
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("Repair path escapes approved root")
        current = path.read_bytes()
        desired = repair_bytes(current, file)
        if desired is not None:
            changes.append((path, current, desired))
    if not changes:
        return {"id": bundle["id"], "status": "healthy", "checks": verify(bundle["checks"], attempts=1)}
    if not apply:
        return {"id": bundle["id"], "status": "would_repair", "files": [str(p.relative_to(root)) for p, _, _ in changes]}
    # Snapshot every file before the first write. Files, owner and mode are preserved.
    backup = state / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + bundle["id"])
    backup.mkdir(parents=True)
    for path, old, _ in changes:
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(old)
    written = []
    try:
        for path, old, desired in changes:
            if path.read_bytes() != old:
                raise ValueError("Source changed during repair")
            atomic_write(path, desired)
            written.append((path, old, desired))
        reload_services(bundle["services"])
        checks = verify(bundle["checks"])
        return {"id": bundle["id"], "status": "repaired", "backup": str(backup), "checks": checks}
    except Exception as error:
        for path, old, desired in reversed(written):
            if path.read_bytes() != desired:
                raise RuntimeError("Concurrent source change; manual recovery required: " + str(backup)) from error
            atomic_write(path, old)
        reload_services(bundle["services"])
        raise RuntimeError("Repair rolled back; backup: " + str(backup)) from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="/etc/intech-seo-repairs/manifest.json")
    parser.add_argument("--state", default="/var/lib/intech-seo-repairs")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    with (state / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads(Path(args.manifest).read_text())
        results = []
        for bundle in manifest["bundles"]:
            try:
                results.append(apply_bundle(bundle, state, args.apply))
            except Exception as exc:
                results.append({"id": bundle["id"], "status": "blocked", "reason": str(exc)})
        report = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "apply": args.apply,
                  "worker_sha256": digest(Path(__file__).read_bytes()),
                  "manifest_sha256": digest(Path(args.manifest).read_bytes()),
                  "results": results, "not_enabled": manifest.get("not_enabled", [])}
        payload = json.dumps(report, indent=2)
        (state / "latest.json").write_text(payload + "\n")
        (state / (dt.datetime.now(dt.timezone.utc).strftime("report-%Y%m%dT%H%M%S%f.json"))).write_text(payload + "\n")
        print(payload)
        return int(any(r["status"] == "blocked" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
