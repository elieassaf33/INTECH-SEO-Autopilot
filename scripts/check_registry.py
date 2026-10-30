"""CI validation; pin monitored properties against accidental loss."""
from pathlib import Path
from client_registry import load_registry

EXPECTED = {'lbelectrical.uk', 'getintech.lt', 'getintech.eu', 'alisosfotografija.lt',
            'klaipedosaliejus.lt', 'jegaainis.lt', 'cardbrostcg.com', 'teslaeu.eu',
            'tvarikirpeja.lt', 'naturalusmaistas.lt', 'cardbrostcg.co.uk',
            'grikiudievas.lt', 'thefurrytale.com'}
REPOSITORIES = {
    'lbelectrical.uk': 'LB_Electrical', 'getintech.lt': 'commerce_well',
    'getintech.eu': 'commerce_well', 'alisosfotografija.lt': 'alisos_foto_django',
    'klaipedosaliejus.lt': 'klaipedos_aliejus', 'jegaainis.lt': 'jegaainis',
    'cardbrostcg.com': 'pokemon', 'teslaeu.eu': 'nemokek.lt',
    'tvarikirpeja.lt': 'ainos_plauku', 'naturalusmaistas.lt': 'naturalus_maistas',
    'cardbrostcg.co.uk': 'pokemon', 'grikiudievas.lt': 'grikiu_dievas',
    'thefurrytale.com': 'thefurrytale',
}


def check(path):
    sites = load_registry(path)
    if not {'sc-domain:' + domain for domain in EXPECTED} <= {s.get('gsc_property') for s in sites}:
        raise ValueError('A monitored property has been removed')
    for site in sites:
        domain = site.get('gsc_property', '').removeprefix('sc-domain:')
        if domain in REPOSITORIES:
            repo = REPOSITORIES[domain]
            if site.get('repository') != 'elieassaf33/' + repo:
                raise ValueError(f'Owner-confirmed repository mapping changed for {domain}')
            expected_branch = 'master' if repo in ('commerce_well', 'alisos_foto_django') else 'main'
            if site.get('default_branch') != expected_branch:
                raise ValueError(f'Verified default branch changed for {domain}; reverify it before updating')
    cardbros = [s for s in sites if s.get('gsc_property') in ('sc-domain:cardbrostcg.com', 'sc-domain:cardbrostcg.co.uk')]
    if len({s['client_id'] for s in cardbros}) != 1 or any(s.get('repository') != 'elieassaf33/pokemon' for s in cardbros):
        raise ValueError('CardBros must share one client identity and repository')
    print(f'Validated {len(sites)} monitored properties')


if __name__ == '__main__':
    check(Path(__file__).resolve().parents[1] / 'seo-sites.json')
