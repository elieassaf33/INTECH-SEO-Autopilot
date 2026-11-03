"""Free discovery and conservative metadata copy supported by the site's own text."""
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from keyword_content import page_context, normalized
from technical_audit import fetch


class Head(HTMLParser):
    def __init__(self):
        super().__init__(); self.head=False; self.title=False; self.values={'title':'','description':''}
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='head': self.head=True
        if self.head and tag=='title': self.title=True
        if self.head and tag=='meta' and attrs.get('name','').lower()=='description':
            self.values['description']=attrs.get('content','')
    def handle_endtag(self, tag):
        if tag=='title': self.title=False
        if tag=='head': self.head=self.title=False
    def handle_data(self, data):
        if self.head and self.title: self.values['title']+=data


def context(url):
    from urllib.parse import urlsplit
    response=fetch(url,{urlsplit(url).hostname})
    if response.get('status')!=200 or response.get('truncated'):
        raise ValueError('Current homepage unavailable or incomplete')
    parser=Head(); parser.feed(response['body'].decode('utf-8'))
    return {**page_context(url),**parser.values}


def suggestions(seed, language, country):
    import time
    time.sleep(.25)
    query={'client':'firefox','q':seed,'hl':language}
    if country!='EU': query['gl']=country.lower()
    request=Request('https://suggestqueries.google.com/complete/search?'+urlencode(query),headers={'User-Agent':'INTECH-SEO-Metadata/1.0'})
    with urlopen(request,timeout=8) as response:
        data=json_load(response.read(262145))
    if not isinstance(data,list) or len(data)<2 or not isinstance(data[1],list):
        raise ValueError('Unexpected autocomplete response')
    return [v for v in data[1] if isinstance(v,str)][:10]


def json_load(raw):
    import json
    if len(raw)>262144: raise ValueError('Oversized autocomplete response')
    return json.loads(raw.decode('utf-8'))


def supported(keyword, page):
    if not isinstance(keyword,str) or not 5<=len(keyword)<=65 or not 2<=len(keyword.split())<=7:
        return False
    if any(c in keyword for c in '<>{}\r\n\x00'):
        return False
    # Demand signals are not factual proof. The full phrase must occur on this site's page.
    return re.search(r'(?<!\w)'+re.escape(normalized(keyword).casefold())+r'(?!\w)',page['text'].casefold()) is not None


def copy_for(keyword, target, page):
    if not supported(keyword,page): raise ValueError('Keyword is not supported by current visible site text')
    baseline=target['metadata_baseline']
    title=baseline['title']
    if keyword.casefold() not in title.casefold():
        candidate=keyword[0].upper()+keyword[1:]+' | '+title
        if len(candidate)<=70: title=candidate
    if len(title)>70: raise ValueError('Candidate title is too long')
    description=baseline['description']
    if keyword.casefold() not in description.casefold():
        prefix=keyword[0].upper()+keyword[1:]+'. '
        sentences=re.split(r'(?<=[.!?])\s+',description)
        selected=''
        for sentence in sentences:
            if len(prefix+selected+sentence)>170: break
            selected+=sentence+' '
        if not selected.strip(): raise ValueError('No complete existing description sentence fits')
        description=prefix+selected.strip()
    if any(c in title+description for c in '<>{}\r\n\x00'):
        raise ValueError('Metadata must be plain text')
    if not 10<=len(title)<=70 or not 30<=len(description)<=200:
        raise ValueError('Metadata copy outside configured length limits')
    if set(re.findall(r'\d+',title+' '+description))-set(re.findall(r'\d+',page['text'])):
        raise ValueError('Original metadata numbers are not supported by current visible facts')
    return {'title':title,'description':description}


def validate(proposal,target,page):
    if proposal.get('scope')!='metadata_only' or set(proposal)-{'gsc_property','status','scope','keyword','title','description','reason','ideas','errors'}:
        raise ValueError('Only metadata proposals are accepted')
    desired=copy_for(proposal['keyword'],target,page)
    if any(proposal.get(k)!=v for k,v in desired.items()):
        raise ValueError('Proposed copy differs from deterministic supported metadata')
    return desired


def patch_metadata(source,target,proposal):
    import hashlib
    originals=target['original_tags']
    restored=source
    for field in ('title','description'):
        start='<!-- INTECH META '+field.upper()+' START -->'
        end='<!-- INTECH META '+field.upper()+' END -->'
        if start in restored or end in restored:
            if restored.count(start)!=1 or restored.count(end)!=1 or restored.index(start)>restored.index(end):
                raise ValueError('Ambiguous metadata markers')
            restored=re.sub(re.escape(start)+r'.*?'+re.escape(end),lambda m:originals[field],restored,count=1,flags=re.S)
    if hashlib.sha256(restored.encode()).hexdigest()!=target['base_sha256']:
        raise ValueError('Source changed outside managed metadata')
    result=restored
    for field in ('title','description'):
        old=originals[field]
        if result.count(old)!=1: raise ValueError('Metadata tag is missing or ambiguous')
        if field=='title':
            match=re.fullmatch(r'(<title\b[^>]*>)(.*?)(</title>)',old,re.I|re.S)
        else:
            match=re.fullmatch(r'(<meta\b[^>]*\bcontent=")(.*?)("[^>]*>)',old,re.I|re.S)
        if not match: raise ValueError('Unsupported metadata tag syntax')
        value=html.escape(proposal[field],quote=True)
        if target['kind']=='django':
            path=target['display_path']
            if not re.fullmatch(r'/[a-zA-Z0-9/_-]*',path): raise ValueError('Invalid homepage path')
            value="{% if request.path == '"+path+"' %}"+value+'{% else %}'+match[2]+'{% endif %}'
        tag=match[1]+value+match[3]
        block='<!-- INTECH META '+field.upper()+' START -->'+tag+'<!-- INTECH META '+field.upper()+' END -->'
        result=result.replace(old,block,1)
    # Everything outside these two tag regions came from the unchanged source.
    return result
