#!/usr/bin/env python3
"""
File Tag Manager Script

This script processes all files in a directory, removing and re-adding
their existing tags using the 'tag' command.

Usage:
    python tag_manager.py [directory] [--test]
    
Arguments:
    directory: Path to directory to process (default: current directory)
    --test: Run in test mode - show commands without executing them
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from typing import List

# ANSI color codes for prettier output
COLORS = {
    'green': '\033[92m',
    'yellow': '\033[93m',
    'red': '\033[91m',
    'blue': '\033[94m',
    'reset': '\033[0m',
    'bold': '\033[1m'
}

def colorize(text: str, color: str) -> str:
    """Add color to terminal output if supported."""
    if sys.stdout.isatty():  # Only colorize if running in a terminal
        return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"
    return text

def get_file_tags(filepath):
    """Get existing tags for a file using the tag command.
    
    Args:
        filepath (Path or str): Path to the file to get tags from.
        
    Returns:
        list: A list of strings containing the file's tags. Empty list if no tags
            or if an error occurs.
            
    Raises:
        SystemExit: If the tag command is not found on the system.
    """
    try:
        result = subprocess.run(
            ['tag', '-l', str(filepath)], 
            capture_output=True, 
            text=True, 
            check=True
        )
        # Parse the output: format is "filename\ttag1,tag2,tag3"
        output = result.stdout.strip()
        if not output:
            return []
        
        # Split by tab - tags come after the filename
        parts = output.split('\t', 1)
        if len(parts) < 2:
            return []
        
        # Split tags by comma and clean whitespace
        tags_str = parts[1].strip()
        if not tags_str:
            return []
        
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        return tags
    except subprocess.CalledProcessError as e:
        print(f"Error getting tags for {filepath}: {e}")
        return []
    except FileNotFoundError:
        print("Error: 'tag' command not found. Please install tag command-line tool.")
        sys.exit(1)


def remove_tags(filepath, tags, test_mode=False):
    """Remove specific tags from a file.
    
    Args:
        filepath (Path or str): Path to the file to remove tags from.
        tags (list): List of tag strings to remove.
        test_mode (bool, optional): If True, only print commands without executing.
            Defaults to False.
            
    Returns:
        bool: True if tags were removed successfully or if no tags to remove,
            False if an error occurred.
    """
    if not tags:
        return True
    
    # Join tags with commas for the tag command
    tags_str = ','.join(tags)
    cmd = ['tag', '-r', tags_str, str(filepath)]
    
    if test_mode:
        print(f"Would run: {' '.join(repr(arg) if ' ' in arg else arg for arg in cmd)}")
        return True
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error removing tags from {filepath}: {e}")
        return False


def add_tags(filepath, tags, test_mode=False):
    """Add tags to a file in a specific order.
    
    Color tags (Yellow, Green, Blue, Purple) are prioritized and added first,
    followed by other tags in alphabetical order.
    
    Args:
        filepath (Path or str): Path to the file to add tags to.
        tags (list): List of tag strings to add.
        test_mode (bool, optional): If True, only print commands without executing.
            Defaults to False.
            
    Returns:
        bool: True if tags were added successfully or if no tags to add,
            False if an error occurred.
    """
    if not tags:
        return True
        
    # Ensure no extra spaces and join tags with commas
    clean_tags = [tag.strip() for tag in tags if tag.strip()]
    if not clean_tags:
        return True
    
    # Sort tags with specific ordering: Yellow, Green, Blue, Purple first, then others alphabetically
    def tag_sort_key(tag):
        priority_order = {'Yellow': 0, 'Green': 1, 'Blue': 2, 'Purple': 3}
        if tag in priority_order:
            return (0, priority_order[tag])  # Priority tags come first
        else:
            return (1, tag.lower())  # Other tags sorted alphabetically
    
    sorted_tags = sorted(clean_tags, key=tag_sort_key)
    tags_str = ','.join(sorted_tags)
    cmd = ['tag', '-a', tags_str, str(filepath)]
    
    if test_mode:
        print(f"Would run: {' '.join(repr(arg) if ' ' in arg else arg for arg in cmd)}")
        return True
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error adding tags to {filepath}: {e}")
        return False


def process_file(filepath, test_mode=False):
    """Process tags for a single file by removing and re-adding them in sorted order.
    
    This function gets the existing tags, removes them, and then re-adds them
    in a standardized order (color tags first, then alphabetical).
    
    Args:
        filepath (Path or str): Path to the file to process.
        test_mode (bool, optional): If True, only print commands without executing.
            Defaults to False.
            
    Returns:
        bool: True if file was processed successfully, False if an error occurred.
    """
    # Get existing tags
    tags = get_file_tags(filepath)
    
    if not tags:
        return True
    
    # Remove tags
    if not remove_tags(filepath, tags, test_mode):
        return False
    
    # Sort tags for re-adding
    clean_tags = [tag.strip() for tag in tags if tag.strip()]
    def tag_sort_key(tag):
        priority_order = {'Yellow': 0, 'Green': 1, 'Blue': 2, 'Purple': 3}
        if tag in priority_order:
            return (0, priority_order[tag])
        else:
            return (1, tag.lower())
    
    sorted_tags = sorted(clean_tags, key=tag_sort_key)
    
    # Re-add tags using the sorted order
    if not add_tags(filepath, sorted_tags, test_mode):
        return False
    
    # Simplified output with color coding
    mode = colorize("[TEST]", "yellow") if test_mode else colorize("✓", "green")
    filename = os.path.basename(filepath)
    tags_str = ", ".join(colorize(tag, "blue") for tag in sorted_tags)
    print(f"{mode} {filename}: {tags_str}")
    
    return True


def process_directory(directory, test_mode=False, recursive=False):
    """Process all files in a directory by normalizing their tags.
    
    Args:
        directory (Path or str): Path to the directory to process.
        test_mode (bool, optional): If True, only print commands without executing.
            Defaults to False.
        recursive (bool, optional): If True, process files in subdirectories.
            Defaults to False.
            
    Returns:
        bool: True if all files were processed successfully,
            False if any errors occurred.
    """
    directory = Path(directory)
    
    if not directory.exists():
        print(colorize("Error: Directory not found: ", "red") + str(directory))
        return False
    
    if not directory.is_dir():
        print(colorize("Error: Not a directory: ", "red") + str(directory))
        return False
    
    # Get all files
    if recursive:
        files = [f for f in directory.rglob('*') if f.is_file()]
    else:
        files = [f for f in directory.iterdir() if f.is_file()]
    
    if not files:
        print(colorize("No files found.", "yellow"))
        return True
    
    # Print header
    mode_str = []
    if test_mode:
        mode_str.append(colorize("TEST MODE", "yellow"))
    if recursive:
        mode_str.append(colorize("RECURSIVE", "blue"))
    
    header = f"\nProcessing {colorize(str(directory), 'bold')}"
    if mode_str:
        header += f" ({' + '.join(mode_str)})"
    print(header)
    
    success_count = 0
    total_count = len(files)
    
    try:
        for filepath in files:
            if process_file(filepath, test_mode):
                success_count += 1
                
    except KeyboardInterrupt:
        print(colorize("\nOperation cancelled by user.", "yellow"))
    except Exception as e:
        print(colorize(f"\nUnexpected error: {e}", "red"))
    finally:
        # Print summary
        if success_count == total_count:
            status = colorize("✓", "green")
        else:
            status = colorize("!", "red")
        
        print(f"\n{status} Processed {success_count}/{total_count} files")
    
    return success_count == total_count


def main():
    """Main entry point for the script.
    
    Parses command line arguments and initiates the tag normalization process.
    Supports the following operations:
    - Processing current or specified directory
    - Test mode for previewing changes
    - Recursive processing of subdirectories
    
    The script will exit with status code 0 if successful,
    or status code 1 if any errors occurred.
    """
    parser = argparse.ArgumentParser(
        description="Remove and re-add tags to all files in a directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python tag_manager.py                    # Process current directory
    python tag_manager.py /path/to/files     # Process specific directory
    python tag_manager.py -r                 # Process current directory recursively
    python tag_manager.py /path/to/files -r  # Process specific directory recursively
    python tag_manager.py --test             # Test mode for current directory
    python tag_manager.py /path/to/files --test  # Test mode for specific directory
    python tag_manager.py -r --test          # Test recursive mode
        """
    )
    
    parser.add_argument(
        'directory', 
        nargs='?', 
        default='.', 
        help='Directory to process (default: current directory)'
    )
    
    parser.add_argument(
        '-r', '--recursive', 
        action='store_true', 
        help='Process files recursively in subdirectories'
    )
    
    parser.add_argument(
        '--test', 
        action='store_true', 
        help='Test mode: show commands without executing them'
    )
    
    args = parser.parse_args()
    
    # Check if tag command is available
    try:
        subprocess.run(['tag', '--version'], capture_output=True, check=True)
    except FileNotFoundError:
        print("Error: 'tag' command not found.")
        print("Please install the tag command-line tool.")
        print("On macOS: brew install tag")
        sys.exit(1)
    except subprocess.CalledProcessError:
        # tag command exists but --version might not be supported
        pass
    
    success = process_directory(args.directory, args.test, args.recursive)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()