#!/usr/bin/env python3
"""Sync macOS Finder tags from a source directory to a destination directory."""

import argparse
import os
import plistlib
import random
import subprocess
import sys

# ANSI colors
_RST = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"

# Status prefixes with icons
_SKIP = f"{_DIM}  {'--':<9}{_RST}"
_SET = f"{_GREEN}  {'SET':<9}{_RST}"
_CLEAR = f"{_YELLOW}  {'CLEAR':<9}{_RST}"
_REORDER = f"{_CYAN}  {'REORDER':<9}{_RST}"
_SCRAMBLE = f"{_MAGENTA}  {'SCRAMBLE':<9}{_RST}"
_MISSING = f"{_YELLOW}  {'MISSING':<9}{_RST}"
_EXTRA = f"{_YELLOW}  {'EXTRA':<9}{_RST}"
_ERROR = f"{_RED}  {'ERROR':<9}{_RST}"

XATTR_KEY = "com.apple.metadata:_kMDItemUserTags"

# Color tag name -> Finder color index
COLOR_IDS = {
    "Gray": 1, "Green": 2, "Purple": 3, "Blue": 4,
    "Yellow": 5, "Orange": 6, "Red": 7,
}


def get_tags(filepath):
    """Get the ordered list of tags for a file, preserving stored order."""
    result = subprocess.run(
        ["xattr", "-px", XATTR_KEY, filepath],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    raw = bytes.fromhex(result.stdout.replace(" ", "").replace("\n", ""))
    entries = plistlib.loads(raw)
    return [entry.split("\n")[0] for entry in entries]


FINDER_INFO_KEY = "com.apple.FinderInfo"
FINDER_INFO_EMPTY = b'\x00' * 32


def _set_finder_color(filepath, color_id):
    """Set or clear the legacy Finder color label in FinderInfo.

    color_id: 0 to clear, or a COLOR_IDS value (1-7) to set.
    The label is stored in bits 1-3 of byte 9 (value << 1).
    """
    result = subprocess.run(
        ["xattr", "-px", FINDER_INFO_KEY, filepath],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if color_id == 0:
            return  # nothing to clear
        # No FinderInfo yet — create a fresh 32-byte block
        raw = bytearray(32)
    else:
        raw = bytearray(bytes.fromhex(result.stdout.replace(" ", "").replace("\n", "")))
    if len(raw) < 10:
        raw.extend(b'\x00' * (10 - len(raw)))

    # Clear old color bits, then set new ones
    raw[9] = (raw[9] & ~0x0E) | ((color_id & 0x07) << 1)

    if bytes(raw) == FINDER_INFO_EMPTY:
        subprocess.run(["xattr", "-d", FINDER_INFO_KEY, filepath], capture_output=True)
    else:
        subprocess.run(
            ["xattr", "-wx", FINDER_INFO_KEY, bytes(raw).hex(), filepath],
            capture_output=True, text=True
        )


def remove_all_tags(filepath):
    """Remove all tags and legacy FinderInfo color from a file."""
    subprocess.run(
        ["xattr", "-d", XATTR_KEY, filepath],
        capture_output=True, text=True
    )
    _set_finder_color(filepath, 0)


def set_tags(filepath, tags):
    """Set tags on a file in exact order, preserving color metadata."""
    entries = []
    for tag in tags:
        color_id = COLOR_IDS.get(tag)
        if color_id is not None:
            entries.append(f"{tag}\n{color_id}")
        else:
            entries.append(tag)
    data = plistlib.dumps(entries, fmt=plistlib.FMT_BINARY)
    hex_data = data.hex()
    subprocess.run(
        ["xattr", "-wx", XATTR_KEY, hex_data, filepath],
        capture_output=True, text=True
    )
    # Set FinderInfo color label to the first tag's color (for Finder dot display)
    first_color = COLOR_IDS.get(tags[0], 0) if tags else 0
    _set_finder_color(filepath, first_color)


# Preferred tag order: Yellow, Green always come first (in that order).
# A 3rd tag can be either Purple or Blue (but not both), and must come after Yellow+Green.
# Valid combos: Green, Yellow, Yellow+Green, Yellow+Green+Purple, Yellow+Green+Blue.
# Max 3 tags. Unknown tags are left at the end.
TAG_ORDER = ["Yellow", "Green", "Purple", "Blue"]


def sort_tags(tags):
    """Sort tags into preferred order, leaving unknown tags at the end."""
    known = [t for t in TAG_ORDER if t in tags]
    other = [t for t in tags if t not in TAG_ORDER]
    return known + other


def collect_files(directory):
    """Walk a directory and return a sorted list of relative paths (files only)."""
    paths = []
    for root, _, files in os.walk(directory):
        for name in files:
            if name == ".DS_Store":
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, directory)
            paths.append(rel)
    paths.sort()
    return paths


def fix_order(directory):
    """Reorder tags on every file to match preferred order. Returns exit code."""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        print(f"{_ERROR}not a directory: {directory}")
        return 1

    files = collect_files(directory)
    fixed = 0
    skipped = 0
    errors = 0

    for rel in files:
        filepath = os.path.join(directory, rel)
        try:
            tags = get_tags(filepath)
            if not tags:
                print(f"{_SKIP}{rel}  {_DIM}(no tags){_RST}")
                skipped += 1
                continue
            ordered = sort_tags(tags)
            if tags == ordered:
                print(f"{_SKIP}{rel}  {_DIM}[{', '.join(tags)}]{_RST}")
                skipped += 1
            else:
                remove_all_tags(filepath)
                set_tags(filepath, ordered)
                print(f"{_REORDER}{rel}  [{', '.join(tags)}] -> [{', '.join(ordered)}]")
                fixed += 1
        except Exception as e:
            print(f"{_ERROR}{rel}  {e}")
            errors += 1

    total = fixed + skipped + errors
    print(f"\n{_BOLD}{total} files:{_RST} {_CYAN}{fixed} reordered{_RST}, {_DIM}{skipped} skipped{_RST}, {_RED}{errors} errors{_RST}")
    return 1 if errors else 0


def reset(directory):
    """Remove all tags from every file in a directory. Returns exit code."""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        print(f"{_ERROR}not a directory: {directory}")
        return 1

    files = collect_files(directory)
    cleared = 0
    skipped = 0
    errors = 0

    for rel in files:
        filepath = os.path.join(directory, rel)
        try:
            tags = get_tags(filepath)
            if not tags:
                print(f"{_SKIP}{rel}")
                skipped += 1
            else:
                remove_all_tags(filepath)
                print(f"{_CLEAR}{rel}  [{', '.join(tags)}]")
                cleared += 1
        except Exception as e:
            print(f"{_ERROR}{rel}  {e}")
            errors += 1

    total = cleared + skipped + errors
    print(f"\n{_BOLD}{total} files:{_RST} {_YELLOW}{cleared} cleared{_RST}, {_DIM}{skipped} skipped{_RST}, {_RED}{errors} errors{_RST}")
    return 1 if errors else 0


def sync(source_dir, dest_dir):
    """Sync tags from source to destination. Returns exit code."""
    source_dir = os.path.abspath(source_dir)
    dest_dir = os.path.abspath(dest_dir)

    if not os.path.isdir(source_dir):
        print(f"{_ERROR}source is not a directory: {source_dir}")
        return 1
    if not os.path.isdir(dest_dir):
        print(f"{_ERROR}destination is not a directory: {dest_dir}")
        return 1

    files = collect_files(source_dir)
    skipped = 0
    updated = 0
    cleared = 0
    missing = 0
    errors = 0

    for rel in files:
        src_path = os.path.join(source_dir, rel)
        dst_path = os.path.join(dest_dir, rel)

        if not os.path.exists(dst_path):
            print(f"{_MISSING}{rel}")
            missing += 1
            continue

        try:
            src_tags = sort_tags(get_tags(src_path))
            dst_tags = get_tags(dst_path)

            # Always clear dest first, then re-apply to force Finder refresh
            remove_all_tags(dst_path)

            if not src_tags and not dst_tags:
                print(f"{_SKIP}{rel}")
                skipped += 1
            elif not src_tags and dst_tags:
                print(f"{_CLEAR}{rel}  [{', '.join(dst_tags)}] -> []")
                cleared += 1
            elif src_tags == dst_tags:
                set_tags(dst_path, src_tags)
                print(f"{_SKIP}{rel}  {_DIM}[{', '.join(src_tags)}]{_RST}")
                skipped += 1
            else:
                set_tags(dst_path, src_tags)
                old = ', '.join(dst_tags) if dst_tags else ''
                new = ', '.join(src_tags)
                print(f"{_SET}{rel}  [{old}] -> [{new}]")
                updated += 1
        except Exception as e:
            print(f"{_ERROR}{rel}  {e}")
            errors += 1

    total = skipped + updated + cleared + missing + errors
    print(f"\n{_BOLD}{total} files:{_RST} {_GREEN}{updated} set{_RST}, {_YELLOW}{cleared} cleared{_RST}, {_DIM}{skipped} skipped{_RST}, {_YELLOW}{missing} missing{_RST}, {_RED}{errors} errors{_RST}")

    # Warn about files in dest that don't exist in source
    dest_files = set(collect_files(dest_dir))
    src_files = set(files)
    extra = sorted(dest_files - src_files)
    if extra:
        print(f"\n{_YELLOW}{_BOLD}WARNING:{_RST} {len(extra)} files in dest not in source:")
        for rel in extra:
            print(f"{_EXTRA}{rel}")

    return 1 if errors else 0


def scramble(directory):
    """Randomly shuffle tag order on every tagged file. Returns exit code."""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        print(f"{_ERROR}not a directory: {directory}")
        return 1

    files = collect_files(directory)
    scrambled = 0
    skipped = 0
    errors = 0

    for rel in files:
        filepath = os.path.join(directory, rel)
        try:
            tags = get_tags(filepath)
            if len(tags) < 2:
                print(f"{_SKIP}{rel}  {_DIM}{tags if tags else '(no tags)'}{_RST}")
                skipped += 1
                continue
            shuffled = tags[:]
            while shuffled == tags:
                random.shuffle(shuffled)
            remove_all_tags(filepath)
            set_tags(filepath, shuffled)
            print(f"{_SCRAMBLE}{rel}  [{', '.join(tags)}] -> [{', '.join(shuffled)}]")
            scrambled += 1
        except Exception as e:
            print(f"{_ERROR}{rel}  {e}")
            errors += 1

    total = scrambled + skipped + errors
    print(f"\n{_BOLD}{total} files:{_RST} {_MAGENTA}{scrambled} scrambled{_RST}, {_DIM}{skipped} skipped{_RST}, {_RED}{errors} errors{_RST}")
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description="Sync macOS Finder tags between directories.")
    parser.add_argument("source", help="Source directory (tags are read from here)")
    parser.add_argument("dest", nargs="?", help="Destination directory (tags are written here)")
    parser.add_argument("--sync-dest", action="store_true", help="Sync tags from source to dest (exact match, preserving order)")
    parser.add_argument("--fix-src", action="store_true", help="Reorder source tags to preferred order and exit")
    parser.add_argument("--scramble-test-src", action="store_true", help="Randomly shuffle source tag order for testing")
    args = parser.parse_args()

    if args.scramble_test_src:
        sys.exit(scramble(args.source))
    elif args.fix_src:
        sys.exit(fix_order(args.source))
    elif args.sync_dest:
        if not args.dest:
            print(f"{_ERROR}--sync-dest requires a dest directory")
            sys.exit(1)
        sys.exit(sync(args.source, args.dest))
    else:
        if not args.dest:
            print(f"{_ERROR}dest directory is required for sync")
            sys.exit(1)
        sys.exit(sync(args.source, args.dest))


if __name__ == "__main__":
    main()
