"""
EXIF Writer: Embeds timestamps, GPS coordinates, and descriptions directly
into media file headers (JPEG, TIFF, WebP) using Pillow.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger("takeout_engine")

SUPPORTED_EXIF_EXTENSIONS = {".jpg", ".jpeg", ".tiff", ".tif", ".webp"}


def decimal_to_dms(deg_float: float) -> Tuple[float, float, float]:
    """Converts decimal degrees to (degrees, minutes, seconds) tuple."""
    abs_d = abs(deg_float)
    d = int(abs_d)
    m_float = (abs_d - d) * 60.0
    m = int(m_float)
    s = round((m_float - m) * 60.0, 4)
    return (float(d), float(m), float(s))


def inject_exif_metadata(
    image_path: Path,
    date_taken: Optional[datetime] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    altitude: Optional[float] = None,
    description: Optional[str] = None,
) -> bool:
    """
    Injects capture date, GPS coordinates, and description directly into the image EXIF tags.
    Preserves existing image pixels without re-encoding quality degradation where possible.
    """
    ext = image_path.suffix.lower()
    if ext not in SUPPORTED_EXIF_EXTENSIONS:
        return False

    # Check if there is anything to write
    if not (date_taken or latitude is not None or longitude is not None or description):
        return False

    try:
        with Image.open(image_path) as img:
            exif = img.getexif()

            # 1. Capture Dates
            if date_taken:
                dt_str = date_taken.strftime("%Y:%m:%d %H:%M:%S")
                # Main IFD DateTime tag 306
                exif[306] = dt_str
                # Exif sub-IFD (0x8769)
                exif_sub = exif.get_ifd(0x8769)
                # DateTimeOriginal (36867) & DateTimeDigitized (36868)
                exif_sub[36867] = dt_str
                exif_sub[36868] = dt_str

            # 2. Description / Caption
            if description:
                # ImageDescription tag 270
                exif[270] = description

            # 3. GPS Coordinates
            if latitude is not None and longitude is not None and (latitude != 0.0 or longitude != 0.0):
                gps_ifd = exif.get_ifd(0x8825)
                # GPSLatitudeRef (tag 1) & GPSLatitude (tag 2)
                gps_ifd[1] = "N" if latitude >= 0 else "S"
                gps_ifd[2] = decimal_to_dms(latitude)

                # GPSLongitudeRef (tag 3) & GPSLongitude (tag 4)
                gps_ifd[3] = "E" if longitude >= 0 else "W"
                gps_ifd[4] = decimal_to_dms(longitude)

                # Altitude (tag 5 ref, tag 6 altitude)
                if altitude is not None:
                    gps_ifd[5] = 0 if altitude >= 0 else 1
                    gps_ifd[6] = float(abs(altitude))

            # Save back to file with updated EXIF
            # Note: For JPEG, saving with existing format keeps parameters
            img.save(image_path, exif=exif)
            return True
    except Exception as e:
        logger.debug(f"Could not inject EXIF into {image_path.name}: {e}")
        return False
