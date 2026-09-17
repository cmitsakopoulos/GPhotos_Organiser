"""
Integration tests for TakeoutOrganizer full pipeline and dry-run execution.
"""

import json
import tempfile
from pathlib import Path
from takeout_engine.organizer import TakeoutOrganizer


def test_organizer_dry_run_and_execution():
    with tempfile.TemporaryDirectory() as in_tmp, tempfile.TemporaryDirectory() as out_tmp:
        in_dir = Path(in_tmp)
        out_dir = Path(out_tmp)

        # 1. Create simulated Takeout structure:
        # Year folder: Photos from 2021
        year_folder = in_dir / "Photos from 2021"
        year_folder.mkdir()

        # Regular photo + JSON
        img1 = year_folder / "beach.jpg"
        img1.write_bytes(b"Beach image content 12345")
        json1 = year_folder / "beach.jpg.json"
        with open(json1, "w") as f:
            json.dump({"title": "beach.jpg", "photoTakenTime": {"timestamp": "1629037800"}}, f)

        # Truncated photo + JSON (51-char bug)
        long_name = "this_is_an_extraordinary_long_photo_name_from_summer.jpg"
        img2 = year_folder / long_name
        img2.write_bytes(b"Long image content 67890")
        json2 = year_folder / f"{long_name[:46]}.json"
        with open(json2, "w") as f:
            json.dump({"title": long_name, "photoTakenTime": {"timestamp": "1629037800"}}, f)

        # Album folder: Greece 2021 (Contains duplicate of beach.jpg)
        album_folder = in_dir / "Greece 2021"
        album_folder.mkdir()
        img1_dup = album_folder / "beach.jpg"
        img1_dup.write_bytes(b"Beach image content 12345")  # Identical content!

        # 2. Test Dry Run
        dry_organizer = TakeoutOrganizer(
            input_dir=in_dir,
            output_dir=out_dir,
            divide_to_dates=True,
            copy_files=True,
            album_behavior="shortcut",
            dry_run=True,
            verbose=False
        )
        dry_organizer.run()

        # Verify Dry Run didn't write to output
        assert not (out_dir / "ALL_PHOTOS").exists()
        assert dry_organizer.stats.total_media_found == 3
        assert dry_organizer.stats.duplicates_removed == 1  # Album duplicate caught!
        assert "truncated_46" in dry_organizer.stats.match_types
        assert "exact" in dry_organizer.stats.match_types

        # 3. Test Live Execution (Copy Mode)
        live_organizer = TakeoutOrganizer(
            input_dir=in_dir,
            output_dir=out_dir,
            divide_to_dates=True,
            copy_files=True,
            album_behavior="shortcut",
            dry_run=False,
            verbose=False
        )
        live_organizer.run()

        # Check organized output
        organized_dir = out_dir / "ALL_PHOTOS" / "2021" / "08"
        assert organized_dir.exists()
        assert (organized_dir / "beach.jpg").exists()
        assert (organized_dir / long_name).exists()


def test_organizer_dry_run_loud():
    import zipfile

    with tempfile.TemporaryDirectory() as in_tmp, tempfile.TemporaryDirectory() as out_tmp:
        in_dir = Path(in_tmp)
        out_dir = Path(out_tmp)

        # Create a zip archive with photo and sidecar
        z_path = in_dir / "takeout-2026-001.zip"
        with zipfile.ZipFile(z_path, "w") as zf:
            zf.writestr("Takeout/Google Photos/Photos from 2026/img1.jpg", "image_data_loud")
            zf.writestr(
                "Takeout/Google Photos/Photos from 2026/img1.jpg.json",
                json.dumps({"photoTakenTime": {"timestamp": "1773750000"}})
            )

        organizer = TakeoutOrganizer(
            input_dir=in_dir,
            output_dir=out_dir,
            divide_to_dates=True,
            copy_files=False,
            dry_run_loud=True,
            verbose=True  # quiet progress in test
        )
        organizer.run()

        # Output folder must remain clean (0 bytes written)
        assert not (out_dir / "ALL_PHOTOS").exists()
        assert organizer.stats.total_media_found == 1
        assert organizer.stats.date_sources["json"] == 1
        assert len(organizer.planned_actions) == 1
