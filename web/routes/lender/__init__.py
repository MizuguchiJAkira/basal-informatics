"""Lender-facing routes — Basal Informatics Nature Exposure Reports.

These are the pages a Farm Credit loan officer or ag bank's collateral
reviewer sees. Design intent is compliance-forward:
  - No hero video, no teal consumer accent, no individual-animal tracking
  - Monochrome palette (slate/gray) with tier-specific risk colors
    (green / amber / orange / red) used only for exposure levels
  - Dense, information-first layout; every number has a method note
  - Downloadable PDF report (planned)

Mounted under ``/lender/`` on the ``site="basal"`` Flask app only — the
Strecker hunter-facing app never registers this blueprint.

Access control: requires ``is_owner=True`` at v1 (the same check Basal's
existing owner routes use). In production this splits further into
LenderClient-scoped access — each lender sees only their own parcels.
Deferred until we have more than one lender.

Module layout (post-split, 2026-05-10)
---------------------------------------

This package replaces a 1,210-line ``lender.py`` monolith. The same
public surface (``lender_bp`` + the few names imported by app.py and
tests) is re-exported here for backward compatibility.

  blueprint.py       Just the ``Blueprint()`` definition. Imported by
                     every other module to avoid circular imports.
  helpers.py         Shared compute + report-shape helpers.
  portfolio.py       ``GET /``, ``GET /<lender_slug>/``.
  parcel_report.py   ``GET /<lender_slug>/parcel/<id>``,
                     ``GET /<lender_slug>/parcel/<id>/upload``.
  api.py             ``GET  /api/<slug>/parcel/<id>/exposure``,
                     ``POST /api/<slug>/parcel/<id>/valuation/override``.
"""

# Blueprint must exist before route modules import it.
from .blueprint import lender_bp  # noqa: F401

# Re-exports kept for back-compat with existing callers.
#   - app.py:  ``from web.routes.lender import lender_bp,
#                                              parcel_valuation_override``
#   - tests/test_invariants.py: ``from web.routes.lender import _hog_history``
from .helpers import (  # noqa: F401, E402
    _hog_history,
    lender_access_required,
)

# Importing the route modules is what registers their handlers on
# ``lender_bp``. These imports MUST come last; their decorators bind
# at import time.
from . import api  # noqa: F401, E402
from . import parcel_report  # noqa: F401, E402
from . import portfolio  # noqa: F401, E402

# Re-exported by name for ``app.py``'s ``csrf.exempt(...)`` call.
from .api import parcel_valuation_override  # noqa: F401, E402

# Re-exported for tests/test_valuation_api.py, which reaches into the
# rate-limiter's storage directly to reset state between tests. Keeping
# this back-compat import means the rate-limit test doesn't need to
# track the post-split module path.
from .api import (  # noqa: F401, E402
    _override_rate_lock,
    _override_rate_log,
)
