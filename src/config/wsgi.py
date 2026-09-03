"""
WSGI config for Django 15-Factor Application Accelerator project.

This module contains the WSGI application used by Django's development server
and any production WSGI deployments. It should expose a module-level variable
named ``application``. Django's ``runserver`` and ``runfcgi`` commands discover
this application via the ``WSGI_APPLICATION`` setting.

Usually you will have the standard Django WSGI application here, but it also
might make sense to replace the whole Django WSGI application with a custom one
that later delegates to the Django one. For example, you could introduce WSGI
middleware here, or combine a Django application with an application of another
framework.

"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Deliberately below the settings default above: importing this module reads
# DJANGO_SETTINGS_MODULE. The `# noqa: E402` that used to sit here went with the
# `sys.path` insert, whose `SRC_DIR = ...` assignment was what tripped the rule --
# ruff tolerates several things before an import (a docstring, `__future__`,
# conditional blocks, and mutations of `os.environ` *and* `sys.path`), so lint is
# not what would catch a re-added insert. tests/unit/test_import_roots.py is.
from config.observability import configure_observability

configure_observability()

# This application object is used by any WSGI server configured to use this
# file. This includes Django's development server, if the WSGI_APPLICATION
# setting points here.
application = get_wsgi_application()
