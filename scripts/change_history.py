"""Durable metadata change journal; plain data only, never a source of commands."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo('America/Los_Angeles')


def identity(target):
    return target.get('target_id') or target['gsc_property']


def windows(published_at):
    timestamp = dt.datetime.fromisoformat(published_at)
    if timestamp.tzinfo is None:
        raise ValueError('Change timestamps must include a timezone')
    day = timestamp.astimezone(PT).date()
    return {'before': [(day-dt.timedelta(days=28)).isoformat(), (day-dt.timedelta(days=1)).isoformat()],
            'after': [(day+dt.timedelta(days=1)).isoformat(), (day+dt.timedelta(days=28)).isoformat()],
            'ready_date': (day+dt.timedelta(days=31)).isoformat()}


def begin_change(target, page, proposal, now):
    record = {'target_id': identity(target), 'gsc_property': target['gsc_property'],
              'url': target['url'], 'page_type': target.get('page_type', 'homepage'),
              'published_at': now.isoformat(), 'keyword': proposal['keyword'],
              'before': {key: page[key] for key in ('title','description')},
              'after': {key: proposal[key] for key in ('title','description')},
              'provenance': 'captured_before_publication'}
    record['change_id'] = hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()[:24]
    return record


def append_event(state, record, status, receipt=None):
    event = {**record, 'status': status, 'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    if receipt:
        event['receipt'] = {k: receipt[k] for k in ('backup','deploy_id','previous_deploy','source_sha256') if k in receipt}
    path = Path(state)/'metadata-changes.jsonl'
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(descriptor,'a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(event, ensure_ascii=False)+'\n'); stream.flush(); os.fsync(stream.fileno())
    return event


def read_changes(state):
    path = Path(state)/'metadata-changes.jsonl'
    if not path.exists(): return []
    if path.stat().st_size > 20_000_000: raise ValueError('Change history exceeds the supported limit')
    latest = {}
    text=path.read_text(encoding='utf-8');lines=text.splitlines()
    for index,line in enumerate(lines):
        if not line.strip(): continue
        try:record = json.loads(line)
        except json.JSONDecodeError:
            if index==len(lines)-1 and not text.endswith('\n'):break
            raise
        latest[record['change_id']] = record
    return sorted(latest.values(), key=lambda r:r['published_at'])[-2000:]
