"""Deduplicated GitHub notifications for this repository's managed SEO incident."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from github_reports import GitHub

MARKER='<!-- INTECH SEO ALERT MANAGED v1 -->'
TITLE='[SEO monitoring] Action required'


def notify(client,report,assignee=''):
    issues=[]
    for page in range(1,6):
        batch=client.call('GET',f'issues?state=all&per_page=100&page={page}')
        issues.extend(batch)
        if len(batch)<100:break
    managed=next((r for r in issues if not r.get('pull_request') and r.get('title')==TITLE and MARKER in (r.get('body') or '')),None)
    incidents=sorted(report.get('incidents',[]),key=lambda r:r['key'])
    if not incidents:
        if managed and managed['state']=='open':
            client.call('POST',f"issues/{managed['number']}/comments",{'body':'All monitored pages and publishing checks have recovered. Closing this automated alert.'})
            client.call('PATCH',f"issues/{managed['number']}",{'state':'closed','state_reason':'completed'})
            return {'status':'resolved','url':managed['html_url']}
        return {'status':'healthy','notified':False}
    fingerprint=hashlib.sha256(json.dumps(incidents,sort_keys=True).encode()).hexdigest()
    tag='<!-- SEO INCIDENT '+fingerprint+' -->'
    lines=[MARKER,tag,'Daily SEO checks found issues requiring attention.','',f"Checked: {report['generated_at']}",'']
    for row in incidents:
        # No scraped page text or arbitrary HTML is ever sent as an alert message.
        url=row.get('url','').replace('`','').replace('@','%40')
        lines.append('- **'+row['code'].replace('_',' ')+'**: '+row['message']+(' URL: `'+url+'`' if url else ''))
    body='\n'.join(lines)+'\n\nSee the private SEO insights workflow artifact for the dashboard and details.'
    if managed and managed['state']=='open' and tag in managed['body']:return {'status':'already_notified','url':managed['html_url']}
    payload={'title':TITLE,'body':body,'state':'open'}
    if managed:
        client.call('PATCH',f"issues/{managed['number']}",payload)
        client.call('POST',f"issues/{managed['number']}/comments",{'body':'The active SEO incident list changed. The issue description now contains the current checks.'})
        return {'status':'updated','url':managed['html_url']}
    payload.pop('state')
    if assignee and re.fullmatch(r'[\w-]+',assignee):payload['assignees']=[assignee]
    issue=client.call('POST','issues',payload)
    return {'status':'created','url':issue['html_url']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--report',default='seo-reports/insights/health.json');a=p.parse_args()
    path=Path(a.report)
    report=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'incidents':[{
            'key':'monitoring:missing_report','code':'monitoring_failed','message':'The daily check did not produce a health report. Inspect the workflow logs.'}]}
    path.parent.mkdir(parents=True,exist_ok=True)
    result=notify(GitHub(),report,os.environ.get('SEO_ALERT_ASSIGNEE',''))
    Path(a.report).with_name('notifications.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
