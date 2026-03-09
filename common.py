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

    # Build candidate sub-paths from most specific to least
    segments = rel_path.split("/")
    candidates = []
    for depth in range(len(segments), 0, -1):
        candidates.append(os.path.join(*segments[-depth:]))

    # Skip markers for volumes that aren't useful targets
    _SKIP_MARKERS = (".com.apple.timemachine.donotpresent", ".Spotlight-V100")

    # Check other mounted volumes, filtering out system/TM volumes
    try:
        all_volumes = [v for v in os.listdir(volumes_root)
                       if v != source_volume and os.path.isdir(os.path.join(volumes_root, v))]
    except OSError:
        return None

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
                print(f"  {GREEN}found{RST}")
                return test
            print()

    # No match found — scan a few levels deep using scandir for speed
    target = segments[-1].lower()
    print(f"{DIM}  No exact match. Scanning volumes for \"{segments[-1]}\" (up to 3 levels deep)...{RST}")

    def _scan_dirs(path, max_depth, depth=0):
        """Recursively scan directories using scandir, yielding (name, full_path)."""
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        yield entry.name, entry.path
                        if depth < max_depth - 1:
                            yield from _scan_dirs(entry.path, max_depth, depth + 1)
        except PermissionError:
            pass

    for vol in volumes:
        vol_root = os.path.join(volumes_root, vol)
        print(f"{DIM}    Scanning {vol_root}/{RST}")
        for name, full_path in _scan_dirs(vol_root, 3):
            if name.lower() == target:
                print(f"{DIM}      {GREEN}found{RST}{DIM}: {full_path}{RST}")
                return full_path

    print(f"{DIM}  No matching destination found.{RST}")
    return None


def prompt_dirs(source=None, dest=None, source_prompt="Select SOURCE directory", dest_prompt="Select DESTINATION directory"):
    """Prompt for source and/or dest via macOS folder chooser if not provided. Returns (source, dest)."""
    source = source or choose_folder(source_prompt)

    default_dest = None
    if not dest:
        default_dest = guess_dest(source)
        if default_dest:
            print(f"{DIM}  Guessed destination: {default_dest}{RST}")

    dest = dest or choose_folder(dest_prompt, default_dest)
    return source, dest
