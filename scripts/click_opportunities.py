"""Prioritize observed search demand; estimates are planning heuristics, not forecasts."""
import argparse
import json
from pathlib import Path
from gsc_analysis import demand_queries
from business_priorities import load_priorities


def opportunities(audit, limit=10,priorities=None):
    priorities=priorities or {}
    clients=[]
    for site in audit.get('sites',[]):
        business=priorities.get(site.get('gsc_property'),{})
        pages={p['url']:{'url':p['url'],'priority_score':0,'queries':[],'business_page_priority':index+1,
            'role':p['role'],'label':p['label'],'action':'Build relevant service visibility and verify the path to an enquiry or booking.'}
            for index,p in enumerate(business.get('pages',[]))}
        for row in demand_queries(site.get('gsc',{})):
            impressions=row.get('impressions',0)
            position=row.get('position')
            if impressions<10 or position is None or not 1<=position<=20:continue
            # Conservative comparison bands for prioritization, not expected CTR.
            benchmark=.05 if position<=3 else .03 if position<=10 else .01
            gap=max(0,impressions*benchmark-row.get('clicks',0))
            if not gap:continue
            url=row['page'];page=pages.setdefault(url,{'url':url,'priority_score':0,'queries':[]})
            page['priority_score']+=gap
            page['queries'].append({'query':row['keyword'],'impressions':impressions,
                'clicks':row.get('clicks',0),'position':position,'ctr':row.get('ctr',0),
                'action':'Review title and description against query intent' if position<=10 else 'Review existing page coverage and relevant internal links'})
        ranked=sorted(pages.values(),key=lambda p:(p.get('business_page_priority',1000),-p['priority_score'],p['url']))[:limit]
        for page in ranked:
            page['priority_score']=round(page['priority_score'],2)
            page['queries']=sorted(page['queries'],key=lambda q:-q['impressions'])[:5]
        clients.append({'name':site['name'],'gsc_property':site.get('gsc_property'),
            'business_priority':business.get('priority',1000),'conversion_goal':business.get('conversion'),
            'data_status':site.get('gsc',{}).get('status','unavailable'),'pages':ranked})
    clients.sort(key=lambda s:(s['business_priority'],s['name']))
    return {'note':'Owner-selected commercial pages are listed first, including pages with sparse search data. Scores prioritize observed query/page samples using heuristic CTR bands; they are not revenue or traffic forecasts. Query data is partial. Conversion goals are objectives, not measured leads.','sites':clients}


def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=opportunities(json.loads(Path(a.audit).read_text(encoding='utf-8')),priorities=load_priorities())
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Search click opportunities','',report['note'],'']
    for site in report['sites']:
        lines.extend(['## '+site['name'],'','Search Console: '+site['data_status'],''])
        if site.get('conversion_goal'):lines.extend(['Business goal: '+site['conversion_goal'].replace('_',' '),''])
        if not site['pages']:lines.extend(['No qualifying opportunity in the available data.',''])
        for page in site['pages']:
            lines.extend([page['url'],''])
            if page.get('role'):lines.extend([page['label']+' — '+page['role'],''])
            if not page['queries'] and page.get('action'):lines.extend([page['action']+' No query met the opportunity thresholds; this is not evidence of zero traffic.',''])
            for q in page['queries']:
                term=q['query'].replace('\n',' ').replace('\r',' ')
                lines.append(f"- {term}: {q['impressions']} impressions, {q['clicks']} clicks, position {q['position']:.1f}. {q['action']}.")
            lines.append('')
    output.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':main()
