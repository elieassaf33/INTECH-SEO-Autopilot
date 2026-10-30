"""Keep artifacts, then fail on missing access or incomplete technical audits."""
import json
import os
from pathlib import Path


def main():
    report = json.loads(Path('seo-reports/controller/report.json').read_text(encoding='utf-8'))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        lines = ['# SEO property health', '', '| Property | GSC | Technical |', '|---|---|---|']
        for s in report['sites']:
            prop = str(s.get('gsc_property', '')).replace('|', '').replace('\n', '').replace('\r', '')
            lines.append(f"| {prop} | {s['gsc']['status']} | {s.get('status', 'error')} |")
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write('\n'.join(lines) + '\n')
    bad = [s for s in report['sites'] if s['gsc']['status'] not in ('ok', 'no_data') or s.get('status') != 'ok']
    if bad:
        raise SystemExit(f'{len(bad)} properties require attention; see report artifacts')


if __name__ == '__main__':
    main()
