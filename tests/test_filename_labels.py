"""Ground-truth extraction from hunter-curated filenames.

Backs strecker.filename_labels. The reconciliation logic runs at the
end of every worker job; these tests guard the mapping table and the
per-species confusion accounting.
"""

from strecker.filename_labels import (
    build_accuracy_report, extract_ground_truth,
)


# ---------------------------------------------------------------------------
# extract_ground_truth
# ---------------------------------------------------------------------------

def test_extract_species_from_hunter_filenames():
    cases = [
        ("CF Pig 2025-05-19 Goldilocks MH.JPG",  "feral_hog"),
        ("CF Hog 2024-11-02.JPG",                "feral_hog"),
        ("CF Deer 2025-10-20 TS 6.JPG",          "white_tailed_deer"),
        ("CF Buck 2023-09-11 8pt.JPG",           "white_tailed_deer"),
        ("CF Doe 2024-06-03.JPG",                "white_tailed_deer"),
        ("CF Fawn 2024-06-03 birth.JPG",         "white_tailed_deer"),
        ("CF Elk 2025-05-22 (2).JPG",            "elk"),
        ("CF Bear 2025-08-28 BS.JPG",            "black_bear"),
        ("CF Turkey 2025-06-28 Tan BS.JPG",      "turkey"),
        ("CF Coyote 2024-04-01.JPG",             "coyote"),
        ("CF Fox 2024-04-01.JPG",                "fox"),
        ("CF Bobcat 2024-04-01.JPG",             "bobcat"),
        ("CF Raccoon 2024-04-01.JPG",            "raccoon"),
    ]
    for fname, expected in cases:
        assert extract_ground_truth(fname) == expected, fname


def test_untagged_filenames_return_none():
    for fname in [
        "MFDC0001.JPG",
        "MFDC1727.JPG",
        "IMG_20260419_142233.JPG",
        "",
        "random.jpg",
    ]:
        assert extract_ground_truth(fname) is None, fname


def test_case_insensitive():
    assert extract_ground_truth("cf pig 2025.JPG")    == "feral_hog"
    assert extract_ground_truth("CF PIG 2025.JPG")    == "feral_hog"
    assert extract_ground_truth("cF Pig 2025.JPG")    == "feral_hog"


def test_ignores_species_word_inside_longer_word():
    """'Pigeon' contains 'Pig' but should not match."""
    assert extract_ground_truth("Pigeon at feeder.JPG") is None


def test_accepts_path_as_well_as_basename():
    # extract_ground_truth runs os.path.basename, so a full path works too
    assert extract_ground_truth("CAM-02/CF Pig something.JPG") == "feral_hog"


# ---------------------------------------------------------------------------
# build_accuracy_report
# ---------------------------------------------------------------------------

def test_empty_report_on_no_labels():
    r = build_accuracy_report([
        ("MFDC0001.JPG", "feral_hog"),
        ("MFDC0002.JPG", None),
    ])
    assert r["n_total"]   == 2
    assert r["n_labeled"] == 0
    assert r["n_matched"] == 0
    assert r["per_species"] == {}


def test_perfect_match():
    r = build_accuracy_report([
        ("CF Pig 2025 A.JPG",  "feral_hog"),
        ("CF Deer 2025 A.JPG", "white_tailed_deer"),
        ("CF Elk 2025 A.JPG",  "elk"),
    ])
    assert r["n_total"]    == 3
    assert r["n_labeled"]  == 3
    assert r["n_matched"]  == 3
    assert r["n_missed"]   == 0
    assert r["n_confused"] == 0
    assert r["per_species"]["feral_hog"]["matched"] == 1
    assert r["per_species"]["elk"]["matched"] == 1


def test_confusion_and_miss_accounting():
    r = build_accuracy_report([
        # matched
        ("CF Pig 2025 A.JPG",  "feral_hog"),
        ("CF Pig 2025 B.JPG",  "feral_hog"),
        # confused: pig labeled, classifier said deer
        ("CF Pig 2025 C.JPG",  "white_tailed_deer"),
        # missed: labeled but classifier said None
        ("CF Deer 2025 A.JPG", None),
        # matched
        ("CF Deer 2025 B.JPG", "white_tailed_deer"),
        # untagged: ignored in accuracy math
        ("MFDC9999.JPG",       "feral_hog"),
    ])
    assert r["n_total"]    == 6
    assert r["n_labeled"]  == 5
    assert r["n_matched"]  == 3
    assert r["n_missed"]   == 1
    assert r["n_confused"] == 1

    pig = r["per_species"]["feral_hog"]
    assert pig["labeled"] == 3
    assert pig["matched"] == 2
    assert pig["confused_as"] == {"white_tailed_deer": 1}

    deer = r["per_species"]["white_tailed_deer"]
    assert deer["labeled"] == 2
    assert deer["matched"] == 1
    assert deer["missed"]  == 1


def test_unknown_classifier_treated_as_missed():
    r = build_accuracy_report([
        ("CF Pig A.JPG", ""),
        ("CF Pig B.JPG", "unknown"),
    ])
    assert r["n_missed"] == 2
    assert r["n_matched"] == 0
