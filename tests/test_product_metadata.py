import hashlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from product_metadata import prepare
from metadata_pages import patch


class ProductMetadataTests(unittest.TestCase):
    def test_product_copy_is_escaped_and_homepage_and_body_are_preserved(self):
        try:
            from django.template import Context,Engine
            from django.conf import settings
        except ImportError:self.skipTest('Django render verification requires Django')
        source='<head><title>Shop title</title><meta name="description" content="Shop description"></head><body>Preserved</body>'
        target={'kind':'django','display_path':'/en/','original_tags':{'title':'<title>Shop title</title>','description':'<meta name="description" content="Shop description">'},'base_sha256':hashlib.sha256(source.encode()).hexdigest()}
        current=patch(source,target,{'title':'Approved homepage','description':'Approved homepage description'})
        updated,baseline,policy=prepare(current,target)
        if not settings.configured:settings.configure(USE_I18N=False)
        engine=Engine()
        def render(text,path,**values):return engine.from_string(text).render(Context({'request':SimpleNamespace(path=path),**values}))
        self.assertEqual(render(current,'/en/'),render(updated,'/en/'))
        for kind in ('card','product'):
            output=render(updated,'/en/card/11/',**{kind:{'name':'A & B "card"','description':'<b>Actual product facts</b>'}})
            self.assertIn('A &amp; B &quot;card&quot; | Card Bros TCG',output)
            self.assertIn('Actual product facts',output)
            self.assertNotIn('<b>',output)
            self.assertEqual(output.split('</head>')[1],'<body>Preserved</body>')
        # Future metadata publication still accepts and preserves the new fallback.
        later=patch(updated,{**target,**policy},{'title':'Next homepage','description':'Next description'})
        self.assertIn('Next homepage',render(later,'/en/'))
        self.assertIn('Example | Card Bros TCG',render(later,'/en/card/11/',card={'name':'Example'}))
        self.assertIn('card.name',baseline)
        with self.assertRaisesRegex(ValueError,'already installed'):prepare(updated,{**target,**policy})
