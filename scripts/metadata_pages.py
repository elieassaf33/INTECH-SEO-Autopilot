"""Compose independent page rules inside the two existing metadata tag regions."""
import base64
import hashlib
import html
import json
import re


def file_key(target):
    return (target['provider'],target.get('root') or target.get('site_id'),target['file'])


def tag_parts(tag, field):
    pattern=r'(<title\b[^>]*>)(.*?)(</title>)' if field=='title' else r'(<meta\b[^>]*\bcontent=")(.*?)("[^>]*>)'
    match=re.fullmatch(pattern,tag,re.I|re.S)
    if not match:raise ValueError('Unsupported metadata tag syntax')
    return match.groups()


def patch(source,target,proposal):
    originals=target['original_tags'];restored=source;maps={}
    group=target.get('_file_targets',[target])
    allowed={item['display_path'] for item in group} if target['kind']=='django' else {'*'}
    if any(item['base_sha256']!=target['base_sha256'] or item['original_tags']!=originals for item in group):
        raise ValueError('Page policies disagree about their shared source')
    for field in ('title','description'):
        start='<!-- INTECH META '+field.upper()+' START -->';end='<!-- INTECH META '+field.upper()+' END -->'
        values={}
        if start in restored or end in restored:
            if restored.count(start)!=1 or restored.count(end)!=1 or restored.index(start)>restored.index(end):
                raise ValueError('Ambiguous metadata markers')
            region=restored.split(start,1)[1].split(end,1)[0]
            stored=re.findall(r'<!-- INTECH META MAP ([A-Za-z0-9+/=]+) -->',region)
            if stored:
                if len(stored)!=1:raise ValueError('Ambiguous page metadata map')
                raw=base64.b64decode(stored[0],validate=True)
                if len(raw)>16000:raise ValueError('Oversized page metadata map')
                values=json.loads(raw)
                if not isinstance(values,dict) or len(values)>32:raise ValueError('Invalid page metadata map')
            else:
                # Migrate the already-installed homepage-only format without losing it.
                prefix,original,suffix=tag_parts(originals[field],field)
                match=re.fullmatch(re.escape(prefix)+r'(.*?)'+re.escape(suffix),region,re.S)
                if not match:raise ValueError('Unrecognized existing metadata rule')
                value=match[1]
                if target['kind']=='django':
                    rule=re.fullmatch(r"\{% if request.path == '([^']+)' %\}(.*?)\{% else %\}"+re.escape(original)+r'\{% endif %\}',value,re.S)
                    if not rule:raise ValueError('Unrecognized existing conditional metadata')
                    values[rule[1]]=html.unescape(rule[2])
                else:values['*']=html.unescape(value)
            restored=restored.replace(start+region+end,originals[field],1)
        if set(values)-allowed:raise ValueError('Source contains an unconfigured page rule')
        for path,value in values.items():
            if not isinstance(value,str) or len(value)>200 or any(c in value for c in '<>{}\r\n\x00'):
                raise ValueError('Invalid stored metadata copy')
        maps[field]=values
    if hashlib.sha256(restored.encode()).hexdigest()!=target['base_sha256']:
        raise ValueError('Source changed outside managed metadata')
    result=restored
    for field in ('title','description'):
        old=originals[field]
        if result.count(old)!=1:raise ValueError('Metadata tag is missing or ambiguous')
        prefix,original,suffix=tag_parts(old,field);values=maps[field]
        values[target['display_path'] if target['kind']=='django' else '*']=proposal[field]
        if target['kind']=='django':
            parts=[]
            for index,(path,value) in enumerate(sorted(values.items())):
                if not re.fullmatch(r'/[\w/-]*',path):raise ValueError('Invalid page path')
                parts.append("{% "+('if' if index==0 else 'elif')+" request.path == '"+path+"' %}"+html.escape(value,quote=True))
            inner=''.join(parts)+'{% else %}'+original+'{% endif %}'
        else:inner=html.escape(values['*'],quote=True)
        encoded=base64.b64encode(json.dumps(values,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()).decode()
        block=('<!-- INTECH META '+field.upper()+' START --><!-- INTECH META MAP '+encoded+' -->'+prefix+inner+suffix+'<!-- INTECH META '+field.upper()+' END -->')
        result=result.replace(old,block,1)
    return result
