import copy,datetime as dt,hashlib,json,re,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from free_metadata import patch_metadata,copy_for,validate,supported
from free_metadata_research import research
from metadata_worker import process


class MetadataOnlyTests(unittest.TestCase):
    def setUp(self):
        self.source='<html><head><title>Old title</title><meta name="description" content="Existing description."><link rel="canonical" href="https://example.com/"></head><body><h1>Existing heading</h1><p>Electrical testing and inspection is offered here.</p></body></html>'
        self.target={'gsc_property':'sc-domain:example.com','name':'Example','url':'https://example.com/','keywords':['electrical testing and inspection'],
            'country':'GB','language':'en','kind':'static','slot_id':'example','client_id':'example','provider':'vps',
            'file':'base.html','services':[],'checks':[],
            'original_tags':{'title':'<title>Old title</title>','description':'<meta name="description" content="Existing description.">'},
            'base_sha256':hashlib.sha256(self.source.encode()).hexdigest(),
            'metadata_baseline':{'title':'Old title','description':'Discuss electrical work at your property. Contact our team for details.'}}
        self.page={'title':'Old title','description':'Existing description.','text':'Electrical testing and inspection is offered here.','language':'en'}
        self.keyword='electrical testing and inspection'
        self.proposal={'gsc_property':self.target['gsc_property'],'status':'approved','scope':'metadata_only','keyword':self.keyword,
                       **copy_for(self.keyword,self.target,self.page)}
        self.now=dt.datetime.now(dt.timezone.utc)
        self.report={'scope':'metadata_only','generated_at':self.now.isoformat(),'results':[self.proposal]}

    def test_metadata_patch_preserves_body_and_canonical_byte_for_byte(self):
        updated=patch_metadata(self.source,self.target,self.proposal)
        self.assertEqual(updated.split('<body>')[1],self.source.split('<body>')[1])
        self.assertIn('<link rel="canonical" href="https://example.com/">',updated)
        self.assertIn(self.proposal['title'],updated)
        self.assertEqual(patch_metadata(updated,self.target,self.proposal),updated)

    def test_refuses_unrelated_source_drift_and_ambiguous_markers(self):
        for source in (self.source+'new code',self.source+'<!-- INTECH META TITLE START -->'):
            with self.assertRaises(ValueError):patch_metadata(source,self.target,self.proposal)

    def test_research_rejects_unsupported_autocomplete_and_never_calls_a_paid_api(self):
        result=research(self.target,{},fetch=lambda *a:['free guaranteed repairs',self.keyword],get_context=lambda u:self.page)
        self.assertEqual(result['status'],'approved')
        self.assertEqual(result['keyword'],self.keyword)
        self.assertIsNone(result['ideas'][0]['search_volume'])
        self.assertNotIn('paragraph',result)

    def test_current_best_candidate_is_not_replaced_by_a_weaker_one(self):
        current={**self.page,**copy_for(self.keyword,self.target,self.page)}
        result=research(self.target,{},fetch=lambda *a:[self.keyword],get_context=lambda u:current)
        self.assertEqual(result['status'],'unchanged')

    def test_discovery_failure_is_explicit(self):
        def fail(*args):raise TimeoutError()
        self.assertEqual(research(self.target,{},fetch=fail,get_context=lambda u:self.page)['status'],'blocked')

    def test_arbitrary_copy_and_visible_text_fields_are_rejected(self):
        for change in ({'title':'Guaranteed free repairs'},{'paragraph':'Injected visible text'},{'scope':'content'}):
            with self.assertRaises(ValueError):validate({**self.proposal,**change},self.target,self.page)

    def test_worker_enforces_broad_homepage_topics_independently(self):
        proposal={**self.proposal,'keyword':'is offered here'}
        with self.assertRaisesRegex(ValueError,'homepage topics'):
            validate(proposal,self.target,self.page)

    def test_keyword_requires_the_entire_phrase_in_source(self):
        self.assertFalse(supported('inspection electrical testing',self.page))
        self.assertFalse(supported('inspection offered free',self.page))
        self.assertTrue(supported(self.keyword,self.page))

    def test_django_homepage_condition_preserves_child_blocks_and_other_pages(self):
        # Real Django rendering is exercised separately using the app's venv.
        target={**self.target,'kind':'django','display_path':'/'}
        updated=patch_metadata(self.source,target,self.proposal)
        self.assertEqual(updated.count("{% if request.path == '/' %}"),2)
        self.assertEqual(updated.split('<body>')[1],self.source.split('<body>')[1])

    def test_rejects_stale_evidence_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            report={**self.report,'generated_at':(self.now-dt.timedelta(days=2)).isoformat()}
            with self.assertRaises(ValueError):process(report,[self.target],{},Path(directory),now=self.now)

    def test_alias_is_not_written_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            result=process(self.report,[{**self.target,'alias_of':'primary'}],{},Path(directory),apply=True,now=self.now)
            self.assertEqual(result[0]['status'],'shared_template')

    def test_vps_publication_rebases_recovery_and_persists_each_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'base.html').write_text(self.source)
            target={**self.target,'root':str(root)}
            manifest={'bundles':[{'id':'example','checks':[],'files':[]}]};saved=[]
            with patch('keyword_publisher.reload_services'),patch('keyword_publisher.verify'),patch('metadata_worker.verify_metadata'):
                result=process(self.report,[target],manifest,root,apply=True,now=self.now,get_context=lambda u:self.page,
                               persist=lambda m:saved.append(copy.deepcopy(m)))
            self.assertEqual(result[0]['status'],'published')
            self.assertEqual(len(saved),1)
            self.assertEqual(len(manifest['bundles'][0]['files'][0]['recoverable_snippets']),3)
            self.assertTrue((root/'metadata-ledger.json').exists())
            self.assertEqual((root/'base.html').read_text().split('<body>')[1],self.source.split('<body>')[1])

    def test_weekly_cooldown_prevents_repeated_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'metadata-ledger.json').write_text(json.dumps({'example':{'published_at':self.now.isoformat()}}))
            result=process(self.report,[self.target],{},root,apply=True,now=self.now)
            self.assertEqual(result[0]['status'],'cooldown')

    def test_all_thirteen_properties_remain_configured(self):
        root=Path(__file__).resolve().parents[1]
        registry=json.loads((root/'seo-sites.json').read_text(encoding='utf-8'))
        targets=json.loads((root/'metadata-targets.json').read_text(encoding='utf-8'))
        self.assertEqual({s['gsc_property'] for s in registry},{s['gsc_property'] for s in targets})
        workflow=(root/'.github/workflows/weekday-keyword-growth.yml').read_text(encoding='utf-8-sig')
        self.assertNotIn('OPENAI_API_KEY',workflow)
        self.assertNotIn('keyword_research.py',workflow)
        self.assertIn('metadata <',workflow)
