"""
Google Photos Takeout Organizer CLI
A robust, high-performance CLI to organize Google Takeout photo archives,
match sidecars, deduplicate albums, and restore chronological order.
"""

import argparse
import sys
from pathlib import Path

from takeout_engine.organizer import TakeoutOrganizer


def parse_args():
    parser = argparse.ArgumentParser(
        prog="takeout-organizer",
        description="Organize Google Photos Takeout archives into a clean, chronological library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run preview with verbose analysis:
  python main.py -i "C:\\Takeout" -o "C:\\Photos" --dry-run

  # Execute move and organize by Year/Month:
  python main.py -i "C:\\Takeout" -o "C:\\Photos"

  # Copy instead of move, with Windows album shortcuts:
  python main.py -i "C:\\Takeout" -o "C:\\Photos" --copy --albums shortcut
        """
    )

    parser.add_argument(
        "-i", "--input",
        dest="input_dir",
        type=str,
        help="Input folder containing extracted Google Photos Takeout folders."
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
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output."
    )

    return parser.parse_args()


def interactive_prompt():
    """Fallback interactive prompt if run without arguments."""
    print("=" * 65)
    print("      GOOGLE PHOTOS TAKEOUT ORGANIZER (Interactive Mode)")
    print("=" * 65)

    input_dir = input("Enter path to Takeout folder: ").strip().strip('"\'')
    while not input_dir or not Path(input_dir).is_dir():
        print("[!] Invalid directory. Please enter an existing path.")
        input_dir = input("Enter path to Takeout folder: ").strip().strip('"\'')

    output_dir = input("Enter destination folder for organized photos: ").strip().strip('"\'')
    while not output_dir:
        output_dir = input("Enter destination folder for organized photos: ").strip().strip('"\'')

    dry_run_choice = input("Run in Dry-Run mode first to preview? [Y/n]: ").strip().lower()
    dry_run = dry_run_choice != "n"

    return input_dir, output_dir, dry_run


def main():
    args = parse_args()

    if not args.input_dir or not args.output_dir:
        if sys.stdin.isatty():
            input_dir, output_dir, dry_run = interactive_prompt()
            copy_files = False
            divide_to_dates = True
            album_behavior = "shortcut"
            skip_extras = False
            verbose = False
        else:
            print("Error: Both --input and --output are required when running non-interactively.", file=sys.stderr)
            print("Run with --help for usage instructions.", file=sys.stderr)
            sys.exit(1)
    else:
        input_dir = args.input_dir
        output_dir = args.output_dir
        dry_run = args.dry_run
        copy_files = args.copy
        divide_to_dates = args.divide_to_dates
        album_behavior = args.albums
        skip_extras = args.skip_extras
        verbose = args.verbose

    organizer = TakeoutOrganizer(
        input_dir=input_dir,
        output_dir=output_dir,
        divide_to_dates=divide_to_dates,
        copy_files=copy_files,
        album_behavior=album_behavior,
        skip_extras=skip_extras,
        dry_run=dry_run,
        verbose=verbose,
    )

    try:
        organizer.run()
    except KeyboardInterrupt:
        print("\n[!] Process interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n[!] Fatal error: {e}", file=sys.stderr)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
