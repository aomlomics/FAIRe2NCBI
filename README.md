<div align="center">
  <img src="banner_faire2ncbi.png" alt="FAIRe2NCBI Banner" width="800">
</div>

# FAIRe2NCBI

Convert FAIRe metadata sheets (NOAA format) to NCBI BioSample and SRA submission templates with automated configuration management.

## Overview

FAIRe2NCBI is a comprehensive toolkit for converting FAIRe (FAIR evironmental) metadata to NCBI submission formats. It provides two main conversion modes:

- **BioSamples Mode**: Convert FAIRe sample metadata to NCBI BioSample format
- **SRA Mode**: Convert FAIRe experimental run metadata to NCBI SRA submission format

## Features

### BioSamples Mode Features
- Hardcoded field mapping for deterministic results
- Bioproject accession handling (single value or expedition-based grouping)
- Mandatory field validation and filling
- Numerical column unit detection and assignment
- Duplicate row detection and resolution
- Sample title generation from metadata fields
- Additional column selection from FAIRe metadata

### SRA Mode Features
- Assay selection (all or specific assays)
- Library field configuration (strategy, source, selection)
- Platform value determination (assay-specific vs project-level)
- Instrument model configuration
- Automatic filetype detection from filename extensions
- Library title generation with metadata integration
- Library layout determination (single/paired) from filename presence

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

# BioSamples mode help
python scripts/FAIRe2NCBI.py BioSamples -h

# SRA mode help  
python scripts/FAIRe2NCBI.py SRA -h
```

## Usage

### BioSamples Mode

Convert FAIRe sample metadata to NCBI BioSample format.

```bash
python scripts/FAIRe2NCBI.py BioSamples \
  --FAIReMetadata your_FAIRe_Metadata.xlsx \
  --BioSampleTemplate docs/NCBI_BioSample_Metadata_Template.tsv \
  --BioSampleMetadata your_output_biosample.tsv \
  [--bioproject_accession PRJNA123456] \
  [--config_file config.yaml] \
  [--force]
```

### SRA Mode

Convert FAIRe experimental run metadata to NCBI SRA submission format.

```bash
python scripts/FAIRe2NCBI.py SRA \
  --FAIReMetadata your_FAIRe_Metadata.xlsx \
  --SRA_Template docs/NCBI_SRA_Metadata_Template.xlsx \
  --SRA_Metadata your_output_sra.xlsx \
  [--config_file config.yaml] \
  [--force]
```

### Arguments

#### Required Arguments
- `--FAIReMetadata`: Path to FAIRe metadata Excel file (.xlsx)
- `--BioSampleTemplate`: Path to MIMARKS template file (.tsv) **[BioSamples mode only]**
- `--BioSampleMetadata`: Output TSV file for BioSample metadata **[BioSamples mode only]**
- `--SRA_Template`: Path to SRA template file (.xlsx) **[SRA mode only]**
- `--SRA_Metadata`: Output Excel file for SRA metadata **[SRA mode only]**

#### Optional Arguments
- `--bioproject_accession`: Bioproject accession to use for all samples **[BioSamples mode only]**
- `--config_file`: Path to YAML configuration file for automated responses
- `--force`: Overwrite output files without prompting

## Configuration System

### Template-Based Workflow

1. **Use Template**: Start with a configuration template to set default answers
2. **Generate Config**: Script creates a new config file based on your output filename
3. **Reuse Config**: Use the generated config file for consistent, automated processing

### Configuration Templates

- **BioSample**: `docs/BioSample_Metadata_Config_Template.yaml`
- **SRA**: `docs/SRA_Metadata_Config_Template.yaml`

- ✅ **Templates are never modified** - they remain clean for reuse
- ✅ **New config files are created** based on your output filename
- ✅ **Generated configs are fully reusable** for automated workflows


## License


## Contributing

This project is developed and maintained by NOAA Omics Group, including Clement Coclet, Luke Thompson, and Katherine Silliman. For questions or contributions, please open an issue.

## Citation

When using FAIRe2NCBI in your research, please cite this repository.
