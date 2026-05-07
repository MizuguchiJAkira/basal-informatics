"""CAD adapter interface.

Each Texas county runs its own County Appraisal District (CAD); few
publish bulk parcel data and none publish in a uniform schema. Stage 7
abstracts that with one adapter per county slug. v1 adapters return
hand-curated snapshots for known demo parcels; v1.1 will swap individual
adapters for PTAD-download or scrape-based implementations without
touching downstream pipeline code.

Usage::

    from valuation.adapters.cad import get_adapter

    adapter = get_adapter("kimble_tx")
    record = adapter.fetch(parcel_id="TX-KIM-2026-00001",
                           as_of_date=date(2025, 10, 1))
    if record:
        # write to cad_snapshot, derive parcel_valuation_status
        ...

The adapter contract:

  * ``fetch()`` MUST be deterministic: same arguments, same output.
  * ``fetch()`` returns ``None`` for unknown parcels (don't raise).
  * Returned ``CADRecord`` carries the canonical Stage 7 classification
    enum (``ag_open_space`` | ``wildlife_open_space`` | ``timber`` |
    ``market`` | ``unknown``). Each adapter is responsible for mapping
    its county's local terminology to those keys.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from typing import Any


CLASSIFICATION_VALUES = (
    "ag_open_space",        # 1-d-1 (open-space agricultural)
    "wildlife_open_space",  # 1-d-1(w) (wildlife)
    "timber",               # §23.71 (timber)
    "market",               # market value (no special-use appraisal)
    "unknown",              # CAD didn't supply a usable classification
)


@dataclass(frozen=True)
class CADRecord:
    """One CAD record for one parcel at one as-of-date.

    Frozen so the scoring path can rely on input invariance for
    reproducibility — the same record always yields the same score.
    """
    parcel_id: str
    county_slug: str
    classification: str             # one of CLASSIFICATION_VALUES
    assessed_value_per_acre: float | None
    market_value_per_acre: float | None
    ownership_change_date: date | None
    as_of_date: date
    # Adapter-specific raw record. Persisted as JSON in cad_snapshot.
    # Auditors can re-derive the score from this without re-pulling.
    raw: dict[str, Any] = field(default_factory=dict)


class CADAdapter(abc.ABC):
    """Abstract base for per-county CAD adapters."""

    #: Lowercase county slug, e.g. "kimble_tx", "brazos_tx".
    county_slug: str

    @abc.abstractmethod
    def fetch(
        self, parcel_id: str, *, as_of_date: date,
    ) -> CADRecord | None:
        """Return a CAD record for ``parcel_id`` as of ``as_of_date``.

        Returns ``None`` when the parcel isn't found in this CAD's data.
        Implementations MUST NOT raise for missing parcels — that's a
        normal case during portfolio import.
        """
        raise NotImplementedError
