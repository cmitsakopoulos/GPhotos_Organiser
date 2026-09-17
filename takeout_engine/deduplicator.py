"""
Deduplication and album relationship detection.
Uses fast two-stage hashing (size -> partial SHA-256 -> full SHA-256) to identify duplicates
and link photos belonging to multiple albums without duplicating disk storage.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class DiscoveredMedia:
    file_path: Path
    file_size: int
    is_from_year_folder: bool
    album_name: Optional[str] = None
    albums: Set[str] = field(default_factory=set)
    full_hash: Optional[str] = None


def is_year_folder(folder_name: str) -> bool:
    """
    Checks if a directory is a standard Google Photos year folder.
    Supports English ('Photos from 2021') and common localized Takeout variations (DE, FR, ES, IT, PL).
    """
    pattern = r"^(?:Photos from|Fotos von|Photos de|Fotos de|Foto del|Zdjęcia z roku) (?:18|19|20)\d{2}$"
    return bool(re.match(pattern, folder_name.strip(), re.IGNORECASE))


def compute_partial_hash(file_path: Path, chunk_size: int = 32768) -> str:
    """Computes a quick hash of the head and tail 32KB of a file."""
    h = hashlib.sha256()
    size = file_path.stat().st_size
    with open(file_path, "rb") as f:
        if size <= chunk_size * 2:
            h.update(f.read())
        else:
            h.update(f.read(chunk_size))
            f.seek(-chunk_size, 2)
            h.update(f.read(chunk_size))
    return h.hexdigest()


def compute_full_hash(file_path: Path, chunk_size: int = 65536) -> str:
    """Computes full SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DeduplicationResult:
    unique_media: List[DiscoveredMedia]
    duplicate_files: List[Tuple[Path, Path]]  # (duplicate_path, kept_path)
    bytes_saved: int
    albums_found: Set[str]


def deduplicate_and_group_albums(media_items: List[DiscoveredMedia]) -> DeduplicationResult:
    """
    Groups files by size, then partial hash, then full hash.
    Merges album copies into a single master DiscoveredMedia record.
    """
    # 1. Group by file size
    by_size: Dict[int, List[DiscoveredMedia]] = {}
    for item in media_items:
        by_size.setdefault(item.file_size, []).append(item)

    unique_items: List[DiscoveredMedia] = []
    duplicate_pairs: List[Tuple[Path, Path]] = []
    bytes_saved = 0
    all_albums: Set[str] = set()

    for size, size_group in by_size.items():
        if len(size_group) == 1:
            item = size_group[0]
            if item.album_name:
                item.albums.add(item.album_name)
                all_albums.add(item.album_name)
            unique_items.append(item)
            continue

        # 2. Files with identical size -> group by partial hash
        by_partial: Dict[str, List[DiscoveredMedia]] = {}
        for item in size_group:
            try:
                p_hash = compute_partial_hash(item.file_path)
                by_partial.setdefault(p_hash, []).append(item)
            except OSError:
                # File access error, keep as is
                unique_items.append(item)

        for p_hash, partial_group in by_partial.items():
            if len(partial_group) == 1:
                item = partial_group[0]
                if item.album_name:
                    item.albums.add(item.album_name)
                    all_albums.add(item.album_name)
                unique_items.append(item)
                continue

            # 3. Identical partial hash -> compute full hash
            by_full: Dict[str, List[DiscoveredMedia]] = {}
            for item in partial_group:
                try:
                    f_hash = compute_full_hash(item.file_path)
                    item.full_hash = f_hash
                    by_full.setdefault(f_hash, []).append(item)
                except OSError:
                    unique_items.append(item)

            for f_hash, hash_group in by_full.items():
                if len(hash_group) == 1:
                    item = hash_group[0]
                    if item.album_name:
                        item.albums.add(item.album_name)
                        all_albums.add(item.album_name)
                    unique_items.append(item)
                    continue

                # Duplicates detected!
                # Prioritize: Year folder version first, then shortest filename
                hash_group.sort(
                    key=lambda x: (
                        not x.is_from_year_folder,
                        len(x.file_path.name)
                    )
                )

                primary = hash_group[0]
                if primary.album_name:
                    primary.albums.add(primary.album_name)
                    all_albums.add(primary.album_name)

                for dup in hash_group[1:]:
                    if dup.album_name:
                        primary.albums.add(dup.album_name)
                        all_albums.add(dup.album_name)
                    duplicate_pairs.append((dup.file_path, primary.file_path))
                    bytes_saved += dup.file_size

                unique_items.append(primary)

    return DeduplicationResult(
        unique_media=unique_items,
        duplicate_files=duplicate_pairs,
        bytes_saved=bytes_saved,
        albums_found=all_albums
    )
