"""
Unit tests for heuristic sidecar JSON matching.
"""

import tempfile
from pathlib import Path
from takeout_engine.matcher import find_json_for_media, bracket_swap_candidate, strip_extra_suffixes


def test_bracket_swap_candidate():
    assert bracket_swap_candidate("photo(1).jpg") == "photo.jpg(1)"
    assert bracket_swap_candidate("IMG_1234(99).HEIC") == "IMG_1234.HEIC(99)"
    assert bracket_swap_candidate("no_brackets.jpg") is None


def test_strip_extra_suffixes():
    candidates = strip_extra_suffixes("IMG_1234-edited.jpg")
    assert "IMG_1234.jpg" in candidates
    assert "IMG_1234" in candidates

    candidates_effects = strip_extra_suffixes("sample-effects.png")
    assert "sample.png" in candidates_effects


def test_find_json_heuristics():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # 1. Exact match
        photo1 = tmp / "sunset.jpg"
        photo1.touch()
        json1 = tmp / "sunset.jpg.json"
        json1.touch()

        found, reason = find_json_for_media(photo1)
        assert found == json1
        assert reason == "exact"

        # 2. 51-char truncation bug
        # e.g., name is 55 chars long -> truncated to 46 chars
        long_name = "this_is_a_very_long_file_name_that_exceeds_google_limit.jpg"
        long_photo = tmp / long_name
        long_photo.touch()
        truncated_json_name = f"{long_name[:46]}.json"
        trunc_json = tmp / truncated_json_name
        trunc_json.touch()

        found, reason = find_json_for_media(long_photo)
        assert found == trunc_json
        assert reason == "truncated_46"

        # 3. Bracket swap
        photo_dup = tmp / "family(1).jpg"
        photo_dup.touch()
        json_dup = tmp / "family.jpg(1).json"
        json_dup.touch()

        found, reason = find_json_for_media(photo_dup)
        assert found == json_dup
        assert reason == "bracket_swap"

        # 4. Edited suffix
        photo_edited = tmp / "portrait-edited.jpg"
        photo_edited.touch()
        json_base = tmp / "portrait.jpg.json"
        json_base.touch()

        found, reason = find_json_for_media(photo_edited)
        assert found == json_base
        assert reason == "extra_stripped"

        # 5. Extensionless base
        photo_extless = tmp / "archive_scan.jpg"
        photo_extless.touch()
        json_extless = tmp / "archive_scan.json"
        json_extless.touch()

        found, reason = find_json_for_media(photo_extless)
        assert found == json_extless
        assert reason == "extensionless"

        # 6. Digit removal (_removeDigit from Dart tryhard)
        photo_num = tmp / "vacation(2).jpg"
        photo_num.touch()
        json_base_num = tmp / "vacation.jpg.json"
        json_base_num.touch()

        found, reason = find_json_for_media(photo_num)
        assert found == json_base_num
        assert reason == "digit_removed"

        # 7. Supplemental metadata exact match (Google Takeout 2026 format)
        photo_supp = tmp / "PXL_20260914_140111136.jpg"
        photo_supp.touch()
        json_supp = tmp / "PXL_20260914_140111136.jpg.supplemental-metadata.json"
        json_supp.touch()

        found, reason = find_json_for_media(photo_supp)
        assert found == json_supp
        assert reason == "exact"

        # 8. Supplemental metadata duplicate bracket swap: photo(1).jpg -> photo.jpg.supplemental-metadata(1).json
        photo_supp_dup = tmp / "Scan 4(1).png"
        photo_supp_dup.touch()
        json_supp_dup = tmp / "Scan 4.png.supplemental-metadata(1).json"
        json_supp_dup.touch()

        found, reason = find_json_for_media(photo_supp_dup)
        assert found == json_supp_dup
        assert reason == "bracket_swap"

