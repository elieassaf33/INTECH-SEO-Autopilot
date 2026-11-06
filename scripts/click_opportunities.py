"""Prioritize observed search demand; estimates are planning heuristics, not forecasts."""
import argparse
import json
from pathlib import Path


def opportunities(audit, limit=10):
    clients=[]
    for site in audit.get('sites',[]):
        pages={}
        for row in site.get('gsc',{}).get('queries',[]):
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
        ranked=sorted(pages.values(),key=lambda p:(-p['priority_score'],p['url']))[:limit]
        for page in ranked:
            page['priority_score']=round(page['priority_score'],2)
            page['queries']=sorted(page['queries'],key=lambda q:-q['impressions'])[:5]
        clients.append({'name':site['name'],'gsc_property':site.get('gsc_property'),
            'data_status':site.get('gsc',{}).get('status','unavailable'),'pages':ranked})
    return {'note':'Scores prioritize observed query/page samples using heuristic CTR bands. They are not traffic forecasts; query data is partial. Content and link changes require review.','sites':clients}


def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=opportunities(json.loads(Path(a.audit).read_text(encoding='utf-8')))
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Search click opportunities','',report['note'],'']
    for site in report['sites']:
        lines.extend(['## '+site['name'],'','Search Console: '+site['data_status'],''])
        if not site['pages']:lines.extend(['No qualifying opportunity in the available data.',''])
        for page in site['pages']:
            lines.extend([page['url'],''])
            for q in page['queries']:
                term=q['query'].replace('\n',' ').replace('\r',' ')
                lines.append(f"- {term}: {q['impressions']} impressions, {q['clicks']} clicks, position {q['position']:.1f}. {q['action']}.")
            lines.append('')
    output.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':main()
