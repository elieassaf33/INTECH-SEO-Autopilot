import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from change_history import windows,append_event,read_changes
from change_performance import evaluate,assess,page_metrics
from daily_health import check_page,run
from seo_alerts import notify,MARKER,TITLE
from metadata_pages import patch
from build_dashboard import build
from enroll_metadata_pages import page_type


class PerformanceTests(unittest.TestCase):
    def record(self,when='2026-10-01T01:00:00+00:00'):
        return {'change_id':'one','target_id':'page','gsc_property':'sc-domain:example.com','url':'https://example.com/service/',
                'published_at':when,'status':'published','before':{'title':'Old','description':'Old copy'},'after':{'title':'New','description':'New copy'}}
    def test_windows_follow_google_pacific_dates_and_exclude_change_day(self):
        result=windows('2026-11-02T01:00:00+00:00')
        self.assertEqual(result['before'],['2026-10-04','2026-10-31'])
        self.assertEqual(result['after'],['2026-11-02','2026-11-29'])
        self.assertEqual(result['ready_date'],'2026-12-02')
    def test_waits_for_full_period_without_calling_google(self):
        fetch=Mock()
        result=evaluate([self.record('2026-11-03T10:00:00+00:00')],object(),now=dt.datetime(2026,11,10,tzinfo=dt.timezone.utc),fetch=fetch)
        self.assertEqual(result['results'][0]['status'],'waiting_for_data');fetch.assert_not_called()
    def test_page_aggregates_use_exact_url_filter_not_query_sums(self):
        session=Mock();response=Mock(status_code=200);response.json.return_value={'rows':[{'clicks':10,'impressions':100,'ctr':.1,'position':5}]};session.post.return_value=response
        result=page_metrics(session,'sc-domain:example.com','https://example.com/service/',['2026-09-01','2026-09-28'])
        body=session.post.call_args.kwargs['json']
        self.assertEqual(body['dimensions'],[]);self.assertEqual(body['aggregationType'],'byPage')
        self.assertEqual(body['dimensionFilterGroups'][0]['filters'][0]['expression'],'https://example.com/service/')
        self.assertEqual(result['clicks'],10)
    def test_sparse_or_missing_data_is_not_a_success(self):
        self.assertEqual(assess(None,{'clicks':0})['status'],'insufficient_data')
        metric={'clicks':2,'impressions':20,'ctr':.1,'position':7}
        self.assertEqual(assess(metric,metric)['status'],'insufficient_data')
    def test_descriptive_improvement_and_confounders(self):
        before={'clicks':20,'impressions':200,'ctr':.1,'position':10};after={'clicks':60,'impressions':400,'ctr':.15,'position':6}
        result=assess(before,after)
        self.assertEqual(result['status'],'observed_improvement');self.assertEqual(result['delta']['clicks'],40)
        self.assertEqual(len(result['confounders']),2)
    def test_overlap_prevents_attributing_results_to_one_edit(self):
        a=self.record();b={**self.record('2026-10-10T12:00:00+00:00'),'change_id':'two'}
        result=evaluate([a,b],now=dt.datetime(2026,11,20,tzinfo=dt.timezone.utc))
        self.assertEqual(next(r for r in result['results'] if r['change_id']=='one')['status'],'overlapping_change')
    def test_completed_results_are_cached_and_errors_retry(self):
        fetch=Mock(return_value={'clicks':20,'impressions':200,'ctr':.1,'position':5});now=dt.datetime(2026,11,20,tzinfo=dt.timezone.utc)
        report=evaluate([self.record()],object(),now=now,fetch=fetch);self.assertEqual(fetch.call_count,2)
        fetch.reset_mock();again=evaluate([self.record()],object(),previous=report,now=now,fetch=fetch)
        fetch.assert_not_called();self.assertEqual(again['results'][0]['status'],'no_clear_change')
    def test_journal_preserves_planned_and_final_states(self):
        with tempfile.TemporaryDirectory() as directory:
            record=self.record();append_event(directory,record,'planned');append_event(directory,record,'published',{'deploy_id':'safe-id'})
            rows=read_changes(directory)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'published');self.assertEqual(rows[0]['receipt']['deploy_id'],'safe-id')


