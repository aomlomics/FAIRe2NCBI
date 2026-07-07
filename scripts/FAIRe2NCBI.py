#!/usr/bin/env python3
"""
FAIRe2NCBI main entry point

This script provides a unified interface for converting FAIRe metadata to NCBI submission formats.
It supports both BioSample and SRA modes.
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
  BioSample     Convert FAIRe metadata to NCBI BioSample format
  SRA           Convert FAIRe metadata to NCBI SRA format

For mode-specific help, use:
  python FAIRe2NCBI.py BioSample -h
  python FAIRe2NCBI.py SRA -h
        """
    )
    
    # Create subparsers for different modes
    subparsers = parser.add_subparsers(dest='mode', help='Conversion modes')
    subparsers.required = True
    
    # BioSample mode subparser
    biosample_parser = subparsers.add_parser(
        'BioSample',
        help='Convert FAIRe metadata to NCBI BioSample format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python FAIRe2NCBI.py BioSample --FAIReMetadata data.xlsx --BioSample_Metadata output.tsv --bioproject_accession PRJNA123456
        """
    )
    
    # BioSample mode FAIRe input arguments (either workbook or all 3 sheet files)
    biosample_parser.add_argument('--FAIReMetadata', type=str,
                                 help='Path to FAIRe metadata Excel file (.xlsx)')
    biosample_parser.add_argument('--projectMetadata', type=str,
                                 help='Path to projectMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    biosample_parser.add_argument('--sampleMetadata', type=str,
                                 help='Path to sampleMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    biosample_parser.add_argument('--experimentRunMetadata', type=str,
                                 help='Path to experimentRunMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    biosample_parser.add_argument('--BioSample_Template', type=str,
                                 help='Path to MIMARKS template file (.tsv). Defaults to bundled docs/NCBI_BioSample_Metadata_Template.tsv')
    biosample_parser.add_argument('--BioSample_Metadata', type=str, required=True,
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
Examples:
  python FAIRe2NCBI.py SRA --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv
  python FAIRe2NCBI.py SRA --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --NCBI_accession_number ncbi_accessions.tsv
  python FAIRe2NCBI.py SRA --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --filter-fastq /path/to/fastq_folder
  python FAIRe2NCBI.py SRA --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --split_by_BioProject BioSample_attributes.csv
        """
    )
    
    # SRA mode FAIRe input arguments (either workbook or all 3 sheet files)
    sra_parser.add_argument('--FAIReMetadata', type=str,
                           help='Path to FAIRe metadata Excel file (.xlsx)')
    sra_parser.add_argument('--projectMetadata', type=str,
                           help='Path to projectMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    sra_parser.add_argument('--sampleMetadata', type=str,
                           help='Path to sampleMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    sra_parser.add_argument('--experimentRunMetadata', type=str,
                           help='Path to experimentRunMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    sra_parser.add_argument('--SRA_Template', type=str,
                           help='Path to SRA template file (.xlsx). Defaults to bundled docs/NCBI_SRA_Metadata_Template.xlsx')
    sra_parser.add_argument('--SRA_Metadata', type=str, required=True,
                           help='Output file for SRA metadata (.tsv format required)')
    sra_parser.add_argument('--config_file', type=str,
                           help='Path to YAML configuration file for automated responses (optional)')
    sra_parser.add_argument('--NCBI_accession_number', type=str,
                           help='Path to table with NCBI accession numbers (biosample and/or bioproject accessions) (optional)')
    sra_parser.add_argument('--filter-fastq', type=str,
                           help='Path to fastq folder to scan for empty/corrupted files and filter SRA rows (optional)')
    sra_parser.add_argument(
        '--split_by_BioProject',
        type=str,
        nargs='?',
        const='__USE_NCBI_ACCESSION__',
        default=None,
        help=(
            'Path to table used to split SRA output by BioProject (optional). '
            'If provided without a value, --NCBI_accession_number is used.'
        )
    )
    sra_parser.add_argument('--fastq_folder', type=str,
                           help='Path to fastq folder used when split_by_BioProject creates per-group fastq directories (optional)')
    sra_parser.add_argument('--force', action='store_true',
                           help='Overwrite output files without prompting (optional)')
    
    # Parse arguments
    args = parser.parse_args()
    
    has_workbook = bool(getattr(args, 'FAIReMetadata', None))
    sheet_args = [
        getattr(args, 'projectMetadata', None),
        getattr(args, 'sampleMetadata', None),
        getattr(args, 'experimentRunMetadata', None),
    ]
    has_any_sheet = any(bool(x) for x in sheet_args)
    has_all_sheets = all(bool(x) for x in sheet_args)
    if has_workbook and has_any_sheet:
        parser.error(
            "Use either --FAIReMetadata OR all three sheet arguments "
            "(--projectMetadata, --sampleMetadata, --experimentRunMetadata), not both."
        )
    if not has_workbook and not has_any_sheet:
        parser.error(
            "Provide either --FAIReMetadata or all three sheet arguments "
            "(--projectMetadata, --sampleMetadata, --experimentRunMetadata)."
        )
    if not has_workbook and not has_all_sheets:
        parser.error(
            "When using sheet arguments, all are required: "
            "--projectMetadata, --sampleMetadata, --experimentRunMetadata."
        )
    if has_workbook and not os.path.exists(args.FAIReMetadata):
        parser.error(f"File not found: {args.FAIReMetadata}")
    if not has_workbook:
        for p in sheet_args:
            if not os.path.exists(p):
                parser.error(f"File not found: {p}")

    # Check if NCBI_accession_number file exists if provided (for SRA mode)
    if args.mode == 'SRA' and hasattr(args, 'NCBI_accession_number') and args.NCBI_accession_number:
        if not os.path.exists(args.NCBI_accession_number):
            parser.error(f"File not found: {args.NCBI_accession_number}")

    # Check filter-fastq folder exists if provided (for SRA mode)
    if args.mode == 'SRA' and hasattr(args, 'filter_fastq') and args.filter_fastq:
        if not os.path.isdir(args.filter_fastq):
            parser.error(f"Folder not found: {args.filter_fastq}")

    # Check if split_by_BioProject file exists if provided (for SRA mode)
    if args.mode == 'SRA' and hasattr(args, 'split_by_BioProject') and args.split_by_BioProject:
        if args.split_by_BioProject == '__USE_NCBI_ACCESSION__':
            if not args.NCBI_accession_number:
                parser.error(
                    "--split_by_BioProject was provided without a file path, but --NCBI_accession_number was not provided. "
                    "Provide --NCBI_accession_number or pass a file path to --split_by_BioProject."
                )
        elif not os.path.exists(args.split_by_BioProject):
            parser.error(f"File not found: {args.split_by_BioProject}")

        # split_by_BioProject requires fastq source folder from --fastq_folder or --filter-fastq
        if not getattr(args, 'fastq_folder', None) and not getattr(args, 'filter_fastq', None):
            parser.error(
                "--split_by_BioProject requires a fastq folder source. "
                "Provide --fastq_folder or --filter-fastq."
            )

    # Validate fastq_folder if provided
    if args.mode == 'SRA' and hasattr(args, 'fastq_folder') and args.fastq_folder:
        if not os.path.isdir(args.fastq_folder):
            parser.error(f"Folder not found: {args.fastq_folder}")
    
    # Route to appropriate function based on mode
    if args.mode == 'BioSample':
        print(f"\nRunning BioSample mode...")
        biosample_mode(args)
        
    elif args.mode == 'SRA':
        print(f"\nRunning SRA mode...")
        sra_mode(args)


if __name__ == '__main__':
    main()
