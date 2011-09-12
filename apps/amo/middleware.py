"""
Borrowed from: http://code.google.com/p/django-localeurl

Note: didn't make sense to use localeurl since we need to capture app as well
"""
import contextlib
import time
import urllib

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponsePermanentRedirect
from django.middleware import common
from django.utils.cache import patch_vary_headers, patch_cache_control
from django.utils.encoding import iri_to_uri, smart_str

import commonware.log
import lxml.html
import MySQLdb as mysql
import tower
import jingo
from statsd import statsd

import amo
from . import urlresolvers
from .helpers import urlparams


class LocaleAndAppURLMiddleware(object):
    """
    1. search for locale first
    2. see if there are acceptable apps
    3. save those matched parameters in the request
    4. strip them from the URL so we can do stuff
    """

    def process_request(self, request):
        # Find locale, app
        prefixer = urlresolvers.Prefixer(request)
        urlresolvers.set_url_prefix(prefixer)
        full_path = prefixer.fix(prefixer.shortened_path)

        if 'lang' in request.GET:
            # Blank out the locale so that we can set a new one.  Remove lang
            # from query params so we don't have an infinite loop.
            prefixer.locale = ''
            new_path = prefixer.fix(prefixer.shortened_path)
            query = dict((smart_str(k), request.GET[k]) for k in request.GET)
            query.pop('lang')
            return HttpResponsePermanentRedirect(urlparams(new_path, **query))

        if full_path != request.path:
            query_string = request.META.get('QUERY_STRING', '')
            full_path = urllib.quote(full_path.encode('utf-8'))

            if query_string:
                full_path = "%s?%s" % (full_path, query_string)

            response = HttpResponsePermanentRedirect(full_path)
            # Cache the redirect for a year.
            patch_cache_control(response, max_age=60 * 60 * 24 * 365)

            # Vary on Accept-Language or User-Agent if we changed the locale or
            # app.
            old_app = prefixer.app
            old_locale = prefixer.locale
            new_locale, new_app, _ = prefixer.split_path(full_path)
            if old_locale != new_locale:
                patch_vary_headers(response, ['Accept-Language'])
            if old_app != new_app:
                patch_vary_headers(response, ['User-Agent'])
            return response

        request.path_info = '/' + prefixer.shortened_path
        tower.activate(prefixer.locale)
        request.APP = amo.APPS.get(prefixer.app, amo.FIREFOX)
        request.LANG = prefixer.locale


class NoVarySessionMiddleware(SessionMiddleware):
    """
    SessionMiddleware sets Vary: Cookie anytime request.session is accessed.
    request.session is accessed indirectly anytime request.user is touched.
    We always touch request.user to see if the user is authenticated, so every
    request would be sending vary, so we'd get no caching.

    We skip the cache in Zeus if someone has an AMOv3 cookie, so varying on
    Cookie at this level only hurts us.
    """

    def process_response(self, request, response):
        if settings.READ_ONLY:
            return response
        # Let SessionMiddleware do its processing but prevent it from changing
        # the Vary header.
        vary = response.get('Vary', None)
        new_response = (super(NoVarySessionMiddleware, self)
                        .process_response(request, response))
        if vary:
            new_response['Vary'] = vary
        else:
            del new_response['Vary']
        return new_response


class RemoveSlashMiddleware(object):
    """
    Middleware that tries to remove a trailing slash if there was a 404.

    If the response is a 404 because url resolution failed, we'll look for a
    better url without a trailing slash.
    """

    def process_response(self, request, response):
        if (response.status_code == 404
            and request.path_info.endswith('/')
            and not common._is_valid_path(request.path_info)
            and common._is_valid_path(request.path_info[:-1])):
            # Use request.path because we munged app/locale in path_info.
            newurl = request.path[:-1]
            if request.GET:
                with safe_query_string(request):
                    newurl += '?' + request.META['QUERY_STRING']
            return HttpResponsePermanentRedirect(newurl)
        else:
            return response


@contextlib.contextmanager
def safe_query_string(request):
    """
    Turn the QUERY_STRING into a unicode- and ascii-safe string.

    We need unicode so it can be combined with a reversed URL, but it has to be
    ascii to go in a Location header.  iri_to_uri seems like a good compromise.
    """
    qs = request.META['QUERY_STRING']
    try:
        request.META['QUERY_STRING'] = iri_to_uri(qs)
        yield
    finally:
        request.META['QUERY_STRING'] = qs


class CommonMiddleware(common.CommonMiddleware):

    def process_request(self, request):
        with safe_query_string(request):
            return super(CommonMiddleware, self).process_request(request)


class ReadOnlyMiddleware(object):

    def process_request(self, request):
        if request.method == 'POST':
            return jingo.render(request, 'amo/read-only.html', status=503)

    def process_exception(self, request, exception):
        if isinstance(exception, mysql.OperationalError):
            return jingo.render(request, 'amo/read-only.html', status=503)


timing_log = commonware.log.getLogger('z.timer')


class TimingMiddleware(object):

    def process_request(self, request):
        request._start = time.time()

    def process_response(self, request, response):
        auth = 'ANON'
        if hasattr(request, 'user') and request.user.is_authenticated():
            auth = 'AUTH'
        d = {'method': request.method, 'time': time.time() - request._start,
             'code': response.status_code, 'auth': auth,
             'url': smart_str(request.path_info)}
        msg = '{method} "{url}" ({code}) {time:.2f} [{auth}]'.format(**d)
        timing_log.info(msg)
        return response


pjax_log = commonware.log.getLogger('z.timer')


class LazyPjaxMiddleware(object):

    def process_request(self, request):
        # This activates JS in templates:
        request.ALLOWS_PJAX = True

    def process_response(self, request, response):
        if request.META.get('HTTP_X_PJAX') and response.status_code == 200:
            # TODO(Kumar) cache this.
            with statsd.timer('pjax.parse'):
                tree = lxml.html.document_fromstring(response.content)
                # HTML is encoded as ascii with entity refs for non-ascii.
                html = []
                found_pjax = False
                for elem in tree.cssselect('title,%s'
                                           % settings.PJAX_SELECTOR):
                    if elem.tag == 'title':
                        # Inject a <title> for jquery-pjax
                        html.append(lxml.html.tostring(elem, encoding=None))
                    else:
                        found_pjax = True
                        if elem.text:
                            html.append(elem.text.encode('ascii',
                                                         'xmlcharrefreplace'))
                        for ch in elem.iterchildren():
                            html.append(lxml.html.tostring(ch, encoding=None))
                if not found_pjax:
                    msg = ('pjax response for %s does not contain selector %r'
                           % (request.path, settings.PJAX_SELECTOR))
                    if settings.DEBUG:
                        # Tell the developer the template is bad.
                        raise ValueError(msg)
                    else:
                        pjax_log.error(msg)
                        return response

                response.content = ''.join(html)

        return response
