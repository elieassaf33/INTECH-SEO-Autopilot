import base64
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from client_registry import load_registry
import gsc_api
import gsc_analysis
import gsc_diagnostics
import intech_controller
import remediation
import technical_audit as technical
import report_health
import intech_register
from check_registry import check


def response(status=200, payload=None):
    result = Mock(status_code=status)
    result.json.return_value = payload or {}
    return result


class GoogleTests(unittest.TestCase):
    def test_retry_only_transient_status(self):
        session = Mock()
        session.post.side_effect = [response(429), response(503), response(200, {'ok': True})]
        with patch('gsc_api.time.sleep') as sleep:
            self.assertEqual(gsc_api.request(session, 'post', 'url'), {'ok': True})
        self.assertEqual(sleep.call_count, 2)

    def test_forbidden_does_not_retry_or_leak_response(self):
        session = Mock()
        session.get.return_value = response(403, {'secret': 'NEVER_LOG'})
        with self.assertRaises(gsc_api.ApiError) as ctx:
            gsc_api.request(session, 'get', 'url')
        self.assertNotIn('NEVER_LOG', str(ctx.exception))
        self.assertEqual(session.get.call_count, 1)

    def test_access_denied_is_actionable(self):
        session = Mock()
        session.get.return_value = response(403)
        result = gsc_diagnostics.property_access(session, 'sc-domain:example.com')
        self.assertEqual(result['http_status'], 403)
        self.assertIn('Users and permissions', result['required_action'])

    def test_hidden_property_404_is_actionable_without_claiming_it_does_not_exist(self):
        session = Mock()
        session.get.return_value = response(404)
        result = gsc_diagnostics.property_access(session, 'sc-domain:example.com')
        self.assertEqual(result['http_status'], 404)
        self.assertEqual(result['error_code'], 'property_not_visible')
        self.assertIn('Verify the exact property', result['required_action'])

    def test_indexing_uses_read_only_inspection(self):
        session = Mock()
        session.post.return_value = response(200, {'inspectionResult': {'indexStatusResult': {'verdict': 'PASS'}}})
        result = gsc_diagnostics.indexing(session, 'sc-domain:example.com', 'https://example.com/')
        self.assertEqual(result['verdict'], 'PASS')
        self.assertIn('/urlInspection/index:inspect', session.post.call_args.args[0])

    def test_aggregates_are_not_query_sums(self):
        session = Mock()
        totals = {'clicks': 99, 'impressions': 1000, 'ctr': .099, 'position': 3}
        query = {'keys': ['term', 'https://example.com/'], 'clicks': 1, 'impressions': 10, 'ctr': .1, 'position': 8}
        session.post.side_effect = [response(200, {'rows': [totals]}), response(200, {'rows': [totals]}),
                                    response(200, {'rows': [query]}), response(200, {})]
        result = gsc_analysis.weekly_analysis(session, 'p')
        self.assertEqual(result['site_metrics']['current']['metrics']['clicks'], 99)
        self.assertEqual(result['queries'][0]['clicks'], 1)
        self.assertEqual(session.post.call_args_list[0].kwargs['json']['dimensions'], [])
        self.assertEqual(session.post.call_args_list[0].kwargs['json']['aggregationType'], 'byProperty')

    def test_query_failure_preserves_property_metrics(self):
        session = Mock()
        totals = {'clicks': 1, 'impressions': 10, 'ctr': .1, 'position': 3}
        session.post.side_effect = [response(200, {'rows': [totals]}), response(200, {'rows': [totals]}), response(403)]
        result = gsc_analysis.weekly_analysis(session, 'p')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['site_metrics']['current']['status'], 'ok')

    def test_three_failures_exhaust_retry(self):
        session = Mock()
        session.get.return_value = response(503)
        with patch('gsc_api.time.sleep'), self.assertRaises(gsc_api.ApiError):
            gsc_api.request(session, 'get', 'url')
        self.assertEqual(session.get.call_count, 3)


