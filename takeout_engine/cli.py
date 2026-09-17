"""
Google Photos Takeout Organizer CLI.
Pure ASCII terminal interface with colored accents for universal platform compatibility.
"""

import argparse
import sys
from pathlib import Path

from takeout_engine.organizer import TakeoutOrganizer
from takeout_engine.ui import (
    Theme,
    badge_archive,
    badge_clean,
    badge_info,
    badge_success,
    badge_warn,
    print_banner,
    set_use_color,
)


def parse_args():
    parser = argparse.ArgumentParser(
        prog="takeout-organizer",
        description="Organize Google Photos Takeout archives into a clean, chronological library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run preview with animated ASCII progress bars:
  takeout-organizer -i "C:\\Takeout" -o "C:\\Photos" --dry-run-loud

  # Full run: organize, inject EXIF/GPS, sort by Year/Month:
  takeout-organizer -i "C:\\Takeout" -o "C:\\Photos"

  # Copy instead of move, preserving original Takeout files:
  takeout-organizer -i "C:\\Takeout" -o "C:\\Photos" --copy --albums shortcut

  # Standalone extraction of zip archives:
  takeout-organizer --extract-only -i "C:\\Takeout" -o "C:\\Photos_Extracted"
        """
    )

    parser.add_argument(
        "-i", "--input",
        dest="input_dir",
        type=str,
        help="Input folder containing extracted Google Photos Takeout folders or zip archives."
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_dir",
        type=str,
        help="Target destination directory for organized photos."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the entire process and print a detailed diagnostic report without moving or modifying files."
    )
    parser.add_argument(
        "--dry-run-loud",
        action="store_true",
        help="Simulate the entire process including extraction with animated ASCII progress bars without writing to disk."
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them (leaves input folder intact)."
    )
    parser.add_argument(
        "--divide-to-dates",
        dest="divide_to_dates",
        action="store_true",
        default=True,
        help="Organize into Year/Month subfolders (e.g. ALL_PHOTOS/2021/08). Default: True."
    )
    parser.add_argument(
        "--no-divide-to-dates",
        dest="divide_to_dates",
        action="store_false",
        help="Keep all photos in a single flat directory."
    )
    parser.add_argument(
        "--albums",
        choices=["shortcut", "copy", "json", "ignore"],
        default="shortcut",
        help="How to handle album folders: 'shortcut' (create .lnk shortcuts), 'copy' (duplicate files into album folders), 'json' (record in albums-info.json), 'ignore' (omit album duplicates)."
    )
    parser.add_argument(
        "--skip-extras",
        action="store_true",
        help="Skip automated Google edits/effects (-edited, -effects) if base photo is present."
    )
    parser.add_argument(
        "--extract-zips",
        dest="extract_zips",
        action="store_true",
        default=True,
        help="Automatically discover and stage Google Takeout zip archives found in input_dir. Default: True."
    )
    parser.add_argument(
        "--no-extract-zips",
        dest="extract_zips",
        action="store_false",
        help="Do not unpack zip archives automatically."
    )
    parser.add_argument(
        "--write-exif",
        dest="write_exif",
        action="store_true",
        default=True,
        help="Embed capture date, GPS coordinates, and descriptions into image EXIF metadata. Default: True."
    )
    parser.add_argument(
        "--no-write-exif",
        dest="write_exif",
        action="store_false",
        help="Disable injecting EXIF metadata into image headers."
    )
    parser.add_argument(
        "--cleanup-residuals",
        dest="cleanup_residuals",
        action="store_true",
        default=True,
        help="Purge orphan JSON sidecars and prune empty input directories after moving. Default: True."
    )
    parser.add_argument(
        "--no-cleanup-residuals",
        dest="cleanup_residuals",
        action="store_false",
        help="Leave leftover JSON sidecars and empty folders in input directory."
    )
    parser.add_argument(
        "--archive-residuals",
        dest="archive_residuals",
        action="store_true",
        default=True,
        help="Bundle residual metadata JSONs into takeout_metadata_archive.zip in output directory before deletion. Default: True."
    )
    parser.add_argument(
        "--no-archive-residuals",
        dest="archive_residuals",
        action="store_false",
        help="Delete residual JSONs without archiving them into a zip file."
    )
    parser.add_argument(
        "--delete-zips",
        action="store_true",
        default=False,
        help="Delete original source zip archives after successful organization. Default: False (archives are kept as backups)."
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only discover and unpack Takeout zip archives to output_dir without organizing."
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI terminal colors."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output."
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.no_color:
        set_use_color(False)

    print_banner()

    # Standalone CLI zip extraction mode
    if args.extract_only:
        if not args.input_dir:
            print(f"{badge_warn()} --input is required when using --extract-only.", file=sys.stderr)
            sys.exit(1)
        from takeout_engine.zip_handler import find_takeout_zips, stage_takeout_archives
        in_p = Path(args.input_dir).resolve()
        out_p = Path(args.output_dir).resolve() if args.output_dir else (in_p if in_p.is_dir() else in_p.parent) / "Extracted_Takeout"
        zips = find_takeout_zips(in_p)
        if not zips:
            print(f"{badge_warn()} No Takeout zip archives found for '{in_p}'.", file=sys.stderr)
            sys.exit(1)
        print(f"{badge_archive()} Found {Theme.value(str(len(zips)))} zip archive(s). Extracting to '{Theme.primary(str(out_p))}'...")
        stage_takeout_archives(zips, out_p, mix_folders=True, show_progress=True)
        print(f"\n{badge_success()} Extraction complete! All files extracted and merged into '{Theme.primary(str(out_p))}'.")
        sys.exit(0)

    if not args.input_dir or not args.output_dir:
        print(f"{badge_warn()} Both -i/--input and -o/--output are required.", file=sys.stderr)
        print("Run 'takeout-organizer --help' for usage instructions.\n", file=sys.stderr)
        sys.exit(2)
    else:
        input_dir = args.input_dir
        output_dir = args.output_dir
        dry_run = args.dry_run or args.dry_run_loud
        dry_run_loud = args.dry_run_loud
        copy_files = args.copy
        divide_to_dates = args.divide_to_dates
        album_behavior = args.albums
        skip_extras = args.skip_extras
        verbose = args.verbose
        extract_zips = args.extract_zips
        write_exif = args.write_exif
        cleanup_residuals = args.cleanup_residuals
        archive_residuals = args.archive_residuals
        delete_zips = args.delete_zips

    organizer = TakeoutOrganizer(
        input_dir=input_dir,
        output_dir=output_dir,
        divide_to_dates=divide_to_dates,
        copy_files=copy_files,
        album_behavior=album_behavior,
        skip_extras=skip_extras,
        dry_run=dry_run,
        dry_run_loud=dry_run_loud,
        verbose=verbose,
        extract_zips=extract_zips,
        write_exif=write_exif,
        cleanup_residuals=cleanup_residuals,
        archive_residuals=archive_residuals,
        delete_zips=delete_zips,
    )

    try:
        organizer.run()
    except KeyboardInterrupt:
        print(f"\n{badge_warn()} Process interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n{badge_warn()} Fatal error: {e}", file=sys.stderr)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
