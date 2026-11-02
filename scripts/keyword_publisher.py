"""Installed, root-owned publisher. Accepts checked plain text, never remote code."""
import argparse
import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from keyword_content import patch_content, page_context, validate_copy, strip_managed
from production_repairs import atomic_write, digest, reload_services, verify, missing_metadata_variants


class NetlifyContent:
    def __init__(self, token_path): self.token = Path(token_path).read_text().strip()
    def request(self, path, method='GET', payload=None, raw=False):
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): raise ValueError('Unexpected API redirect')
        headers = {'Authorization': 'Bearer ' + self.token}
        if raw and method == 'GET': headers['Content-Type'] = 'application/vnd.bitballoon.v1.raw'
        elif isinstance(payload, bytes): headers['Content-Type'] = 'application/octet-stream'
        else: headers['Content-Type'] = 'application/json'
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode() if payload is not None else None
        request = Request('https://api.netlify.com/api/v1/' + path, headers=headers, data=data, method=method)
        with build_opener(NoRedirect()).open(request, timeout=40) as response:
            content = response.read(10_000_001)
            if len(content) > 10_000_000: raise ValueError('Oversized API response')
            return content if raw else json.loads(content)


def snapshot(relative, data, original_sha):
    return {'path': relative, 'content_base64': base64.b64encode(data).decode(), 'sha256': digest(data),
            'approved_predecessors': [original_sha], 'recoverable_snippets': []}


def check_content(target, proposal):
    # Check the public rendered copy, not just the edited source. Original facts
    # are extracted without the managed section by page_context separately.
    from technical_audit import fetch
    from urllib.parse import urlsplit
    import html
    for url in target['checks']:
        response = fetch(url, {urlsplit(url).hostname})
        if response.get('status') != 200 or response.get('truncated'):
            raise ValueError('Updated public page is unavailable')
        body = html.unescape(response['body'].decode('utf-8'))
        if proposal['heading'] not in body or proposal['paragraph'] not in body:
            raise ValueError('Updated content is absent from rendered public page')


def verify_content(target, proposal):
    for attempt in range(6):
        try: return check_content(target, proposal)
        except Exception:
            if attempt == 5: raise
            time.sleep(5)


