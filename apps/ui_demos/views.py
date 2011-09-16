import os

from django import http

from jingo import render


APP_DIR = os.path.dirname(__file__)
UI_MEDIA_DIR = os.path.join(APP_DIR, 'media')


def template(request, tpl_path):
    if tpl_path.startswith('.') or not tpl_path.endswith('.html'):
        return http.HttpResponse404()
    return render(request, 'ui_demos/%s' % tpl_path,
                  {'UI_MEDIA_DIR': UI_MEDIA_DIR})
