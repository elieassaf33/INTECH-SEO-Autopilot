"""No paid API: discover new phrases and propose metadata only for supported matches."""
import argparse
import datetime as dt
import json
from pathlib import Path
from free_metadata import context,suggestions,copy_for,eligible


def select_properties(targets, limit=0):
    properties=list(dict.fromkeys(t['gsc_property'] for t in targets))
    if limit<0:raise ValueError('Property limit must be zero (all) or positive')
    return properties[:limit] if limit else properties


def research(target,audit,fetch=suggestions,get_context=context):
    page=get_context(target['url']); ideas={}; errors=[]
    for seed in target['keywords'][:4]:
        try:
            for term in fetch(seed,target['language'],target['country']):
                ideas.setdefault(term.casefold(),{'keyword':term,'seed':seed,'source':'google_autocomplete','search_volume':None})
        except Exception:
            errors.append({'seed':seed,'error':'Autocomplete unavailable'})
    output={'gsc_property':target['gsc_property'],'status':'no_suitable_keyword','scope':'metadata_only',
            'ideas':list(ideas.values()),'errors':errors,'target_id':target.get('target_id',target['gsc_property']),'url':target['url']}
    observed={}
    for row in audit.get('gsc',{}).get('queries',[]):
        term=(row.get('keyword') or row.get('query','')).strip()
        if row.get('page')!=target['url'] or not term:continue
        observed[term.casefold()]=row.get('impressions',0)
        if eligible(term,target):
            ideas.setdefault(term.casefold(),{'keyword':term,'source':'google_search_console','search_volume':None})
    # Actual page demand takes precedence over autocomplete; autocomplete failure
    # must not prevent using an observed, independently validated search phrase.
    candidates=sorted(ideas.values(),key=lambda r:(-observed.get(r['keyword'].casefold(),0),r['keyword']))
    for item in candidates:
        # A homepage keeps its broad topic. Product-specific autocomplete expansions
        # remain ideas until there is a dedicated page policy.
        if not eligible(item['keyword'],target): continue
        try: copy=copy_for(item['keyword'],target,page)
        except ValueError: continue
        if copy['title']==page['title'] and copy['description']==page['description']:
            output.update(status='unchanged',keyword=item['keyword'],**copy)
            return output
        output.update(status='approved',keyword=item['keyword'],**copy)
        return output
    if errors and len(errors)==len(target['keywords'][:4]):
        output.update(status='blocked',reason='All autocomplete requests failed')
    return output


def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--limit',type=int,default=0,help='Maximum properties; zero researches all configured properties')
    p.add_argument('--targets',default='metadata-targets.json');p.add_argument('--output',default='seo-reports/metadata/proposals.json')
    args=p.parse_args();audit=json.loads(Path(args.audit).read_text(encoding='utf-8'))
    age=dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(audit['generated_at'])
    if not dt.timedelta(0)<=age<=dt.timedelta(days=7): raise ValueError('Audit must be at most seven days old')
    indexed={s['gsc_property']:s for s in audit['sites']};results=[]
    targets=json.loads(Path(args.targets).read_text(encoding='utf-8'))
    selected=select_properties(targets,args.limit)
    for target in [t for t in targets if t['gsc_property'] in selected]:
        try:
            item=indexed[target['gsc_property']]
            if item.get('gsc',{}).get('status') not in ('ok','no_data'): raise ValueError('Audit access is incomplete')
            results.append(research(target,item))
        except Exception:
            results.append({'gsc_property':target['gsc_property'],'status':'blocked','reason':'Site context or audit unavailable','scope':'metadata_only','target_id':target.get('target_id',target['gsc_property']),'url':target['url']})
    report={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'metadata_only','results':results}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'property':r['gsc_property'],'status':r['status'],'ideas':len(r.get('ideas',[]))} for r in results]))
    return int(any(r['status']=='blocked' for r in results))

if __name__=='__main__':raise SystemExit(main())