def fetched(body=b'', status=200, url='https://example.com/', content_type='text/html', **kwargs):
    return {'status': status, 'final_url': url, 'body': body, 'content_type': content_type, **kwargs}


class TechnicalTests(unittest.TestCase):
    def audit(self, home, robots=None, sitemap=None):
        with patch.object(technical, 'fetch', side_effect=[home, robots or fetched(status=404),
                      sitemap or fetched(b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>')]):
            return technical.inspect({'name': 'Example', 'url': 'https://example.com'})

    def test_empty_metadata_and_canonical_are_missing(self):
        result = self.audit(fetched(b'<html><head><title> </title><meta name="description" content=""><link rel="canonical" href=""></head></html>'))
        self.assertTrue({'missing_title', 'missing_description', 'missing_canonical'} <= {i['code'] for i in result['findings']})

    def test_redirected_homepage_uses_final_origin_for_checks(self):
        with patch.object(technical, 'fetch', side_effect=[fetched(b'<html/>', url='https://www.example.com/en/'), fetched(status=404), fetched(status=404)]) as fetch:
            technical.inspect({'name': 'Example', 'url': 'https://example.com'})
        self.assertEqual(fetch.call_args_list[1].args[0], 'https://www.example.com/robots.txt')

    def test_failed_or_truncated_home_does_not_invent_missing_tags(self):
        for home in [fetched(status=403), fetched(b'<html>', truncated=True)]:
            with self.subTest(home=home):
                result = self.audit(home)
                self.assertFalse(any(i['code'].startswith('missing_') for i in result['findings']))

    def test_absent_robots_is_not_an_indexing_error(self):
        result = self.audit(fetched(b'<html/>'))
        self.assertFalse(any(i['code'].startswith('robots_') for i in result['findings']))

    def test_googlebot_robots_block_and_html_sitemap(self):
        result = self.audit(fetched(b'<html/>'), fetched(b'User-agent: Googlebot\nDisallow: /'), fetched(b'<html/>'))
        codes = {i['code'] for i in result['findings']}
        self.assertIn('robots_blocks_homepage', codes)
        self.assertIn('sitemap_invalid', codes)

    def test_internal_link_opportunity_is_not_orphan_claim(self):
        result = self.audit(fetched(b'<html><a href="/about/">About</a></html>'),
                            sitemap=fetched(b'<urlset><url><loc>https://example.com/other/</loc></url></urlset>'))
        self.assertEqual(result['checks']['internal_links']['count'], 1)
        self.assertIn('internal_link_opportunity', {i['code'] for i in result['findings']})

    def test_no_private_network_requests(self):
        with patch('technical_audit.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                technical.public_url('https://example.com/')
        for url in ['file:///etc/passwd', 'https://user:password@example.com/', 'https://example.com:22/']:
            with self.assertRaises(ValueError):
                technical.public_url(url)

    def test_cross_domain_redirect_needs_explicit_policy(self):
        redirects = technical.Redirects({'example.com'})
        with patch.object(technical, 'public_url'), self.assertRaises(ValueError):
            redirects.redirect_request(Mock(), None, 301, '', {}, 'https://another.test/')


class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.source = '<html><head><title>Example</title></head><body>Content</body></html>'
        self.site = {'client_id': 'example', 'gsc_property': 'sc-domain:example.com', 'repository': 'owner/site',
                     'default_branch': 'master', 'repository_status': 'confirmed_by_owner', 'remediation_enabled': True}
        self.policy = {'gsc_property': self.site['gsc_property'], 'repository': 'owner/site', 'default_branch': 'master',
                       'issue': 'missing_description', 'file': 'index.html', 'url': 'https://example.com/',
                       'source_sha256': hashlib.sha256(self.source.encode()).hexdigest(), 'approved_value': 'Approved & clear',
                       'reviewed_commit': 'a' * 40,
                       'branch_push_reviewed': True}
        self.report = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'sites': [
            {'gsc_property': self.site['gsc_property'], 'findings': [{'code': 'missing_description', 'url': 'https://example.com/'}]}]}

    def test_minimal_escaped_patch(self):
        result = remediation.static_patch(self.source, 'missing_description', 'Approved & clear')
        self.assertIn('content="Approved &amp; clear"', result)
        self.assertEqual(result.replace('    <meta name="description" content="Approved &amp; clear">\n', ''), self.source)

    def test_rejects_dynamic_and_existing_metadata(self):
        for source in [self.source + '{{ variable }}', self.source.replace('</head>', '<meta name="description" content=""></head>')]:
            with self.assertRaises(ValueError):
                remediation.static_patch(source, 'missing_description', 'Approved')
        with self.assertRaises(ValueError):
            remediation.static_patch(self.source, 'missing_canonical', 'https://example.com/')

    def test_explicit_enable_and_verified_source_required(self):
        for change in [{'remediation_enabled': False}, {'repository_status': 'source_correlated'}]:
            with self.assertRaises(ValueError):
                remediation.validate_policy(self.policy, [{**self.site, **change}], self.report)

    def test_path_traversal_secret_and_workflow_paths_rejected(self):
        for path in ['../index.html', '/index.html', '.github/workflows/a.html', 'foo\\index.html', '.env']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                remediation.validate_policy({**self.policy, 'file': path}, [self.site], self.report)

    def test_stale_evidence_and_unreviewed_deployment_triggers_rejected(self):
        with self.assertRaises(ValueError):
            remediation.validate_policy(self.policy, [self.site], {**self.report, 'generated_at': '2020-01-01T00:00:00+00:00'})
        with self.assertRaises(ValueError):
            remediation.validate_policy({**self.policy, 'branch_push_reviewed': False}, [self.site], self.report)

    def api(self, duplicate=False, drift=False):
        return [{'default_branch': 'master'}, {'sha': 'a' * 40},
                {'type': 'file', 'encoding': 'base64', 'sha': 'blob', 'content': base64.b64encode((self.source + ('changed' if drift else '')).encode()).decode()},
                [{'html_url': 'https://github.com/owner/site/pull/1'}] if duplicate else []]

    def test_dry_run_has_no_writes(self):
        with patch.object(remediation, 'gh', side_effect=self.api()) as api:
            result = remediation.propose(self.policy, [self.site], self.report)
        self.assertEqual(result['status'], 'validated')
        self.assertTrue(all(call.kwargs.get('payload') is None for call in api.call_args_list))

    def test_duplicate_pr_is_reused_even_if_closed(self):
        with patch.object(remediation, 'gh', side_effect=self.api(duplicate=True)) as api:
            result = remediation.propose(self.policy, [self.site], self.report, True)
        self.assertEqual(result['status'], 'existing_pr')
        self.assertEqual(api.call_count, 4)

    def test_source_drift_blocks_publication(self):
        with patch.object(remediation, 'gh', side_effect=self.api(drift=True)) as api, self.assertRaises(ValueError):
            remediation.propose(self.policy, [self.site], self.report, True)
        self.assertEqual(api.call_count, 3)

    def test_repository_drift_requires_deployment_trigger_review_again(self):
        replies = self.api()
        replies[1] = {'sha': 'b' * 40}
        with patch.object(remediation, 'gh', side_effect=replies) as api, self.assertRaises(ValueError):
            remediation.propose(self.policy, [self.site], self.report, True)
        self.assertEqual(api.call_count, 2)

    def test_only_draft_pr_targeting_actual_default_branch(self):
        with patch.object(remediation, 'gh', side_effect=self.api() + [{}, {}, {'html_url': 'pr'}]) as api:
            result = remediation.propose(self.policy, [self.site], self.report, True)
        payload = api.call_args.kwargs['payload']
        self.assertTrue(payload['draft'])
        self.assertEqual(payload['base'], 'master')
        self.assertEqual(result['status'], 'draft_pr_created')
        self.assertFalse(any('/merge' in str(c) for c in api.call_args_list))


class RegistryTests(unittest.TestCase):
    def test_future_client_is_monitored_but_remediation_stays_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'registry.json'
            path.write_text(json.dumps([{'name': 'Existing', 'url': 'https://existing.test'}]))
            entry = intech_register.register(path, 'New', 'https://new.test', 'owner/repo', 'sc-domain:new.test', 'shared')
            self.assertFalse(entry['remediation_enabled'])
            self.assertNotIn('default_branch', entry)
            self.assertEqual(len(load_registry(path)), 2)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                intech_register.register(path, 'Invalid', 'https://other.test', '', 'sc-domain:new.test')
            self.assertEqual(path.read_bytes(), before)

    def test_all_thirteen_and_shared_identity(self):
        check(Path(__file__).resolve().parents[1] / 'seo-sites.json')

    def test_duplicate_property_and_invalid_root_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'registry.json'
            site = {'url': 'https://example.com', 'name': 'Example', 'gsc_property': 'sc-domain:example.com'}
            for sites in [[site, site], [{**site, 'url': 'http://example.com'}], [{**site, 'url': 'https://other.test'}]]:
                path.write_text(json.dumps(sites))
                with self.assertRaises(ValueError):
                    load_registry(path)


class HealthTests(unittest.TestCase):
    def test_health_gate_fails_denied_and_preserves_no_data_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            for status, fails in [('access_denied', True), ('partial', True), ('no_data', False), ('ok', False)]:
                path.write_text(json.dumps({'sites': [{'gsc': {'status': status}, 'status': 'ok'}]}))
                with patch.object(report_health, 'Path', return_value=path), patch.dict('os.environ', {}, clear=True):
                    if fails:
                        with self.assertRaises(SystemExit):
                            report_health.main()
                    else:
                        report_health.main()


class LocalGoogleIntegrationTests(unittest.TestCase):
    def test_controller_thirteen_properties_with_real_http_transport(self):
        """Exercise serialization and isolation without real Google or production data."""
        import requests
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if 'denied.test' in self.path:
                    self.send_response(403); self.end_headers(); self.wfile.write(b'{}'); return
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"permissionLevel":"siteFullUser"}')
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if 'urlInspection' in self.path:
                    result = {'inspectionResult': {'indexStatusResult': {'verdict': 'PASS'}}}
                elif payload.get('dimensions') == []:
                    result = {'rows': [{'clicks': 20, 'impressions': 100, 'ctr': .2, 'position': 4}]}
                else:
                    result = {'rows': []}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get(self, url, **kwargs): return requests.get(f'http://127.0.0.1:{server.server_port}' + urlsplit(url).path, **kwargs)
            def post(self, url, **kwargs): return requests.post(f'http://127.0.0.1:{server.server_port}' + urlsplit(url).path, **kwargs)
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                sites = [{'name': f'Client {i}', 'url': f'https://client{i}.test', 'gsc_property': f'sc-domain:client{i}.test', 'client_id': f'client{i}'} for i in range(12)]
                sites.insert(3, {'name': 'Denied', 'url': 'https://denied.test', 'gsc_property': 'sc-domain:denied.test', 'client_id': 'denied'})
                registry = root / 'registry.json'; registry.write_text(json.dumps(sites))
                import os
                with patch.object(intech_controller, 'REGISTRY', registry), patch.object(intech_controller, 'OUT', root), \
                        patch.object(intech_controller, 'inspect', side_effect=lambda s: {'name': s['name'], 'base_url': s['url'], 'status': 'ok', 'findings': []}), \
                        patch('google.auth.default', return_value=(Mock(), None)), \
                        patch('google.auth.transport.requests.AuthorizedSession', return_value=Session()), \
                        patch.dict(os.environ, {'GCP_USE_ADC': 'true'}), patch('builtins.print'):
                    intech_controller.main()
                report = json.loads((root / 'report.json').read_text())
                self.assertEqual(report['property_count'], 13)
                self.assertEqual(sum(s['gsc']['status'] == 'access_denied' for s in report['sites']), 1)
                self.assertEqual(report['sites'][-1]['gsc']['site_metrics']['current']['metrics']['clicks'], 20)
                self.assertTrue((root / 'remediation-plan.json').exists())
                self.assertEqual(len(list(root.glob('snapshot-*.json'))), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
