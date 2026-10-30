"""Write a credential-free permission checklist from observed property results."""
import json


def write_access_actions(report, output):
    actions, unverified = [], []
    for site in report['sites']:
        gsc = site['gsc']
        if gsc['status'] == 'access_denied':
            access = gsc.get('access', {})
            actions.append({
                'gsc_property': site['gsc_property'], 'client_id': site['client_id'],
                'identity': gsc.get('identity', 'Configured ADC identity (email not reported)'),
                'http_status': access.get('http_status'),
                'action': 'Verify this exact property in Search Console > Settings > Users and permissions; grant the monitoring service account Full user access, then rerun verification.',
            })
        elif gsc['status'] not in ('ok', 'no_data'):
            unverified.append({'gsc_property': site.get('gsc_property'), 'status': gsc['status']})
    payload = {'generated_at': report['generated_at'], 'permission_actions': actions,
               'other_unverified_properties': unverified,
               'verification_command': 'gh workflow run verify-gsc.yml --repo elieassaf33/INTECH-SEO-Autopilot --ref main'}
    (output / 'access-actions.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    lines = ['# Search Console access actions', '',
             'These are actions for the property owner; no permissions were changed.', '',
             'Windsor access and Google Cloud IAM roles do not grant per-property Search Console access.', '']
    for action in actions:
        prop = action['gsc_property'].replace('\n', '').replace('\r', '')
        identity = action['identity'].replace('\n', '').replace('\r', '')
        lines += [f"## {prop}", f"Monitoring identity: `{identity}`", f"Observed property lookup: HTTP {action['http_status']}", action['action'], '']
    if not actions:
        lines.append('No property-level access denials observed in this run.')
    if unverified:
        lines += ['', 'Other properties remain unverified due to setup, transport or partial-data errors; see health.json and report.json.']
    lines += ['', 'After granting access, run the verification workflow on the reviewed default branch:', '',
              '```text', payload['verification_command'], '```', '']
    (output / 'access-actions.md').write_text('\n'.join(lines), encoding='utf-8')
