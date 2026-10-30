"""Verify the actual ADC identity against every registered GSC property."""
import json
import os
from pathlib import Path
from client_registry import load_registry
from intech_controller import search_console


def main():
    os.environ['GCP_USE_ADC'] = 'true'
    sites = load_registry(Path(__file__).resolve().parents[1] / 'seo-sites.json')
    results = []
    for site in sites:
        result = search_console(site)
        results.append({'property': site['gsc_property'], 'status': result['status'],
                        'identity': result.get('identity'),
                        'access': result.get('access'), 'site_metrics': result.get('site_metrics'),
                        'indexing': result.get('indexing')})
    output = Path('seo-reports/verification')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'gsc-access.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    for result in results:
        print(result['property'], result['status'])
    if any(r['status'] not in ('ok', 'no_data') for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
