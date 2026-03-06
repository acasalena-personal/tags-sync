#!/usr/bin/env python3

"""
sync_finder_tags.py
Synchronizes macOS Finder tags between two folders based on matching filenames
Usage: python3 sync_finder_tags.py /path/to/source/folder /path/to/destination/folder
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


class TagSyncer:
    """Class to handle Finder tag synchronization between folders"""
    
    def __init__(self, test_mode: bool = False, recursive: bool = False, no_remove: bool = False):
        self.processed = 0
        self.updated = 0
        self.errors = 0
        self.test_mode = test_mode
        self.recursive = recursive
        self.no_remove = no_remove
    
    def log(self, level: str, message: str) -> None:
        """Log messages with color coding and timestamps"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        color_map = {
            'INFO': Colors.BLUE,
            'SUCCESS': Colors.GREEN,
            'WARNING': Colors.YELLOW,
            'ERROR': Colors.RED
        }
        
        color = color_map.get(level, Colors.NC)
        print(f"{color}[{level}]{Colors.NC} {message}")
    
    def check_tag_command(self) -> bool:
        """Check if the 'tag' command is available"""
        try:
            subprocess.run(['tag', '--help'], 
                         capture_output=True, 
                         check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.log('ERROR', "'tag' command not found.")
            self.log('ERROR', "Please install it using: brew install tag")
            return False
    
    def normalize_tags(self, tags: str) -> str:
        """Normalize tag order and format for consistent comparison"""
        if not tags:
            return ""
        
        # Split tags, strip whitespace, and filter out empty tags
        tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
        
        # Define priority order for color tags
        priority_tags = ['Yellow', 'Green', 'Blue', 'Purple']
        
        # Separate priority tags from other tags
        priority_found = []
        other_tags = []
        
        for tag in tag_list:
            if tag in priority_tags:
                priority_found.append(tag)
            else:
                other_tags.append(tag)
        
        # Sort priority tags in the specified order
        priority_sorted = []
        for priority_tag in priority_tags:
            if priority_tag in priority_found:
                priority_sorted.append(priority_tag)
        
        # Sort other tags alphabetically
        other_tags.sort()
        
        # Combine: priority tags first, then other tags
        final_order = priority_sorted + other_tags
        
        return ','.join(final_order)
    
    def get_file_tags(self, file_path: Path) -> Optional[str]:
        """Get tags for a file using the 'tag' command"""
        try:
            result = subprocess.run(['tag', '-l', str(file_path)], 
                                  capture_output=True, 
                                  text=True, 
                                  check=True)
            output = result.stdout.strip()
            
            # tag -l output format is: filename\ttags
            # If there are no tags, only the filename is returned
            if '\t' in output:
                # Split on tab and return the tags part (second part)
                tags = output.split('\t', 1)[1]
                return self.normalize_tags(tags.strip())
            else:
                # No tab means no tags
                return ""
        except subprocess.CalledProcessError:
            return None
    
    def set_file_tags(self, file_path: Path, tags: str) -> bool:
        """Set tags for a file using the 'tag' command"""
        if self.test_mode:
            self.log('INFO', f"[TEST MODE] Would set tags '{tags}' on: {file_path.name}")
            return True
        
        # Normalize tags before setting to ensure consistent ordering
        normalized_tags = self.normalize_tags(tags)
        if not normalized_tags:
            return self.remove_all_tags(file_path)
            
        try:
            subprocess.run(['tag', '-s', normalized_tags, str(file_path)], 
                          capture_output=True, 
                          check=True)
            return True
        except subprocess.CalledProcessError:
            return False
    
    def remove_all_tags(self, file_path: Path) -> bool:
        """Remove all tags from a file using the 'tag' command"""
        if self.test_mode:
            # Get current tags to show what would be removed
            current_tags = self.get_file_tags(file_path)
            if current_tags:
                self.log('INFO', f"[TEST MODE] Would remove all tags from: {file_path.name} (currently: {current_tags})")
            else:
                self.log('INFO', f"[TEST MODE] Would remove all tags from: {file_path.name} (currently: no tags)")
            return True
            
        try:
            subprocess.run(['tag', '-r', '*', str(file_path)], 
                          capture_output=True, 
                          check=True)
            return True
        except subprocess.CalledProcessError:
            return False
    
    def sync_file_tags(self, source_file: Path, dest_file: Path, display_name: str = None) -> tuple[bool, bool]:
        """Sync tags between source and destination files
        
        Returns:
            tuple[bool, bool]: (success, changed)
            - success: True if operation completed without error
            - changed: True if tags were actually modified
        """
        filename = display_name or source_file.name
        
        # Get tags from source file
        source_tags = self.get_file_tags(source_file)
        if source_tags is None:
            source_tags = ""  # Treat None as empty string
        
        # Get current tags from destination file
        current_tags = self.get_file_tags(dest_file)
        if current_tags is None:
            current_tags = ""  # Treat None as empty string
        
        # Compare tags
        if source_tags == current_tags:
            # Don't log files that don't need changes (clean behavior by default)
            return True, False  # Success but no change needed
        
        # Update destination file tags to match source
        if source_tags:
            # Source has tags, set them on destination
            if self.set_file_tags(dest_file, source_tags):
                if not self.test_mode:
                    self.log('SUCCESS', f"Updated tags for: {filename}")
                    self.log('INFO', f"  Tags: {source_tags}")
                return True, True  # Success and changed
            else:
                self.log('ERROR', f"Failed to set tags for: {filename}")
                return False, False  # Failed
        else:
            # Source has no tags
            if self.no_remove:
                # Don't remove tags when no-remove flag is set
                return True, False  # No change needed
            else:
                # Remove all tags from destination
                if self.remove_all_tags(dest_file):
                    if not self.test_mode:
                        self.log('SUCCESS', f"Removed all tags from: {filename}")
                    return True, True  # Success and changed
                else:
                    self.log('ERROR', f"Failed to remove tags from: {filename}")
                    return False, False  # Failed
    
    def validate_folder(self, folder_path: str, folder_type: str) -> Optional[Path]:
        """Validate that a folder exists and is accessible"""
        path = Path(folder_path).resolve()
        
        if not path.exists():
            self.log('ERROR', f"{folder_type} folder does not exist: {folder_path}")
            return None
        
        if not path.is_dir():
            self.log('ERROR', f"{folder_type} path is not a directory: {folder_path}")
            return None
        
        return path
    
    def get_files_in_folder(self, folder_path: Path, relative_path: str = "") -> List[tuple[Path, Path, str]]:
        """Get all files in a folder, optionally recursive
        
        Returns:
            List of tuples: (source_file_path, dest_file_path, relative_path)
        """
        files = []
        
        try:
            for item in folder_path.iterdir():
                current_relative = relative_path
                
                if item.is_file():
                    # For files, add them to the list
                    files.append((item, None, current_relative))  # dest_file_path will be calculated later
                    
                elif item.is_dir() and self.recursive:
                    # For directories, recurse if recursive mode is enabled
                    subdir_relative = os.path.join(current_relative, item.name) if current_relative else item.name
                    files.extend(self.get_files_in_folder(item, subdir_relative))
                    
        except PermissionError:
            self.log('ERROR', f"Permission denied accessing folder: {folder_path}")
            
        return files
    
    def sync_folders(self, source_folder: str, dest_folder: str) -> bool:
        """Main function to synchronize tags between folders"""
        
        # Check if tag command exists
        if not self.check_tag_command():
            return False
        
        if self.test_mode:
            mode_suffix = ""
            self.log('WARNING', f"RUNNING IN TEST MODE - NO CHANGES WILL BE MADE")
            print()
        
        # Validate folders
        source_path = self.validate_folder(source_folder, "Source")
        if not source_path:
            return False
        
        dest_path = self.validate_folder(dest_folder, "Destination")
        if not dest_path:
            return False
        
        self.log('INFO', "Starting tag synchronization...")
        self.log('INFO', f"Source folder: {source_path}")
        self.log('INFO', f"Destination folder: {dest_path}")
        print()
        
        # Get all files in source folder
        source_files = self.get_files_in_folder(source_path)
        
        if not source_files:
            self.log('WARNING', "No files found in source folder")
            return True
        
        mode_info = []
        if self.recursive:
            mode_info.append("recursive")
        if self.no_remove:
            mode_info.append("no-remove")
        if self.test_mode:
            mode_info.append("test mode")
            
        mode_text = f" ({', '.join(mode_info)})" if mode_info else ""
        self.log('INFO', f"Processing {len(source_files)} files{mode_text}...")
        print()
        
        # Process each file
        for source_file, _, relative_path in source_files:
            # Calculate destination file path
            if relative_path:
                dest_file = dest_path / relative_path / source_file.name
                display_name = f"{relative_path}/{source_file.name}"
            else:
                dest_file = dest_path / source_file.name
                display_name = source_file.name
            
            self.processed += 1
            
            # Check if destination directory exists for subdirectories
            if relative_path:
                dest_dir = dest_path / relative_path
                if not dest_dir.exists():
                    # Don't log missing directories (clean behavior by default)
                    continue
                if not dest_dir.is_dir():
                    # Don't log non-directory paths (clean behavior by default)
                    continue
            
            # Check if corresponding file exists in destination
            if not dest_file.exists():
                # Don't log missing files (clean behavior by default)
                continue
            
            if not dest_file.is_file():
                # Don't log non-file paths (clean behavior by default)
                continue
            
            # Sync tags
            success, changed = self.sync_file_tags(source_file, dest_file, display_name)
            if success:
                if changed:
                    self.updated += 1
            else:
                self.errors += 1
        
        # Print summary
        print()
        mode_text = " (TEST MODE)" if self.test_mode else ""
        self.log('INFO', f"Synchronization complete!{mode_text}")
        self.log('INFO', f"Files processed: {self.processed}")
        if self.test_mode:
            self.log('INFO', f"Files that would be updated: {self.updated}")
        else:
            self.log('INFO', f"Files updated: {self.updated}")
        
        if self.errors > 0:
            self.log('ERROR', f"Errors encountered: {self.errors}")
            return False
        else:
            if self.test_mode:
                self.log('SUCCESS', "Test completed successfully - no actual changes made")
            else:
                self.log('SUCCESS', "No errors encountered")
            return True


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Synchronizes macOS Finder tags between two folders based on matching filenames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Requirements:
  - 'tag' command must be installed (brew install tag)
  - Both source and destination folders must exist
  - Files are matched by exact filename (case-sensitive)

Examples:
  python3 sync_finder_tags.py ~/Documents/Source ~/Documents/Destination
  python3 sync_finder_tags.py /path/to/source /path/to/dest
        """
    )
    
    parser.add_argument('source_folder', 
                       help='Folder containing files with correct tags')
    parser.add_argument('destination_folder', 
                       help='Folder where tags will be updated')
    parser.add_argument('--test', 
                       action='store_true',
                       help='Run in test mode - show what would be done without making changes')
    parser.add_argument('--recursive', '-r',
                       action='store_true',
                       help='Process subdirectories recursively')
    parser.add_argument('--no-remove',
                       action='store_true',
                       help='Prevent removing all tags when source file has no tags')
    
    args = parser.parse_args()
    
    # Create syncer instance and run
    syncer = TagSyncer(test_mode=args.test, recursive=args.recursive, no_remove=args.no_remove)
    success = syncer.sync_folders(args.source_folder, args.destination_folder)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()