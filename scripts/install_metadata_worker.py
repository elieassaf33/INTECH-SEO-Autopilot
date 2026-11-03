"""Administrator installation of the tested, root-owned metadata-only command."""
import datetime as dt,hashlib,json,os,shutil,stat,subprocess
from pathlib import Path

if os.geteuid()!=0:raise SystemExit('Administrator installation required')
package=Path(__file__).resolve().parents[1]
destination=Path('/usr/local/lib/intech-seo-repairs')
dispatcher=Path('/usr/local/sbin/intech-seo-repairs')
state=Path('/var/lib/intech-seo-repairs')
if destination.is_symlink() or destination.stat().st_uid!=0 or destination.stat().st_mode & 0o022:
    raise SystemExit('Installed worker directory is not root-controlled')
existing=dispatcher.read_text()
if 'metadata)' in existing:raise SystemExit('Metadata command already installed; review before replacing')
expected='''#!/bin/sh
set -eu
case "${SSH_ORIGINAL_COMMAND:-}" in
  apply) exec /usr/bin/python3 /usr/local/lib/intech-seo-repairs/worker.py --apply ;;
  check) exec /usr/bin/python3 /usr/local/lib/intech-seo-repairs/worker.py ;;
  *) printf 'Only the installed SEO worker is allowed.\\n' >&2; exit 126 ;;
esac
'''
if existing!=expected:raise SystemExit('Restricted dispatcher changed; review required')
if (package/'scripts/production_repairs.py').read_bytes()!=(destination/'worker.py').read_bytes():
    raise SystemExit('Existing recovery worker differs from tested dependency')
modules=['free_metadata.py','metadata_worker.py','keyword_publisher.py','keyword_content.py','production_repairs.py','technical_audit.py']
if any((destination/name).exists() for name in modules):raise SystemExit('New worker files already exist; review required')
# No server application code or privileged operations are supplied by Actions.
backup=state/dt.datetime.now(dt.timezone.utc).strftime('metadata-install-%Y%m%dT%H%M%S%f')
backup.mkdir(mode=0o700);shutil.copy2(dispatcher,backup/'dispatcher.before')
for name in modules:
    shutil.copyfile(package/'scripts'/name,destination/name);os.chmod(destination/name,0o600)
config=Path('/etc/intech-seo-repairs/metadata-targets.json')
if config.exists():raise SystemExit('Metadata source config already exists; review required')
shutil.copyfile(package/'metadata-targets.json',config);os.chmod(config,0o600)
updated=existing.replace('  *) printf', '  metadata) exec /usr/bin/python3 /usr/local/lib/intech-seo-repairs/metadata_worker.py --apply ;;\n  *) printf')
temporary=dispatcher.with_suffix('.metadata-new');temporary.write_text(updated);os.chmod(temporary,0o755)
subprocess.run(['/bin/sh','-n',str(temporary)],check=True)
os.replace(temporary,dispatcher)
receipt={'backup':str(backup),'modules':{name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in modules},
         'targets_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'scope':'metadata_only'}
(backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({'installed':'metadata_only','backup':str(backup),'properties':len(json.loads(config.read_text()))}))
