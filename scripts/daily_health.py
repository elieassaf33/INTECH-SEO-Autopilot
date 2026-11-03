"""Daily confirmed public-page checks; no website writes or inferred outage verdicts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from production_repairs import Metadata
from technical_audit import fetch


class HealthParser(Metadata):
    def __init__(self):
        super().__init__();self.title_count=0;self.noindex=False
    def handle_starttag(self,tag,attrs):
        super().handle_starttag(tag,attrs);attrs=dict(attrs)
        if self.head and tag=='title':self.title_count+=1
        if self.head and tag=='meta' and attrs.get('name','').lower() in ('robots','googlebot'):
            if set(re.split(r'[\s,]+',attrs.get('content','').lower())) & {'noindex','none'}:self.noindex=True


def check_page(target,fetcher=fetch,sleep=time.sleep):
    url=target['url'];row={'target_id':target.get('target_id',target['gsc_property']),'gsc_property':target['gsc_property'],
        'url':url,'name':target.get('name',target['gsc_property']),'issues':[]}
    response=None
    for attempt in range(3):
        response=fetcher(url,{urlsplit(url).hostname})
        if response.get('status')==200 and not response.get('truncated'):break
        if attempt<2:sleep(3 if attempt==0 else 7)
    status=response.get('status');row['http_status']=status
    if status!=200:
        row['issues'].append({'code':'availability_failed' if status is None or status>=500 or status==404 else 'check_unavailable',
                              'message':'Page failed repeated availability checks.' if status is None or status>=500 or status==404 else 'Page could not be checked; access or rate limiting may apply.'})
    elif response.get('truncated') or 'text/html' not in response.get('content_type',''):
        row['issues'].append({'code':'incomplete_page','message':'Page response is incomplete or is not HTML.'})
    else:
        parser=HealthParser();parser.feed(response['body'].decode('utf-8','replace'))
        if parser.title_count!=1 or not parser.values['title'].strip():row['issues'].append({'code':'missing_title','message':'Title is missing or ambiguous.'})
        if len(parser.values['description'])!=1 or not parser.values['description'][0]:row['issues'].append({'code':'missing_description','message':'Description is missing or ambiguous.'})
        header=set(re.split(r'[\s,:]+',response.get('x_robots_tag','').lower()))
        if parser.noindex or header & {'noindex','none'}:row['issues'].append({'code':'unexpected_noindex','message':'A configured public page declares noindex.'})
    row['status']='needs_attention' if row['issues'] else 'healthy'
    return row


def run(targets,workflows=None,history=None,now=None,checker=check_page):
    now=now or dt.datetime.now(dt.timezone.utc)
    unique={t['url']:t for t in targets}
    with ThreadPoolExecutor(max_workers=4) as pool:pages=list(pool.map(checker,unique.values()))
    incidents=[{'key':r['url']+'#'+issue['code'],'gsc_property':r['gsc_property'],'url':r['url'],**issue}
               for r in pages for issue in r['issues']]
    for item in workflows or []:
        workflow=item.get('workflow','unknown');record=item.get('run')
        if item.get('status')=='unavailable':
            incidents.append({'key':'workflow:'+workflow,'code':'workflow_unavailable','message':'Latest workflow status could not be read.','workflow':workflow})
        elif record and record.get('conclusion') not in ('success','skipped'):
            incidents.append({'key':'workflow:'+workflow,'code':'workflow_failed','message':'Latest completed workflow did not succeed.','workflow':workflow,'url':record.get('html_url','')})
        elif workflow=='intech-seo-controller.yml' and (not record or now-dt.datetime.fromisoformat(record['updated_at'].replace('Z','+00:00'))>dt.timedelta(days=10)):
            incidents.append({'key':'audit:stale','code':'audit_stale','message':'No successful main audit within ten days.'})
    if history and history.get('status')=='unavailable':
        incidents.append({'key':'history:unavailable','code':'history_unavailable','message':'The installed change-history export is unavailable.'})
    for change in (history or {}).get('changes',[]):
        incomplete=change.get('status')=='needs_review' or change.get('status')=='planned' and now-dt.datetime.fromisoformat(change['published_at'])>dt.timedelta(hours=1)
        if incomplete:incidents.append({'key':'change:'+change['change_id'],'code':'publication_incomplete','message':'A publication has no confirmed completion; inspect its recovery receipt.','url':change['url']})
    return {'generated_at':now.isoformat(),'pages':pages,'incidents':incidents,'healthy_pages':sum(r['status']=='healthy' for r in pages),'page_count':len(pages)}


def load(path,default):return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',default='seo-reports/insights');p.add_argument('--targets',default='metadata-targets.json');a=p.parse_args()
    directory=Path(a.directory);directory.mkdir(parents=True,exist_ok=True)
    sources=load(directory/'sources.json',[])
    # Previous dashboard retrieval is a cache, not a workflow health dependency.
    sources=[r for r in sources if r['workflow']!='seo-insights.yml']
    report=run(load(a.targets,[]),sources,load(directory/'history.json',{'status':'unavailable'}))
    performance=load(directory/'performance.json',{})
    if performance.get('credentials_status')=='unavailable' or any(r.get('status')=='error' for r in performance.get('results',[])):
        report['incidents'].append({'key':'performance:unavailable','code':'performance_unavailable','message':'Search Console change-performance collection needs attention.'})
    (directory/'health.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked_pages':report['page_count'],'incidents':len(report['incidents'])}))
    return int(bool(report['incidents']))

if __name__=='__main__':raise SystemExit(main())
