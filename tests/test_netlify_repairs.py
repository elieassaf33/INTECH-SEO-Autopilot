import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from netlify_repairs import apply_site, validate_digest


class NetlifyRepairsTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'id': 'example', 'site_id': 'site', 'deploy_id': 'approved', 'checks': [],
                       'files': {'/index.html': 'good', '/asset.js': 'asset', '/sitemap.xml': 'sitemap'},
                       'metadata_variants': {'/index.html': ['missing-title']}, 'recoverable_files': ['/sitemap.xml']}
        self.current = {'published_deploy': {'id': 'previous'}}
        self.bad_files = [{'path': '/index.html', 'sha': 'missing-title'}, {'path': '/asset.js', 'sha': 'asset'}]
        self.good_files = [{'path': k, 'sha': v} for k, v in self.policy['files'].items()]

    def test_only_approved_metadata_variants_and_missing_sitemap_are_recoverable(self):
        self.assertTrue(validate_digest({f['path']:f['sha'] for f in self.bad_files}, self.policy))
        self.assertFalse(validate_digest(self.policy['files'], self.policy))
        for files in [{'/index.html':'unknown', '/asset.js':'asset'}, {'/index.html':'good'},
                      {**self.policy['files'], '/new.html':'new'}, {**self.policy['files'], '/asset.js':'new'}]:
            with self.assertRaises(ValueError):
                validate_digest(files, self.policy)

    def test_healthy_and_dry_run_never_publish(self):
        for files, status in [(self.good_files, 'healthy'), (self.bad_files, 'would_repair')]:
            client = Mock(); client.api.side_effect = [self.current, files]
            self.assertEqual(apply_site(self.policy, client, Mock(return_value=[]))['status'], status)
            self.assertTrue(all(len(c.args) == 1 for c in client.api.call_args_list))

    def test_repair_restores_whole_approved_deploy_and_checks_digest(self):
        client=Mock(); client.api.side_effect=[self.current,self.bad_files,self.current,{},self.good_files]
        result=apply_site(self.policy,client,Mock(return_value=[]),True)
        self.assertEqual(result['status'],'repaired')
        self.assertIn(unittest.mock.call('sites/site/deploys/approved/restore','POST'),client.api.call_args_list)

    def test_live_failure_rolls_back_previous_release(self):
        client=Mock(); client.api.side_effect=[self.current,self.bad_files,self.current,{},
                                             {'published_deploy':{'id':'approved'}},{}]
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            apply_site(self.policy,client,Mock(side_effect=ValueError('bad live HTML')),True)
        self.assertEqual(client.api.call_args.args,('sites/site/deploys/previous/restore','POST'))

    def test_concurrent_or_locked_release_is_never_overwritten(self):
        client=Mock(); client.api.side_effect=[{'published_deploy':{'id':'previous','locked':True}}]
        with self.assertRaisesRegex(ValueError,'locked'):
            apply_site(self.policy,client,Mock(),True)
        client=Mock(); client.api.side_effect=[self.current,self.bad_files,{'published_deploy':{'id':'new'}}]
        with self.assertRaisesRegex(ValueError,'advanced'):
            apply_site(self.policy,client,Mock(),True)
        self.assertTrue(all(len(c.args)==1 for c in client.api.call_args_list))

    def test_function_changes_are_blocked_even_when_static_files_match(self):
        client=Mock();client.api.return_value={'published_deploy':{'id':'new','available_functions':[{'n':'payment','d':'new-code'}]}}
        with self.assertRaisesRegex(ValueError,'functions'):
            apply_site(self.policy,client,Mock(),True)
        self.assertEqual(client.api.call_count,1)


if __name__ == '__main__':
    unittest.main()
