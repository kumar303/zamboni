import os

from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^(?P<tpl_path>[^/]+)$', views.template,
        name='ui_demo.template'),
    (r'^media/(?P<path>.*)$', 'django.views.static.serve',
     {'document_root': os.path.join(views.UI_MEDIA_DIR, 'media')}),
)
