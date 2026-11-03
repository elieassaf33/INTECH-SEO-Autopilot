"""Page-filtered 28-day comparisons; descriptive evidence, never causal attribution."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
from change_history import windows, PT
from gsc_api import request

MIN_IMPRESSIONS = 100
MIN_CLICKS = 10
NOTE = 'Observed before/after comparison, not proof the metadata caused a change. Query mix, seasonality, rankings and Google snippet choices can affect results.'
FINAL = {'observed_improvement','observed_decline','mixed','no_clear_change','insufficient_data'}


def page_metrics(session, prop, url, period):
    body = request(session,'post','https://searchconsole.googleapis.com/webmasters/v3/sites/'+quote(prop,safe='')+'/searchAnalytics/query',json={
        'startDate':period[0], 'endDate':period[1], 'dimensions':[], 'aggregationType':'byPage',
        'type':'web', 'dataState':'final', 'dimensionFilterGroups':[{'groupType':'and','filters':[
            {'dimension':'page','operator':'equals','expression':url}]}]})
    rows=body.get('rows',[])
    if not rows: return None
    if len(rows)!=1:raise ValueError('Page aggregate response is ambiguous')
    row=rows[0]; result={key:float(row.get(key,0)) for key in ('clicks','impressions','ctr','position')}
    if any(not math.isfinite(value) or value<0 for value in result.values()): raise ValueError('Invalid Google metrics')
    result['clicks']=int(result['clicks']); result['impressions']=int(result['impressions'])
    result['ctr']=result['clicks']/result['impressions'] if result['impressions'] else 0
    if not result['impressions']: result['position']=None
    return result


def assess(before,after):
    if not before or not after:
        return {'status':'insufficient_data','before_metrics':before,'after_metrics':after,'reason':'A period has no returned page aggregate; missing rows are not assumed to be zero traffic.'}
    delta={'clicks':after['clicks']-before['clicks'], 'impressions':after['impressions']-before['impressions'],
           'ctr_percentage_points':(after['ctr']-before['ctr'])*100,
           'click_change_percent':(after['clicks']/before['clicks']-1)*100 if before['clicks'] else None,
           'position_improvement':before['position']-after['position'] if before['position'] is not None and after['position'] is not None else None}
    result={'before_metrics':before,'after_metrics':after,'delta':delta}
    if min(before['impressions'],after['impressions'])<MIN_IMPRESSIONS or before['clicks']+after['clicks']<MIN_CLICKS:
        return {**result,'status':'insufficient_data','reason':f'Needs at least {MIN_IMPRESSIONS} impressions in each period and {MIN_CLICKS} combined clicks.'}
    clicks=delta['click_change_percent']; ctr=delta['ctr_percentage_points']
    up=(clicks is not None and clicks>=10) or ctr>=.3
    down=(clicks is not None and clicks<=-10) or ctr<=-.3
    result['status']='mixed' if up and down else 'observed_improvement' if up else 'observed_decline' if down else 'no_clear_change'
    result['confounders']=[]
    if abs(delta['position_improvement'] or 0)>=2: result['confounders'].append('Average ranking position changed substantially.')
    if before['impressions'] and abs(after['impressions']/before['impressions']-1)>=.5: result['confounders'].append('Search exposure changed by at least 50%.')
    return result


def evaluate(changes, session=None, previous=None, now=None, fetch=page_metrics, max_queries=50):
    now=now or dt.datetime.now(dt.timezone.utc); today=now.astimezone(PT).date()
    cache={r['change_id']:r for r in (previous or {}).get('results',[])}; results=[]; queried=0
    published=sorted((r for r in changes if r.get('status')=='published'),key=lambda r:r['published_at'],reverse=True)
    for record in published:
        period=windows(record['published_at'])
        base={k:record[k] for k in ('change_id','target_id','gsc_property','url','published_at')}
        fingerprint=hashlib.sha256(json.dumps({k:record[k] for k in ('change_id','target_id','gsc_property','url','published_at','before','after')},sort_keys=True).encode()).hexdigest()
        result={**base,**period,'source_fingerprint':fingerprint,'note':NOTE}
        following=[r for r in published if r['change_id']!=record['change_id'] and r['gsc_property']==record['gsc_property'] and r['url']==record['url'] and dt.datetime.fromisoformat(record['published_at'])<dt.datetime.fromisoformat(r['published_at'])]
        if any(dt.datetime.fromisoformat(r['published_at']).astimezone(PT).date()<=dt.date.fromisoformat(period['after'][1]) for r in following):
            result.update(status='overlapping_change',reason='Another metadata change occurred inside the observation window.')
        elif today<dt.date.fromisoformat(period['ready_date']):
            result.update(status='waiting_for_data',days_remaining=(dt.date.fromisoformat(period['ready_date'])-today).days)
        elif record['change_id'] in cache and cache[record['change_id']].get('source_fingerprint')==fingerprint and cache[record['change_id']]['status'] in FINAL:
            result=cache[record['change_id']]
        elif session is None:
            result.update(status='credentials_unavailable',reason='Search Console read-only credentials are unavailable.')
        elif queried>=max_queries:
            result.update(status='deferred',reason='Daily evaluation limit reached; try on the next run.')
        else:
            try:
                queried+=1
                before=fetch(session,record['gsc_property'],record['url'],period['before'])
                after=fetch(session,record['gsc_property'],record['url'],period['after'])
                result.update(assess(before,after))
            except Exception:
                result.update(status='error',reason='Page performance collection failed; no values were inferred.')
        results.append(result)
    return {'generated_at':now.isoformat(),'results':results,'note':NOTE}


def main():
    p=argparse.ArgumentParser();p.add_argument('--history',required=True);p.add_argument('--previous');p.add_argument('--output',default='seo-reports/insights/performance.json');a=p.parse_args()
    history=json.loads(Path(a.history).read_text(encoding='utf-8'));previous=json.loads(Path(a.previous).read_text(encoding='utf-8')) if a.previous and Path(a.previous).exists() else None
    session=None
    if os.environ.get('GCP_USE_ADC')=='true':
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/webmasters.readonly']);session=AuthorizedSession(credentials)
        except Exception:pass
    report=evaluate(history.get('changes',[]),session,previous)
    report['credentials_status']='ok' if session else 'unavailable'
    if session and history.get('changes'):
        # Confirm the real page-filtered API connection without inventing a mature comparison.
        probe=next((r for r in history['changes'] if r.get('status')=='published'),None)
        if probe:
            end=dt.datetime.now(PT).date()-dt.timedelta(days=3)
            try:
                page_metrics(session,probe['gsc_property'],probe['url'],[(end-dt.timedelta(days=27)).isoformat(),end.isoformat()])
                report['connection_probe']={'status':'ok','url':probe['url']}
            except Exception:
                report['credentials_status']='unavailable'
                report['connection_probe']={'status':'error'}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if session:session.close()
    print(json.dumps({'changes':len(report['results']),'statuses':sorted({r['status'] for r in report['results']})}))
    return int(any(r['status'] in ('error','credentials_unavailable') for r in report['results']))

if __name__=='__main__':raise SystemExit(main())
