#!/usr/bin/env python3
"""Compare files between a source and destination directory by hash or modification date."""

import argparse
from datetime import datetime
import hashlib
import os
import shutil
import sys

from common import *

# Status prefixes with icons
_SKIP = f"{DIM}  {'--':<9}{RST}"
_DIFF = f"{RED}  {'DIFF':<9}{RST}"
_MATCH = f"{GREEN}  {'MATCH':<9}{RST}"
_MISSING = MISSING
_EXTRA = EXTRA
_RENAME = f"{CYAN}  {'RENAME':<9}{RST}"
_COPY = f"{GREEN}  {'COPY':<9}{RST}"
_COPY_ERR = f"{RED}  {'COPY ERR':<9}{RST}"
_ERROR = ERROR


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


def copy_file_with_progress(src, dst, rel):
    """Copy a single file from src to dst with a console progress bar."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    size = os.path.getsize(src)
    copied = 0
    chunk = 1024 * 1024  # 1 MB
    bar_width = 30
    total_str = fmt_size(size)

    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            buf = fsrc.read(chunk)
            if not buf:
                break
            fdst.write(buf)
            copied += len(buf)
            if size > 0:
                pct = copied / size
                filled = int(bar_width * pct)
                bar = f"[{'#' * filled}{'.' * (bar_width - filled)}]"
                print(f"\r{_COPY}{rel}  {bar} {pct:5.1%} of {total_str}", end="", flush=True)

    # Explicitly set timestamps to match source
    st = os.stat(src)
    os.utime(dst, (st.st_atime, st.st_mtime))

    print(f"\r{_COPY}{rel}  {'[' + '#' * bar_width + ']'} 100.0% of {total_str}")


def copy_missing_files(missing_files, source_dir, dest_dir):
    """Prompt user and copy missing files from source to dest with progress. Returns (copied, errors)."""
    if not missing_files:
        return 0, 0

    print(f"\n{YELLOW}{BOLD}{len(missing_files)} file(s) missing from destination.{RST}")
    answer = input("Copy missing files from source to destination? [y/N] ").strip().lower()
    if answer != "y":
        print(f"{DIM}  Skipping copy.{RST}")
        return 0, 0

    print()
    copied = 0
    errs = 0
    for rel in missing_files:
        src_path = os.path.join(source_dir, rel)
        dst_path = os.path.join(dest_dir, rel)
        try:
            copy_file_with_progress(src_path, dst_path, rel)
            copied += 1
        except Exception as e:
            print(f"\r{_COPY_ERR}{rel}  {e}")
            errs += 1

    print(f"\n{BOLD}{copied + errs} file(s):{RST} {GREEN}{copied} copied{RST}, {RED}{errs} errors{RST}")
    return copied, errs


def compare(source_dir, dest_dir, type_check):
    """Compare files between source and dest. Returns exit code."""
    source_dir = os.path.abspath(source_dir)
    dest_dir = os.path.abspath(dest_dir)

    if not check_dirs(source_dir, dest_dir):
        return 1

    src_files = collect_files(source_dir)
    matched = 0
    differed = 0
    missing = 0
    missing_files = []
    errors = 0

    for rel in src_files:
        src_path = os.path.join(source_dir, rel)
        dst_path = os.path.join(dest_dir, rel)

        if not os.path.exists(dst_path):
            print(f"{_MISSING}{rel}")
            missing += 1
            missing_files.append(rel)
            continue

        # Dest smaller than src → treat as incomplete/truncated, flag for replacement
        src_sz = os.path.getsize(src_path)
        dst_sz = os.path.getsize(dst_path)
        if dst_sz < src_sz:
            print(f"{_MISSING}{rel}  {DIM}(dest smaller: {fmt_size(dst_sz)} < {fmt_size(src_sz)}){RST}")
            missing += 1
            missing_files.append(rel)
            continue

        try:
            if type_check == "HASH":
                src_val = file_hash(src_path)
                dst_val = file_hash(dst_path)
                if src_val == dst_val:
                    print(f"{_MATCH}{rel}  {DIM}{src_val[:12]}...{RST}")
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
                    print(f"{_MATCH}{rel}  {DIM}{src_dt} - {fmt_size(src_sz)}{RST}")
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
        f"\n{BOLD}{total} files:{RST} {GREEN}{matched} matched{RST}, {RED}{differed} different{RST}, {YELLOW}{missing} missing{RST}, {RED}{errors} errors{RST}"
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
        print(f"\n{CYAN}{BOLD}RENAMES:{RST} {len(renames)} probable renames detected:")
        for src_rel, dst_rel, fp in renames:
            if type_check == "HASH":
                reason = f"same hash {fp[:12]}..."
            else:
                reason = f"same date {fmt_date(fp[0])} & size {fmt_size(fp[1])}"
            print(f"{_RENAME}{src_rel}  ->  {dst_rel}  {DIM}({reason}){RST}")

    remaining_src = sorted(r for r in src_only if r not in matched_src)
    remaining_dst = sorted(r for r in extra if r not in matched_dst)

    if remaining_dst:
        print(
            f"\n{YELLOW}{BOLD}WARNING:{RST} {len(remaining_dst)} files in dest not in source:"
        )
        for rel in remaining_dst:
            print(f"{_EXTRA}{rel}")

    # Offer to copy missing files (excluding probable renames) from source to dest
    copy_candidates = [r for r in missing_files if r not in matched_src]
    _copied, copy_errors = copy_missing_files(copy_candidates, source_dir, dest_dir)
    if copy_errors:
        errors += copy_errors

    return 1 if (errors or differed) else 0


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

    source, dest = prompt_dirs(args.source, args.dest)

    sys.exit(compare(source, dest, args.type_check))


if __name__ == "__main__":
    main()
