#!/usr/bin/env python3
"""
FAIRe2NCBI main entry point

This script provides a unified interface for converting FAIRe metadata to NCBI submission formats.
It supports both BioSamples and SRA modes.
"""

import argparse
import os
import sys
from pathlib import Path

# Import the conversion modules
from FAIRe2BioSample import biosample_mode
from FAIRe2SRA import sra_mode


def main():
    """Main CLI entry point."""
    # Create main parser with simplified description
    parser = argparse.ArgumentParser(
        description="FAIRe2NCBI: Convert FAIRe sample metadata to NCBI submission formats.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available modes:
  BioSamples    Convert FAIRe metadata to NCBI BioSample format
  SRA           Convert FAIRe metadata to NCBI SRA format

For mode-specific help, use:
  python FAIRe2NCBI.py BioSamples -h
  python FAIRe2NCBI.py SRA -h
        """
    )
    
    # Create subparsers for different modes
    subparsers = parser.add_subparsers(dest='mode', help='Conversion modes')
    subparsers.required = True
    
    # BioSamples mode subparser
    biosample_parser = subparsers.add_parser(
        'BioSamples',
        help='Convert FAIRe metadata to NCBI BioSample format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python FAIRe2NCBI.py BioSamples --FAIReMetadata data.xlsx --BioSampleTemplate template.tsv --BioSampleMetadata output.tsv --bioproject_accession PRJNA123456
        """
    )
    
    # BioSample mode arguments
    biosample_parser.add_argument('--FAIReMetadata', type=str, required=True,
                                 help='Path to FAIRe metadata Excel file (.xlsx)')
    biosample_parser.add_argument('--BioSampleTemplate', type=str, required=True,
                                 help='Path to MIMARKS template file (.tsv)')
    biosample_parser.add_argument('--BioSampleMetadata', type=str, required=True,
                                 help='Output TSV file for BioSample metadata')
    biosample_parser.add_argument('--bioproject_accession', type=str,
                                 help='Bioproject accession to use for all samples (optional)')
    biosample_parser.add_argument('--config_file', type=str,
                                 help='Path to YAML configuration file for automated responses (optional)')
    biosample_parser.add_argument('--force', action='store_true',
                                 help='Overwrite output files without prompting (optional)')
    
    # SRA mode subparser
    sra_parser = subparsers.add_parser(
        'SRA',
        help='Convert FAIRe metadata to NCBI SRA format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python FAIRe2NCBI.py SRA --FAIReMetadata data.xlsx --SRA_Template sra_template.tsv --SRA_Metadata sra_output.tsv
        """
    )
    
    # SRA mode arguments
    sra_parser.add_argument('--FAIReMetadata', type=str, required=True,
                           help='Path to FAIRe metadata Excel file (.xlsx)')
    sra_parser.add_argument('--SRA_Template', type=str, required=True,
                           help='Path to SRA template file (.tsv)')
    sra_parser.add_argument('--SRA_Metadata', type=str, required=True,
                           help='Output TSV file for SRA metadata')
    sra_parser.add_argument('--config_file', type=str,
                           help='Path to YAML configuration file for automated responses (optional)')
    sra_parser.add_argument('--force', action='store_true',
                           help='Overwrite output files without prompting (optional)')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Route to appropriate function based on mode
    if args.mode == 'BioSamples':
        print(f"\nRunning BioSamples mode...")
        biosample_mode(args)
        
    elif args.mode == 'SRA':
        print(f"\nRunning SRA mode...")
        sra_mode(args)


if __name__ == '__main__':
    main()