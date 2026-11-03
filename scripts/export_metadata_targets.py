"""Read-only administrator export of exact installed metadata source targets."""
import hashlib,json,re,sys
from pathlib import Path
from urllib.request import Request,urlopen

m=json.loads(Path('/etc/intech-seo-repairs/manifest.json').read_text())
targets=json.loads(Path(sys.argv[1]).read_text());out=[]
for t in targets:
    try:
        if t['provider']=='vps':
            bundle=next(b for b in m['bundles'] if b['id']==t['client_id'])
            t['file']=bundle['files'][0]['path'];t['root']=bundle['root']
            data=(Path(t['root'])/t['file']).read_bytes()
            approved=next(f for f in bundle['files'] if f['path']==t['file'])
            if hashlib.sha256(data).hexdigest()!=approved['sha256']:raise ValueError('Live template differs from approved source')
        else:
            policy=next(p for p in m['netlify_sites'] if p['site_id']==t['site_id'])
            token=Path(m['netlify_token_path']).read_text().strip()
            request=Request('https://api.netlify.com/api/v1/sites/'+t['site_id']+'/files'+t['file'],headers={'Authorization':'Bearer '+token,'Content-Type':'application/vnd.bitballoon.v1.raw'})
            with urlopen(request,timeout=30) as response:data=response.read(1500001)
            if len(data)>1500000 or hashlib.sha1(data).hexdigest()!=policy['files'][t['file']]:raise ValueError('Netlify file differs from approved source')
        s=data.decode();title=re.findall(r'<title\b[^>]*>.*?</title>',s,re.I|re.S)
        desc=re.findall(r'<meta\b[^>]*name=[\'\"]description[\'\"][^>]*>',s,re.I|re.S)
        if len(title)!=1 or len(desc)!=1:raise ValueError('Ambiguous metadata source')
        t.update(base_sha256=hashlib.sha256(data).hexdigest(),original_tags={'title':title[0],'description':desc[0]})
        out.append(t)
    except Exception as exc:raise RuntimeError(t['gsc_property']+': '+type(exc).__name__+': '+str(exc)) from None
print(json.dumps(out,ensure_ascii=True,indent=2))
