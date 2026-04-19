"""Extract hunter-provided ground-truth labels from trail-cam filenames.

Hunters who curate their SD cards routinely fold species tags into
filenames — the TNDeer dump uses ``CF Pig 2025-05-19 Goldilocks MH.JPG``
for hand-labeled photos alongside ``MFDC1727.JPG`` for Moultrie-defaults.
When those labels are present we get per-photo ground truth for free,
which the worker uses to compute a classifier accuracy report at the
end of a job without any extra annotation work.

This module is the single source of truth for:

  - The filename → ground-truth mapping (``extract_ground_truth``)
  - The reconciliation that compares classifier predictions to
    ground-truth labels (``build_accuracy_report``)

Kept dependency-free (stdlib only) so the web container can import
it without pulling torch.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Iterable, Optional


_SPECIES_WORDS = re.compile(
    r'\b(Pig|Hog|Deer|Buck|Doe|Fawn|Elk|Turkey|Bear|Coyote|Fox|'
    r'Bobcat|Raccoon|Opossum|Squirrel)\b',
    re.IGNORECASE)


# Hunter lexicon → Basal species_key (same mapping used by the
# regression-fixture builder in scripts/build_tndeer_fixture.py).
_SPECIES_MAP = {
    "pig":    "feral_hog", "hog":    "feral_hog",
    "deer":   "white_tailed_deer", "buck": "white_tailed_deer",
    "doe":    "white_tailed_deer", "fawn": "white_tailed_deer",
    "elk":    "elk",
    "turkey": "turkey",
    "bear":   "black_bear",
    "coyote": "coyote",
    "fox":    "fox",
    "bobcat": "bobcat",
    "raccoon":  "raccoon",
    "opossum":  "opossum",
    "squirrel": "squirrel",
}


def extract_ground_truth(filename: str) -> Optional[str]:
    """Return the Basal species_key inferred from a filename, or None.

    ``None`` covers two cases: (a) the filename doesn't contain a
    recognisable species word, (b) the species word is "Unknown" or
    some sentinel the hunter uses for "I didn't classify this one."

    >>> extract_ground_truth("CF Pig 2025-05-19 Goldilocks MH.JPG")
    'feral_hog'
    >>> extract_ground_truth("CF Elk 2025-05-22 (2).JPG")
    'elk'
    >>> extract_ground_truth("MFDC1727.JPG") is None
    True
    >>> extract_ground_truth("IMG_0042.JPG") is None
    True
    """
    base = os.path.basename(filename)
    m = _SPECIES_WORDS.search(base)
    if not m:
        return None
    return _SPECIES_MAP.get(m.group(1).lower())


def build_accuracy_report(
    predictions: Iterable[tuple[str, str | None]],
) -> dict:
    """Compute a classifier accuracy report from ``(filename, pred)`` pairs.

    Args:
        predictions: iterable of ``(filename, predicted_species_key)``
            tuples. ``predicted_species_key`` may be None for photos
            the classifier flagged as empty / below the SpeciesNet
            confidence threshold.

    Returns:
        Report dict suitable for JSON-serialising into
        ``ProcessingJob.accuracy_report_json``::

            {
              "n_total": 142,          # total photos in the job
              "n_labeled": 107,        # photos with a filename-derived label
              "n_matched": 94,         # labeled photos where pred == label
              "n_missed": 8,           # labeled as animal, classifier said empty
              "n_confused": 5,         # labeled as X, classifier said Y (≠ X)
              "per_species": {
                "feral_hog": {
                  "labeled": 14, "matched": 13, "missed": 0,
                  "confused_as": {"white_tailed_deer": 1}
                },
                ...
              }
            }

    Photos with no ground-truth label (``None`` from
    extract_ground_truth) contribute only to ``n_total`` — they
    don't score against accuracy.
    """
    n_total = 0
    n_labeled = 0
    n_matched = 0
    n_missed = 0
    n_confused = 0
    per_species: dict[str, dict] = defaultdict(
        lambda: {"labeled": 0, "matched": 0, "missed": 0,
                 "confused_as": defaultdict(int)}
    )

    for filename, predicted in predictions:
        n_total += 1
        gt = extract_ground_truth(filename)
        if gt is None:
            continue
        n_labeled += 1
        bucket = per_species[gt]
        bucket["labeled"] += 1
        if predicted is None or predicted == "" or predicted == "unknown":
            n_missed += 1
            bucket["missed"] += 1
        elif predicted == gt:
            n_matched += 1
            bucket["matched"] += 1
        else:
            n_confused += 1
            bucket["confused_as"][predicted] += 1

    # Flatten defaultdicts for JSON friendliness
    flattened = {}
    for sp, stats in per_species.items():
        flattened[sp] = {
            "labeled":     stats["labeled"],
            "matched":     stats["matched"],
            "missed":      stats["missed"],
            "confused_as": dict(stats["confused_as"]),
        }

    return {
        "n_total":    n_total,
        "n_labeled":  n_labeled,
        "n_matched":  n_matched,
        "n_missed":   n_missed,
        "n_confused": n_confused,
        "per_species": flattened,
    }
