"""Read-only checks of configured pages and high-exposure search landing pages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from free_metadata import Head
from technical_audit import fetch
from gsc_analysis import demand_queries


def check(target):
    url=target['url'];parts=urlsplit(url);host=parts.hostname.removeprefix('www.')
    response=fetch(url,{host,'www.'+host})
    row={**target,'http_status':response.get('status'),'final_url':response['final_url'],'issues':[]}
    if response.get('status')!=200 or response.get('truncated'):
        row['issues'].append('Page could not be fully checked; review HTTP status and redirect policy')
        return row
    if 'text/html' not in response.get('content_type','').lower():
        row['issues'].append('Landing page did not return HTML');return row
    parser=Head();parser.feed(response['body'].decode('utf-8','replace'))
    row.update(parser.values)
    if not parser.values['title'].strip():row['issues'].append('Missing title')
    if not parser.values['description'].strip():row['issues'].append('Missing description')
    if parser.noindex or any(token in response.get('x_robots_tag','').lower().replace(',',' ').split() for token in ('noindex','none')):
        row['issues'].append('Landing page declares noindex; verify whether intentional')
    row['canonicals']=[urljoin(response['final_url'],c) for c in parser.canonicals]
    if len(parser.canonicals)>1:row['issues'].append('Multiple HTML canonical declarations')
    primary=target.get('primary_origin')
    approved_primary=(primary.rstrip('/')+urlsplit(response['final_url']).path).rstrip('/') if primary else None
    if row['canonicals'] and row['canonicals'][0].rstrip('/') not in {response['final_url'].rstrip('/'),approved_primary}:
        row['issues'].append('HTML canonical points to another URL; review intended search landing page')
    return row


def targets(audit,configured):
    selected={}
    for site in audit.get('sites',[]):
        host=urlsplit(site['base_url']).hostname.removeprefix('www.')
        scores={}
        for row in demand_queries(site.get('gsc',{})):
            url=row['page'];parts=urlsplit(url)
            if parts.scheme not in ('http','https') or (parts.hostname or '').removeprefix('www.')!=host or parts.username or parts.password:continue
            scores[url]=scores.get(url,0)+row.get('impressions',0)
        urls=[site['base_url']]+sorted(scores,key=lambda u:(-scores[u],u))[:3]
        urls += [t['url'] for t in configured if t['gsc_property']==site.get('gsc_property')]
        for url in urls:selected[(site.get('gsc_property'),url)]={'name':site['name'],'gsc_property':site.get('gsc_property'),'url':url,'primary_origin':site.get('primary_origin')}
    return list(selected.values())


def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--targets',default='metadata-targets.json');p.add_argument('--output',required=True);a=p.parse_args()
    audit=json.loads(Path(a.audit).read_text(encoding='utf-8'));configured=json.loads(Path(a.targets).read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=4) as pool:pages=list(pool.map(check,targets(audit,configured)))
    report={'scope':'read_only','pages':pages,'checked_pages':len(pages),'pages_needing_review':sum(bool(r['issues']) for r in pages)}
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Search landing page checks','','Read-only live HTML checks; canonical differences and noindex directives require review.','']
    for row in pages:
        if row['issues']:lines.extend([row['name']+' — '+row['url']]+['- '+issue for issue in row['issues']]+[''])
    output.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('checked_pages','pages_needing_review')}))


if __name__=='__main__':main()
