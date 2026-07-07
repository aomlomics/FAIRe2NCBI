#!/usr/bin/env python3
"""Find empty or corrupted FASTQ files and write a filename list."""

import os
import sys
import gzip
import argparse

def is_file_empty_or_corrupted(file_path):
    """
    Check if a file is empty or corrupted (contains only invalid characters).
    
    Args:
        file_path (str): Path to the file to check
    
    Returns:
        bool: True if file appears empty/corrupted, False otherwise
    """
    try:
        # Check file size first
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return True
        
        # For .gz files, try to read and check content
        if file_path.endswith('.gz'):
            try:
                with gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore') as f:
                    # Read first chunk
                    content = f.read(1024)  # Read first 1KB
                    if not content:
                        return True
                    # Check if content is only question marks/whitespace
                    content_stripped = content.strip()
                    if not content_stripped or all(c in '? \n\r\t' for c in content_stripped):
                        return True
            except (gzip.BadGzipFile, UnicodeDecodeError, OSError):
                # If we can't read it, it's likely corrupted
                return True
        else:
            # For regular files
            try:
                with open(file_path, 'rb') as f:
                    # Read first chunk
                    content = f.read(1024)
                    if not content:
                        return True
                    # Try to decode and check
                    try:
                        content_str = content.decode('utf-8', errors='ignore')
                        content_stripped = content_str.strip()
                        if not content_stripped or all(c in '? \n\r\t' for c in content_stripped):
                            return True
                    except:
                        # If we can't decode, check if it's all null bytes or similar
                        if all(b == 0 or b == ord('?') for b in content[:100]):
                            return True
            except (UnicodeDecodeError, OSError):
                return True
        
        return False
    except (OSError, PermissionError) as e:
        print(f"Warning: Could not check {file_path}: {e}", file=sys.stderr)
        return False

def is_fastq_name(file_name):
    lower = file_name.lower()
    return (
        lower.endswith(".fastq")
        or lower.endswith(".fq")
        or lower.endswith(".fastq.gz")
        or lower.endswith(".fq.gz")
    )


def find_empty_corrupted_files(root_dir):
    """
    Find all empty/corrupted FASTQ files in a directory tree.
    
    Args:
        root_dir (str): Root directory to search
    
    Returns:
        list: List of paths to empty/corrupted files
    """
    empty_files = []
    
    if not os.path.exists(root_dir):
        print(f"Error: Directory '{root_dir}' does not exist.", file=sys.stderr)
        return empty_files
    
    print(f"Searching for empty/corrupted FASTQ files in: {os.path.abspath(root_dir)}", file=sys.stderr)
    
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if not is_fastq_name(file):
                continue
            file_path = os.path.join(root, file)
            try:
                if is_file_empty_or_corrupted(file_path):
                    empty_files.append(file_path)
                    print(f"Found empty/corrupted FASTQ: {file_path}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Error checking {file_path}: {e}", file=sys.stderr)
    
    return empty_files

def main():
    parser = argparse.ArgumentParser(
        description="Find empty/corrupted FASTQ files and write filename list."
    )
    parser.add_argument(
        "search_dir",
        nargs="?",
        default="01_OKEX_PROJECT/RAW_READS",
        help="Folder to scan recursively for fastq/fq(.gz) files",
    )
    parser.add_argument(
        "--output",
        default="empty_corrupted_fastq_files.txt",
        help="Output .txt with one filename per line",
    )
    args = parser.parse_args()
    search_dir = args.search_dir
    
    # Find empty/corrupted files
    empty_files = find_empty_corrupted_files(search_dir)
    
    # Output file
    output_file = args.output
    
    # Write to file (just filenames, not full paths)
    if empty_files:
        print(f"\nFound {len(empty_files)} empty/corrupted FASTQ file(s).", file=sys.stderr)
        print(f"Writing list to: {output_file}", file=sys.stderr)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for file_path in empty_files:
                # Write just the filename
                filename = os.path.basename(file_path)
                f.write(f"{filename}\n")
        
        print(f"Successfully wrote {len(empty_files)} empty/corrupted FASTQ filenames to {output_file}", file=sys.stderr)
        print(f"\nFirst few empty/corrupted FASTQ files found:", file=sys.stderr)
        for file_path in empty_files[:10]:
            print(f"  {os.path.basename(file_path)}", file=sys.stderr)
        if len(empty_files) > 10:
            print(f"  ... and {len(empty_files) - 10} more", file=sys.stderr)
    else:
        print(f"\nNo empty/corrupted FASTQ files found in {search_dir}", file=sys.stderr)
        # Create empty file anyway
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# No empty/corrupted FASTQ files found\n")
        print(f"Created {output_file} (no empty/corrupted files found)", file=sys.stderr)

if __name__ == '__main__':
    main()

