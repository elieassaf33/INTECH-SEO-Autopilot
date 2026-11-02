import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import keyword_publisher as publisher
from keyword_content import patch_content, strip_managed


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.source = '<html><head><title>Home</title></head><body><main>Existing business facts</main></body></html>'
        self.target = {'kind':'static','display_path':'/','css_class':'container','base_sha256':hashlib.sha256(self.source.encode()).hexdigest(),
                       'client_id':'example','file':'index.html','services':['example.service'],'checks':['https://example.com/'],'site_id':'site'}
        self.proposal={'keyword':'local photography','heading':'Planning local photography',
                       'paragraph':'Discuss portrait photography with our studio before arranging a session.'}

    def test_vps_success_updates_only_managed_source_and_approved_recovery_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'index.html').write_text(self.source)
            manifest={'bundles':[{'id':'example','checks':[],'files':[]}]}
            with patch.object(publisher,'verify'),patch.object(publisher,'verify_content'),patch.object(publisher,'reload_services'):
                result=publisher.publish_vps({**self.target,'root':str(root)},self.proposal,manifest,root)
            self.assertEqual(result['status'],'published')
            self.assertEqual(strip_managed((root/'index.html').read_text()),self.source)
            self.assertEqual(manifest['bundles'][0]['files'][0]['sha256'],hashlib.sha256((root/'index.html').read_bytes()).hexdigest())
            self.assertEqual(Path(result['backup'],'original.html').read_bytes(),self.source.encode())

    def test_vps_failed_live_check_restores_source_and_does_not_advance_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'index.html').write_text(self.source)
            manifest={'bundles':[{'id':'example','checks':[],'files':[]}]};before=copy.deepcopy(manifest)
            with patch.object(publisher,'verify'),patch.object(publisher,'verify_content',side_effect=ValueError('missing copy')),patch.object(publisher,'reload_services') as reload:
                with self.assertRaisesRegex(RuntimeError,'rolled back'):
                    publisher.publish_vps({**self.target,'root':str(root)},self.proposal,manifest,root)
                self.assertEqual(reload.call_count,2)
            self.assertEqual((root/'index.html').read_text(),self.source)
            self.assertEqual(manifest,before)

    def fixture(self):
        old=self.source.encode();desired=patch_content(self.source,self.target,self.proposal).encode()
        old_sha=hashlib.sha1(old).hexdigest();new_sha=hashlib.sha1(desired).hexdigest()
        files={'/index.html':old_sha,'/asset.js':'unchanged'}
        policy={'site_id':'site','files':files.copy(),'functions':{},'checks':[],'metadata_variants':{},'deploy_id':'old'}
        manifest={'netlify_sites':[policy],'netlify_token_path':'unused'}
        current={'id':'old','available_functions':[]};ready={'id':'new','state':'ready','available_functions':[]}
        return manifest,current,ready,old,new_sha

    def test_netlify_preserves_other_assets_and_updates_baseline_only_after_verification(self):
        manifest,current,ready,old,new_sha=self.fixture();client=Mock()
        client.request.side_effect=[{'published_deploy':current},[{'path':k,'sha':v} for k,v in manifest['netlify_sites'][0]['files'].items()],old,
                                   {'id':'new','required':[new_sha]},b'',ready,{'published_deploy':current},{},
                                   {'published_deploy':ready},[{'path':'/index.html','sha':new_sha},{'path':'/asset.js','sha':'unchanged'}]]
        with tempfile.TemporaryDirectory() as temp,patch.object(publisher,'NetlifyContent',return_value=client),patch.object(publisher,'verify'),patch.object(publisher,'verify_content'):
            result=publisher.publish_netlify({**self.target,'file':'/index.html'},self.proposal,manifest,Path(temp))
        self.assertEqual(result['status'],'published')
        self.assertEqual(manifest['netlify_sites'][0]['deploy_id'],'new')
        request=client.request.call_args_list[3].args[2]
        self.assertTrue(request['draft']);self.assertEqual(request['files']['/asset.js'],'unchanged')

    def test_netlify_runtime_drift_is_rejected_before_publication(self):
        manifest,current,ready,old,new_sha=self.fixture();client=Mock()
        client.request.side_effect=[{'published_deploy':current},[{'path':k,'sha':v} for k,v in manifest['netlify_sites'][0]['files'].items()],old,
                                   {'id':'new','required':[]},{**ready,'available_functions':[{'n':'unexpected','d':'new-code'}]}]
        with tempfile.TemporaryDirectory() as temp,patch.object(publisher,'NetlifyContent',return_value=client):
            with self.assertRaisesRegex(ValueError,'runtime differs'):
                publisher.publish_netlify({**self.target,'file':'/index.html'},self.proposal,manifest,Path(temp))
        self.assertFalse(any('/restore' in c.args[0] for c in client.request.call_args_list))

    def test_netlify_live_failure_rolls_back_without_advancing_approved_release(self):
        manifest,current,ready,old,new_sha=self.fixture();client=Mock();before=copy.deepcopy(manifest)
        client.request.side_effect=[{'published_deploy':current},[{'path':k,'sha':v} for k,v in manifest['netlify_sites'][0]['files'].items()],old,
                                   {'id':'new','required':[]},ready,{'published_deploy':current},{},{'published_deploy':ready},{}]
        with tempfile.TemporaryDirectory() as temp,patch.object(publisher,'NetlifyContent',return_value=client),patch.object(publisher,'verify'),patch.object(publisher,'verify_content',side_effect=ValueError('live failed')):
            with self.assertRaisesRegex(RuntimeError,'rolled back'):
                publisher.publish_netlify({**self.target,'file':'/index.html'},self.proposal,manifest,Path(temp))
        self.assertEqual(client.request.call_args.args[0],'sites/site/deploys/old/restore')
        self.assertEqual(manifest,before)


if __name__=='__main__': unittest.main()
