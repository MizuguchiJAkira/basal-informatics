"""Lender blueprint object — defined in its own module to avoid the
circular import that would otherwise occur when route modules import
``lender_bp`` from the package ``__init__``.

Pattern: ``__init__`` imports the route modules at the bottom of its
own body to register handlers, but the route modules need to import
``lender_bp`` to decorate. Keeping the Blueprint() in this leaf module
breaks the cycle — route modules ``from .blueprint import lender_bp``,
not ``from . import lender_bp``.
"""

from flask import Blueprint


lender_bp = Blueprint(
    "lender", __name__,
    url_prefix="/lender",
    template_folder="../../templates/lender",
)
