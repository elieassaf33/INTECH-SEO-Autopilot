"""Read-only page enrollment plan; the server separately verifies source bindings."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import re
from urllib.parse import urljoin,urlsplit,unquote
import xml.etree.ElementTree as ET
from free_metadata import context,supported
from technical_audit import fetch


def page_type(url):
    path=unquote(urlsplit(url).path).lower()
    if re.search(r'/(admin|account|cart|checkout|login|search|privacy|cookies|slapuku|privatumo)(/|[.-]|$)',path):return None
    if re.search(r'/(products|produktai|prekes|vehicles|automobiliai)/?$',path):return 'category'
    if re.search(r'/(products?|produktas|produktai|preke|prekes|vehicles?|automobiliai|dovanu-kuponas)(/|$)',path):return 'product'
    if re.search(r'/(category|categories|kategorija|kategorijos|shop)(/|$)',path):return 'category'
    if re.search(r'/(services|service|paslaugos|fotosesijos)(/|$)',path):return 'service'
    return None


def sitemap_candidates(home):
    hosts={urlsplit(home['url']).hostname};response=fetch(urljoin(home['url'],'/sitemap.xml'),hosts)
    if response.get('status')!=200 or response.get('truncated'):return []
    root=ET.fromstring(response['body']);urls=[el.text.strip() for el in root.findall('.//{*}loc') if el.text]
    if root.tag.rsplit('}',1)[-1]=='sitemapindex':
        result=[]
        for url in urls[:2]:
            if urlsplit(url).hostname not in hosts:continue
            child=fetch(url,hosts)
            if child.get('status')==200 and not child.get('truncated'):
                result.extend(el.text.strip() for el in ET.fromstring(child['body']).findall('.//{*}loc') if el.text)
        urls=result
    return urls[:300]


def enroll(home,audit,max_pages=2,get_context=context,get_sitemap=sitemap_candidates):
    if home.get('alias_of'):return []
    rows=audit.get('gsc',{}).get('queries',[]);host=urlsplit(home['url']).hostname
    scores={}
    for row in rows:scores[row.get('page','')]=scores.get(row.get('page',''),0)+row.get('impressions',0)
    try:urls=list(dict.fromkeys([r.get('page','') for r in rows]+get_sitemap(home)))
    except Exception:urls=list(scores)
    valid=[]
    for url in urls:
        parsed=urlsplit(url);kind=page_type(url)
        if parsed.scheme!='https' or parsed.hostname!=host or parsed.query or parsed.fragment or not kind or len(parsed.path)>180:continue
        if parsed.username or parsed.password or '..' in parsed.path or '\\' in parsed.path:continue
        if home['display_path'].startswith('/en/') and not parsed.path.startswith('/en/'):continue
        valid.append(url)
    valid.sort(key=lambda u:(-scores.get(u,0),u));planned=[]
    for url in valid[:15]:
        if len(planned)>=max_pages:break
        try:
            page=get_context(url)
            if page.get('canonical')!=url or not page.get('indexable',True):continue
            if not page['title'] or not page['description']:continue
            words=[]
            for row in sorted(rows,key=lambda r:-r.get('impressions',0)):
                term=row.get('keyword') or row.get('query','')
                if row.get('page')==url and supported(term,page):words.append(term)
            heading=re.split(r'\s+[|&\u2013\u2014]\s+',page['title'])[0].strip()
            if supported(heading,page):words.append(heading)
            short=' '.join(heading.split()[:3]).strip(' ,:;.-')
            if supported(short,page):words.append(short)
            words=list(dict.fromkeys(words))[:4]
            if not words:continue
            target=copy.deepcopy(home);path=unquote(urlsplit(url).path)
            target.update(target_id=home['gsc_property']+'::'+path,url=url,checks=[url],display_path=path,
                          page_type=page_type(url),slot_id=home['slot_id']+':'+path,keywords=words,
                          metadata_baseline={k:page[k] for k in ('title','description')},language=page['language'].split('-')[0] or home['language'])
            if target['kind']=='django' and not re.fullmatch(r'/[\w/-]*',path):continue
            if target['kind']=='static':
                prefix='/_en' if home['file'].startswith('/_en/') else ''
                target['file']=prefix+urlsplit(url).path+('index.html' if path.endswith('/') else '')
                target.pop('original_tags',None);target.pop('base_sha256',None)
            planned.append(target)
        except Exception:continue
    return planned


def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--output',default='seo-reports/insights/page-plan.json');a=p.parse_args()
    homes=json.loads(Path('metadata-targets.json').read_text(encoding='utf-8'));audit=json.loads(Path(a.audit).read_text(encoding='utf-8'))
    indexed={r['gsc_property']:r for r in audit['sites']}
    for home in homes:home.setdefault('target_id',home['gsc_property']);home.setdefault('page_type','homepage')
    with ThreadPoolExecutor(max_workers=4) as pool:children=list(pool.map(lambda h:enroll(h,indexed.get(h['gsc_property'],{})),homes))
    targets=homes+[child for group in children for child in group]
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(targets,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'homepages':len(homes),'additional_pages':len(targets)-len(homes),'page_types':sorted({t['page_type'] for t in targets})}))

if __name__=='__main__':main()
