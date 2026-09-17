"""
Multi-tier date extraction and metadata parsing.
Cascades through JSON sidecars, EXIF tags, filename patterns, and folder hints.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

from PIL import Image

from .constants import FILENAME_DATETIME_PATTERNS, PHOTO_EXTENSIONS
from .matcher import find_json_for_media
from .deduplicator import is_year_folder

logger = logging.getLogger("takeout_engine")


@dataclass
class MediaMetadata:
    date_taken: Optional[datetime] = None
    date_source: str = "none"  # "json", "exif", "filename_guess", "folder_guess", "none"
    match_type: Optional[str] = None
    json_path: Optional[Path] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    description: Optional[str] = None


def extract_from_json_data(data: dict, json_path: Optional[Path] = None) -> Optional[MediaMetadata]:
    """Parses timestamps, GPS, and description from a Google Takeout JSON dictionary."""
    meta = MediaMetadata(json_path=json_path, date_source="json")

    # 1. Parse timestamp: photoTakenTime > creationTime
    ts = None
    if "photoTakenTime" in data and isinstance(data["photoTakenTime"], dict):
        ts = data["photoTakenTime"].get("timestamp")
    if not ts and "creationTime" in data and isinstance(data["creationTime"], dict):
        ts = data["creationTime"].get("timestamp")

    if ts:
        try:
            epoch = int(ts)
            meta.date_taken = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(None).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            pass

    # 2. Parse description/caption
    desc = data.get("description")
    if desc and isinstance(desc, str) and desc.strip():
        meta.description = desc.strip()

    # 3. Parse Geo / GPS data
    geo = data.get("geoData") or data.get("geoDataExif")
    if geo and isinstance(geo, dict):
        try:
            lat = float(geo.get("latitude", 0.0))
            lon = float(geo.get("longitude", 0.0))
            alt = float(geo.get("altitude", 0.0))
            if lat != 0.0 or lon != 0.0:
                meta.latitude = lat
                meta.longitude = lon
                meta.altitude = alt
        except (ValueError, TypeError):
            pass

    return meta


def extract_from_json(json_path: Path) -> Optional[MediaMetadata]:
    """Parses timestamps, GPS, and description from a Google Takeout JSON sidecar."""
    try:
        with open(json_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as e:
        logger.debug(f"Failed to read JSON {json_path}: {e}")
        return None

    return extract_from_json_data(data, json_path=json_path)


def extract_from_exif(media_path: Path) -> Optional[datetime]:
    """Extracts date from embedded EXIF headers in supported image formats."""
    if media_path.suffix.lower() not in PHOTO_EXTENSIONS:
        return None

    try:
        with Image.open(media_path) as img:
            exif = img.getexif()
            if not exif:
                return None

            # EXIF tags: 36867 (DateTimeOriginal), 36868 (DateTimeDigitized), 306 (DateTime)
            for tag_id in (36867, 36868, 306):
                val = exif.get(tag_id)
                if val and isinstance(val, str):
                    cleaned = (
                        val.strip()
                        .replace("/", ":")
                        .replace("-", ":")
                        .replace(".", ":")
                    )
                    # Expected format: "YYYY:MM:DD HH:MM:SS"
                    try:
                        return datetime.strptime(cleaned[:19], "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
    except Exception as e:
        logger.debug(f"Could not read EXIF from {media_path}: {e}")

    # Fallback: scan binary header for standard EXIF datetime string (supports RAW files like .ARW, .CR2, .NEF, .DNG)
    try:
        with open(media_path, "rb") as f:
            header = f.read(131072)
            import re
            m = re.search(rb'((?:20|19)\d{2}:[01]\d:[0-3]\d [0-2]\d:[0-5]\d:[0-5]\d)', header)
            if m:
                dt_str = m.group(1).decode("ascii")
                return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass

    return None


def guess_from_filename(filename: str) -> Optional[datetime]:
    """Attempts to parse a datetime directly from common camera/device filename conventions."""
    for pattern, fmt in FILENAME_DATETIME_PATTERNS:
        match = pattern.search(filename)
        if not match:
            continue

        try:
            if fmt:
                date_str = match.group(1)
                return datetime.strptime(date_str, fmt)
            else:
                # Custom handler for complex or normalized patterns
                if len(match.groups()) == 2:
                    # WhatsApp style: "2020-10-26" and "16.38.32"
                    d_part, t_part = match.group(1), match.group(2).replace(".", ":")
                    return datetime.strptime(f"{d_part} {t_part}", "%Y-%m-%d %H:%M:%S")
                elif len(match.groups()) == 1:
                    raw = match.group(1).replace("_", " ").replace("-", ":").replace(".", ":")
                    # raw is like "2021:08:15 12:30:45"
                    parts = raw.split(" ")
                    if len(parts) == 2:
                        d_str = parts[0]
                        t_str = parts[1]
                        return datetime.strptime(f"{d_str} {t_str}", "%Y:%m:%d %H:%M:%S")
        except (ValueError, IndexError):
            continue

    return None


def extract_from_folder_year(folder_name: str) -> Optional[datetime]:
    """Fallback: extract year datetime from folder name like 'Photos from 2021'."""
    if is_year_folder(folder_name):
        import re
        m_year = re.search(r"\b(18|19|20)\d{2}\b", folder_name)
        if m_year:
            year_int = int(m_year.group(0))
            return datetime(year_int, 1, 1, 12, 0, 0)
    return None


def extract_media_metadata(
    media_path: Path,
    folder_title_index: Optional[Dict[str, Path]] = None,
    guess_from_name: bool = True
) -> MediaMetadata:
    """
    Cascades through all available extractors to find the most accurate metadata for a file:
      1. Sidecar JSON
      2. Embedded EXIF tags
      3. Filename guessing
      4. Folder year fallback
    """
    # 1. Search for Sidecar JSON
    json_path, match_type = find_json_for_media(media_path, folder_title_index)
    if json_path:
        meta = extract_from_json(json_path)
        if meta and meta.date_taken:
            meta.match_type = match_type
            return meta

    # 2. Embedded EXIF fallback
    exif_date = extract_from_exif(media_path)
    if exif_date:
        return MediaMetadata(date_taken=exif_date, date_source="exif")

    # 3. Guess from filename
    if guess_from_name:
        guessed_date = guess_from_filename(media_path.name)
        if guessed_date:
            return MediaMetadata(date_taken=guessed_date, date_source="filename_guess")

    # 4. Folder name fallback (e.g. "Photos from 2021", "Fotos von 2021")
    folder_date = extract_from_folder_year(media_path.parent.name)
    if folder_date:
        return MediaMetadata(date_taken=folder_date, date_source="folder_guess")

    return MediaMetadata(date_taken=None, date_source="none")
