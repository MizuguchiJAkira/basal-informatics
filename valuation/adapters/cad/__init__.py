"""CAD adapter registry.

Adding a county is a two-file change:
  1. New module ``valuation/adapters/cad/<slug>.py`` with one subclass
     of ``CADAdapter``.
  2. One line in ``_REGISTRY`` below.

No pipeline code outside this package needs to change.
"""

from __future__ import annotations

from valuation.adapters.cad.base import (  # noqa: F401  re-exports
    CADAdapter, CADRecord, CLASSIFICATION_VALUES,
)
from valuation.adapters.cad.brazos_tx import BrazosCADAdapter
from valuation.adapters.cad.kimble_tx import KimbleCADAdapter
from valuation.adapters.cad.llano_tx import LlanoCADAdapter


_REGISTRY: dict[str, CADAdapter] = {
    "kimble_tx": KimbleCADAdapter(),
    "brazos_tx": BrazosCADAdapter(),
    "llano_tx":  LlanoCADAdapter(),
}


def get_adapter(county_slug: str) -> CADAdapter | None:
    """Look up the adapter for a county.

    Returns ``None`` if no adapter is registered. Caller is expected
    to fail loud rather than silently substitute another county's
    adapter — the wrong adapter would produce a CADRecord whose
    ``classification`` and dollar values are for the wrong parcel.
    """
    return _REGISTRY.get(county_slug)


def registered_counties() -> list[str]:
    """Stable list of county slugs the registry knows about."""
    return sorted(_REGISTRY.keys())
