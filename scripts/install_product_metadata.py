"""Administrator migration of CardBros product metadata and pinned recovery source."""
import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from product_metadata import prepare


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if not hasattr(os,'geteuid') or os.geteuid()!=0:raise SystemExit('Administrator installation required')
    import fcntl
    sys.path.insert(0,'/usr/local/lib/intech-seo-repairs')
    from production_repairs import atomic_write
    from free_metadata import context
    from technical_audit import fetch,MetadataParser
    from change_history import begin_change,append_event
    state=Path('/var/lib/intech-seo-repairs');config=Path('/etc/intech-seo-repairs/metadata-targets.json');manifest_path=config.with_name('manifest.json')
    def restart(services):
        for service in services:
            # The service manager allows 90 seconds to stop this application.
            subprocess.run(['systemctl','restart',service],check=True,capture_output=True,timeout=150)
    with (state/'worker.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        targets=json.loads(config.read_text());t=next(t for t in targets if t['gsc_property']=='sc-domain:cardbrostcg.com')
        path=Path(t['root'])/t['file'];source=path.read_text();updated,baseline,policy=prepare(source,t)
        manifest=json.loads(manifest_path.read_text());bundle=next(b for b in manifest['bundles'] if b['id']=='cardbros-tcg');entry=next(f for f in bundle['files'] if f['path']==t['file'])
        if entry['sha256']!=hashlib.sha256(source.encode()).hexdigest():raise ValueError('Recovery baseline does not match live source')
        if not args.apply:print(json.dumps({'status':'validated','policy':policy}));return
        before_home={u:context(u) for u in t['checks']}
        response=fetch(t['url'],{'cardbrostcg.com','www.cardbrostcg.com'});head=MetadataParser();head.feed(response['body'].decode())
        urls=sorted({'https://cardbrostcg.com'+u for u in head.links if re.fullmatch('/en/card/[0-9]+/',u)})
        if not urls:raise ValueError('No product checks found')
        before={u:context(u) for u in urls};names={}
        for u in urls:
            response=fetch(u,{'cardbrostcg.com','www.cardbrostcg.com'})
            match=re.search(r'<h1\b[^>]*>(.*?)</h1>',response['body'].decode(),re.S)
            if not match:raise ValueError('Product heading unavailable')
            names[u]=html.unescape(re.sub('<[^>]+>','',match[1])).strip()
        backup=state/('cardbros-product-metadata-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S'))
        backup.mkdir(mode=0o700);shutil.copy2(path,backup/'base.before.html');shutil.copy2(config,backup/'targets.before.json');shutil.copy2(manifest_path,backup/'manifest.before.json')
        for item in targets:
            if item['provider']=='vps' and item.get('root')==t['root'] and item['file']==t['file']:item.update(policy)
        entry.update(content_base64=base64.b64encode(updated.encode()).decode(),sha256=hashlib.sha256(updated.encode()).hexdigest())
        entry['recoverable_snippets']=re.findall(r'<title\b[^>]*>.*?</title>|<meta\b[^>]*name=[\'\"]description[\'\"][^>]*>|<link\b[^>]*rel=[\'\"]canonical[\'\"][^>]*>',updated,re.S|re.I)
        if len(entry['recoverable_snippets'])>3:raise ValueError('Ambiguous recovery snippets')
        try:
            atomic_write(path,updated.encode());atomic_write(config,(json.dumps(targets,ensure_ascii=False,indent=2)+'\n').encode());atomic_write(manifest_path,(json.dumps(manifest,indent=2)+'\n').encode());restart(t['services'])
            for u in t['checks']:
                after=context(u)
                if any(after[k]!=before_home[u][k] for k in ('title','description','canonical')):raise ValueError('Homepage changed')
            after_products={u:context(u) for u in urls}
            for u,page in after_products.items():
                name=names[u];short=name if len(name)<=52 else name[:51]+'…'
                if page['title']!=short+' | Card Bros TCG' or not page['description'].startswith(name if len(name)<=65 else name[:64]+'…'):raise ValueError('Product metadata verification failed')
        except Exception:
            atomic_write(path,(backup/'base.before.html').read_bytes());atomic_write(config,(backup/'targets.before.json').read_bytes());atomic_write(manifest_path,(backup/'manifest.before.json').read_bytes());restart(t['services']);raise
        now=dt.datetime.now(dt.timezone.utc)
        for u,page in after_products.items():
            target={**t,'target_id':t['gsc_property']+'::'+u.split('.com',1)[1],'url':u,'page_type':'product'}
            record=begin_change(target,before[u],{'keyword':names[u],**page},now)
            append_event(state,record,'published',{'backup':str(backup),'source_sha256':entry['sha256']})
        receipt={'status':'published','verified_products':len(urls),'verified_homepages':len(t['checks']),'backup':str(backup),'policy':policy,'targets_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'source_sha256':entry['sha256']}
        (backup/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))


if __name__=='__main__':main()
