"""
TakeoutOrganizer: The core orchestration engine for scanning, deduplicating,
resolving metadata, and organizing Google Photos Takeout archives.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tqdm import tqdm

from .constants import ALL_MEDIA_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from .date_extractor import MediaMetadata, extract_media_metadata
from .deduplicator import DiscoveredMedia, deduplicate_and_group_albums, is_year_folder
from .file_ops import create_windows_shortcut, get_collision_safe_path, set_file_creation_and_mtime

logger = logging.getLogger("takeout_engine")


@dataclass
class PlannedFileAction:
    source_path: Path
    target_path: Path
    metadata: MediaMetadata
    album_shortcuts: List[Path] = field(default_factory=list)
    album_copies: List[Path] = field(default_factory=list)


@dataclass
class OrganizerStats:
    total_scanned_files: int = 0
    total_media_found: int = 0
    photos_count: int = 0
    videos_count: int = 0
    json_count: int = 0
    duplicates_removed: int = 0
    bytes_saved: int = 0
    albums_discovered: Set[str] = field(default_factory=set)
    date_sources: Dict[str, int] = field(default_factory=lambda: {
        "json": 0, "exif": 0, "filename_guess": 0, "folder_guess": 0, "none": 0
    })
    match_types: Dict[str, int] = field(default_factory=dict)
    skipped_extras: int = 0


class TakeoutOrganizer:
    def __init__(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        divide_to_dates: bool = True,
        copy_files: bool = False,
        album_behavior: str = "shortcut",  # "shortcut", "copy", "json", "ignore"
        skip_extras: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ):
        self.input_dir = Path(input_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.divide_to_dates = divide_to_dates
        self.copy_files = copy_files
        self.album_behavior = album_behavior
        self.skip_extras = skip_extras
        self.dry_run = dry_run
        self.verbose = verbose

        self.stats = OrganizerStats()
        self.folder_title_indexes: Dict[Path, Dict[str, Path]] = {}
        self.discovered_media: List[DiscoveredMedia] = []
        self.planned_actions: List[PlannedFileAction] = []
        self.albums_catalog: Dict[str, List[str]] = {}

    def scan_and_discover(self):
        """Walks the input folder, classifies directories, and pre-indexes sidecar JSON files."""
        if not self.input_dir.is_dir():
            raise FileNotFoundError(f"Input directory does not exist: {self.input_dir}")

        logger.info(f"Scanning directory: {self.input_dir}")
        print(f"[*] Scanning files in '{self.input_dir}'...")

        # 1. Walk directory tree
        for root_str, dirs, files in os.walk(self.input_dir):
            root = Path(root_str)
            folder_name = root.name
            is_year = is_year_folder(folder_name)

            # Check if parent or sibling indicates an album
            # If not a year folder and contains media files, treat folder name as album
            album_name = None if is_year else folder_name

            title_index: Dict[str, Path] = {}

            for f in files:
                self.stats.total_scanned_files += 1
                file_path = root / f
                ext = file_path.suffix.lower()

                if ext == ".json":
                    self.stats.json_count += 1
                    # Try reading title for the directory index
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="replace") as jf:
                            data = json.load(jf)
                            if isinstance(data, dict) and "title" in data and isinstance(data["title"], str):
                                title_index[data["title"]] = file_path
                    except Exception:
                        pass
                    continue

                if ext in ALL_MEDIA_EXTENSIONS:
                    self.stats.total_media_found += 1
                    if ext in PHOTO_EXTENSIONS:
                        self.stats.photos_count += 1
                    elif ext in VIDEO_EXTENSIONS:
                        self.stats.videos_count += 1

                    try:
                        size = file_path.stat().st_size
                    except OSError:
                        continue

                    self.discovered_media.append(
                        DiscoveredMedia(
                            file_path=file_path,
                            file_size=size,
                            is_from_year_folder=is_year,
                            album_name=album_name
                        )
                    )

            if title_index:
                self.folder_title_indexes[root] = title_index

        print(f"[*] Found {self.stats.total_media_found} media files ({self.stats.photos_count} photos, {self.stats.videos_count} videos) and {self.stats.json_count} JSON sidecars.")

    def process_and_plan(self):
        """Runs deduplication, resolves dates and metadata, and calculates planned target paths."""
        if not self.discovered_media:
            return

        # 1. Deduplicate files and merge albums
        print("[*] Deduplicating files and linking albums...")
        dedup_res = deduplicate_and_group_albums(self.discovered_media)
        self.stats.duplicates_removed = len(dedup_res.duplicate_files)
        self.stats.bytes_saved = dedup_res.bytes_saved
        self.stats.albums_discovered = dedup_res.albums_found

        print(f"[*] Deduplication finished. {len(dedup_res.unique_media)} unique files identified. {self.stats.duplicates_removed} duplicate copies skipped ({self.stats.bytes_saved / (1024 * 1024):.1f} MB saved).")

        # 2. Resolve metadata for each unique file
        print("[*] Matching JSON sidecars and extracting timestamps...")
        for item in tqdm(dedup_res.unique_media, desc="Resolving dates", disable=self.verbose):
            title_idx = self.folder_title_indexes.get(item.file_path.parent)
            meta = extract_media_metadata(item.file_path, title_idx)

            # Update stats
            self.stats.date_sources[meta.date_source] += 1
            if meta.match_type:
                self.stats.match_types[meta.match_type] = self.stats.match_types.get(meta.match_type, 0) + 1

            # 3. Determine target destination
            date = meta.date_taken
            filename = item.file_path.name

            if date:
                if self.divide_to_dates:
                    rel_dir = Path("ALL_PHOTOS") / f"{date.year}" / f"{date.month:02d}"
                else:
                    rel_dir = Path("ALL_PHOTOS")
            else:
                rel_dir = Path("ALL_PHOTOS") / "_unorganized"

            target_path = self.output_dir / rel_dir / filename

            action = PlannedFileAction(
                source_path=item.file_path,
                target_path=target_path,
                metadata=meta
            )

            # 4. Handle albums
            if item.albums:
                self.albums_catalog[filename] = sorted(list(item.albums))
                for album in item.albums:
                    album_clean = "".join(c for c in album if c not in r'\/:*?"<>|').strip() or "Untitled_Album"
                    if self.album_behavior == "shortcut":
                        action.album_shortcuts.append(self.output_dir / "Albums" / album_clean)
                    elif self.album_behavior == "copy":
                        action.album_copies.append(self.output_dir / "Albums" / album_clean / filename)

            self.planned_actions.append(action)

    def print_dry_run_report(self):
        """Prints an extensive, clear report of the planned operations."""
        print("\n" + "=" * 78)
        print("                 GOOGLE PHOTOS TAKEOUT ORGANIZER - DRY RUN REPORT")
        print("=" * 78)

        print("\n--- [1] SCANNING & DISCOVERY SUMMARY ---")
        print(f"  Input folder:             {self.input_dir}")
        print(f"  Output folder:            {self.output_dir}")
        print(f"  Total files scanned:      {self.stats.total_scanned_files}")
        print(f"  Total media files found:  {self.stats.total_media_found}")
        print(f"    - Photos:               {self.stats.photos_count}")
        print(f"    - Videos:               {self.stats.videos_count}")
        print(f"  JSON sidecars found:      {self.stats.json_count}")
        print(f"  Distinct albums found:    {len(self.stats.albums_discovered)}")

        print("\n--- [2] DEDUPLICATION & STORAGE EFFICIENCY ---")
        print(f"  Unique files to keep:     {len(self.planned_actions)}")
        print(f"  Duplicate files detected: {self.stats.duplicates_removed}")
        mb_saved = self.stats.bytes_saved / (1024 * 1024)
        print(f"  Disk space preserved:     {mb_saved:.2f} MB ({mb_saved / 1024:.2f} GB)")

        print("\n--- [3] METADATA & TIMESTAMP RESOLUTION ---")
        total_unique = len(self.planned_actions) if self.planned_actions else 1
        for src, count in self.stats.date_sources.items():
            pct = (count / total_unique) * 100
            label = {
                "json": "From JSON sidecar:       ",
                "exif": "From embedded EXIF:      ",
                "filename_guess": "Guessed from filename:   ",
                "folder_guess": "Fallback to folder year: ",
                "none": "No date found (_unorg):  ",
            }.get(src, src)
            print(f"  {label} {count:6d}  ({pct:5.1f}%)")

        print("\n--- [4] HEURISTIC SIDECAR MATCHING BREAKDOWN ---")
        if self.stats.match_types:
            for match_type, count in sorted(self.stats.match_types.items(), key=lambda x: -x[1]):
                label = {
                    "exact": "Exact filename match (photo.jpg.json)",
                    "truncated_46": "Takeout 51-char truncation fix",
                    "truncated_47": "Takeout 47-char truncation boundary",
                    "truncated_51": "Takeout 51-char truncation boundary",
                    "bracket_swap": "Bracket swap duplicate fix (photo.jpg(1).json)",
                    "bracket_swap_truncated": "Truncated bracket swap fix",
                    "extra_stripped": "Creation suffix stripped (-edited/-effects)",
                    "extra_bracket_swap": "Suffix + bracket swap combination",
                    "extensionless": "Uploaded without extension (photo.json)",
                    "title_indexed": "In-folder title attribute match",
                }.get(match_type, match_type)
                print(f"  - {label:<50}: {count}")
        else:
            print("  (No sidecar JSONs matched)")

        if self.stats.albums_discovered:
            print(f"\n--- [5] ALBUM RELATIONSHIPS ({len(self.stats.albums_discovered)} Albums) ---")
            print(f"  Album Strategy:           {self.album_behavior.upper()}")
            sample_albums = list(self.stats.albums_discovered)[:8]
            for album in sample_albums:
                print(f"  - {album}")
            if len(self.stats.albums_discovered) > 8:
                print(f"  ... and {len(self.stats.albums_discovered) - 8} more albums")

        print("\n--- [6] SAMPLE OF PLANNED ACTIONS (First 15 items) ---")
        sample_actions = self.planned_actions[:15]
        for idx, act in enumerate(sample_actions, 1):
            dt_str = act.metadata.date_taken.strftime("%Y-%m-%d %H:%M:%S") if act.metadata.date_taken else "UNKNOWN DATE"
            reason = f"[{act.metadata.date_source}:{act.metadata.match_type or 'direct'}]"
            print(f"  [{idx:02d}] {act.source_path.name}")
            print(f"       Date:   {dt_str} {reason}")
            try:
                rel_dest = act.target_path.relative_to(self.output_dir)
            except ValueError:
                rel_dest = act.target_path
            print(f"       Target: {rel_dest}")
            if act.album_shortcuts:
                print(f"       Links:  {len(act.album_shortcuts)} album shortcut(s)")
            print()

        print("=" * 78)
        print("  DRY RUN COMPLETE: No files were moved or altered.")
        print("  To execute these actions, run without the --dry-run flag.")
        print("=" * 78 + "\n")

    def execute(self):
        """Executes the planned file transfers and updates filesystem timestamps."""
        if not self.planned_actions:
            print("[!] No actions to execute.")
            return

        mode_str = "Copying" if self.copy_files else "Moving"
        print(f"[*] {mode_str} {len(self.planned_actions)} files to '{self.output_dir}'...")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        transfer_count = 0
        error_count = 0

        for action in tqdm(self.planned_actions, desc=f"{mode_str} media"):
            dest = get_collision_safe_path(action.target_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                if self.copy_files:
                    shutil.copy2(action.source_path, dest)
                else:
                    shutil.move(str(action.source_path), str(dest))

                # Update Windows NTFS creation time and modification time
                if action.metadata.date_taken:
                    set_file_creation_and_mtime(dest, action.metadata.date_taken)

                # Create album shortcuts
                for sc_dir in action.album_shortcuts:
                    create_windows_shortcut(dest, sc_dir)

                # Copy to album directories if configured
                for copy_path in action.album_copies:
                    album_dest = get_collision_safe_path(copy_path)
                    album_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, album_dest)
                    if action.metadata.date_taken:
                        set_file_creation_and_mtime(album_dest, action.metadata.date_taken)

                transfer_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing {action.source_path.name}: {e}")

        # Write albums-info.json if album_behavior == 'json'
        if self.album_behavior == "json" and self.albums_catalog:
            catalog_file = self.output_dir / "albums-info.json"
            with open(catalog_file, "w", encoding="utf-8") as f:
                json.dump(self.albums_catalog, f, indent=2)
            print(f"[*] Saved album catalog to '{catalog_file}'")

        print(f"\n[+] Processing complete! {transfer_count} files organized successfully. ({error_count} errors)")

    def run(self):
        """Full pipeline runner."""
        self.scan_and_discover()
        self.process_and_plan()

        if self.dry_run:
            self.print_dry_run_report()
        else:
            self.execute()
