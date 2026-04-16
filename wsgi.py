"""WSGI entry points for Gunicorn.

Gunicorn can't call create_app(site='strecker') inline — it needs a
module-level application object. This file provides one for each site.

Usage:
    gunicorn wsgi:strecker_app   # Hunter-facing
    gunicorn wsgi:basal_app      # Enterprise-facing
"""

import os

from web.app import create_app

# Determine mode from environment
_demo = os.environ.get("DEMO_MODE", "0") == "1"

# Build only the app for the active SITE. Building both doubles boot time
# and causes N workers × 2 apps = 2N concurrent db.create_all() + migrations
# against the shared Postgres, which can exceed the health-check window.
_site = os.environ.get("SITE", "strecker")
if _site == "basal":
    basal_app = create_app(demo=_demo, site="basal")
    app = basal_app
else:
    strecker_app = create_app(demo=_demo, site="strecker")
    app = strecker_app
