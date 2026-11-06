"""Prepare CardBros product metadata while preserving managed homepage rules."""
import hashlib
import re
from metadata_pages import tag_parts


def prepare(source,target):
    if any('card.name' in tag for tag in target['original_tags'].values()):
        raise ValueError('Product metadata is already installed')
    restored=source
    updated=source
    tags={}
    for field in ('title','description'):
        old=target['original_tags'][field]
        prefix,inner,suffix=tag_parts(old,field)
        if field=='title':
            dynamic='{% if card.name %}{{ card.name|truncatechars:52 }} | Card Bros TCG{% elif product.name %}{{ product.name|truncatechars:52 }} | Card Bros TCG{% else %}'+inner+'{% endif %}'
        else:
            dynamic='{% if card.name %}{{ card.name|truncatechars:65 }}. {{ card.description|striptags|truncatechars:95 }}{% elif product.name %}{{ product.name|truncatechars:65 }}. {{ product.description|striptags|truncatechars:95 }}{% else %}'+inner+'{% endif %}'
        tags[field]=prefix+dynamic+suffix
        start='<!-- INTECH META '+field.upper()+' START -->'
        end='<!-- INTECH META '+field.upper()+' END -->'
        if source.count(start)!=1 or source.count(end)!=1:raise ValueError('Expected exactly one managed metadata region')
        region=source.split(start,1)[1].split(end,1)[0]
        fallback='{% else %}'+inner+'{% endif %}'
        if region.count(fallback)!=1:raise ValueError('Unexpected managed fallback; review source')
        updated=updated.replace(start+region+end,start+region.replace(fallback,'{% else %}'+dynamic+'{% endif %}',1)+end,1)
        restored=restored.replace(start+region+end,old,1)
    if hashlib.sha256(restored.encode()).hexdigest()!=target['base_sha256']:raise ValueError('Source differs outside managed metadata')
    baseline=restored
    for field in tags:
        if baseline.count(target['original_tags'][field])!=1:raise ValueError('Ambiguous original tag')
        baseline=baseline.replace(target['original_tags'][field],tags[field],1)
    if source.split('</head>',1)[1]!=updated.split('</head>',1)[1]:raise ValueError('Body changed')
    return updated,baseline,{'original_tags':tags,'base_sha256':hashlib.sha256(baseline.encode()).hexdigest()}
