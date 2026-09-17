"""
Takeout Zip Handler: Discovery, extraction, and staging of Google Takeout zip archives.
Supports:
- Multi-chunk archives (takeout-*-001.zip .. takeout-*-NNN.zip)
- Direct photo downloads (Photos-*.zip) with auto-merging into the primary Takeout folder
- Standalone extraction mode (--extract-only) via CLI
"""

import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from tqdm import tqdm

from .constants import ALL_MEDIA_EXTENSIONS
from .date_extractor import (
    MediaMetadata,
    extract_from_folder_year,
    extract_from_json_data,
    guess_from_filename,
)
from .deduplicator import DiscoveredMedia, is_year_folder

logger = logging.getLogger("takeout_engine")


def find_takeout_zips(target: Path) -> List[Path]:
    """
    Finds Google Takeout and Google Photos zip files:
    - If target is a directory: discovers all takeout/photos archives in it.
    - If target is a single zip file: returns it and any sibling chunks of the same export.
    """
    if target.is_file():
        if target.suffix.lower() != ".zip":
            return []
        # Check if it's a split chunk (e.g. takeout-...-001.zip)
        m_chunk = re.search(r"^(.*?)-(?:1-)?\d{3}\.zip$", target.name, re.IGNORECASE)
        if m_chunk:
            prefix = m_chunk.group(1).lower()
            parent = target.parent
            siblings = [
                f for f in parent.iterdir()
                if f.is_file() and f.suffix.lower() == ".zip" and f.name.lower().startswith(prefix)
            ]
            # Also include any Photos-*.zip in the same directory
            photos_zips = [
                f for f in parent.iterdir()
                if f.is_file() and f.suffix.lower() == ".zip" and f.name.lower().startswith("photos")
            ]
            combined = sorted(list(set(siblings + photos_zips)), key=lambda p: p.name)
            return combined
        return [target]

    if not target.is_dir():
        return []

    found = []
    for f in target.iterdir():
        if f.is_file() and f.suffix.lower() == ".zip":
            name_lower = f.name.lower()
            if "takeout" in name_lower or "photos" in name_lower:
                found.append(f)
            else:
                # Inspect zip table of contents for Google Photos signature
                try:
                    with zipfile.ZipFile(f, "r") as z:
                        nl = z.namelist()[:5]
                        if any("takeout" in x.lower() or "google photos" in x.lower() for x in nl):
                            found.append(f)
                except (zipfile.BadZipFile, OSError):
                    continue

    return sorted(found, key=lambda p: p.name)


def extract_archive(
    zip_path: Path,
    target_dir: Path,
    show_progress: bool = True,
    prefix: str = ""
) -> bool:
    """Safely extracts a zip file to target_dir with progress tracking and dynamic terminal width."""
    if not zip_path.is_file():
        logger.error(f"Archive not found: {zip_path}")
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Extracting {zip_path.name} to {target_dir}")

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            members = z.infolist()
            desc = f"{prefix}Unpacking {zip_path.name}" if prefix else f"Unpacking {zip_path.name}"
            iterator = tqdm(
                members,
                desc=desc,
                unit="file",
                dynamic_ncols=True,
                mininterval=0.05,
                colour="magenta",
                ascii=True
            ) if show_progress else members
            for member in iterator:
                z.extract(member, target_dir)
        return True
    except Exception as e:
        logger.error(f"Failed to extract {zip_path}: {e}")
        return False


def find_primary_takeout_photos_dir(root_dir: Path) -> Optional[Path]:
    """Finds the main 'Photos from <Year>' or 'Google Photos' directory within root_dir."""
    for p in root_dir.rglob("*"):
        if p.is_dir() and "photos from" in p.name.lower():
            return p
    for p in root_dir.rglob("*"):
        if p.is_dir() and p.name.lower() == "google photos":
            return p
    return None


