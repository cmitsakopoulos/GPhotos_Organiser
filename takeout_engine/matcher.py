"""
Heuristic sidecar JSON matcher.
Resolves Google Takeout's various JSON naming quirks (51-char truncation, bracket swap,
edited/effects suffixes, and extensionless uploads).
"""

import re
import unicodedata
from pathlib import Path
from typing import Optional, Tuple, Dict, List
from .constants import TAKEOUT_MAX_NAME_LEN, EXTRA_FORMATS


def normalize_unicode(s: str) -> str:
    """Normalize string to NFC to avoid Unicode decomposition mismatches (e.g. macOS NFD)."""
    return unicodedata.normalize("NFC", s)


def bracket_swap_candidate(filename: str) -> Optional[str]:
    """
    Google Takeout often writes duplicate numbers after the file extension in JSON:
    e.g. 'image(11).jpg' -> 'image.jpg(11).json'
    """
    matches = list(re.finditer(r'\(\d+\)\.', filename))
    if not matches:
        return None
    last_match = matches[-1]
    bracket = filename[last_match.start():last_match.end() - 1]  # '(11)'
    without_bracket = filename[:last_match.start()] + filename[last_match.end() - 1:]
    return f"{without_bracket}{bracket}"


def strip_extra_suffixes(filename: str) -> List[str]:
    """
    Strips Google Photos automated creation / edit suffixes like '-edited', '-effects', etc.
    Returns potential base filenames.
    """
    results = []
    norm = normalize_unicode(filename)
    path = Path(norm)
    stem = path.stem
    suffix = path.suffix

    for extra in EXTRA_FORMATS:
        if extra in stem.lower():
            # e.g., 'IMG_1234-edited' -> 'IMG_1234'
            idx = stem.lower().rfind(extra)
            new_stem = stem[:idx] + stem[idx + len(extra):]
            if new_stem:
                results.append(f"{new_stem}{suffix}")
                results.append(new_stem)

    # Regex for any other '-word' edit tag before extension or before '(1)'
    # e.g., 'something-edited(1).jpg' -> 'something(1).jpg'
    m = re.search(r'(-[A-Za-zÀ-ÖØ-öø-ÿ]+)(\(\d+\))?(\.[^.]*)?$', norm)
    if m:
        extra_word = m.group(1)
        cleaned = norm.replace(extra_word, "", 1)
        if cleaned not in results:
            results.append(cleaned)

    return results


def find_json_for_media(
    media_path: Path,
    folder_title_index: Optional[Dict[str, Path]] = None
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Finds the corresponding JSON sidecar file for a given media file using cascading heuristics.
    
    Returns:
        (json_path, match_reason) if found, else (None, None).
    """
    parent_dir = media_path.parent
    filename = media_path.name
    stem = media_path.stem

    # Helper to test file existence across supplemental-metadata and standard JSON suffixes
    def check(candidate_name: str, reason: str) -> Optional[Tuple[Path, str]]:
        for ext in (".supplemental-metadata.json", ".json"):
            p = parent_dir / f"{candidate_name}{ext}"
            if p.is_file():
                return p, reason
        return None

    # 1. Exact match: "photo.jpg.supplemental-metadata.json" or "photo.jpg.json"
    res = check(filename, "exact")
    if res:
        return res

    # 2. Google 51-char truncation bug:
    # If "filename.json" > 51 chars, Takeout truncates to 46 chars (51 - len(".json"))
    if len(filename) > TAKEOUT_MAX_NAME_LEN:
        res = check(filename[:TAKEOUT_MAX_NAME_LEN], "truncated_46")
        if res:
            return res
    # Test boundary lengths 47 and 51 just in case of slight variation
    for length in (47, 51):
        if len(filename) > length:
            res = check(filename[:length], f"truncated_{length}")
            if res:
                return res

    # 3. Bracket swap for numbered duplicates:
    # Supplemental: 'image(1).jpg' -> 'image.jpg.supplemental-metadata(1).json'
    # Traditional:   'image(1).jpg' -> 'image.jpg(1).json'
    matches = list(re.finditer(r'\(\d+\)\.', filename))
    if matches:
        last_match = matches[-1]
        bracket = filename[last_match.start():last_match.end() - 1]  # '(1)'
        without_bracket = filename[:last_match.start()] + filename[last_match.end() - 1:]

        # Check 'image.jpg.supplemental-metadata(1).json'
        p_supp_bracket = parent_dir / f"{without_bracket}.supplemental-metadata{bracket}.json"
        if p_supp_bracket.is_file():
            return p_supp_bracket, "bracket_swap"

        # Check 'image.jpg(1).json'
        p_trad_bracket = parent_dir / f"{without_bracket}{bracket}.json"
        if p_trad_bracket.is_file():
            return p_trad_bracket, "bracket_swap"

    swapped = bracket_swap_candidate(filename)
    if swapped:
        res = check(swapped, "bracket_swap")
        if res:
            return res
        # Also check truncated bracket swap
        if len(swapped) > TAKEOUT_MAX_NAME_LEN:
            res = check(swapped[:TAKEOUT_MAX_NAME_LEN], "bracket_swap_truncated")
            if res:
                return res

    # 3b. Digit removal (Dart _removeDigit): 'image(1).jpg' -> 'image.jpg.json' or 'image.json'
    no_digit = re.sub(r'\(\d+\)\.', '.', filename)
    if no_digit != filename:
        res = check(no_digit, "digit_removed")
        if res:
            return res
        no_digit_stem = Path(no_digit).stem
        res = check(no_digit_stem, "digit_removed_stem")
        if res:
            return res

    # 4. Extras stripping: '-edited', '-effects', '-smile', etc.
    for extra_clean in strip_extra_suffixes(filename):
        res = check(extra_clean, "extra_stripped")
        if res:
            return res
        # Check bracket swap on stripped extra (e.g. IMG-edited(1).jpg)
        swapped_extra = bracket_swap_candidate(extra_clean)
        if swapped_extra:
            res = check(swapped_extra, "extra_bracket_swap")
            if res:
                return res

    # 5. Extensionless base match: "photo.json"
    # If the user originally uploaded the file without an extension (e.g. "20030616")
    res = check(stem, "extensionless")
    if res:
        return res

    # 6. Folder title index fallback:
    # Matches if a JSON file in the same directory explicitly specifies title == filename
    if folder_title_index and filename in folder_title_index:
        indexed_path = folder_title_index[filename]
        if indexed_path.is_file():
            return indexed_path, "title_indexed"

    return None, None
