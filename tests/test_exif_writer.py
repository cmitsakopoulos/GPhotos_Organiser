"""
Unit tests for exif_writer.
"""

import tempfile
from datetime import datetime
from pathlib import Path
from PIL import Image

from takeout_engine.exif_writer import inject_exif_metadata, decimal_to_dms


def test_decimal_to_dms():
    d, m, s = decimal_to_dms(48.8566)
    assert d == 48.0
    assert m == 51.0
    assert round(s, 2) == 23.76


def test_inject_exif_metadata():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        img_path = tmp / "test_photo.jpg"

        # Create blank JPEG
        img = Image.new("RGB", (50, 50), color="red")
        img.save(img_path)

        dt = datetime(2026, 8, 15, 10, 30, 0)
        lat = 37.9838
        lon = 23.7275
        alt = 150.0
        desc = "Acropolis visit"

        success = inject_exif_metadata(
            image_path=img_path,
            date_taken=dt,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            description=desc
        )
        assert success is True

        # Verify EXIF written
        with Image.open(img_path) as verify_img:
            exif = verify_img.getexif()
            assert exif.get(306) == "2026:08:15 10:30:00"
            assert exif.get(270) == "Acropolis visit"

            # Sub-IFD DateTimeOriginal
            sub = exif.get_ifd(0x8769)
            assert sub.get(36867) == "2026:08:15 10:30:00"

            # GPS IFD
            gps = exif.get_ifd(0x8825)
            assert gps.get(1) == "N"
            assert gps.get(3) == "E"
            assert gps.get(6) == 150.0
