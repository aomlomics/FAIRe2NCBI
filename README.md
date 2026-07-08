<div align="center">
  <img src="banner_faire2ncbi.png" alt="FAIRe2NCBI Banner" width="800">
</div>

# FAIRe2NCBI

Convert FAIRe metadata sheets (NOAA format) to NCBI BioSample and SRA submission templates with automated configuration management.

## Overview

FAIRe2NCBI is a comprehensive toolkit for converting FAIRe (FAIR evironmental) metadata to NCBI submission formats. It provides two main conversion modes:

- **BioSample Mode**: Convert FAIRe sample metadata to NCBI BioSample format
- **SRA Mode**: Convert FAIRe experimental run metadata to NCBI SRA submission format

## Features

### BioSample Mode Features
- Input as one workbook (`--FAIReMetadata`) or three sheet files (`--projectMetadata`, `--sampleMetadata`, `--experimentRunMetadata`)
- Bioproject accession handling (single value or expedition-based grouping)
- Mandatory field validation and filling
- Numerical column unit detection and assignment
- Duplicate row detection and resolution
- Sample title generation from metadata fields
- Optional experimentRunMetadata associatedSequences filtering (`all` / `blank_only`)

### SRA Mode Features
- Input as one workbook (`--FAIReMetadata`) or three sheet files (`--projectMetadata`, `--sampleMetadata`, `--experimentRunMetadata`)
- lib_id selection workflow (all or selected values from user-selected columns)
- Optional experimentRunMetadata associatedSequences filtering (`all` / `blank_only`)
- Optional fastq quality filter with `--filter-fastq` (detect empty/corrupted fastq and remove matching SRA rows)
- Optional split output by BioProject (`--split_by_BioProject`) with one SRA output file per BioProject
- Absolute fastq symlink creation in split-specific subfolders (under `--fastq_folder` or `--filter-fastq`)
- Platform/instrument/model determination from metadata with interactive fallback prompts

## Installation and Setup

1. **Clone the repository:**
```bash
git clone https://github.com/aomlomics/FAIRe2NCBI.git
cd FAIRe2NCBI
```

2. **Create a conda environment:**
```bash
conda create --name FAIRe2NCBI python=3.13
conda activate FAIRe2NCBI
```

3. **Install required packages:**
```bash
conda install pandas pyyaml openpyxl rapidfuzz
```

## Get Help
```bash
# Main help
python scripts/FAIRe2NCBI.py -h

# BioSample mode help
python scripts/FAIRe2NCBI.py BioSample -h

# SRA mode help  
python scripts/FAIRe2NCBI.py SRA -h
```

## Usage

### BioSample Mode

Convert FAIRe sample metadata to NCBI BioSample format.

```bash
# Option 1: single workbook
python scripts/FAIRe2NCBI.py BioSample \
  --FAIReMetadata your_FAIRe_Metadata.xlsx \
  --BioSample_Metadata your_output_biosample.tsv \
  [--BioSample_Template custom_template.tsv] \
  [--bioproject_accession PRJNA123456] \
  [--config_file config.yaml] \
  [--force]

# Option 2: three individual sheet files
python scripts/FAIRe2NCBI.py BioSample \
  --projectMetadata your_projectMetadata.tsv \
  --sampleMetadata your_sampleMetadata.tsv \
  --experimentRunMetadata your_experimentRunMetadata.tsv \
  --BioSample_Metadata your_output_biosample.tsv \
  [--BioSample_Template custom_template.tsv] \
  [--bioproject_accession PRJNA123456] \
  [--config_file config.yaml] \
  [--force]
```

### SRA Mode

Convert FAIRe experimental run metadata to NCBI SRA submission format.

