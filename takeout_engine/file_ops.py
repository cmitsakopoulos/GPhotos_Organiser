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


def get_collision_safe_path(target_path: Path) -> Path:
    """
    Returns an available path by appending (1), (2), etc. before suffix if file already exists.
    """
    if not target_path.exists():
        return target_path

    parent = target_path.parent
    stem = target_path.stem
    suffix = target_path.suffix

    counter = 1
    while True:
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def create_windows_shortcut(target_path: Path, destination_dir: Path) -> Optional[Path]:
    """
    Creates a Windows .lnk shortcut pointing to target_path (relative).
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    shortcut_name = f"{target_path.name}.lnk"
    shortcut_path = get_collision_safe_path(destination_dir / shortcut_name)

    try:
        rel_target = os.path.relpath(target_path, destination_dir)
        cmd = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{shortcut_path}'); "
            f"$s.TargetPath = '{rel_target}'; "
            f"$s.Save()"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and shortcut_path.exists():
            return shortcut_path
    except Exception:
        pass

    # Fallback to symbolic link if shortcut fails
    try:
        shortcut_path.symlink_to(target_path)
        return shortcut_path
    except Exception:
        return None
