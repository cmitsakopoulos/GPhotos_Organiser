"""
Unit tests for date extraction and metadata parsing.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from takeout_engine.date_extractor import (
    extract_from_json,
    guess_from_filename,
    extract_media_metadata
)


def test_guess_from_filename():
    # Screenshot pattern
    dt = guess_from_filename("Screenshot_20210815-143022.png")
    assert dt == datetime(2021, 8, 15, 14, 30, 22)

    # Standard camera pattern
    dt = guess_from_filename("IMG_20200509_181245.jpg")
    assert dt == datetime(2020, 5, 9, 18, 12, 45)

    # Signal pattern
    dt = guess_from_filename("signal-2022-10-26-163832.jpg")
    assert dt == datetime(2022, 10, 26, 16, 38, 32)

    # WhatsApp pattern
    dt = guess_from_filename("WhatsApp Image 2021-07-04 at 12.15.30.jpeg")
    assert dt == datetime(2021, 7, 4, 12, 15, 30)


def test_extract_from_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        json_file = tmp / "test.json"

        # Timestamp 1629037822 = 2021-08-15 14:30:22 UTC
        data = {
            "title": "test.jpg",
            "description": "Vacation in Greece",
            "photoTakenTime": {
                "timestamp": "1629037822"
            },
            "geoData": {
                "latitude": 37.9838,
                "longitude": 23.7275,
                "altitude": 150.0
            }
        }
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        meta = extract_from_json(json_file)
        assert meta is not None
        assert meta.date_taken is not None
        assert meta.date_taken.year == 2021
        assert meta.date_taken.month == 8
        assert meta.description == "Vacation in Greece"
        assert meta.latitude == 37.9838
        assert meta.longitude == 23.7275