class HealthAndAlertsTests(unittest.TestCase):
    target={'gsc_property':'sc-domain:example.com','url':'https://example.com/','name':'Example'}
    def response(self,html=None,status=200):
        return {'status':status,'content_type':'text/html','body':(html or '<html><head><title>Example</title><meta name="description" content="Business description"></head><body>Visible text</body></html>').encode()}
    def test_transient_outage_is_rechecked_before_alerting(self):
        fetch=Mock(side_effect=[self.response(status=503),self.response()]);row=check_page(self.target,fetcher=fetch,sleep=lambda n:None)
        self.assertEqual(row['status'],'healthy');self.assertEqual(fetch.call_count,2)
    def test_persistent_outage_is_actionable(self):
        row=check_page(self.target,fetcher=lambda *a:self.response(status=503),sleep=lambda n:None)
        self.assertEqual(row['issues'][0]['code'],'availability_failed')
    def test_noindex_missing_and_duplicate_metadata_are_detected(self):
        row=check_page(self.target,fetcher=lambda *a:self.response('<head><title>One</title><title>Two</title><meta name="robots" content="noindex"></head>'),sleep=lambda n:None)
        self.assertEqual({r['code'] for r in row['issues']},{'missing_title','missing_description','unexpected_noindex'})
    def test_body_robots_text_does_not_block_indexing(self):
        row=check_page(self.target,fetcher=lambda *a:self.response('<head><title>Example</title><meta name="description" content="Copy"></head><body><meta name="robots" content="noindex"></body>'),sleep=lambda n:None)
        self.assertFalse(row['issues'])
    def test_failed_workflow_is_an_incident_even_when_sites_are_healthy(self):
        result=run([],workflows=[{'workflow':'metadata.yml','run':{'conclusion':'failure','html_url':'https://github.com/a/b/actions/runs/1'}}])
        self.assertEqual(result['incidents'][0]['code'],'workflow_failed')
    def test_first_alert_assigns_owner_and_repeated_alert_is_deduplicated(self):
        client=Mock();client.call.side_effect=[[],{'html_url':'https://github.com/a/b/issues/1'}]
        report={'generated_at':'2026-11-03T10:00:00+00:00','incidents':[{'key':'one','code':'missing_title','message':'Title is missing.'}]}
        self.assertEqual(notify(client,report,'owner')['status'],'created')
        payload=client.call.call_args_list[1].args[2];self.assertEqual(payload['assignees'],['owner'])
        client.reset_mock();client.call.side_effect=None;client.call.return_value=[{'title':TITLE,'body':payload['body'],'state':'open','number':1,'html_url':'https://github.com/a/b/issues/1'}]
        self.assertEqual(notify(client,report,'owner')['status'],'already_notified');self.assertEqual(client.call.call_count,1)
    def test_recovery_closes_only_managed_issue(self):
        client=Mock();client.call.side_effect=[[{'title':TITLE,'body':MARKER,'state':'open','number':3,'html_url':'url'}],{},{}]
        self.assertEqual(notify(client,{'incidents':[]})['status'],'resolved')
        self.assertEqual(client.call.call_args_list[-1].args[2]['state'],'closed')


class PagePolicyTests(unittest.TestCase):
    def setUp(self):
        self.source='<head><title>{{ title }}</title><meta name="description" content="{{ description }}"><link rel="canonical" href="{{ canonical }}"></head><body>Unchanged body</body>'
        self.home={'kind':'django','display_path':'/','base_sha256':hashlib.sha256(self.source.encode()).hexdigest(),
                   'original_tags':{'title':'<title>{{ title }}</title>','description':'<meta name="description" content="{{ description }}">'}}
        self.service={**self.home,'display_path':'/services/testing/'}
        group=[self.home,self.service];self.home['_file_targets']=group;self.service['_file_targets']=group
    def test_multiple_pages_preserve_each_other_and_original_fallback(self):
        home={'title':'Home service title','description':'Home service description'};service={'title':'Testing page title','description':'Testing page description'}
        first=patch(self.source,self.home,home);second=patch(first,self.service,service)
        self.assertIn('Home service title',second);self.assertIn('Testing page title',second);self.assertIn('{% else %}{{ title }}',second)
        self.assertEqual(second.split('<body>')[1],self.source.split('<body>')[1])
        self.assertEqual(patch(second,self.service,service),second)
    def test_unknown_page_maps_and_source_drift_are_blocked(self):
        updated=patch(self.source,self.service,{'title':'Testing page title','description':'Testing page description'})
        target={k:v for k,v in self.home.items() if k!='_file_targets'}
        with self.assertRaises(ValueError):patch(updated,target,{'title':'Home title','description':'Home description'})
        with self.assertRaises(ValueError):patch(self.source+'new body',self.home,{'title':'Home title','description':'Home description'})
    def test_only_public_business_page_types_are_enrolled(self):
        self.assertEqual(page_type('https://example.com/products/product-name/'),'product')
        self.assertEqual(page_type('https://example.com/services/testing/'),'service')
        self.assertIsNone(page_type('https://example.com/checkout/'))


class DashboardTests(unittest.TestCase):
    def test_self_contained_dashboard_escapes_script_closing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            malicious='</script><script>alert("private data")</script>'
            Path(directory,'audit.json').write_text(json.dumps({'sites':[{'name':malicious}]}),encoding='utf-8')
            output,data=build(directory,targets=[])
            self.assertNotIn(malicious,output)
            raw=re.search(r'<script type="application/json" id="report-data">(.*?)</script>',output,re.S)[1]
            self.assertEqual(json.loads(raw)['audit']['sites'][0]['name'],malicious)
            self.assertNotIn('<script src=',output)
    def test_missing_inputs_are_not_fabricated_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            output,data=build(directory,targets=[])
            self.assertEqual(data['performance'],{});self.assertIn('Awaiting sufficient data',output)

class NetlifyMetadataCacheTests(unittest.TestCase):
    def test_fresh_upload_changes_only_managed_title_region(self):
        from keyword_publisher import fresh_metadata_upload
        original=b'<head><!-- INTECH META TITLE START --><title>Title</title><!-- INTECH META TITLE END --></head><body>Unchanged</body>'
        first=fresh_metadata_upload(original);second=fresh_metadata_upload(original)
        self.assertNotEqual(first,second)
        import re
        self.assertEqual(re.sub(rb'<!-- INTECH DEPLOY [a-f0-9]{32} -->',b'',first),original)
        with self.assertRaises(ValueError):fresh_metadata_upload(b'<title>Unmanaged</title>')

