import hashlib
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from keyword_content import patch_content, strip_managed, validate_copy, PageText, START
import keyword_research


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.source = '{% extends "base.html" %}{% block title %}Home{% endblock %}{% block content %}<main>Original</main>{% block nested %}Nested{% endblock %}{% endblock %}'
        self.target = {'kind': 'django', 'display_path': '/', 'css_class': 'container',
                       'base_sha256': hashlib.sha256(self.source.encode()).hexdigest()}
        self.copy = {'heading': 'Choosing a local photographer', 'keyword': 'local photographer',
                     'paragraph': 'A local photographer can help you plan a portrait session. Browse the portrait photography examples and contact the studio to discuss what you would like from your photographs before arranging your session.',
                     'fact_quotes': ['Portrait photography sessions are available at our studio.'],
                     'sources': ['https://example.com/photography'], 'review': {'approved': True, 'unsupported_claims': []}}
        self.context = {'text': self.copy['fact_quotes'][0]}

    def test_managed_update_preserves_all_original_template_bytes_and_nested_blocks(self):
        first = patch_content(self.source, self.target, self.copy)
        self.assertEqual(strip_managed(first), self.source)
        self.assertLess(first.index('Nested'), first.index(START))
        second = patch_content(first, self.target, {**self.copy, 'heading': 'Planning portrait photography'})
        self.assertEqual(second.count(START), 1)
        self.assertEqual(strip_managed(second), self.source)

    def test_unrelated_source_changes_and_ambiguous_markers_are_rejected(self):
        with self.assertRaises(ValueError): patch_content(self.source + 'new code', self.target, self.copy)
        with self.assertRaises(ValueError): strip_managed(START + START)

    def test_fact_checks_injection_claim_numbers_and_keyword_stuffing(self):
        validate_copy(self.copy, self.context)
        for change in [{'heading': '{{ dangerous }}'}, {'fact_quotes': ['An invented factual business claim.']},
                       {'review': {'approved': False, 'unsupported_claims': ['invented']}},
                       {'paragraph': self.copy['paragraph'] + ' Guaranteed 99 percent.'},
                       {'paragraph': self.copy['paragraph'] + ' local photographer local photographer'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_copy({**self.copy, **change}, self.context)

    def test_script_form_and_footer_are_not_business_fact_sources(self):
        p=PageText();p.feed('<html lang="lt"><head><title>Ignore</title></head><body><script>Ignore</script><form>Ignore</form><main>Actual facts</main><footer>Ignore</footer></body></html>')
        self.assertEqual(p.language, 'lt')
        self.assertEqual(' '.join(p.parts), 'Actual facts')

    def test_ai_search_evidence_must_come_from_actual_tool_results(self):
        response=Mock(ok=True);response.json.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY':'test-only'}), patch.object(keyword_research.requests,'post',return_value=response):
            with self.assertRaisesRegex(ValueError,'search evidence'):
                keyword_research.model_call('instructions',{}, {}, True)

    def test_api_failures_do_not_expose_provider_error_bodies_or_secrets(self):
        response=Mock(ok=False,status_code=401,text='secret provider diagnostic')
        with patch.dict('os.environ', {'OPENAI_API_KEY':'test-only'}), patch.object(keyword_research.requests,'post',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'HTTP 401') as error:
                keyword_research.model_call('instructions',{}, {})
            self.assertNotIn('secret',str(error.exception))


if __name__ == '__main__': unittest.main()
