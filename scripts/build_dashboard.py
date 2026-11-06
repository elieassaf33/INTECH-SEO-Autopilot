"""Generate a self-contained private HTML dashboard; no external hosting or trackers."""
import argparse
import datetime as dt
import json
from pathlib import Path
from business_priorities import load_priorities

ROOT=Path(__file__).resolve().parents[1]


def load(path,default):return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() and Path(path).stat().st_size else default


def build(directory,targets=None):
    directory=Path(directory)
    data={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'targets':[
        {k:t.get(k) for k in ('target_id','gsc_property','url','page_type','name','keywords')}
        for t in (targets if targets is not None else load(ROOT/'metadata-targets.json',[]))]}
    for name,default in [('audit',{}),('health',{}),('history',{}),('performance',{}),('research',{}),('publication',{}),('notifications',{})]:
        data[name]=load(directory/(name+'.json'),default)
    data['business_priorities']=load_priorities()
    payload=json.dumps(data,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=(ROOT/'assets/seo-dashboard.html').read_text(encoding='utf-8-sig')
    if template.count('__SEO_DATA__')!=1:raise ValueError('Dashboard template marker is ambiguous')
    return template.replace('__SEO_DATA__',payload),data


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',default='seo-reports/insights');a=p.parse_args()
    output=Path(a.directory);output.mkdir(parents=True,exist_ok=True);html,data=build(output)
    (output/'index.html').write_text(html,encoding='utf-8',newline='\n')
    (output/'dashboard-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Private dashboard generated:',output/'index.html')

if __name__=='__main__':main()
