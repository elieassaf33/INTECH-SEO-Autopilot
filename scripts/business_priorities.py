"""Owner-selected commercial priorities; never inferred revenue or write policies."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]


def load_priorities(path=None,registry=None):
    path=Path(path) if path else ROOT/'business-priorities.json'
    if not path.exists():return {}
    document=json.loads(path.read_text(encoding='utf-8'))
    sites=document['sites']
    registry=registry if registry is not None else json.loads((ROOT/'seo-sites.json').read_text(encoding='utf-8'))
    hosts={s['gsc_property']:urlsplit(s['url']).hostname.removeprefix('www.') for s in registry if s.get('gsc_property')}
    for prop,site in sites.items():
        if prop not in hosts or type(site['priority']) is not int or site['priority']<1:raise ValueError('Invalid business property priority')
        seen=set()
        for page in site['pages']:
            url=page['url'];parts=urlsplit(url)
            if parts.scheme!='https' or (parts.hostname or '').removeprefix('www.')!=hosts[prop] or parts.username or parts.password or parts.query or parts.fragment or parts.port not in (None,443) or url in seen:raise ValueError('Invalid business landing page')
            seen.add(url)
    return sites


def priority_targets(priorities):
    return [{'name':site['name'],'gsc_property':prop,'target_id':prop+'::'+urlsplit(page['url']).path,
             'url':page['url'],'page_type':page['role'],'business_priority':site['priority']}
            for prop,site in priorities.items() for page in site['pages']]
