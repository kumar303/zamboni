# -*- coding: utf-8 -*-
from django import http
from django.conf import settings
from django import test

from commonware.middleware import HidePasswordOnException
from mock import patch
from nose.tools import eq_, raises
from pyquery import PyQuery as pq
from test_utils import RequestFactory

import amo.tests
from amo.middleware import LazyPjaxMiddleware
from amo.urlresolvers import reverse
from zadmin.models import Config, _config_cache


class TestMiddleware(amo.tests.TestCase):

    def test_no_vary_cookie(self):
        # We don't break good usage of Vary.
        response = test.Client().get('/')
        eq_(response['Vary'], 'Accept-Language, User-Agent, X-Mobile')

        # But we do prevent Vary: Cookie.
        response = test.Client().get('/', follow=True)
        eq_(response['Vary'], 'X-Mobile, User-Agent')


def test_redirect_with_unicode_get():
    response = test.Client().get('/da/firefox/addon/5457?from=/da/firefox/'
            'addon/5457%3Fadvancedsearch%3D1&lang=ja&utm_source=Google+%E3'
            '%83%90%E3%82%BA&utm_medium=twitter&utm_term=Google+%E3%83%90%'
            'E3%82%BA')
    eq_(response.status_code, 301)


def test_trailing_slash_middleware():
    response = test.Client().get(u'/en-US/firefox/about/?xxx=\xc3')
    eq_(response.status_code, 301)
    assert response['Location'].endswith('/en-US/firefox/about?xxx=%C3%83')


class AdminMessageTest(amo.tests.TestCase):

    def test_message(self):
        c = Config()
        c.key = 'site_notice'
        c.value = 'ET Sighted.'
        c.save()

        if ('site_notice',) in _config_cache:
            del _config_cache[('site_notice',)]

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(doc('#site-notice').text(), 'ET Sighted.')

        c.delete()

        del _config_cache[('site_notice',)]

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(len(doc('#site-notice')), 0)


def test_hide_password_middleware():
    request = RequestFactory().post('/', dict(x=1, password=2, password2=2))
    request.POST._mutable = False
    HidePasswordOnException().process_exception(request, Exception())
    eq_(request.POST['x'], '1')
    eq_(request.POST['password'], '******')
    eq_(request.POST['password2'], '******')


class TestLazyPjaxMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.patch = patch.object(settings, 'PJAX_SELECTOR', '#page')
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def process(self, page_content, title=''):
        request = self.factory.get('/', HTTP_X_PJAX=True)
        response = self.view(request, page_content, title=title)
        return LazyPjaxMiddleware().process_response(request, response)

    def view(self, request, page_content, title=''):
        if title:
            title = '<title>%s</title>' % title
        return http.HttpResponse("""<html>%s<body>
                                    <div id="header">the header</div>
                                    <div id="page">%s</div>
                                    </body></html>""" % (title, page_content))

    def test_render_text(self):
        eq_(self.process('the page').content, 'the page')

    def test_render_empty(self):
        eq_(self.process('').content, '')

    def test_render_mixed(self):
        eq_(self.process('the page <div>foo</div>').content,
            'the page <div>foo</div>')

    def test_render_nested(self):
        eq_(self.process('<div><b>strong</b> tea</div>').content,
            '<div><b>strong</b> tea</div>')

    def test_trailing_text(self):
        eq_(self.process('head <b>middle</b> tail').content,
            'head <b>middle</b> tail')

    def test_title(self):
        eq_(self.process('the page', title='Title').content,
            '<title>Title</title>the page')

    def test_unicode(self):
        rs = self.process(u'Ivan Krsti\u0107 <div>Ivan Krsti\u0107</div>')
        eq_(rs.content,
            'Ivan Krsti&#196;&#135; <div>Ivan Krsti&#196;&#135;</div>')

    @raises(ValueError)
    @patch.object(settings, 'DEBUG', True)
    def test_missing_page_element(self):
        request = self.factory.get('/', HTTP_X_PJAX=True)
        response = http.HttpResponse('<html><body></body></html>')
        LazyPjaxMiddleware().process_response(request, response)

    @patch.object(settings, 'DEBUG', False)
    def test_missing_page_element_logged_in_prod(self):
        request = self.factory.get('/', HTTP_X_PJAX=True)
        body = '<html><body></body></html>'
        response = http.HttpResponse(body)
        response = LazyPjaxMiddleware().process_response(request, response)
        eq_(response.content, body)

    def test_non_200_response(self):
        request = self.factory.get('/', HTTP_X_PJAX=True)
        response = http.HttpResponse('<html><body>Error</body></html>',
                                     status=500)
        response = LazyPjaxMiddleware().process_response(request, response)
        assert response.content.startswith('<html>'), (
                    'Did not expect a pjax response: %s' % response.content)
