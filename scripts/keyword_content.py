"""Shared bounded text and template checks for weekday keyword content."""
import hashlib
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit
from technical_audit import fetch

START = '<!-- INTECH SEO CONTENT START -->'
END = '<!-- INTECH SEO CONTENT END -->'


def normalized(value):
    return ' '.join(value.split())


def strip_managed(source):
    if START not in source and END not in source:
        return source
    if source.count(START) != 1 or source.count(END) != 1 or source.index(START) > source.index(END):
        raise ValueError('Ambiguous managed content markers')
    return re.sub(re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '', source, count=1, flags=re.S)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = []; self.language = ''
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html': self.language = attrs.get('lang', '')
        if tag in ('script', 'style', 'nav', 'footer', 'form', 'head'):
            self.skip.append(tag)
    def handle_endtag(self, tag):
        if self.skip and tag == self.skip[-1]: self.skip.pop()
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def page_context(url):
    host = urlsplit(url).hostname
    response = fetch(url, {host})
    if response.get('status') != 200 or response.get('truncated') or 'text/html' not in response.get('content_type', ''):
        raise ValueError('Homepage unavailable, redirected or incomplete')
    parser = PageText(); parser.feed(strip_managed(response['body'].decode('utf-8')))
    text = normalized(' '.join(parser.parts))[:18000]
    if len(text) < 150: raise ValueError('Insufficient business source text')
    return {'url': url, 'language': parser.language, 'text': text}


def validate_copy(proposal, context):
    for field, low, high in [('heading', 8, 120), ('paragraph', 100, 1000), ('keyword', 3, 100)]:
        value = proposal.get(field)
        if not isinstance(value, str) or not low <= len(value) <= high or any(c in value for c in '<>{}\x00\r\n'):
            raise ValueError('Invalid plain text: ' + field)
    if not 25 <= len(proposal['paragraph'].split()) <= 120:
        raise ValueError('Content must be one concise useful paragraph')
    content = proposal['heading'] + ' ' + proposal['paragraph']
    count = content.casefold().count(proposal['keyword'].casefold())
    if not 1 <= count <= 2: raise ValueError('Keyword missing or repeated excessively')
    quotes = proposal.get('fact_quotes', [])
    if not 1 <= len(quotes) <= 4 or any(not isinstance(q, str) or len(q) < 20 or normalized(q) not in context['text'] for q in quotes):
        raise ValueError('Business facts must quote the current original homepage')
    if set(re.findall(r'\d+(?:[.,]\d+)?', content)) - set(re.findall(r'\d+(?:[.,]\d+)?', ' '.join(quotes))):
        raise ValueError('Unsupported numbers in content')
    sources = proposal.get('sources', [])
    if not 1 <= len(sources) <= 8 or any(urlsplit(s).scheme != 'https' or not urlsplit(s).hostname or urlsplit(s).username for s in sources):
        raise ValueError('Search evidence requires real HTTPS sources')
    if proposal.get('review', {}).get('approved') is not True or proposal['review'].get('unsupported_claims') != []:
        raise ValueError('Independent factual/language review did not pass')


def content_anchor(source, kind):
    if kind == 'django':
        stack = []
        found = False
        for match in re.finditer(r'{%\s*(block\s+(\w+)|endblock(?:\s+\w+)?)\s*%}', source):
            if match.group(2):
                stack.append(match.group(2))
                if match.group(2) == 'content':
                    if found: raise ValueError('Multiple content blocks')
                    found = True
            elif stack:
                name = stack.pop()
                if name == 'content': return match.start()
        raise ValueError('No complete homepage content block')
    for pattern in [r'</main\s*>', r'<footer\b', r'</body\s*>']:
        matches = list(re.finditer(pattern, source, re.I))
        if len(matches) == 1: return matches[0].start()
    raise ValueError('No unique static content anchor')


def patch_content(current, target, proposal):
    original = strip_managed(current)
    if hashlib.sha256(original.encode()).hexdigest() != target['base_sha256']:
        raise ValueError('Homepage source changed outside the managed section')
    section = ('<section class="' + html.escape(target['css_class'], quote=True) + '" data-intech-keyword="' +
               html.escape(proposal['keyword'], quote=True) + '"><h2>' + html.escape(proposal['heading']) +
               '</h2><p>' + html.escape(proposal['paragraph']) + '</p></section>')
    if target['kind'] == 'django':
        section = "{% if request.path == '" + target['display_path'] + "' %}" + section + '{% endif %}'
    block = START + '\n' + section + '\n' + END + '\n'
    offset = content_anchor(original, target['kind'])
    result = original[:offset] + block + original[offset:]
    if strip_managed(result) != original: raise ValueError('Managed section invariant failed')
    return result
