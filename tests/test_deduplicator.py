"""
Unit tests for fast hash deduplication and album grouping.
"""

import tempfile
from pathlib import Path
from takeout_engine.deduplicator import (
    DiscoveredMedia,
    deduplicate_and_group_albums,
    is_year_folder
)


def test_is_year_folder():
    assert is_year_folder("Photos from 2021") is True
    assert is_year_folder("Photos from 1999") is True
    assert is_year_folder("Photos from 1895") is True
    assert is_year_folder("Fotos von 2020") is True
    assert is_year_folder("Photos de 2018") is True
    assert is_year_folder("Zdjęcia z roku 2022") is True
    assert is_year_folder("Summer Trip") is False
    assert is_year_folder("Trash") is False


def test_deduplicate_and_group_albums():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # Create two identical files (same content, same size)
        content = b"Mock photo bytes payload - exactly identical across two files!"
        file1 = tmp / "IMG_001.jpg"
        file2 = tmp / "IMG_001_copy.jpg"
        file1.write_bytes(content)
        file2.write_bytes(content)

        # Create a unique third file
        file3 = tmp / "IMG_002.jpg"
        file3.write_bytes(b"Different photo payload")

        items = [
            DiscoveredMedia(file_path=file1, file_size=len(content), is_from_year_folder=True),
            DiscoveredMedia(file_path=file2, file_size=len(content), is_from_year_folder=False, album_name="Trip2021"),
            DiscoveredMedia(file_path=file3, file_size=23, is_from_year_folder=True),
        ]

        result = deduplicate_and_group_albums(items)

        # Should reduce 3 files to 2 unique files
        assert len(result.unique_media) == 2
        assert len(result.duplicate_files) == 1

        # The kept file for the duplicate should have album "Trip2021" associated with it
        primary = next(m for m in result.unique_media if m.file_path == file1)
        assert "Trip2021" in primary.albums
        assert "Trip2021" in result.albums_found
