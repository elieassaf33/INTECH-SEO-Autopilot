"""Administrator-only read-only validation of new page/source mappings."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from free_metadata import context
from keyword_publisher import NetlifyContent
from metadata_pages import patch,file_key


def verify_plan(planned,homes,manifest):
    lookup={t['gsc_property']:t for t in homes};client=NetlifyContent(manifest['netlify_token_path']);accepted=[];excluded=[]
    for candidate in planned:
        target=copy.deepcopy(candidate)
        try:
            parent=lookup[target['gsc_property']]
            if target['provider']!=parent['provider'] or target['kind']!=parent['kind']:raise ValueError('Provider changed')
            if target.get('page_type','homepage')=='homepage':
                if target['base_sha256']!=parent['base_sha256'] or target['original_tags']!=parent['original_tags']:raise ValueError('Original homepage source changed')
            else:
                from urllib.parse import urlsplit
                if urlsplit(target['url']).hostname!=urlsplit(parent['url']).hostname:raise ValueError('Page belongs to another host')
                page=context(target['url'])
                if page.get('canonical')!=target['url'] or not page.get('indexable',True):raise ValueError('Page is not self-canonical and indexable')
                if {k:page[k] for k in ('title','description')}!=target['metadata_baseline']:raise ValueError('Page metadata changed during enrollment')
            if target['provider']=='vps':
                if any(target[k]!=parent[k] for k in ('root','file','services','base_sha256','original_tags')):raise ValueError('VPS source mapping changed')
                source=(Path(parent['root'])/parent['file']).read_text()
                preview={**target,'_file_targets':[t for t in planned if file_key(t)==file_key(target)]}
                patch(source,preview,target['metadata_baseline'])
            else:
                if target['site_id']!=parent['site_id']:raise ValueError('Netlify site changed')
                policy=next(s for s in manifest['netlify_sites'] if s['site_id']==target['site_id'])
                if target['file'] not in policy['files']:raise ValueError('File is not in the approved release')
                data=client.request('sites/'+target['site_id']+'/files'+target['file'],raw=True)
                if hashlib.sha1(data).hexdigest()!=policy['files'][target['file']]:raise ValueError('Netlify source changed')
                if target.get('page_type')!='homepage':
                    source=data.decode();titles=re.findall(r'<title\b[^>]*>.*?</title>',source,re.I|re.S)
                    descriptions=re.findall(r'<meta\b[^>]*name=[\'\"]description[\'\"][^>]*>',source,re.I|re.S)
                    if len(titles)!=1 or len(descriptions)!=1:raise ValueError('Ambiguous page metadata')
                    target.update(base_sha256=hashlib.sha256(data).hexdigest(),original_tags={'title':titles[0],'description':descriptions[0]})
            accepted.append(target)
        except Exception as exc:excluded.append({'url':candidate['url'],'reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__})
    if {t['gsc_property'] for t in accepted if t.get('page_type','homepage')=='homepage'}!={t['gsc_property'] for t in homes}:
        raise ValueError('A registered homepage failed source validation; no replacement config was produced')
    return {'targets':accepted,'excluded':excluded}


def main():
    planned=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    homes=json.loads(Path('/etc/intech-seo-repairs/metadata-targets.json').read_text())
    manifest=json.loads(Path('/etc/intech-seo-repairs/manifest.json').read_text())
    print(json.dumps(verify_plan(planned,homes,manifest),ensure_ascii=True,indent=2))

if __name__=='__main__':main()