def stage_takeout_archives(
    zip_files: List[Path],
    staging_dir: Path,
    mix_folders: bool = True,
    show_progress: bool = True
) -> Tuple[Path, int]:
    """
    Extracts a list of Takeout archives into a unified staging directory:
    1. Multi-chunk archives containing 'Takeout/...' unpack first and merge together.
    2. Direct photo archives (Photos-*.zip) or flat archives unpack directly into the
       primary 'Photos from <Year>' folder if mix_folders is True (so they are mixed
       with the rest of the library instead of becoming an isolated album).
    
    Returns:
        (staging_dir, total_extracted_archives)
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    extracted_count = 0

    # Categorize archives: Takeout root archives first, flat/photos archives second
    takeout_root_zips = []
    other_zips = []

    for z_path in zip_files:
        has_takeout_root = False
        try:
            with zipfile.ZipFile(z_path, "r") as z:
                sample = z.namelist()[:10]
                has_takeout_root = any(x.startswith("Takeout/") or x.startswith("Takeout\\") for x in sample)
        except Exception as e:
            logger.warning(f"Could not inspect {z_path.name}: {e}")

        if has_takeout_root:
            takeout_root_zips.append(z_path)
        else:
            other_zips.append(z_path)

    total_archives = len(takeout_root_zips) + len(other_zips)
    current_idx = 0

    # 1. Unpack Takeout root archives first
    for z_path in takeout_root_zips:
        current_idx += 1
        prefix = f"[{current_idx}/{total_archives}] " if total_archives > 1 else ""
        if extract_archive(z_path, staging_dir, show_progress=show_progress, prefix=prefix):
            extracted_count += 1

    # Find the primary photos destination for non-takeout-root zips
    primary_dir = find_primary_takeout_photos_dir(staging_dir)

    # 2. Unpack other archives (e.g. Photos-1-001.zip)
    for z_path in other_zips:
        current_idx += 1
        prefix = f"[{current_idx}/{total_archives}] " if total_archives > 1 else ""
        is_photos_zip = z_path.name.lower().startswith("photos")
        if mix_folders and primary_dir is not None and is_photos_zip:
            dest = primary_dir
        elif mix_folders and primary_dir is not None:
            dest = primary_dir
        else:
            dest = staging_dir / z_path.stem

        if extract_archive(z_path, dest, show_progress=show_progress, prefix=prefix):
            extracted_count += 1

    return staging_dir, extracted_count


@dataclass
class SimulatedExtractionResult:
    total_archives: int
    total_files: int
    total_uncompressed_bytes: int
    discovered_media: List[DiscoveredMedia] = field(default_factory=list)
    metadata_map: Dict[str, MediaMetadata] = field(default_factory=dict)
    albums_found: Set[str] = field(default_factory=set)


def simulate_takeout_extraction(
    zip_files: List[Path],
    show_progress: bool = True
) -> SimulatedExtractionResult:
    """
    Simulates the extraction of Google Takeout zip archives without writing to disk:
    1. Inspects zip tables of contents in memory.
    2. Renders animated loading bars with progress intervals for each archive.
    3. Parses sidecar JSONs and filenames directly from the zip streams.
    4. Discovers media files, album mappings, and pre-resolves dates for dry-run reports.
    """
    total_files = 0
    total_uncompressed_bytes = 0
    discovered_media: List[DiscoveredMedia] = []
    metadata_map: Dict[str, MediaMetadata] = {}
    albums_found: Set[str] = set()

    total_zips = len(zip_files)

    global_sidecars: Dict[str, dict] = {}
    all_media_entries: List[Tuple[zipfile.ZipInfo, Path, str]] = []

    for idx, z_path in enumerate(zip_files, 1):
        if not z_path.is_file():
            continue

        try:
            with zipfile.ZipFile(z_path, "r") as z:
                members = z.infolist()
                total_files += len(members)
                archive_bytes = sum(m.file_size for m in members)
                total_uncompressed_bytes += archive_bytes

                mb = archive_bytes / (1024 * 1024)
                size_str = f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"

                desc = f"[{idx}/{total_zips}] Simulating unpack: {z_path.name} ({len(members)} files, {size_str})"

                if show_progress:
                    step = max(1, len(members) // 40)
                    with tqdm(
                        total=len(members),
                        desc=desc,
                        unit="file",
                        dynamic_ncols=True,
                        mininterval=0.05,
                        colour="magenta",
                        ascii=True
                    ) as pbar:
                        for chunk_start in range(0, len(members), step):
                            chunk_end = min(chunk_start + step, len(members))
                            pbar.update(chunk_end - chunk_start)
                            time.sleep(0.015)

                for m in members:
                    if m.is_dir():
                        continue
                    m_lower = m.filename.lower()
                    if m_lower.endswith(".json") and Path(m.filename).name.lower() != "metadata.json":
                        try:
                            content = z.read(m).decode("utf-8", errors="replace")
                            global_sidecars[Path(m.filename).name.lower()] = json.loads(content)
                        except Exception:
                            pass
                    else:
                        ext = Path(m.filename).suffix.lower()
                        if ext in ALL_MEDIA_EXTENSIONS:
                            all_media_entries.append((m, Path(m.filename), Path(m.filename).parent.name))

        except Exception as e:
            logger.warning(f"Failed to inspect {z_path.name} in simulation: {e}")

    # Cross-archive media and sidecar resolution
    for m, p, folder_name in all_media_entries:
        is_year = is_year_folder(folder_name)
        album = None if is_year else (folder_name if folder_name and folder_name != "." else None)
        if album:
            albums_found.add(album)

        crc_hash = f"{m.CRC:08x}_{m.file_size}"
        sim_path = Path("SIMULATED_TAKEOUT") / p

        media_item = DiscoveredMedia(
            file_path=sim_path,
            file_size=m.file_size,
            is_from_year_folder=is_year,
            album_name=album,
            full_hash=crc_hash
        )
        discovered_media.append(media_item)

        # Match sidecar if available
        meta = None
        target_names = [
            f"{p.name.lower()}.supplemental-metadata.json",
            f"{p.name.lower()}.json",
            f"{p.stem.lower()}.supplemental-metadata.json",
            f"{p.stem.lower()}.json",
            f"{p.name.lower()[:46]}.supplemental-metadata.json",
            f"{p.name.lower()[:46]}.json",
        ]
        matches = list(re.finditer(r'\(\d+\)\.', p.name))
        if matches:
            last_match = matches[-1]
            bracket = p.name[last_match.start():last_match.end() - 1]
            without_bracket = p.name[:last_match.start()] + p.name[last_match.end() - 1:]
            target_names.append(f"{without_bracket.lower()}.supplemental-metadata{bracket}.json")
            target_names.append(f"{without_bracket.lower()}{bracket}.json")

        for t_name in target_names:
            if t_name in global_sidecars:
                candidate_meta = extract_from_json_data(
                    global_sidecars[t_name],
                    json_path=sim_path.with_suffix(p.suffix + ".json")
                )
                if candidate_meta and candidate_meta.date_taken:
                    meta = candidate_meta
                    meta.match_type = (
                        "exact" if t_name.startswith(p.name.lower())
                        else "bracket_swap" if "(" in t_name
                        else "truncated_46" if len(p.name) > 46
                        else "supplemental"
                    )
                    break

        if not meta:
            guessed_dt = guess_from_filename(p.name)
            if guessed_dt:
                meta = MediaMetadata(date_taken=guessed_dt, date_source="filename_guess")
        if not meta:
            folder_dt = extract_from_folder_year(folder_name)
            if folder_dt:
                meta = MediaMetadata(date_taken=folder_dt, date_source="folder_guess")
        if not meta:
            meta = MediaMetadata(date_source="none")

        metadata_map[str(sim_path)] = meta

    return SimulatedExtractionResult(
        total_archives=total_zips,
        total_files=total_files,
        total_uncompressed_bytes=total_uncompressed_bytes,
        discovered_media=discovered_media,
        metadata_map=metadata_map,
        albums_found=albums_found
    )
