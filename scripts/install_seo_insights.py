"""One-time administrator upgrade; no website content is written by installation."""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from change_history import append_event,begin_change,identity
from free_metadata import context
from production_repairs import atomic_write


def main():
    if os.geteuid()!=0:raise SystemExit('Administrator installation required')
    package=Path(__file__).resolve().parents[1];root=Path('/usr/local/lib/intech-seo-repairs');state=Path('/var/lib/intech-seo-repairs')
    config=Path('/etc/intech-seo-repairs/metadata-targets.json');manifest_path=config.with_name('manifest.json')
    dispatcher=Path('/usr/local/sbin/intech-seo-repairs');expected=json.loads((package/'expected-installed.json').read_text())
    if root.is_symlink() or root.stat().st_uid!=0 or root.stat().st_mode & 0o022:raise ValueError('Worker directory is not root-controlled')
    for name,sha in expected['modules'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('Installed code changed: '+name)
    if hashlib.sha256(config.read_bytes()).hexdigest()!=expected['targets_sha256']:raise ValueError('Existing metadata targets changed')
    before=dispatcher.read_text()
    if 'insights)' in before or 'metadata)' not in before or before.count('  *) printf')!=1:raise ValueError('Dispatcher is not the expected pre-upgrade version')
    targets=json.loads((package/'metadata-targets.json').read_text());homes=json.loads(config.read_text());manifest=json.loads(manifest_path.read_text())
    if len({identity(t) for t in targets})!=len(targets):raise ValueError('Duplicate page target IDs')
    if {t['gsc_property'] for t in targets}!={t['gsc_property'] for t in homes}:raise ValueError('Registered property set changed')
    # Prepare reconstructed historical observations before changing installed files.
    legacy=[]
    if not (state/'metadata-changes.jsonl').exists():
        ledger=json.loads((state/'metadata-ledger.json').read_text())
        for slot,entry in ledger.items():
            target=next(t for t in homes if t['slot_id']==slot and not t.get('alias_of'))
            current=context(target['url'])
            record=begin_change(target,target['metadata_baseline'],{'keyword':entry['keyword'],**{k:current[k] for k in ('title','description')}},dt.datetime.fromisoformat(entry['published_at']))
            record['provenance']='reconstructed_from_existing_ledger';legacy.append(record)
    backup=state/dt.datetime.now(dt.timezone.utc).strftime('insights-install-%Y%m%dT%H%M%S%f')
    with (state/'worker.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        backup.mkdir(mode=0o700);shutil.copy2(config,backup/'metadata-targets.before.json');shutil.copy2(manifest_path,backup/'manifest.before.json');shutil.copy2(dispatcher,backup/'dispatcher.before')
        modules=['metadata_worker.py','free_metadata.py','metadata_pages.py','change_history.py','insights_export.py']
        existed={name:(root/name).exists() for name in modules}
        for name in modules:
            if existed[name]:shutil.copy2(root/name,backup/name)
        history_existed=(state/'metadata-changes.jsonl').exists()
        try:
            modules=['metadata_worker.py','free_metadata.py','metadata_pages.py','change_history.py','insights_export.py']
            for name in modules:
                path=root/name
                if path.exists():shutil.copy2(path,backup/name)
                temporary=root/(name+'.new');shutil.copyfile(package/'scripts'/name,temporary);os.chmod(temporary,0o600);os.replace(temporary,path)
            atomic_write(config,(package/'metadata-targets.json').read_bytes())
            # Include enrolled VPS pages in the same recovery verification as their homepages.
            for target in targets:
                if target['provider']!='vps' or target.get('page_type')=='homepage' or target.get('alias_of'):continue
                bundle=next(b for b in manifest['bundles'] if b['id']==target['client_id'])
                if not any(c['url']==target['url'] for c in bundle['checks']):
                    bundle['checks'].append({'url':target['url'],'expected':{'title':True,'description':True,'canonical':[target['url']]}})
            atomic_write(manifest_path,(json.dumps(manifest,indent=2)+'\n').encode())
            for record in legacy:append_event(state,record,'published')
            updated=before.replace('  *) printf','  insights) exec /usr/bin/python3 /usr/local/lib/intech-seo-repairs/insights_export.py ;;\n  *) printf')
            atomic_write(dispatcher,updated.encode())
        except Exception:
            for name in modules:
                path=root/name
                if existed[name]:atomic_write(path,(backup/name).read_bytes())
                elif path.exists() and path.resolve().parent==root.resolve():path.unlink()
            atomic_write(config,(backup/'metadata-targets.before.json').read_bytes())
            atomic_write(manifest_path,(backup/'manifest.before.json').read_bytes())
            atomic_write(dispatcher,(backup/'dispatcher.before').read_bytes())
            journal=state/'metadata-changes.jsonl'
            if not history_existed and journal.exists() and journal.resolve().parent==state.resolve():journal.unlink()
            raise
        (backup/'receipt.json').write_text(json.dumps({'scope':'metadata_only','pages':len(targets),'properties':len(homes),'reconstructed_changes':len(legacy),'backup':str(backup)},indent=2))
    print(json.dumps({'installed':True,'pages':len(targets),'reconstructed_changes':len(legacy),'backup':str(backup)}))

if __name__=='__main__':main()
