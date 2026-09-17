"""
TakeoutOrganizer: The core orchestration engine for scanning, deduplicating,
resolving metadata, and organizing Google Photos Takeout archives.
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tqdm import tqdm

from .constants import ALL_MEDIA_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from .date_extractor import MediaMetadata, extract_media_metadata
from .deduplicator import DiscoveredMedia, deduplicate_and_group_albums, is_year_folder
from .exif_writer import inject_exif_metadata
from .file_ops import (
    archive_or_delete_residuals,
    create_windows_shortcut,
    get_collision_safe_path,
    prune_empty_directories,
    set_file_creation_and_mtime,
)
from .zip_handler import find_takeout_zips, stage_takeout_archives, simulate_takeout_extraction
from .ui import (
    Theme,
    badge_archive,
    badge_clean,
    badge_dedup,
    badge_gps,
    badge_info,
    badge_match,
    badge_success,
    badge_warn,
)

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
    gps_count: int = 0
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
        dry_run_loud: bool = False,
        verbose: bool = False,
        extract_zips: bool = True,
        write_exif: bool = True,
        cleanup_residuals: bool = True,
        archive_residuals: bool = True,
        delete_zips: bool = False,
    ):
        self.input_dir = Path(input_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.divide_to_dates = divide_to_dates
        self.copy_files = copy_files
        self.album_behavior = album_behavior
        self.skip_extras = skip_extras
        self.dry_run = dry_run or dry_run_loud
        self.dry_run_loud = dry_run_loud
        self.verbose = verbose
        self.extract_zips = extract_zips
        self.write_exif = write_exif
        self.cleanup_residuals = cleanup_residuals
        self.archive_residuals = archive_residuals
        self.delete_zips = delete_zips

        self.stats = OrganizerStats()
        self.staging_dir: Optional[Path] = None
        self.folder_title_indexes: Dict[Path, Dict[str, Path]] = {}
        self.discovered_media: List[DiscoveredMedia] = []
        self.simulated_metadata_map: Dict[str, MediaMetadata] = {}
        self.planned_actions: List[PlannedFileAction] = []
        self.albums_catalog: Dict[str, List[str]] = {}

    def scan_and_discover(self):
        """Walks the input folder, classifies directories, and pre-indexes sidecar JSON files."""
        if not (self.input_dir.is_dir() or (self.input_dir.is_file() and self.input_dir.suffix.lower() == ".zip")):
            raise FileNotFoundError(f"Input path does not exist or is not a directory/zip: {self.input_dir}")

        scan_root = self.input_dir
        if self.extract_zips:
            zip_files = find_takeout_zips(self.input_dir)
            if zip_files:
                print(f"{badge_archive()} Discovered {Theme.value(str(len(zip_files)))} Takeout zip archives for '{Theme.primary(str(self.input_dir))}'.")
                if self.dry_run_loud:
                    print(f"{badge_archive()} [Dry-Run-Loud] Simulating unpacking {Theme.value(str(len(zip_files)))} archives with progress intervals...")
                    sim_res = simulate_takeout_extraction(zip_files, show_progress=not self.verbose)
                    self.discovered_media = sim_res.discovered_media
                    self.simulated_metadata_map = sim_res.metadata_map
                    self.stats.total_scanned_files = sim_res.total_files
                    self.stats.total_media_found = len(sim_res.discovered_media)
                    self.stats.photos_count = sum(1 for m in sim_res.discovered_media if m.file_path.suffix.lower() in PHOTO_EXTENSIONS)
                    self.stats.videos_count = sum(1 for m in sim_res.discovered_media if m.file_path.suffix.lower() in VIDEO_EXTENSIONS)
                    self.stats.json_count = len(sim_res.metadata_map)
                    self.stats.albums_discovered = sim_res.albums_found
                    print(f"{badge_info()} Found {Theme.value(str(self.stats.total_media_found))} media files ({Theme.primary(str(self.stats.photos_count))} photos, {Theme.secondary(str(self.stats.videos_count))} videos) and {Theme.value(str(self.stats.json_count))} JSON sidecars.")
                    return
                elif not self.dry_run:
                    parent_dir = self.input_dir if self.input_dir.is_dir() else self.input_dir.parent
                    staging_path = parent_dir / ".staging_takeout"
                    print(f"{badge_archive()} Unpacking archives to staging directory '{Theme.muted(str(staging_path))}'...")
                    self.staging_dir, _ = stage_takeout_archives(
                        zip_files, staging_path, mix_folders=True, show_progress=not self.verbose
                    )
                    scan_root = self.staging_dir
                else:
                    print(f"{badge_archive()} [Dry-Run] Detected zip archives: {[z.name for z in zip_files]}")

        logger.info(f"Scanning directory: {scan_root}")
        print(f"{badge_info()} Scanning files in '{Theme.primary(str(scan_root))}'...")

        # 1. Walk directory tree
        for root_str, dirs, files in os.walk(scan_root):
            root = Path(root_str)
            folder_name = root.name
            is_year = is_year_folder(folder_name)

            # Check if parent or sibling indicates an album
            # If not a year folder and contains media files, treat folder name as album (unless albums are ignored)
            album_name = None if (is_year or self.album_behavior == "ignore") else folder_name

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

        print(f"{badge_info()} Found {Theme.value(str(self.stats.total_media_found))} media files ({Theme.primary(str(self.stats.photos_count))} photos, {Theme.secondary(str(self.stats.videos_count))} videos) and {Theme.value(str(self.stats.json_count))} JSON sidecars.")

    def process_and_plan(self):
        """Runs deduplication, resolves dates and metadata, and calculates planned target paths."""
        if not self.discovered_media:
            return

        # 1. Deduplicate files and merge albums
        print(f"{badge_dedup()} Deduplicating files and linking albums...")
        dedup_res = deduplicate_and_group_albums(self.discovered_media)
        self.duplicate_files = dedup_res.duplicate_files
        self.stats.duplicates_removed = len(dedup_res.duplicate_files)
        self.stats.bytes_saved = dedup_res.bytes_saved
        self.stats.albums_discovered = dedup_res.albums_found

        print(f"{badge_dedup()} Deduplication finished. {Theme.value(str(len(dedup_res.unique_media)))} unique files identified. {Theme.warning(str(self.stats.duplicates_removed))} duplicates skipped ({Theme.success(f'{self.stats.bytes_saved / (1024 * 1024):.1f} MB saved')}).")

        # 2. Resolve metadata for each unique file
        print(f"{badge_match()} Matching JSON sidecars and extracting timestamps...")
        for item in tqdm(
            dedup_res.unique_media,
            desc="Resolving dates",
            disable=self.verbose,
            dynamic_ncols=True,
            mininterval=0.05,
            colour="cyan",
            ascii=True
        ):
            if str(item.file_path) in self.simulated_metadata_map:
                meta = self.simulated_metadata_map[str(item.file_path)]
            else:
                title_idx = self.folder_title_indexes.get(item.file_path.parent)
                meta = extract_media_metadata(item.file_path, title_idx)

            # Update stats
            self.stats.date_sources[meta.date_source] += 1
            if meta.latitude is not None and meta.longitude is not None:
                self.stats.gps_count += 1
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
        sep = "=" * 78
        print("\n" + Theme.primary(sep))
        print(Theme.bold("                 GOOGLE PHOTOS TAKEOUT ORGANIZER - DRY RUN REPORT"))
        print(Theme.primary(sep))

        print("\n" + Theme.primary("--- [1] SCANNING & DISCOVERY SUMMARY ---"))
        print(f"  Input folder:             {Theme.primary(str(self.input_dir))}")
        print(f"  Output folder:            {Theme.primary(str(self.output_dir))}")
        print(f"  Total files scanned:      {Theme.value(str(self.stats.total_scanned_files))}")
        print(f"  Total media files found:  {Theme.value(str(self.stats.total_media_found))}")
        print(f"    - Photos:               {Theme.primary(str(self.stats.photos_count))}")
        print(f"    - Videos:               {Theme.secondary(str(self.stats.videos_count))}")
        print(f"  JSON sidecars found:      {Theme.value(str(self.stats.json_count))}")
        print(f"  Distinct albums found:    {Theme.value(str(len(self.stats.albums_discovered)))}")

        print("\n" + Theme.warning("--- [2] DEDUPLICATION & STORAGE EFFICIENCY ---"))
        print(f"  Unique files to keep:     {Theme.success(str(len(self.planned_actions)))}")
        print(f"  Duplicate files detected: {Theme.warning(str(self.stats.duplicates_removed))}")
        mb_saved = self.stats.bytes_saved / (1024 * 1024)
        print(f"  Disk space preserved:     {Theme.success(f'{mb_saved:.2f} MB')} ({mb_saved / 1024:.2f} GB)")

        print("\n" + Theme.success("--- [3] METADATA & TIMESTAMP RESOLUTION ---"))
        total_unique = len(self.planned_actions) if self.planned_actions else 1
        print(f"  GPS location embedded:    {Theme.secondary(f'{self.stats.gps_count:6d}')}  ({(self.stats.gps_count / total_unique) * 100:5.1f}%)")
        for src, count in self.stats.date_sources.items():
            pct = (count / total_unique) * 100
            label = {
                "json": "From JSON sidecar:       ",
                "exif": "From embedded EXIF:      ",
                "filename_guess": "Guessed from filename:   ",
                "folder_guess": "Fallback to folder year: ",
                "none": "No date found (_unorg):  ",
            }.get(src, src)
            color_fn = Theme.success if src in ("json", "exif") else Theme.warning if "guess" in src else Theme.danger
            print(f"  {label} {color_fn(f'{count:6d}')}  ({pct:5.1f}%)")

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
            if act.metadata.latitude is not None and act.metadata.longitude is not None:
                alt_str = f", {act.metadata.altitude:.1f}m alt" if act.metadata.altitude is not None else ""
                print(f"       Geo:    {act.metadata.latitude:.5f}, {act.metadata.longitude:.5f}{alt_str}")
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
            print(f"{badge_warn()} No actions to execute.")
            return

        mode_str = "Copying" if self.copy_files else "Moving"
        print(f"{badge_info()} {mode_str} {Theme.value(str(len(self.planned_actions)))} files to '{Theme.primary(str(self.output_dir))}'...")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        transfer_count = 0
        error_count = 0

        for action in tqdm(
            self.planned_actions,
            desc=f"{mode_str} media",
            dynamic_ncols=True,
            mininterval=0.05,
            colour="cyan",
            ascii=True
        ):
            dest, is_identical = get_collision_safe_path(action.target_path, action.source_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                if is_identical:
                    # File already organized with identical content
                    if not self.copy_files:
                        action.source_path.unlink(missing_ok=True)
                else:
                    if self.copy_files:
                        shutil.copy2(action.source_path, dest)
                    else:
                        shutil.move(str(action.source_path), str(dest))

                    # Inject EXIF metadata (GPS, Date, Description) directly into file headers
                    if self.write_exif and action.metadata:
                        inject_exif_metadata(
                            dest,
                            date_taken=action.metadata.date_taken,
                            latitude=action.metadata.latitude,
                            longitude=action.metadata.longitude,
                            altitude=action.metadata.altitude,
                            description=action.metadata.description,
                        )

                    # Update Windows NTFS creation time and modification time
                    if action.metadata.date_taken:
                        set_file_creation_and_mtime(dest, action.metadata.date_taken)

                # Create album shortcuts
                for sc_dir in action.album_shortcuts:
                    create_windows_shortcut(dest, sc_dir)

                # Copy to album directories if configured
                for copy_path in action.album_copies:
                    album_dest, album_identical = get_collision_safe_path(copy_path, dest)
                    album_dest.parent.mkdir(parents=True, exist_ok=True)
                    if not album_identical:
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
            print(f"{badge_info()} Saved album catalog to '{Theme.muted(str(catalog_file))}'")

        # Delete duplicate input files if moving
        if not self.copy_files and hasattr(self, "duplicate_files"):
            for dup_path, _ in self.duplicate_files:
                try:
                    dup_path.unlink(missing_ok=True)
                except OSError:
                    pass

        # Post-transfer cleanup: residual sidecars & empty folder pruning
        if self.cleanup_residuals and not self.copy_files:
            clean_root = self.staging_dir if self.staging_dir else self.input_dir
            cleaned_json_count, zip_arch = archive_or_delete_residuals(
                clean_root,
                self.output_dir,
                archive_zip=self.archive_residuals
            )
            if cleaned_json_count > 0:
                if zip_arch:
                    print(f"{badge_clean()} Archived {Theme.value(str(cleaned_json_count))} residual metadata JSONs to '{Theme.muted(zip_arch.name)}' and purged raw sidecars.")
                else:
                    print(f"{badge_clean()} Purged {Theme.value(str(cleaned_json_count))} residual metadata JSONs from input directory.")

            pruned_count = prune_empty_directories(clean_root)
            if pruned_count > 0:
                print(f"{badge_clean()} Pruned {Theme.value(str(pruned_count))} empty source directories.")

            if self.staging_dir and self.staging_dir.exists():
                shutil.rmtree(self.staging_dir, ignore_errors=True)

        # Delete source zip archives only if explicitly requested via --delete-zips
        if self.delete_zips and not self.copy_files and not self.dry_run:
            zip_files = find_takeout_zips(self.input_dir)
            if zip_files:
                for z_path in zip_files:
                    try:
                        z_path.unlink(missing_ok=True)
                        logger.info(f"Deleted source archive: {z_path.name}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {z_path.name}: {e}")
                print(f"{badge_archive()} Deleted {Theme.value(str(len(zip_files)))} source zip archive(s) (--delete-zips enabled).")

        print(f"\n{badge_success()} Processing complete! {Theme.value(str(transfer_count))} files organized successfully. ({error_count} errors)")

    def run(self):
        """Full pipeline runner."""
        self.scan_and_discover()
        self.process_and_plan()

        if self.dry_run_loud:
            if self.planned_actions:
                mode_str = "Copying" if self.copy_files else "Moving"
                print(f"\n{badge_info()} [Dry-Run-Loud] Simulating {mode_str.lower()} {Theme.value(str(len(self.planned_actions)))} files with progress intervals...")
                step = max(1, len(self.planned_actions) // 50)
                with tqdm(
                    total=len(self.planned_actions),
                    desc=f"[Dry-Run] {mode_str} media",
                    unit="file",
                    dynamic_ncols=True,
                    mininterval=0.05,
                    colour="cyan",
                    ascii=True
                ) as pbar:
                    for chunk_start in range(0, len(self.planned_actions), step):
                        chunk_end = min(chunk_start + step, len(self.planned_actions))
                        pbar.update(chunk_end - chunk_start)
                        time.sleep(0.015)
                print(f"{badge_gps()} Simulated embedding EXIF metadata into media headers.")
                print(f"{badge_clean()} Simulated archiving residual JSON sidecars.")
                print(f"{badge_clean()} Simulated pruning empty source folders.")

            self.print_dry_run_report()
        elif self.dry_run:
            self.print_dry_run_report()
        else:
            self.execute()
