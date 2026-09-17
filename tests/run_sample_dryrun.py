"""
Script to demonstrate the verbose dry-run report on a mock Google Takeout folder.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from takeout_engine.organizer import TakeoutOrganizer


def main():
    with tempfile.TemporaryDirectory() as in_tmp, tempfile.TemporaryDirectory() as out_tmp:
        in_dir = Path(in_tmp)
        out_dir = Path(out_tmp)

        # 1. Create 'Photos from 2022'
        y = in_dir / "Photos from 2022"
        y.mkdir()

        # Normal file with sidecar
        f1 = y / "sunset_over_the_aegean_sea.jpg"
        f1.write_bytes(b"mock_image_1")
        with open(y / "sunset_over_the_aegean_sea.jpg.json", "w") as f:
            json.dump({
                "title": "sunset_over_the_aegean_sea.jpg",
                "description": "Golden hour in Santorini",
                "photoTakenTime": {"timestamp": "1657890000"},
                "geoData": {"latitude": 36.3932, "longitude": 25.4615, "altitude": 100.0}
            }, f)

        # Truncated 51-char Takeout bug file
        long_name = "vacation_party_with_colleagues_at_the_coastal_beach_resort_2022.jpg"
        f2 = y / long_name
        f2.write_bytes(b"mock_image_2")
        with open(y / f"{long_name[:46]}.json", "w") as f:
            json.dump({"title": long_name, "photoTakenTime": {"timestamp": "1657890500"}}, f)

        # File without JSON (guesses from filename)
        f3 = y / "IMG_20220815_143000.jpg"
        f3.write_bytes(b"mock_image_3")

        # Duplicate bracket swap file
        f4 = y / "family(1).jpg"
        f4.write_bytes(b"mock_image_4")
        with open(y / "family.jpg(1).json", "w") as f:
            json.dump({"title": "family.jpg", "photoTakenTime": {"timestamp": "1657891000"}}, f)

        # Album folder with duplicate of f1
        a = in_dir / "Greece 2022"
        a.mkdir()
        f1_dup = a / "sunset_over_the_aegean_sea.jpg"
        f1_dup.write_bytes(b"mock_image_1")

        organizer = TakeoutOrganizer(
            input_dir=in_dir,
            output_dir=out_dir,
            dry_run=True,
            album_behavior="shortcut"
        )
        organizer.run()


if __name__ == "__main__":
    main()
