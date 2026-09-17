"""
Unit tests for zip_handler.
"""

import tempfile
import zipfile
from pathlib import Path
from takeout_engine.zip_handler import find_takeout_zips, stage_takeout_archives


def test_find_takeout_zips():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        z1 = tmp / "takeout-2026-001.zip"
        z2 = tmp / "takeout-2026-002.zip"
        z3 = tmp / "Photos-1-001.zip"
        other = tmp / "random_file.zip"

        for z in (z1, z2, z3, other):
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("test.txt", "dummy content")

        found = find_takeout_zips(tmp)
        found_names = [f.name for f in found]
        assert "takeout-2026-001.zip" in found_names
        assert "takeout-2026-002.zip" in found_names
        assert "Photos-1-001.zip" in found_names
        assert "random_file.zip" not in found_names

        # Test passing single chunk file finds siblings
        single_found = find_takeout_zips(z1)
        single_names = [f.name for f in single_found]
        assert "takeout-2026-001.zip" in single_names
        assert "takeout-2026-002.zip" in single_names


def test_stage_takeout_archives_mixed():
    with tempfile.TemporaryDirectory() as in_tmp, tempfile.TemporaryDirectory() as stage_tmp:
        in_dir = Path(in_tmp)
        stage_dir = Path(stage_tmp)

        # 1. Takeout chunk with Takeout/ root
        z1 = in_dir / "takeout-001.zip"
        with zipfile.ZipFile(z1, "w") as zf:
            zf.writestr("Takeout/Google Photos/Photos from 2026/img1.jpg", "img1")

        # 2. Flat Photos zip
        z2 = in_dir / "Photos-001.zip"
        with zipfile.ZipFile(z2, "w") as zf:
            zf.writestr("img2.jpg", "img2")

        stage_takeout_archives([z1, z2], stage_dir, mix_folders=True, show_progress=False)

        # When mix_folders=True, img2.jpg merges into the primary Photos from 2026 folder
        assert (stage_dir / "Takeout" / "Google Photos" / "Photos from 2026" / "img1.jpg").is_file()
        assert (stage_dir / "Takeout" / "Google Photos" / "Photos from 2026" / "img2.jpg").is_file()


def test_stage_takeout_archives_unmixed():
    with tempfile.TemporaryDirectory() as in_tmp, tempfile.TemporaryDirectory() as stage_tmp:
        in_dir = Path(in_tmp)
        stage_dir = Path(stage_tmp)

        z1 = in_dir / "takeout-001.zip"
        with zipfile.ZipFile(z1, "w") as zf:
            zf.writestr("Takeout/Google Photos/Photos from 2026/img1.jpg", "img1")

        z2 = in_dir / "album_vacation.zip"
        with zipfile.ZipFile(z2, "w") as zf:
            zf.writestr("img2.jpg", "img2")

        stage_takeout_archives([z1, z2], stage_dir, mix_folders=False, show_progress=False)

        assert (stage_dir / "Takeout" / "Google Photos" / "Photos from 2026" / "img1.jpg").is_file()
        assert (stage_dir / "album_vacation" / "img2.jpg").is_file()


def test_simulate_takeout_extraction():
    from takeout_engine.zip_handler import simulate_takeout_extraction
    import json

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        z1 = tmp / "takeout-001.zip"
        with zipfile.ZipFile(z1, "w") as zf:
            zf.writestr("Takeout/Google Photos/Photos from 2026/img1.jpg", "photo_data_123")
            zf.writestr(
                "Takeout/Google Photos/Photos from 2026/img1.jpg.json",
                json.dumps({"photoTakenTime": {"timestamp": "1773750000"}})
            )

        res = simulate_takeout_extraction([z1], show_progress=False)
        assert res.total_archives == 1
        assert res.total_files == 2
        assert len(res.discovered_media) == 1
        assert res.discovered_media[0].file_size == len("photo_data_123")
        assert len(res.metadata_map) == 1
        # Check that date was parsed from sidecar JSON in memory
        sim_path = str(res.discovered_media[0].file_path)
        assert res.metadata_map[sim_path].date_taken is not None
