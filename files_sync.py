#!/usr/bin/env python3
"""Compare files between a source and destination directory by hash or modification date."""

import argparse
from datetime import datetime
import hashlib
import os
import subprocess
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
_RENAME = f"{_CYAN}  {'RENAME':<9}{_RST}"
_ERROR = f"{_RED}  {'ERROR':<9}{_RST}"


def collect_files(directory):
    """Walk a directory and return a sorted list of relative paths (files only)."""
    paths = []
    for root, _, files in os.walk(directory):
        for name in files:
            if name.startswith("."):
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


def fmt_size(size):
    """Format bytes as human-readable size (e.g. 1.2KB, 3.4MB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            if unit == "B":
                return f"{size}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def fmt_date(ts):
    """Format a timestamp as 'Dec 23rd, 2025 at 3:45pm'."""
    dt = datetime.fromtimestamp(ts)
    month = dt.strftime("%b")
    day = dt.day
    year = dt.year
    time = dt.strftime("%-I:%M%p").lower()
    return f"{month} {day}, {year} at {time}"


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
            else:  # DATESIZE
                src_mt = file_mtime(src_path)
                dst_mt = file_mtime(dst_path)
                src_sz = os.path.getsize(src_path)
                dst_sz = os.path.getsize(dst_path)
                src_dt = fmt_date(src_mt)
                dst_dt = fmt_date(dst_mt)
                date_match = src_mt == dst_mt
                size_match = src_sz == dst_sz
                if date_match and size_match:
                    print(f"{_MATCH}{rel}  {_DIM}{src_dt} - {fmt_size(src_sz)}{_RST}")
                    matched += 1
                else:
                    reasons = []
                    if not date_match:
                        if src_mt > dst_mt:
                            reasons.append(f"src newer ({src_dt} > {dst_dt})")
                        else:
                            reasons.append(f"dest newer ({dst_dt} > {src_dt})")
                    if not size_match:
                        reasons.append(f"size {fmt_size(src_sz)} != {fmt_size(dst_sz)}")
                    print(f"{_DIFF}{rel}  {', '.join(reasons)}")
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

    # Detect renames by matching src-only vs dest-only files by content
    src_only = sorted(rel for rel in src_files if not os.path.exists(os.path.join(dest_dir, rel)))
    renames = []
    matched_src = set()
    matched_dst = set()

    if src_only and extra:
        def fingerprint(filepath):
            try:
                if type_check == "HASH":
                    return file_hash(filepath)
                else:
                    return (file_mtime(filepath), os.path.getsize(filepath))
            except Exception:
                return None

        dst_fp = {}
        for rel in extra:
            fp = fingerprint(os.path.join(dest_dir, rel))
            if fp is not None:
                dst_fp.setdefault(fp, []).append(rel)

        for rel in src_only:
            fp = fingerprint(os.path.join(source_dir, rel))
            if fp is not None and fp in dst_fp:
                candidates = dst_fp[fp]
                for dst_rel in candidates:
                    if dst_rel not in matched_dst:
                        renames.append((rel, dst_rel, fp))
                        matched_src.add(rel)
                        matched_dst.add(dst_rel)
                        break

    if renames:
        print(f"\n{_CYAN}{_BOLD}RENAMES:{_RST} {len(renames)} probable renames detected:")
        for src_rel, dst_rel, fp in renames:
            if type_check == "HASH":
                reason = f"same hash {fp[:12]}..."
            else:
                reason = f"same date {fmt_date(fp[0])} & size {fmt_size(fp[1])}"
            print(f"{_RENAME}{src_rel}  ->  {dst_rel}  {_DIM}({reason}){_RST}")

    remaining_src = sorted(r for r in src_only if r not in matched_src)
    remaining_dst = sorted(r for r in extra if r not in matched_dst)

    if remaining_src:
        print(
            f"\n{_YELLOW}{_BOLD}WARNING:{_RST} {len(remaining_src)} files in source not in dest:"
        )
        for rel in remaining_src:
            print(f"{_MISSING}{rel}")

    if remaining_dst:
        print(
            f"\n{_YELLOW}{_BOLD}WARNING:{_RST} {len(remaining_dst)} files in dest not in source:"
        )
        for rel in remaining_dst:
            print(f"{_EXTRA}{rel}")

    return 1 if (errors or differed) else 0


def choose_folder(prompt, default_location=None):
    """Open a macOS folder chooser dialog and return the selected path."""
    if default_location:
        script = f'POSIX path of (choose folder with prompt "{prompt}" default location POSIX file "{default_location}")'
    else:
        script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print(f"{_ERROR}No folder selected. Exiting.")
        sys.exit(1)


def guess_dest(source_path):
    """Given a source on a mounted volume, look for a matching path on other volumes."""
    volumes_root = "/Volumes"
    abs_source = os.path.abspath(source_path)

    # Only works if source is under /Volumes
    if not abs_source.startswith(volumes_root + "/"):
        return None

    # Extract the volume name and the relative path within it
    parts = abs_source[len(volumes_root) + 1:].split("/", 1)
    if len(parts) < 2:
        return None
    source_volume = parts[0]
    rel_path = parts[1]  # e.g. "Music/Artist/Album"

    # Build candidate sub-paths from most specific to least: Album, Artist/Album, Music/Artist/Album
    segments = rel_path.split("/")
    candidates = []
    for depth in range(len(segments), 0, -1):
        candidates.append(os.path.join(*segments[-depth:]))

    # Check other mounted volumes
    try:
        volumes = [v for v in os.listdir(volumes_root)
                   if v != source_volume and os.path.isdir(os.path.join(volumes_root, v))]
    except OSError:
        return None

    print(f"{_DIM}  Looking for destination match on {len(volumes)} other volume(s): {', '.join(volumes)}{_RST}")

    # Try most specific match first (full relative path), then progressively shorter
    for candidate in candidates:
        for vol in volumes:
            test = os.path.join(volumes_root, vol, candidate)
            print(f"{_DIM}    Checking exact path: {test}{_RST}", end="")
            if os.path.isdir(test):
                print(f"  {_GREEN}found{_RST}")
                return test
            print()

    # No match found — try scanning a few levels deep on other volumes
    target = segments[-1].lower()
    print(f"{_DIM}  No exact match. Scanning volumes for \"{segments[-1]}\" (up to 3 levels deep)...{_RST}")
    for vol in volumes:
        vol_root = os.path.join(volumes_root, vol)
        print(f"{_DIM}    Scanning {vol_root}/{_RST}")
        for root, dirs, _ in os.walk(vol_root):
            depth = root[len(vol_root):].count("/")
            if depth >= 3:
                dirs.clear()
                continue
            for d in dirs:
                if d.lower() == target:
                    match = os.path.join(root, d)
                    print(f"{_DIM}      {_GREEN}found{_RST}{_DIM}: {match}{_RST}")
                    return match

    print(f"{_DIM}  No matching destination found.{_RST}")
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Compare files between source and destination directories."
    )
    parser.add_argument("source", nargs="?", default=None, help="Source directory")
    parser.add_argument("dest", nargs="?", default=None, help="Destination directory")
    parser.add_argument(
        "--type-check",
        type=str.upper,
        choices=["HASH", "DATESIZE"],
        default="DATESIZE",
        help="Comparison method: HASH (SHA-256) or DATESIZE (date + file size)",
    )
    args = parser.parse_args()

    source = args.source or choose_folder("Select SOURCE directory")

    default_dest = None
    if not args.dest:
        default_dest = guess_dest(source)
        if default_dest:
            print(f"{_DIM}  Guessed destination: {default_dest}{_RST}")

    dest = args.dest or choose_folder("Select DESTINATION directory", default_dest)

    sys.exit(compare(source, dest, args.type_check))


if __name__ == "__main__":
    main()
