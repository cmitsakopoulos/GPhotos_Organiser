"""
Unit tests for empty directory pruning and residual sidecar cleanup.
"""

import tempfile
import zipfile
from pathlib import Path
from takeout_engine.file_ops import prune_empty_directories, archive_or_delete_residuals, is_identical_file


def test_is_identical_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        f1 = tmp / "a.bin"
        f2 = tmp / "b.bin"
        f3 = tmp / "c.bin"
        f1.write_bytes(b"identical content 12345")
        f2.write_bytes(b"identical content 12345")
        f3.write_bytes(b"different content")

        assert is_identical_file(f1, f2) is True
        assert is_identical_file(f1, f3) is False


def test_prune_empty_directories():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        nested = tmp / "a" / "b" / "c"
        nested.mkdir(parents=True)
        keep = tmp / "x" / "y"
        keep.mkdir(parents=True)
        (keep / "file.txt").write_text("keep me")

        pruned = prune_empty_directories(tmp)
        assert pruned >= 3
        assert not (tmp / "a").exists()
        assert keep.exists()
        assert (keep / "file.txt").exists()


def test_archive_or_delete_residuals():
    with tempfile.TemporaryDirectory() as in_tmp, tempfile.TemporaryDirectory() as out_tmp:
        in_dir = Path(in_tmp)
        out_dir = Path(out_tmp)

        j1 = in_dir / "photo.jpg.supplemental-metadata.json"
        j2 = in_dir / "photo2.json"
        j1.write_text('{"title": "photo.jpg"}')
        j2.write_text('{"title": "photo2.jpg"}')

        count, arch_path = archive_or_delete_residuals(in_dir, out_dir, archive_zip=True)
        assert count == 2
        assert not j1.exists()
        assert not j2.exists()
        assert arch_path is not None and arch_path.is_file()

        with zipfile.ZipFile(arch_path, "r") as z:
            names = z.namelist()
            assert "photo.jpg.supplemental-metadata.json" in names
            assert "photo2.json" in names
