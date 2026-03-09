"""Shared utilities for sync scripts: ANSI colors, folder chooser, and volume guessing."""

import os
import subprocess
import sys

# ANSI colors
RST = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"

ERROR = f"{RED}  {'ERROR':<9}{RST}"
MISSING = f"{YELLOW}  {'MISSING':<9}{RST}"
EXTRA = f"{YELLOW}  {'EXTRA':<9}{RST}"


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
        print(f"{ERROR}No folder selected. Exiting.")
        sys.exit(1)


def guess_dest(source_path):
    """Look for a matching path on mounted volumes (dest is always a different volume)."""
    volumes_root = "/Volumes"
    abs_source = os.path.abspath(source_path)

    # Real path of source for dedup — never return the source itself
    source_real = os.path.realpath(abs_source)

    # Extract the relative path to search for on other volumes
    if abs_source.startswith(volumes_root + "/"):
        # Source is on a mounted volume — strip volume name
        parts = abs_source[len(volumes_root) + 1:].split("/", 1)
        if len(parts) < 2:
            return None
        source_volume = parts[0]
        rel_path = parts[1]  # e.g. "Music/Artist/Album"
    else:
        # Source is on the boot drive
        source_volume = None
        rel_path = abs_source.lstrip("/")  # e.g. "Users/foo/Music/Artist/Album"

    # Build candidate sub-paths from most specific to least
    segments = rel_path.split("/")
    candidates = []
    for depth in range(len(segments), 0, -1):
        candidates.append(os.path.join(*segments[-depth:]))

    def _is_source(path):
        """Check if a candidate resolves to the same location as the source."""
        try:
            return os.path.realpath(path) == source_real
        except OSError:
            return False

    # Skip markers for volumes that aren't useful targets
    _SKIP_MARKERS = (".com.apple.timemachine.donotpresent", ".Spotlight-V100")

    # Exclude any volume on the same device as the source
    source_dev = os.stat(abs_source).st_dev

    try:
        all_entries = [v for v in os.listdir(volumes_root)
                       if os.path.isdir(os.path.join(volumes_root, v))]
    except OSError:
        return None

    same_device = []
    all_volumes = []
    for v in all_entries:
        vol_path = os.path.join(volumes_root, v)
        try:
            if v == source_volume or os.stat(vol_path).st_dev == source_dev:
                same_device.append(v)
            else:
                all_volumes.append(v)
        except OSError:
            pass

    if same_device:
        print(f"{DIM}  Same device as source: {', '.join(same_device)}{RST}")

    volumes = []
    skipped = []
    for v in all_volumes:
        vol_path = os.path.join(volumes_root, v)
        if any(os.path.exists(os.path.join(vol_path, m)) for m in _SKIP_MARKERS):
            skipped.append(v)
        else:
            volumes.append(v)

    if skipped:
        print(f"{DIM}  Skipping volume(s): {', '.join(skipped)}{RST}")
    if not volumes:
        print(f"{DIM}  No candidate volumes found.{RST}")
        return None

    print(f"{DIM}  Looking for destination match on {len(volumes)} volume(s): {', '.join(volumes)}{RST}")

    # Try most specific match first (full relative path), then progressively shorter
    for candidate in candidates:
        for vol in volumes:
            test = os.path.join(volumes_root, vol, candidate)
            print(f"{DIM}    Checking exact path: {test}{RST}", end="")
            if os.path.isdir(test):
                if _is_source(test):
                    print(f"  {YELLOW}skipped (source){RST}")
                else:
                    print(f"  {GREEN}found{RST}")
                    return test
            else:
                print()

    # No match found — scan a few levels deep using scandir for speed
    target = segments[-1].lower()
    print(f"{DIM}  No exact match. Scanning volumes for \"{segments[-1]}\" (up to 4 levels deep)...{RST}")

    def _scan_dirs(path, max_depth, depth=0):
        """Recursively scan directories using scandir, yielding (name, full_path)."""
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        yield entry.name, entry.path
                        if depth < max_depth - 1:
                            yield from _scan_dirs(entry.path, max_depth, depth + 1)
        except (PermissionError, NotADirectoryError, OSError):
            pass

    for vol in volumes:
        vol_root = os.path.join(volumes_root, vol)
        print(f"{DIM}    Scanning {vol_root}/{RST}")
        for name, full_path in _scan_dirs(vol_root, 4):
            if name.lower() == target:
                if _is_source(full_path):
                    print(f"{DIM}      {YELLOW}skipped (source){RST}{DIM}: {full_path}{RST}")
                else:
                    print(f"{DIM}      {GREEN}found{RST}{DIM}: {full_path}{RST}")
                    return full_path

    print(f"{DIM}  No matching destination found.{RST}")
    return None


def check_dirs(*dirs):
    """Validate that all paths are directories. Prints an error and returns False if any are not."""
    for d in dirs:
        if not os.path.isdir(d):
            print(f"{ERROR}not a directory: {d}")
            return False
    return True


def warn_extra(src_files, dest_dir, collect_fn):
    """Warn about files in dest that don't exist in source. Returns the sorted list of extras."""
    dest_files = set(collect_fn(dest_dir))
    src_set = set(src_files) if not isinstance(src_files, set) else src_files
    extra = sorted(dest_files - src_set)
    if extra:
        print(f"\n{YELLOW}{BOLD}WARNING:{RST} {len(extra)} files in dest not in source:")
        for rel in extra:
            print(f"{EXTRA}{rel}")
    return extra


def prompt_dirs(source=None, dest=None, source_prompt="Select SOURCE directory", dest_prompt="Select DESTINATION directory"):
    """Prompt for source and/or dest via macOS folder chooser if not provided. Returns (source, dest)."""
    source = source or choose_folder(source_prompt)
    print(f"{DIM}  Source: {source}{RST}")

    default_dest = None
    if not dest:
        default_dest = guess_dest(source)
        if default_dest:
            print(f"{DIM}  Guessed destination: {default_dest}{RST}")

    dest = dest or choose_folder(dest_prompt, default_dest)
    return source, dest
