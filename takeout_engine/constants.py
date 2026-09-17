"""
Constants and patterns for Google Photos Takeout processing.
"""

from typing import Set, List, Tuple
import re

# Supported media extensions
PHOTO_EXTENSIONS: Set[str] = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".dng", ".raw", ".cr2", ".nef", ".arw", ".gif"
}

VIDEO_EXTENSIONS: Set[str] = {
    ".mp4", ".mov", ".webm", ".avi", ".wmv", ".mkv", ".m4v",
    ".mpg", ".mpeg", ".3gp", ".mts", ".m2ts", ".flv"
}

ALL_MEDIA_EXTENSIONS: Set[str] = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# Google Photos creation/edit suffixes (in multiple languages)
EXTRA_FORMATS: List[str] = [
    # English
    "-edited", "-effects", "-smile", "-mix", "-cover",
    # Polish
    "-edytowane",
    # German
    "-bearbeitet",
    # Dutch
    "-bewerkt",
    # Japanese
    "-編集済み",
    # Italian
    "-modificato",
    # French
    "-modifié",
    # Spanish
    "-ha editado",
    # Catalan
    "-editat",
]

# Regex patterns for guessing datetime directly from filenames
# Matches Dart's (20|19|18) century range for historical scans
FILENAME_DATETIME_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Screenshot_20190919-053857_Camera.jpg or Screenshot_20220101-120000.png
    (re.compile(r'(?:Screenshot_)?((?:20|19|18)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])-\d{6})', re.IGNORECASE), "%Y%m%d-%H%M%S"),
    
    # IMG_20190509_154733.jpg, MVIMG_20190215_193501.MP4, VID_20210815_120000.mp4, PXL_20220101_120000.jpg
    (re.compile(r'(?:[A-Z]+_)?((?:20|19|18)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])_\d{6})', re.IGNORECASE), "%Y%m%d_%H%M%S"),

    # 2021-08-15 12.30.45.jpg or 2021-08-15-12-30-45.jpg or Screenshot_2019-04-16-11-19-37
    (re.compile(r'((?:20|19|18)\d{2}-(?:0[1-9]|1[0-2])-(?:[0-2]\d|3[01])[-_ ]\d{2}[-.]\d{2}[-.]\d{2})'), None), # normalized dynamically
    
    # signal-2020-10-26-163832.jpg
    (re.compile(r'signal-((?:20|19|18)\d{2}-(?:0[1-9]|1[0-2])-(?:[0-2]\d|3[01])-\d{6})', re.IGNORECASE), "%Y-%m-%d-%H%M%S"),
    
    # WhatsApp Image 2020-10-26 at 16.38.32.jpeg
    (re.compile(r'WhatsApp Image ((?:20|19|18)\d{2}-(?:0[1-9]|1[0-2])-(?:[0-2]\d|3[01])) at (\d{2}\.\d{2}\.\d{2})', re.IGNORECASE), None),

    # 2016_01_30_11_49_15.mp4
    (re.compile(r'((?:20|19|18)\d{2}_(?:0[1-9]|1[0-2])_(?:[0-2]\d|3[01])_\d{2}_\d{2}_\d{2})'), "%Y_%m_%d_%H_%M_%S"),

    # Burst formats: 00004XTR_00004_BURST20190216172030.jpg or 20180126114752.jpg
    (re.compile(r'BURST((?:20|19|18)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])\d{6})', re.IGNORECASE), "%Y%m%d%H%M%S"),
    (re.compile(r'^((?:20|19|18)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])\d{6})'), "%Y%m%d%H%M%S"),

    # Date only: 2021-08-15_... or 20210815_...
    (re.compile(r'^((?:20|19|18)\d{2}-(?:0[1-9]|1[0-2])-(?:[0-2]\d|3[01]))'), "%Y-%m-%d"),
    (re.compile(r'^((?:20|19|18)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01]))'), "%Y%m%d"),
]

# Google Takeout truncation boundary (typically 51 characters total for `filename.json`)
TAKEOUT_MAX_JSON_FILENAME_LEN = 51
TAKEOUT_MAX_NAME_LEN = TAKEOUT_MAX_JSON_FILENAME_LEN - len(".json")  # 46 chars
