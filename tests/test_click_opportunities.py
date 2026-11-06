import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from click_opportunities import opportunities
from click_page_audit import targets,check
from unittest.mock import patch
from daily_health import monitoring_targets
from business_priorities import load_priorities,priority_targets
from free_metadata_research import select_properties
import json,tempfile


class ClickOpportunityTests(unittest.TestCase):
    def test_commercial_pages_remain_visible_with_no_search_data(self):
        priorities={'p':{'name':'Priority business','priority':1,'conversion':'booking_enquiry','pages':[
            {'url':'https://example.com/family/','role':'service','label':'Family sessions'}]}}
        report=opportunities({'sites':[{'name':'Other','gsc_property':'other','gsc':{}},
            {'name':'Priority business','gsc_property':'p','gsc':{'status':'no_data'}}]},priorities=priorities)
        self.assertEqual(report['sites'][0]['name'],'Priority business')
        self.assertEqual(report['sites'][0]['pages'][0]['url'],'https://example.com/family/')
        self.assertEqual(report['sites'][0]['pages'][0]['priority_score'],0)
        self.assertEqual(select_properties([{'gsc_property':'other'},{'gsc_property':'p'}],1,priorities),['p'])

    def test_business_configuration_rejects_a_foreign_landing_page(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'priorities.json'
            p.write_text(json.dumps({'sites':{'p':{'priority':1,'pages':[{'url':'https://foreign.test/'}]}}}))
            with self.assertRaises(ValueError):load_priorities(p,[{'url':'https://example.com','gsc_property':'p'}])

    def test_ranks_page_demand_and_excludes_queries_without_a_ctr_gap(self):
        rows=[{'page':'https://example.com/service','keyword':'service','impressions':1000,'clicks':1,'position':6,'ctr':.001},
              {'page':'https://example.com/','keyword':'brand','impressions':1000,'clicks':500,'position':1,'ctr':.5},
              {'page':'https://example.com/unknown','keyword':'unknown','impressions':100,'clicks':0,'position':None}]
        result=opportunities({'sites':[{'name':'Example','gsc':{'status':'ok','queries':rows}}]})
        pages=result['sites'][0]['pages']
        self.assertEqual(len(pages),1)
        self.assertEqual(pages[0]['url'],'https://example.com/service')
        self.assertEqual(pages[0]['priority_score'],29)

    def test_preserves_clients_without_search_data(self):
        result=opportunities({'sites':[{'name':'New client','gsc':{'status':'access_denied'}}]})
        self.assertEqual(result['sites'][0]['data_status'],'access_denied')
        self.assertEqual(result['sites'][0]['pages'],[])

    def test_landing_page_selection_rejects_foreign_hosts(self):
        site={'name':'Example','base_url':'https://example.com/','gsc_property':'property','gsc':{'queries':[
            {'page':'https://foreign.test/','impressions':5000},
            {'page':'https://example.com/service','impressions':100}]}}
        self.assertEqual({t['url'] for t in targets({'sites':[site]},[])},{'https://example.com/','https://example.com/service'})

    def test_approved_primary_canonical_is_preserved(self):
        response={'status':200,'final_url':'https://alias.test/en/','content_type':'text/html',
            'body':b'<head><title>Example</title><meta name="description" content="Example"><link rel="canonical" href="https://primary.test/en/"></head>'}
        with patch('click_page_audit.fetch',return_value=response):
            row=check({'url':'https://alias.test/en/','primary_origin':'https://primary.test'})
        self.assertEqual(row['issues'],[])

    def test_published_pages_are_monitored_only_on_their_registered_property_host(self):
        configured=[{'url':'https://example.com/','gsc_property':'p'}]
        history={'changes':[
            {'status':'published','gsc_property':'p','url':'https://example.com/product/11/'},
            {'status':'published','gsc_property':'p','url':'https://foreign.test/'},
            {'status':'failed','gsc_property':'p','url':'https://example.com/failed/'}]}
        selected=monitoring_targets(configured,history)
        self.assertEqual({t['url'] for t in selected},{'https://example.com/','https://example.com/product/11/'})


if __name__=='__main__':unittest.main()