def publish_vps(target, proposal, manifest, state):
    root = Path(target['root']).resolve(strict=True)
    path = root / target['file']
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Unapproved source path')
    bundle = next(b for b in manifest['bundles'] if b['id'] == target['client_id'])
    verify(bundle['checks'])
    old = path.read_bytes(); desired = patch_content(old.decode(), target, proposal).encode()
    backup = state / ('growth-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(); (backup / 'original.html').write_bytes(old)
    (backup / 'receipt.json').write_text(json.dumps({'root': str(root), 'file': target['file'],
                                                    'old_sha256': digest(old), 'new_sha256': digest(desired)}))
    try:
        if path.read_bytes() != old: raise ValueError('Source changed during publication')
        atomic_write(path, desired); reload_services(target['services'])
        verify(bundle['checks']); verify_content(target, proposal)
    except Exception:
        if path.read_bytes() != desired: raise RuntimeError('Concurrent source change; inspect backup ' + str(backup))
        atomic_write(path, old); reload_services(target['services'])
        raise RuntimeError('Content publication rolled back; backup ' + str(backup))
    entry = next((f for f in bundle['files'] if f['path'] == target['file']), None)
    new = snapshot(target['file'], desired, target['base_sha256'])
    if entry:
        new['approved_predecessors'] = sorted(set(entry.get('approved_predecessors', []) + new['approved_predecessors']))
        new['recoverable_snippets'] = entry.get('recoverable_snippets', [])
        entry.update(new)
    else: bundle['files'].append(new)
    return {'status': 'published', 'backup': str(backup), 'source_sha256': digest(desired)}


def function_signature(deploy):
    return {f['n']: (f['d'], f.get('m'), f.get('r'), f.get('rg')) for f in deploy.get('available_functions', [])}


def publish_netlify(target, proposal, manifest, state):
    policy = next(p for p in manifest['netlify_sites'] if p['site_id'] == target['site_id'])
    client = NetlifyContent(manifest['netlify_token_path']); prefix = 'sites/' + target['site_id']
    current = client.request(prefix)['published_deploy']
    if current.get('locked') or current.get('edge_functions_present') or current.get('server'):
        raise ValueError('Locked or unsupported Netlify runtime')
    files = {f['path']: f['sha'] for f in client.request(prefix + '/files')}
    if files != policy['files'] or {f['n']: f['d'] for f in current.get('available_functions', [])} != policy['functions']:
        raise ValueError('Netlify source/functions changed since approved baseline')
    old = client.request(prefix + '/files' + target['file'], raw=True)
    if hashlib.sha1(old).hexdigest() != files[target['file']]: raise ValueError('Netlify source digest mismatch')
    desired = patch_content(old.decode(), target, proposal).encode(); sha = hashlib.sha1(desired).hexdigest()
    files[target['file']] = sha
    config = {}
    for f in current.get('available_functions', []):
        config[f['n']] = {k: f[v] for k, v in [('display_name', 'dn'), ('generator', 'g'), ('build_data', 'bd'),
                         ('memory', 'm'), ('region', 'rg'), ('priority', 'p')] if f.get(v) is not None}
    payload = {'files': files, 'functions': policy['functions'], 'functions_config': config, 'draft': True,
               'function_schedules': current.get('function_schedules', [])}
    draft = client.request(prefix + '/deploys?draft=true&title=Checked%20keyword%20content', 'POST', payload)
    if draft.get('required_functions') or draft.get('required_edge_functions') or draft.get('required_server'):
        raise ValueError('Draft could not preserve the existing runtime bundles')
    required = set(draft.get('required', []))
    if required - {sha}: raise ValueError('Draft requires unexpected unchanged assets')
    if sha in required:
        client.request('deploys/' + draft['id'] + '/files/' + quote(target['file'].lstrip('/'), safe='/'), 'PUT', desired, True)
    for _ in range(30):
        draft = client.request('deploys/' + draft['id'])
        if draft['state'] == 'ready': break
        if draft['state'] == 'error': raise ValueError('Draft processing failed')
        time.sleep(2)
    if draft['state'] != 'ready' or function_signature(draft) != function_signature(current):
        raise ValueError('Draft runtime differs from current production')
    if client.request(prefix)['published_deploy']['id'] != current['id']:
        raise ValueError('Production advanced during draft validation')
    # The immutable draft must contain exactly the one changed HTML digest;
    # the full original digest, functions and config were retained in its request.
    receipt = state / ('netlify-growth-' + draft['id'] + '.json')
    receipt.write_text(json.dumps({'previous': current['id'], 'draft': draft['id'], 'file': target['file'],
                                    'old_sha1': hashlib.sha1(old).hexdigest(), 'new_sha1': sha}))
    try:
        client.request(prefix + '/deploys/' + draft['id'] + '/restore', 'POST', {})
        verify(policy['checks']); verify_content(target, proposal)
        live = client.request(prefix)['published_deploy']
        actual = {f['path']: f['sha'] for f in client.request(prefix + '/files')}
        if live['id'] != draft['id'] or actual != files or function_signature(live) != function_signature(current):
            raise ValueError('Published source/runtime differs from checked draft')
    except Exception:
        if client.request(prefix)['published_deploy']['id'] != draft['id']:
            raise RuntimeError('Concurrent release; manual Netlify review required')
        client.request(prefix + '/deploys/' + current['id'] + '/restore', 'POST', {})
        raise RuntimeError('Netlify keyword publication rolled back to ' + current['id'])
    policy['files'] = files; policy['deploy_id'] = draft['id']
    head = desired.decode().split('</head>')[0]
    snippets = re.findall(r'<title\b[^>]*>.*?</title>|<meta\b[^>]*name=[\'\"]description[\'\"][^>]*>|<link\b[^>]*rel=[\'\"]canonical[\'\"][^>]*>', head, re.S | re.I)
    policy['metadata_variants'][target['file']] = sorted({hashlib.sha1(v).hexdigest()
        for v in missing_metadata_variants(desired, [s.encode() for s in snippets])} |
        {hashlib.sha1(strip_managed(desired.decode()).encode()).hexdigest()})
    return {'status': 'published', 'deploy_id': draft['id'], 'previous_deploy': current['id']}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--apply', action='store_true')
    parser.add_argument('--config', default='/etc/intech-seo-repairs/growth-targets.json')
    parser.add_argument('--manifest', default='/etc/intech-seo-repairs/manifest.json')
    parser.add_argument('--state', default='/var/lib/intech-seo-repairs'); args = parser.parse_args()
    data = sys.stdin.buffer.read(1_000_001)
    if len(data) > 1_000_000: raise ValueError('Oversized publication request')
    report = json.loads(data); age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(report['generated_at'])
    if not dt.timedelta(0) <= age <= dt.timedelta(hours=24): raise ValueError('Publication evidence must be fresh')
    state = Path(args.state); state.mkdir(mode=0o700, parents=True, exist_ok=True)
    import fcntl
    with (state / 'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        targets = {t['gsc_property']: t for t in json.loads(Path(args.config).read_text())}
        manifest = json.loads(Path(args.manifest).read_text()); ledger_path = state / 'growth-ledger.json'
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        results = []; seen = set()
        for proposal in report['results']:
            prop = proposal['gsc_property']; result = {'gsc_property': prop}
            try:
                target = targets[prop]
                if proposal['status'] != 'approved':
                    results.append({**result, 'status': proposal['status']}); continue
                if target.get('alias_of'):
                    results.append({**result, 'status': 'shared_template', 'primary_property': target['alias_of']}); continue
                slot = target['slot_id']
                if slot in seen: raise ValueError('Duplicate publication target')
                seen.add(slot)
                previous = ledger.get(slot)
                if previous and dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(previous['published_at']) < dt.timedelta(days=14):
                    results.append({**result, 'status': 'cooldown', 'last_publication': previous['published_at']}); continue
                context = page_context(target['url']); validate_copy(proposal, context)
                if not args.apply:
                    results.append({**result, 'status': 'validated'}); continue
                result.update(publish_netlify(target, proposal, manifest, state) if target['provider'] == 'netlify'
                              else publish_vps(target, proposal, manifest, state))
                # Rebase recovery onto only this verified, bounded content change.
                atomic_write(Path(args.manifest), (json.dumps(manifest, indent=2) + '\n').encode())
                ledger[slot] = {'published_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'keyword': proposal['keyword'], **result}
                ledger_path.write_text(json.dumps(ledger, indent=2))
                results.append(result)
            except Exception as exc:
                results.append({**result, 'status': 'blocked', 'reason': str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Publication transport or file operation failed'})
        output = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'apply': args.apply, 'results': results,
                  'publisher_sha256': digest(Path(__file__).read_bytes())}
        content = json.dumps(output, indent=2); (state / 'growth-latest.json').write_text(content)
        (state / (dt.datetime.now(dt.timezone.utc).strftime('growth-report-%Y%m%dT%H%M%S%f.json'))).write_text(content)
        print(content)
        return int(any(r['status'] == 'blocked' for r in results))


if __name__ == '__main__': raise SystemExit(main())
