import logging
import sys

from django.conf import settings
from django import http

from jingo import env, get_standard_processors
import jingo
import jinja2
from jinja2.runtime import new_context
from jinja2.utils import concat


log = logging.getLogger('z.pjax')


def render(request, template, context=None, **kwargs):
    """
    A wrapper around jingo's ``render`` that adds Pjax support.

    Usage::

        return render(request, 'template.html')

    Here is another example with a template context and keywords for
    :class:`django.http.HttpResponse`::

        return render(request, 'template.html', {'some_var': 42}, status=209)

    Pjax requests are those requested with HTTP_X_PJAX.  For a Pjax request,
    a specific block in the template is rendered and returned.  The block
    name must be configured in settings.PJAX_BLOCK (example: 'page_content').
    """
    if request.META.get('HTTP_X_PJAX'):
        if not isinstance(template, jinja2.environment.Template):
            template = env.get_template(template)
        block = find_block(template, settings.PJAX_BLOCK)
        if block is None:
            msg = ('Pjax: template %s for %s does not contain block %r for '
                   '(inherited templates are ignored)'
                   % (template, request.path, settings.PJAX_BLOCK))
            if settings.DEBUG:
                # Tell the developer the template is bad.
                raise ValueError(msg)
            else:
                log.error(msg)
        else:
            return render_block_response(request, template, block,
                                         context=context, **kwargs)

    return jingo.render(request, template, context=context, **kwargs)


def find_block(template, block_name):
    for name, render in template.blocks.iteritems():
        if name == block_name:
            return render


def render_block_response(request, template, block_render, context=None,
                          **kwargs):
    shared = False
    locals_ = None
    vars_ = get_context(request, context)
    ctx = new_context(template.environment, template.name, template.blocks,
                      vars_, shared, template.globals, locals_)
    try:
        rendered = concat(block_render(ctx))
    except:
        exc_info = sys.exc_info()
        rendered = template.environment.handle_exception(exc_info, True)

    return http.HttpResponse(rendered, **kwargs)


def get_context(request, context=None):
    # TODO(Kumar) make this importable from jingo
    c = {} if context is None else context.copy()
    for processor in get_standard_processors():
        c.update(processor(request))
    return c