```bash
# Option 1: single workbook
python scripts/FAIRe2NCBI.py SRA \
  --FAIReMetadata your_FAIRe_Metadata.xlsx \
  --SRA_Metadata your_output_sra.tsv \
  [--SRA_Template custom_sra_template.xlsx] \
  [--config_file config.yaml] \
  [--NCBI_accession_number biosample_or_bioproject_table.tsv] \
  [--filter-fastq /path/to/fastq_folder] \
  [--split_by_BioProject [split_table.tsv]] \
  [--fastq_folder /path/to/fastq_folder] \
  [--force]

# Option 2: three individual sheet files
python scripts/FAIRe2NCBI.py SRA \
  --projectMetadata your_projectMetadata.tsv \
  --sampleMetadata your_sampleMetadata.tsv \
  --experimentRunMetadata your_experimentRunMetadata.tsv \
  --SRA_Metadata your_output_sra.tsv \
  [--SRA_Template custom_sra_template.xlsx] \
  [--config_file config.yaml] \
  [--NCBI_accession_number biosample_or_bioproject_table.tsv] \
  [--filter-fastq /path/to/fastq_folder] \
  [--split_by_BioProject [split_table.tsv]] \
  [--fastq_folder /path/to/fastq_folder] \
  [--force]
```

### Arguments

#### Required Arguments
- `--BioSample_Metadata`: Output TSV file for BioSample metadata **[BioSample mode only]**
- `--SRA_Metadata`: Output TSV file for SRA metadata **[SRA mode only]**
- FAIRe input (both modes): use either
  - `--FAIReMetadata` (single workbook), or
  - all three sheet files: `--projectMetadata`, `--sampleMetadata`, `--experimentRunMetadata`

#### Optional Arguments
- `--BioSample_Template`: Path to MIMARKS template file (.tsv). Defaults to bundled `docs/NCBI_BioSample_Metadata_Template.tsv` **[BioSample mode only]**
- `--SRA_Template`: Path to SRA template file (.xlsx). Defaults to bundled `docs/NCBI_SRA_Metadata_Template.xlsx` **[SRA mode only]**
- `--bioproject_accession`: Bioproject accession to use for all samples **[BioSample mode only]**
- `--NCBI_accession_number`: Table with BioSample and/or BioProject accessions **[SRA mode only]**
- `--filter-fastq`: Fastq folder to scan for empty/corrupted files and remove matching SRA rows (`filename`, `filename2`, `filename3`, `filename4`) **[SRA mode only]**
- `--split_by_BioProject`: Split SRA output by BioProject using a provided table; if used as a flag without a path, `--NCBI_accession_number` is used **[SRA mode only]**
- `--fastq_folder`: Fastq root folder for split-mode symlink subfolders; required with `--split_by_BioProject` unless `--filter-fastq` is provided **[SRA mode only]**
- `--config_file`: Path to YAML configuration file for automated responses
- `--force`: Overwrite output files without prompting

### SRA split fastq behavior

When `--split_by_BioProject` is enabled:

- One SRA metadata file is written per BioProject value.
- A fastq subfolder is created for each BioProject under:
  - `--fastq_folder` if provided, else
  - `--filter-fastq`
- Subfolder names use `<split_column>_<BioProject_value>` (sanitized).
- The script creates **absolute symlinks** (not hard copies) for fastq files referenced in `filename`/`filename2`/`filename3`/`filename4`.

## Configuration System

Bundled NCBI templates are resolved from the repo `docs/` folder automatically, so you can run the script from any working directory without passing `--BioSample_Template` or `--SRA_Template`.

### Template-Based Workflow

1. **First prompt**: `Do you want to use a config file from a previous run? [y/N]:`
   - **y**: provide a path to an existing config file
   - **N** (default): load `docs/` config template as a base, answer interactively, and write a new config next to the output file (template is never modified)
2. **Generate Config**: Script creates/updates a config file based on your output filename
3. **Reuse Config**: Use the generated config file later for automated processing

Numerical fields without a paired `*_unit` column ask whether to use the **MIxS Preferred_unit** from `docs/mixs.yaml` (`[Y/n]`, Y default); otherwise you can enter a custom unit.

### Configuration Templates

- **BioSample**: `docs/BioSample_config_file_template.yaml`
- **SRA**: `docs/SRA_config_file_template.yaml`

- ✅ **Templates are never modified** - they remain clean for reuse
- ✅ **New config files are created** based on your output filename
- ✅ **Generated configs are fully reusable** for automated workflows


## License


## Contributing

This project is developed and maintained by NOAA Omics Group, including Clement Coclet, Luke Thompson, and Katherine Silliman. For questions or contributions, please open an issue.

## Citation

When using FAIRe2NCBI in your research, please cite this repository.
