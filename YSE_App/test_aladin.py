"""#70: Aladin Lite v3, vendored; static hips2fits cutouts where only a picture is shown."""
import hashlib
import os
import re
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase

from .templatetags.sky_extras import hips2fits_url

APP = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(APP, 'templates')
VENDORED = os.path.join(APP, 'static', 'YSE_App', 'aladin-lite', '3.8.2')


class AladinTests(SimpleTestCase):

    def test_no_template_loads_aladin_from_cds(self):
        """The render-blocking v2 includes from CDS are gone (plan 070's first acceptance criterion)."""
        found = []
        for folder, _, files in os.walk(TEMPLATES):
            for name in files:
                path = os.path.join(folder, name)
                with open(path, encoding='utf-8', errors='replace') as f:
                    text = f.read()
                if re.search(r'aladin\.(u-strasbg|cds\.unistra)\.fr|AladinLite/api/v2', text):
                    found.append(os.path.relpath(path, TEMPLATES))
        self.assertEqual(found, [])

    def test_the_vendored_library_is_the_published_one(self):
        """aladin.js is npm's aladin-lite 3.8.2 dist file, unmodified (sha1 recorded in its README)."""
        with open(os.path.join(VENDORED, 'aladin.js'), 'rb') as f:
            digest = hashlib.sha1(f.read()).hexdigest()
        with open(os.path.join(VENDORED, 'README.md')) as f:
            readme = f.read()
        self.assertEqual(digest, '69cd12a7408686d5b1c438bba6c7d40c6b739109')
        for name in ('LICENSE', 'COPYING', 'COPYING.LESSER'):
            self.assertTrue(os.path.exists(os.path.join(VENDORED, name)), name)
        self.assertIn('3.8.2', readme)

    def test_the_loader_uses_our_copy_as_a_module(self):
        html = Template("{% include 'YSE_App/aladin_loader.html' %}").render(Context({}))
        self.assertIn('<script type="module">', html)
        self.assertIn('import A from "%sYSE_App/aladin-lite/3.8.2/aladin.js"' % settings.STATIC_URL, html)
        self.assertIn('window.aladinReady', html)

    def test_the_transient_viewer_names_its_survey_by_address_and_does_not_report_usage(self):
        """A survey name is looked up in CDS's registry, then as a path on this site, again and again while CDS
        is down; an address is one request. log: false stops Aladin sending CDS this page's URL."""
        with open(os.path.join(TEMPLATES, 'YSE_App', 'transient_detail.html')) as f:
            text = f.read()
        self.assertIn('window.aladinView(\'#aladin-lite-div\', {survey: "https://alasky.cds.unistra.fr/DSS/DSSColor"', text)
        self.assertNotIn('survey: "P/DSS2/color"', text)
        self.assertNotIn('A.aladin(', text)  # only through aladinView, which checks the survey first
        loader = Template("{% include 'YSE_App/aladin_loader.html' %}").render(Context({}))
        self.assertIn("{log: false, hipsList: []}", loader)  # no usage reports, no built-in favourites
        self.assertIn("'/properties'", loader)  # the survey is asked once before Aladin starts

    def test_hips2fits_url(self):
        url = urlparse(hips2fits_url(53.168, -27.76996, 0.017, 400, '300.0'))
        self.assertEqual((url.netloc, url.path), ('alasky.cds.unistra.fr', '/hips-image-services/hips2fits'))
        self.assertEqual(parse_qs(url.query), {
            'hips': ['CDS/P/DSS2/color'], 'ra': ['53.168'], 'dec': ['-27.76996'], 'fov': ['0.017'], 'width': ['400'],
            'height': ['300'], 'projection': ['TAN'], 'coordsys': ['icrs'], 'format': ['jpg']})

    def test_the_summary_and_sky_pages_use_static_cutouts(self):
        for name in ('YSE_App/transient_summary_individual.html', 'YSE_App/yse_sky/header.html'):
            with open(os.path.join(TEMPLATES, name)) as f:
                text = f.read()
            self.assertIn('{% hips2fits_url', text, name)
            self.assertNotIn('A.aladin', text, name)
