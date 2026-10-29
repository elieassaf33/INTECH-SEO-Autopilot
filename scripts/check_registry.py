"""CI validation; pin monitored properties against accidental loss."""
from pathlib import Path
from client_registry import load_registry

EXPECTED = {'lbelectrical.uk', 'getintech.lt', 'getintech.eu', 'alisosfotografija.lt',
            'klaipedosaliejus.lt', 'jegaainis.lt', 'cardbrostcg.com', 'teslaeu.eu',
            'tvarikirpeja.lt', 'naturalusmaistas.lt', 'cardbrostcg.co.uk',
            'grikiudievas.lt', 'thefurrytale.com'}


def check(path):
    sites = load_registry(path)
    if not {'sc-domain:' + domain for domain in EXPECTED} <= {s.get('gsc_property') for s in sites}:
        raise ValueError('A monitored property has been removed')
    cardbros = [s for s in sites if s.get('gsc_property') in ('sc-domain:cardbrostcg.com', 'sc-domain:cardbrostcg.co.uk')]
    if len({s['client_id'] for s in cardbros}) != 1 or any(s.get('repository') != 'elieassaf33/pokemon' for s in cardbros):
        raise ValueError('CardBros must share one client identity and repository')
    print(f'Validated {len(sites)} monitored properties')


if __name__ == '__main__':
    check(Path(__file__).resolve().parents[1] / 'seo-sites.json')
