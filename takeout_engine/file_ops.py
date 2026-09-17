"""
File operations: collision-safe destination naming, Windows NTFS creation time setting,
shortcut creation, and file transfer.
"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


def set_file_creation_and_mtime(file_path: Path, dt: datetime) -> bool:
    """
    Sets modification time, access time, and (on Windows) NTFS creation time.
    """
    try:
        ts = dt.timestamp()
    except (OSError, OverflowError, ValueError):
        ts = datetime(1970, 1, 1, 0, 0, 0).timestamp()

    # 1. Set modification and access time
    try:
        os.utime(file_path, (ts, ts))
    except Exception:
        pass

    # 2. On Windows, set creation time (ctime) via SetFileTime
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            # Clamp timestamp to at least 1970-01-01 to avoid negative epoch issues
            safe_ts = max(0.0, ts)
            # Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
            filetime_val = int((safe_ts + 11644473600) * 10000000)
            low = filetime_val & 0xFFFFFFFF
            high = (filetime_val >> 32) & 0xFFFFFFFF

            # GENERIC_WRITE (0x40000000) or FILE_WRITE_ATTRIBUTES (0x0100)
            FILE_WRITE_ATTRIBUTES = 0x0100
            OPEN_EXISTING = 3
            FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

            handle = ctypes.windll.kernel32.CreateFileW(
                str(file_path),
                FILE_WRITE_ATTRIBUTES,
                0,
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                None
            )

            if handle != -1 and handle != 0:
                ft = wintypes.FILETIME(low, high)
                # SetFileTime(hFile, lpCreationTime, lpLastAccessTime, lpLastWriteTime)
                ctypes.windll.kernel32.SetFileTime(handle, ctypes.byref(ft), None, ctypes.byref(ft))
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except Exception:
            return False

    return True


def is_identical_file(path1: Path, path2: Path) -> bool:
    """Compares file size then SHA-256 to check if two files are identical."""
    try:
        if path1.stat().st_size != path2.stat().st_size:
            return False
        import hashlib
        h1 = hashlib.sha256()
        with open(path1, "rb") as f1:
            while chunk := f1.read(65536):
                h1.update(chunk)
        h2 = hashlib.sha256()
        with open(path2, "rb") as f2:
            while chunk := f2.read(65536):
                h2.update(chunk)
        return h1.hexdigest() == h2.hexdigest()
    except OSError:
        return False


def get_collision_safe_path(target_path: Path, source_path: Optional[Path] = None) -> Tuple[Path, bool]:
    """
    Returns (safe_path, is_identical_skip).
    If target_path does not exist: returns (target_path, False).
    If source_path is provided and target_path (or one of its collision numbered versions)
    already has identical content: returns (existing_path, True).
    Otherwise appends (1), (2), etc. and returns (new_path, False).
    """
    if not target_path.exists():
        return target_path, False

    if source_path and is_identical_file(target_path, source_path):
        return target_path, True

    parent = target_path.parent
    stem = target_path.stem
    suffix = target_path.suffix

    counter = 1
    while True:
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate, False
        if source_path and is_identical_file(candidate, source_path):
            return candidate, True
        counter += 1


def create_windows_shortcut(target_path: Path, destination_dir: Path) -> Optional[Path]:
    """
    Creates a Windows .lnk shortcut pointing to target_path (absolute).
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    shortcut_name = f"{target_path.name}.lnk"
    shortcut_path, _ = get_collision_safe_path(destination_dir / shortcut_name)

    abs_target = str(target_path.resolve()).replace("'", "''")
    work_dir = str(target_path.parent.resolve()).replace("'", "''")
    safe_shortcut = str(shortcut_path.resolve()).replace("'", "''")

    try:
        cmd = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{safe_shortcut}'); "
            f"$s.TargetPath = '{abs_target}'; "
            f"$s.WorkingDirectory = '{work_dir}'; "
            f"$s.Save()"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and shortcut_path.exists():
            return shortcut_path
    except Exception:
        pass

    # Fallback to symbolic link if shortcut fails
    try:
        shortcut_path.symlink_to(target_path.resolve())
        return shortcut_path
    except Exception:
        return None


def prune_empty_directories(root_dir: Path) -> int:
    """
    Recursively removes empty directories within root_dir (bottom-up).
    Does not remove root_dir itself.
    Returns count of removed directories.
    """
    if not root_dir.is_dir():
        return 0

    removed = 0
    for root_str, dirs, files in os.walk(str(root_dir), topdown=False):
        current = Path(root_str)
        if current == root_dir:
            continue
        try:
            if not any(current.iterdir()):
                current.rmdir()
                removed += 1
        except OSError:
            pass

    return removed


def archive_or_delete_residuals(
    input_dir: Path,
    output_dir: Path,
    archive_zip: bool = True
) -> Tuple[int, Optional[Path]]:
    """
    Discovers all leftover .json sidecars in input_dir.
    Optionally compresses them into output_dir / 'takeout_metadata_archive.zip'.
    Then deletes the individual json sidecar files from input_dir.
    Returns (count_of_cleaned_files, archive_zip_path_or_None).
    """
    if not input_dir.is_dir():
        return 0, None

    json_files = []
    for root_str, dirs, files in os.walk(str(input_dir)):
        root = Path(root_str)
        for f in files:
            if f.lower().endswith(".json"):
                json_files.append(root / f)

    if not json_files:
        return 0, None

    zip_path = None
    if archive_zip:
        import zipfile
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / "takeout_metadata_archive.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for jf in json_files:
                try:
                    rel = jf.relative_to(input_dir)
                except ValueError:
                    rel = jf.name
                zf.write(jf, arcname=str(rel))

    cleaned_count = 0
    for jf in json_files:
        try:
            jf.unlink(missing_ok=True)
            cleaned_count += 1
        except OSError:
            pass

    return cleaned_count, zip_path

