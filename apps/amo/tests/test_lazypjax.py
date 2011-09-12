from django.conf import settings

import jingo
import jinja2
from mock import Mock, patch
from nose import SkipTest
from nose.tools import eq_, raises
from test_utils import RequestFactory

from amo.lazypjax import render
import amo.tests


TEMPLATES = {
    'lazypjax/base.html': """
<html>
<body>
<div id="header">the header</div>
<div id="page">
{% block page %}{% endblock %}
</div>
</body>
</html>
""",
    'lazypjax/two.html': """
{% extends "lazypjax/base.html" %}
{% block page %}block content{% endblock %}
""",
    'lazypjax/one.html': """
{% extends "lazypjax/two.html" %}
""",
    'lazypjax/parent.html': """
{% set page_url='/defined' %}
""",
    'lazypjax/child.html': """
{% extends "lazypjax/parent.html" %}
{% block page %}{{ page_url }}{% endblock %}
"""
}


class TestLazyPjax(amo.tests.TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.patches = [patch.object(settings, 'PJAX_BLOCK', 'page'),
                        patch.object(settings, 'PJAX_SELECTOR', '#content')]
        for p in self.patches:
            p.start()
        ld = jinja2.DictLoader(TEMPLATES)
        jingo.env.loader.loaders.append(ld)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def get(self, *args, **kw):
        req = self.factory.get(*args, **kw)
        req.APP = Mock()
        req.user = Mock()
        return req

    def render_tpl(self, content, request=None):
        if not request:
            request = self.get('/', HTTP_X_PJAX=True)
        tpl = jinja2.Template(content)
        return render(request, tpl)

    def test_render_block(self):
        response = self.render_tpl("""<html><body>
                                      <div id="header">the header</div>
                                      <div id="page">
                                      {% block page %}
                                      the page
                                      {% endblock %}</div>
                                      </body></html>""")
        eq_(response.content.strip(), 'the page')

    def test_nested_blocks(self):
        raise SkipTest('Not sure how to get nested blocks yet')
        request = self.get('/', HTTP_X_PJAX=True)
        response = render(request, 'lazypjax/one.html')
        eq_(response.content.strip(), 'block content')

    def test_inherited_blocks(self):
        request = self.get('/', HTTP_X_PJAX=True)
        response = render(request, 'lazypjax/two.html')
        eq_(response.content.strip(), 'block content')

    @raises(ValueError)
    @patch.object(settings, 'DEBUG', True)
    def test_missing_page_element(self):
        self.render_tpl('<html><body></body></html>')

    @patch.object(settings, 'DEBUG', False)
    def test_missing_page_element_graceful_in_prod(self):
        body = '<html><body></body></html>'
        response = self.render_tpl(body)
        eq_(response.content, body)

    def test_non_pjax_request(self):
        body = '<html><body>{% block page %}page{% endblock %}</body></html>'
        response = self.render_tpl(body, request=self.get('/'))
        eq_(response.content, '<html><body>page</body></html>')

    @raises(jinja2.TemplateAssertionError)
    def test_template_exception(self):
        self.render_tpl('<html><body>{{ nonexistant|foobar }}</body></html>')

    def test_inherit_context(self):
        raise SkipTest('Not sure how to inherit a context')
        request = self.get('/', HTTP_X_PJAX=True)
        response = render(request, 'lazypjax/child.html')
        # Make sure page_url is inherited from parent:
        eq_(response.content.strip(), '/somewhere')
