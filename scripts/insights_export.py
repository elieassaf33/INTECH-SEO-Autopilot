"""Restricted read-only JSON export for the private dashboard and measurements."""
import datetime as dt
import json
from pathlib import Path
from change_history import read_changes,identity
from production_repairs import digest


def export(state='/var/lib/intech-seo-repairs',targets_path='/etc/intech-seo-repairs/metadata-targets.json'):
    targets=json.loads(Path(targets_path).read_text())
    pages=[{**{k:t.get(k) for k in ('gsc_property','url','name','page_type','slot_id')},'target_id':identity(t)} for t in targets]
    return {'status':'ok','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'changes':read_changes(state),'pages':pages,
            'exporter_sha256':digest(Path(__file__).read_bytes()),'history_module_sha256':digest(Path(__file__).with_name('change_history.py').read_bytes()),
            'targets_sha256':digest(Path(targets_path).read_bytes())}

if __name__=='__main__':print(json.dumps(export(),ensure_ascii=False,indent=2))
