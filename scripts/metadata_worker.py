"""Root-owned, bounded title/description publisher; accepts JSON, never remote code."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
from free_metadata import context,validate,patch_metadata
from keyword_publisher import publish_vps,publish_netlify
from production_repairs import atomic_write,digest,verify
from change_history import identity,begin_change,append_event,windows,read_changes,PT
from metadata_pages import file_key


def verify_metadata(target,proposal):
    verify([{'url':url,'expected':{'title':proposal['title'],'description':[proposal['description']]}} for url in target['checks']])


def process(report,targets,manifest,state,apply=False,now=None,get_context=context,persist=lambda manifest: None):
    fixed_now=now is not None
    now=now or dt.datetime.now(dt.timezone.utc)
    age=now-dt.datetime.fromisoformat(report['generated_at'])
    if report.get('scope')!='metadata_only' or not dt.timedelta(0)<=age<=dt.timedelta(hours=24):
        raise ValueError('Only fresh metadata-only evidence is accepted')
    lookup={identity(t):t for t in targets};results=[];seen=set()
    ledger_path=state/'metadata-ledger.json';ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    for proposal in report['results']:
        prop=proposal['gsc_property'];key=proposal.get('target_id',prop)
        row={'gsc_property':prop,'target_id':key,'scope':'metadata_only'}
        change=None;published=False
        try:
            target=dict(lookup[key])
            if target['gsc_property']!=prop:raise ValueError('Page policy belongs to another property')
            target['_file_targets']=[t for t in targets if file_key(t)==file_key(target)]
            row['url']=target['url'];row['page_type']=target.get('page_type','homepage')
            if key in seen:raise ValueError('Duplicate target')
            seen.add(key)
            if proposal['status']!='approved':
                results.append({**row,'status':proposal['status']});continue
            if target.get('alias_of'):
                results.append({**row,'status':'shared_template','primary_property':target['alias_of']});continue
            previous=ledger.get(target['slot_id'])
            if previous and now.astimezone(PT).date()<dt.date.fromisoformat(windows(previous['published_at'])['ready_date']):
                results.append({**row,'status':'cooldown'});continue
            page=get_context(target['url']);validate(proposal,target,page)
            if page['title']==proposal['title'] and page['description']==proposal['description']:
                results.append({**row,'status':'unchanged'});continue
            if not apply:
                results.append({**row,'status':'validated'});continue
            change=begin_change(target,page,proposal,now)
            append_event(state,change,'planned')
            if target['provider']=='vps':
                row.update(publish_vps(target,proposal,manifest,state,patcher=patch_metadata,verifier=verify_metadata))
                published=True
                bundle=next(b for b in manifest['bundles'] if b['id']==target['client_id'])
                entry=next(f for f in bundle['files'] if f['path']==target['file'])
                import base64
                source=base64.b64decode(entry['content_base64']).decode()
                entry['recoverable_snippets']=re.findall(r'<title\b[^>]*>.*?</title>|<meta\b[^>]*name=[\'\"]description[\'\"][^>]*>|<link\b[^>]*rel=[\'\"]canonical[\'\"][^>]*>',source,re.S|re.I)
                if len(entry['recoverable_snippets'])>3:raise ValueError('Recovery snippets are ambiguous')
            else:
                row.update(publish_netlify(target,proposal,manifest,state,patcher=patch_metadata,verifier=verify_metadata))
            # Persist each success before processing another client; weekly recovery accepts it.
            published=True
            completed_at=now if fixed_now else dt.datetime.now(dt.timezone.utc)
            change['published_at']=completed_at.isoformat()
            persist(manifest)
            append_event(state,change,'published',row)
            ledger[target['slot_id']]={'published_at':completed_at.isoformat(),'keyword':proposal['keyword']}
            ledger_path.write_text(json.dumps(ledger,indent=2))
            results.append(row)
        except Exception as exc:
            if change:append_event(state,change,'needs_review' if published else 'failed',row)
            results.append({**row,'status':'blocked','reason':str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Metadata publication operation failed'})
    return results


def main():
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true')
    p.add_argument('--targets',default='/etc/intech-seo-repairs/metadata-targets.json')
    p.add_argument('--manifest',default='/etc/intech-seo-repairs/manifest.json')
    p.add_argument('--state',default='/var/lib/intech-seo-repairs');a=p.parse_args()
    raw=sys.stdin.buffer.read(1000001)
    if len(raw)>1000000:raise ValueError('Oversized request')
    state=Path(a.state);state.mkdir(mode=0o700,parents=True,exist_ok=True)
    import fcntl
    with (state/'worker.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=json.loads(Path(a.manifest).read_text())
        def persist(updated):
            atomic_write(Path(a.manifest),(json.dumps(updated,indent=2)+'\n').encode())
        results=process(json.loads(raw),json.loads(Path(a.targets).read_text()),manifest,state,a.apply,persist=persist)
        report={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'metadata_only','apply':a.apply,
                'worker_sha256':digest(Path(__file__).read_bytes()),
                'dependencies_sha256':{name:digest(Path(__file__).with_name(name).read_bytes()) for name in
                    ('free_metadata.py','keyword_publisher.py','keyword_content.py','production_repairs.py','technical_audit.py','metadata_pages.py','change_history.py')},
                'targets_sha256':digest(Path(a.targets).read_bytes()),'results':results,'changes':read_changes(state)}
        payload=json.dumps(report,ensure_ascii=False,indent=2)
        (state/'metadata-latest.json').write_text(payload)
        (state/dt.datetime.now(dt.timezone.utc).strftime('metadata-report-%Y%m%dT%H%M%S%f.json')).write_text(payload)
        print(payload)
        return int(any(r['status']=='blocked' for r in results))

if __name__=='__main__':raise SystemExit(main())
