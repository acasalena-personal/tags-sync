#!/usr/bin/env python3
"""Compare files between a source and destination directory by hash or modification date."""

import argparse
import hashlib
import os
import sys

# ANSI colors
_RST = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"

# Status prefixes with icons
_SKIP = f"{_DIM}  {'--':<9}{_RST}"
_DIFF = f"{_RED}  {'DIFF':<9}{_RST}"
_MATCH = f"{_GREEN}  {'MATCH':<9}{_RST}"
_MISSING = f"{_YELLOW}  {'MISSING':<9}{_RST}"
_EXTRA = f"{_YELLOW}  {'EXTRA':<9}{_RST}"
_ERROR = f"{_RED}  {'ERROR':<9}{_RST}"


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


def file_hash(filepath):
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def file_mtime(filepath):
    """Return the modification time of a file."""
    return os.path.getmtime(filepath)


def compare(source_dir, dest_dir, type_check):
    """Compare files between source and dest. Returns exit code."""
    source_dir = os.path.abspath(source_dir)
    dest_dir = os.path.abspath(dest_dir)

    if not os.path.isdir(source_dir):
        print(f"{_ERROR}source is not a directory: {source_dir}")
        return 1
    if not os.path.isdir(dest_dir):
        print(f"{_ERROR}destination is not a directory: {dest_dir}")
        return 1

    src_files = collect_files(source_dir)
    matched = 0
    differed = 0
    missing = 0
    errors = 0

    for rel in src_files:
        src_path = os.path.join(source_dir, rel)
        dst_path = os.path.join(dest_dir, rel)

        if not os.path.exists(dst_path):
            print(f"{_MISSING}{rel}")
            missing += 1
            continue

        try:
            if type_check == "HASH":
                src_val = file_hash(src_path)
                dst_val = file_hash(dst_path)
                if src_val == dst_val:
                    print(f"{_MATCH}{rel}  {_DIM}{src_val[:12]}...{_RST}")
                    matched += 1
                else:
                    print(f"{_DIFF}{rel}  {src_val[:12]}... != {dst_val[:12]}...")
                    differed += 1
            else:  # DATE
                src_val = file_mtime(src_path)
                dst_val = file_mtime(dst_path)
                if src_val == dst_val:
                    print(f"{_MATCH}{rel}  {_DIM}{src_val}{_RST}")
                    matched += 1
                elif src_val > dst_val:
                    print(f"{_DIFF}{rel}  src newer ({src_val} > {dst_val})")
                    differed += 1
                else:
                    print(f"{_DIFF}{rel}  dest newer ({dst_val} > {src_val})")
                    differed += 1
        except Exception as e:
            print(f"{_ERROR}{rel}  {e}")
            errors += 1

    total = matched + differed + missing + errors

    # Warn about files in dest that don't exist in source
    dest_files = set(collect_files(dest_dir))
    src_set = set(src_files)
    extra = sorted(dest_files - src_set)
    extra_count = len(extra)

    print(
        f"\n{_BOLD}{total} files:{_RST} {_GREEN}{matched} matched{_RST}, {_RED}{differed} different{_RST}, {_YELLOW}{missing} missing{_RST}, {_RED}{errors} errors{_RST}"
    )

    if extra:
        print(
            f"\n{_YELLOW}{_BOLD}WARNING:{_RST} {extra_count} files in dest not in source:"
        )
        for rel in extra:
            print(f"{_EXTRA}{rel}")

    return 1 if (errors or differed) else 0


def main():
    parser = argparse.ArgumentParser(
        description="Compare files between source and destination directories."
    )
    parser.add_argument("source", help="Source directory")
    parser.add_argument("dest", help="Destination directory")
    parser.add_argument(
        "--type-check",
        choices=["HASH", "DATE"],
        default="DATE",
        help="Comparison method: HASH (SHA-256) or DATE (modification time)",
    )
    args = parser.parse_args()

    sys.exit(compare(args.source, args.dest, args.type_check))


if __name__ == "__main__":
    main()
