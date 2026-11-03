"""Bounded GitHub artifact reads and managed issue alerts, using job-scoped tokens."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import requests
import zipfile


class GitHub:
    def __init__(self, repo=None, token=None):
        self.repo=repo or os.environ['GITHUB_REPOSITORY']
        if not re.fullmatch(r'[\w.-]+/[\w.-]+',self.repo):raise ValueError('Invalid repository')
        self.session=requests.Session();self.session.headers.update({'Authorization':'Bearer '+(token or os.environ['GH_TOKEN']),
            'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    def call(self,method,path,payload=None):
        response=self.session.request(method,'https://api.github.com/repos/'+self.repo+'/'+path,json=payload,timeout=45)
        if not response.ok:raise RuntimeError('GitHub request returned HTTP '+str(response.status_code))
        return response.json() if response.content else {}
    def latest(self,workflow):
        rows=self.call('GET','actions/workflows/'+workflow+'/runs?branch=main&status=completed&per_page=1')['workflow_runs']
        return {key:rows[0].get(key) for key in ('id','conclusion','html_url','updated_at','name')} if rows else None
    def download(self,run_id,names,destination):
        artifacts=self.call('GET','actions/runs/'+str(run_id)+'/artifacts?per_page=100')['artifacts']
        for artifact in reversed(artifacts):
            if artifact.get('expired'):continue
            response=self.session.get(artifact['archive_download_url'],timeout=60,stream=True)
            if not response.ok:raise RuntimeError('Artifact download failed')
            raw=io.BytesIO()
            for chunk in response.iter_content(65536):
                raw.write(chunk)
                if raw.tell()>30_000_000:raise ValueError('Oversized artifact')
            with zipfile.ZipFile(raw) as archive:
                for wanted,filename in names.items():
                    matches=[entry for entry in archive.infolist() if Path(entry.filename).name==wanted and not entry.is_dir()]
                    if len(matches)>1:raise ValueError('Ambiguous artifact report')
                    if matches:
                        if matches[0].file_size>10_000_000:raise ValueError('Oversized report')
                        data=archive.read(matches[0]);json.loads(data)
                        out=Path(destination)/filename;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)


def collect(client,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);sources=[]
    tasks=[('intech-seo-controller.yml',{'report.json':'audit.json'}),
           ('weekday-keyword-growth.yml',{'proposals.json':'research.json','publication.json':'publication.json'}),
           ('seo-insights.yml',{'performance.json':'previous-performance.json'}),
           ('seo-production-repairs.yml',{})]
    for workflow,names in tasks:
        try:
            run=client.latest(workflow)
            if run and names:client.download(run['id'],names,output)
            sources.append({'workflow':workflow,'run':run})
        except Exception:sources.append({'workflow':workflow,'status':'unavailable'})
    (output/'sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
    return sources


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='seo-reports/insights');a=p.parse_args()
    print(json.dumps(collect(GitHub(),a.output)))

if __name__=='__main__':main()
