import datetime as dt
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import gsc_analysis as gsc
import intech_controller as controller


def row(query='electrician', page='https://example.com/', clicks=1, impressions=100, position=8):
    return dict(keys=[query, page], clicks=clicks, impressions=impressions,
                ctr=clicks / impressions if impressions else 0, position=position)


class WeeklyAnalysisTests(unittest.TestCase):
    def test_adjacent_seven_day_windows_across_year(self):
        self.assertEqual(gsc.periods(dt.date(2026, 1, 5)),
                         ((dt.date(2025, 12, 27), dt.date(2026, 1, 2)),
                          (dt.date(2025, 12, 20), dt.date(2025, 12, 26))))

    def test_pagination_and_encoded_property(self):
        session = Mock()
        session.post.return_value.json.side_effect = [{'rows': [row(), row('other')]}, {'rows': []}]
        with patch.object(gsc, 'PAGE_SIZE', 2):
            rows, capped = gsc.fetch_rows(session, 'sc-domain:example.com', gsc.periods(dt.date(2026, 1, 5))[0])
        self.assertEqual(len(rows), 2)
        self.assertFalse(capped)
        self.assertIn('sc-domain%3Aexample.com', session.post.call_args.args[0])
        self.assertEqual(session.post.call_args.kwargs['json']['startRow'], 2)
        self.assertEqual(session.post.call_args.kwargs['json']['dataState'], 'final')

    def test_recommendations_deltas_and_page_identity(self):
        current = [row(), row(page='https://example.com/new', clicks=3)]
        previous = [row(clicks=10, position=10), row('lost', clicks=5)]
        keywords, actions = gsc.analyze(current, previous)
        continuing = next(k for k in keywords if k['presence'] == 'continuing')
        self.assertEqual(continuing['click_change'], -9)
        self.assertEqual(continuing['position_improvement'], 2)
        self.assertEqual({a['reason'] for a in actions}, {'traffic_decline', 'low_ctr', 'ranking_opportunity'})
        new = next(k for k in keywords if k['presence'] == 'newly_observed')
        self.assertIsNone(new['click_change_percent'])
        lost = next(k for k in keywords if k['presence'] == 'no_longer_observed')
        self.assertIsNone(lost['position'])

    def test_empty_and_cap(self):
        session = Mock()
        session.post.return_value.json.return_value = {}
        self.assertEqual(gsc.weekly_analysis(session, 'p')['status'], 'no_data')
        session.post.return_value.json.return_value = {'rows': [row()]}
        with patch.object(gsc, 'MAX_ROWS', 1), patch.object(gsc, 'PAGE_SIZE', 1):
            self.assertTrue(gsc.weekly_analysis(session, 'p')['row_cap_reached'])

    def test_api_failure_is_not_empty_success(self):
        session = Mock()
        session.post.return_value.raise_for_status.side_effect = RuntimeError('Forbidden')
        result = gsc.weekly_analysis(session, 'p')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['query_status'], 'error')

    def test_missing_setup(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(controller.search_console({'gsc_property': 'p'})['status'], 'not_configured')
        self.assertEqual(controller.search_console({})['status'], 'not_configured')

    def test_search_demand_uses_28_final_days_without_changing_weekly_windows(self):
        with patch.object(gsc,'fetch_rows',return_value=([row()],False)) as fetch:
            result=gsc.search_demand(object(),'p',dt.date(2026,11,6))
        self.assertEqual(result['period'],['2026-10-07','2026-11-03'])
        self.assertEqual(fetch.call_args.args[2],(dt.date(2026,10,7),dt.date(2026,11,3)))
        self.assertEqual(gsc.demand_queries({'search_demand':result})[0]['keyword'],'electrician')

    def test_demand_failure_falls_back_to_weekly_queries(self):
        with patch.object(gsc,'fetch_rows',side_effect=RuntimeError('Unavailable')):
            result=gsc.search_demand(object(),'p')
        self.assertEqual(gsc.demand_queries({'search_demand':result,'queries':[{'keyword':'weekly'}]}),[{'keyword':'weekly'}])

    def test_multiple_clients_and_failure_isolation(self):
        import tempfile
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / 'sites.json'
            registry.write_text(json.dumps([{'name': 'First', 'url': 'https://one.test'},
                                            {'name': 'Future client', 'url': 'https://two.test'}]))
            with patch.object(controller, 'REGISTRY', registry), patch.object(controller, 'OUT', root), \
                    patch.object(controller, 'inspect', side_effect=[RuntimeError('offline'), {'name': 'Future client', 'base_url': 'https://two.test', 'findings': []}]), \
                    patch.object(controller, 'search_console', return_value={'status': 'no_data'}):
                controller.main()
            report = json.loads((root / 'report.json').read_text())
            self.assertEqual(report['client_count'], 2)
            self.assertEqual(report['sites'][1]['gsc']['status'], 'no_data')


if __name__ == '__main__':
    unittest.main()
