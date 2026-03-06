#!/usr/bin/env python3
"""Sync macOS Finder tags from a source directory to a destination directory."""

import argparse
import os
import plistlib
import random
import subprocess
import sys

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


def _clear_finder_color(filepath):
    """Clear the legacy Finder color label from FinderInfo."""
    result = subprocess.run(
        ["xattr", "-px", FINDER_INFO_KEY, filepath],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return
    raw = bytes.fromhex(result.stdout.replace(" ", "").replace("\n", ""))
    if len(raw) >= 10 and (raw[9] & 0x0E):
        # Clear color bits (bits 1-3 of byte 9)
        updated = bytearray(raw)
        updated[9] &= ~0x0E
        if bytes(updated) == FINDER_INFO_EMPTY:
            subprocess.run(["xattr", "-d", FINDER_INFO_KEY, filepath], capture_output=True)
        else:
            subprocess.run(
                ["xattr", "-wx", FINDER_INFO_KEY, bytes(updated).hex(), filepath],
                capture_output=True, text=True
            )


def remove_all_tags(filepath):
    """Remove all tags and legacy FinderInfo color from a file."""
    subprocess.run(
        ["xattr", "-d", XATTR_KEY, filepath],
        capture_output=True, text=True
    )
    _clear_finder_color(filepath)


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
    _clear_finder_color(filepath)


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
        print(f"ERROR: not a directory: {directory}")
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
                print(f"SKIP     {rel}  (no tags)")
                skipped += 1
                continue
            ordered = sort_tags(tags)
            if tags == ordered:
                print(f"SKIP     {rel}  [{', '.join(tags)}]")
                skipped += 1
            else:
                remove_all_tags(filepath)
                set_tags(filepath, ordered)
                print(f"REORDER  {rel}  [{', '.join(tags)}] -> [{', '.join(ordered)}]")
                fixed += 1
        except Exception as e:
            print(f"ERROR    {rel}  {e}")
            errors += 1

    total = fixed + skipped + errors
    print(f"\n{total} files: {fixed} reordered, {skipped} skipped, {errors} errors")
    return 1 if errors else 0


def reset(directory):
    """Remove all tags from every file in a directory. Returns exit code."""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        print(f"ERROR: not a directory: {directory}")
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
                print(f"SKIP     {rel}")
                skipped += 1
            else:
                remove_all_tags(filepath)
                print(f"CLEAR    {rel}  [{', '.join(tags)}]")
                cleared += 1
        except Exception as e:
            print(f"ERROR    {rel}  {e}")
            errors += 1

    total = cleared + skipped + errors
    print(f"\n{total} files: {cleared} cleared, {skipped} skipped, {errors} errors")
    return 1 if errors else 0


def sync(source_dir, dest_dir):
    """Sync tags from source to destination. Returns exit code."""
    source_dir = os.path.abspath(source_dir)
    dest_dir = os.path.abspath(dest_dir)

    if not os.path.isdir(source_dir):
        print(f"ERROR: source is not a directory: {source_dir}")
        return 1
    if not os.path.isdir(dest_dir):
        print(f"ERROR: destination is not a directory: {dest_dir}")
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
            print(f"MISSING  {rel}")
            missing += 1
            continue

        try:
            src_tags = sort_tags(get_tags(src_path))
            dst_tags = get_tags(dst_path)

            # Always clear dest first, then re-apply to force Finder refresh
            remove_all_tags(dst_path)

            if not src_tags and not dst_tags:
                print(f"SKIP     {rel}")
                skipped += 1
            elif not src_tags and dst_tags:
                print(f"CLEAR    {rel}  [{', '.join(dst_tags)}] -> []")
                cleared += 1
            elif src_tags == dst_tags:
                set_tags(dst_path, src_tags)
                print(f"SKIP     {rel}  [{', '.join(src_tags)}]")
                skipped += 1
            else:
                set_tags(dst_path, src_tags)
                old = ', '.join(dst_tags) if dst_tags else ''
                new = ', '.join(src_tags)
                print(f"SET      {rel}  [{old}] -> [{new}]")
                updated += 1
        except Exception as e:
            print(f"ERROR    {rel}  {e}")
            errors += 1

    total = skipped + updated + cleared + missing + errors
    print(f"\n{total} files: {updated} set, {cleared} cleared, {skipped} skipped, {missing} missing, {errors} errors")

    # Warn about files in dest that don't exist in source
    dest_files = set(collect_files(dest_dir))
    src_files = set(files)
    extra = sorted(dest_files - src_files)
    if extra:
        print(f"\nWARNING: {len(extra)} files in dest not in source:")
        for rel in extra:
            print(f"  EXTRA  {rel}")

    return 1 if errors else 0


def scramble(directory):
    """Randomly shuffle tag order on every tagged file. Returns exit code."""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        print(f"ERROR: not a directory: {directory}")
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
                print(f"SKIP     {rel}  {tags if tags else '(no tags)'}")
                skipped += 1
                continue
            shuffled = tags[:]
            while shuffled == tags:
                random.shuffle(shuffled)
            remove_all_tags(filepath)
            set_tags(filepath, shuffled)
            print(f"SCRAMBLE {rel}  [{', '.join(tags)}] -> [{', '.join(shuffled)}]")
            scrambled += 1
        except Exception as e:
            print(f"ERROR    {rel}  {e}")
            errors += 1

    total = scrambled + skipped + errors
    print(f"\n{total} files: {scrambled} scrambled, {skipped} skipped, {errors} errors")
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
            print("ERROR: --sync-dest requires a dest directory")
            sys.exit(1)
        sys.exit(sync(args.source, args.dest))
    else:
        if not args.dest:
            print("ERROR: dest directory is required for sync")
            sys.exit(1)
        sys.exit(sync(args.source, args.dest))


if __name__ == "__main__":
    main()
