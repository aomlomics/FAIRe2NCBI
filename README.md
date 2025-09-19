<div align="center">
  <img src="banner_faire2ncbi.png" alt="FAIRe2NCBI Banner" width="800">
</div>

# FAIRe2NCBI

Convert FAIRe metadata sheets (NOAA format) to NCBI BioSample and SRA submission templates with automated configuration management.

## Overview

FAIRe2NCBI is a comprehensive toolkit for converting FAIRe (FAIR evironmental) metadata to NCBI submission formats. It provides two main conversion modes:

- **BioSamples Mode**: Convert FAIRe sample metadata to NCBI BioSample MIMARKS format
- **SRA Mode**: Convert FAIRe experimental run metadata to NCBI SRA submission format

## Features

- 🔄 **Unified CLI Interface**: Single entry point with mode-specific help
- 📋 **Template-Based Configuration**: Reusable YAML configuration templates
- 🛡️ **Template Protection**: Original templates are never modified
- ⚡ **Automated Workflows**: Use config files for consistent, repeatable processing
- 🎯 **Interactive Mode**: Guided prompts for missing configuration values
- 📊 **Smart Field Mapping**: Hardcoded mapping based on fuzzy pairing results
- 🔧 **Unit Handling**: Automatic unit detection and assignment for numerical fields
- 🔍 **Duplicate Detection**: Identifies and helps resolve duplicate entries
- 📝 **Sample Title Generation**: Automatic generation of descriptive sample titles

## Installation

### Requirements

- Python 3.7+
- Required packages: `pandas`, `pyyaml`, `openpyxl`, `rapidfuzz`

### Setup

1. Clone the repository:
```bash
git clone https://github.com/aomlomics/FAIRe2NCBI.git
cd FAIRe2NCBI
```

2. Install required packages:
```bash
pip install pandas pyyaml openpyxl rapidfuzz
```

Or using conda:
```bash
conda install pandas pyyaml openpyxl rapidfuzz
```

## Usage

### Basic Command Structure

```bash
python scripts/FAIRe2NCBI.py {BioSamples|SRA} [arguments]
```

### BioSamples Mode

Convert FAIRe sample metadata to NCBI BioSample MIMARKS format.

#### Basic Usage
```bash
python scripts/FAIRe2NCBI.py BioSamples \
  --FAIReMetadata your_data.xlsx \
  --BioSampleTemplate docs/NCBI_BioSample_Metadata_Template.tsv \
  --BioSampleMetadata output_biosample.tsv
```

#### With Configuration Template
```bash
python scripts/FAIRe2NCBI.py BioSamples \
  --FAIReMetadata your_data.xlsx \
  --BioSampleTemplate docs/NCBI_BioSample_Metadata_Template.tsv \
  --BioSampleMetadata output_biosample.tsv \
  --config_file docs/BioSample_Metadata_Config_Template.yaml \
  --force
```

#### With Bioproject Accession
```bash
python scripts/FAIRe2NCBI.py BioSamples \
  --FAIReMetadata your_data.xlsx \
  --BioSampleTemplate docs/NCBI_BioSample_Metadata_Template.tsv \
  --BioSampleMetadata output_biosample.tsv \
  --bioproject_accession PRJNA123456
```

#### BioSamples Mode Arguments
- `--FAIReMetadata`: Path to FAIRe metadata Excel file (.xlsx) **[required]**
- `--BioSampleTemplate`: Path to MIMARKS template file (.tsv) **[required]**
- `--BioSampleMetadata`: Output TSV file for BioSample metadata **[required]**
- `--bioproject_accession`: Bioproject accession to use for all samples [optional]
- `--config_file`: Path to YAML configuration file for automated responses [optional]
- `--force`: Overwrite output files without prompting [optional]

### SRA Mode

Convert FAIRe experimental run metadata to NCBI SRA submission format.

#### Basic Usage
```bash
python scripts/FAIRe2NCBI.py SRA \
  --FAIReMetadata your_data.xlsx \
  --SRA_Template docs/NCBI_SRA_Metadata_Template.xlsx \
  --SRA_Metadata output_sra.xlsx
```

#### With Configuration Template
```bash
python scripts/FAIRe2NCBI.py SRA \
  --FAIReMetadata your_data.xlsx \
  --SRA_Template docs/NCBI_SRA_Metadata_Template.xlsx \
  --SRA_Metadata output_sra.xlsx \
  --config_file docs/SRA_Metadata_Config_Template.yaml \
  --force
```

#### SRA Mode Arguments
- `--FAIReMetadata`: Path to FAIRe metadata Excel file (.xlsx) **[required]**
- `--SRA_Template`: Path to SRA template file (.xlsx) **[required]**
- `--SRA_Metadata`: Output Excel file for SRA metadata **[required]**
- `--config_file`: Path to YAML configuration file for automated responses [optional]
- `--force`: Overwrite output files without prompting [optional]

## Configuration System

### Template-Based Workflow

1. **Use Template**: Start with a configuration template to set default answers
2. **Generate Config**: Script creates a new config file based on your output filename
3. **Reuse Config**: Use the generated config file for consistent, automated processing

### Configuration Templates

- **BioSample**: `docs/BioSample_Metadata_Config_Template.yaml`
- **SRA**: `docs/SRA_Metadata_Config_Template.yaml`

### Template Protection

- ✅ **Templates are never modified** - they remain clean for reuse
- ✅ **New config files are created** based on your output filename
- ✅ **Generated configs are fully reusable** for automated workflows

### Example Workflow

```bash
# Step 1: Use template (creates my_data_config.yaml)
python scripts/FAIRe2NCBI.py BioSamples \
  --config_file docs/BioSample_Metadata_Config_Template.yaml \
  --FAIReMetadata my_data.xlsx \
  --BioSampleTemplate docs/NCBI_BioSample_Metadata_Template.tsv \
  --BioSampleMetadata my_data.tsv \
  --force

# Step 2: Reuse generated config (automated)
python scripts/FAIRe2NCBI.py BioSamples \
  --config_file my_data_config.yaml \
  --FAIReMetadata my_data.xlsx \
  --BioSampleTemplate docs/NCBI_BioSample_Metadata_Template.tsv \
  --BioSampleMetadata my_data.tsv \
  --force
```

## File Structure

```
FAIRe2NCBI/
├── scripts/
│   ├── FAIRe2NCBI.py           # Main entry point
│   ├── FAIRe2BioSample.py      # BioSample conversion logic
│   ├── FAIRe2SRA.py            # SRA conversion logic
│   └── __init__.py             # Python package initialization
├── docs/
│   ├── BioSample_Metadata_Config_Template.yaml    # BioSample config template
│   ├── SRA_Metadata_Config_Template.yaml          # SRA config template
│   ├── NCBI_BioSample_Metadata_Template.tsv       # NCBI BioSample template
│   └── NCBI_SRA_Metadata_Template.xlsx            # NCBI SRA template
├── README.md                   # This documentation
├── LICENSE                     # CC0-1.0 license
└── banner_faire2ncbi.png       # Project banner
```

## Help and Documentation

### Get Help
```bash
# Main help
python scripts/FAIRe2NCBI.py -h

# BioSamples mode help
python scripts/FAIRe2NCBI.py BioSamples -h

# SRA mode help  
python scripts/FAIRe2NCBI.py SRA -h
```

### Key Features by Mode

#### BioSamples Mode Features
- Hardcoded field mapping for deterministic results
- Bioproject accession handling (single value or expedition-based grouping)
- Mandatory field validation and filling
- Numerical column unit detection and assignment
- Duplicate row detection and resolution
- Sample title generation from metadata fields
- Additional column selection from FAIRe metadata

#### SRA Mode Features
- Assay selection (all or specific assays)
- Library field configuration (strategy, source, selection)
- Platform value determination (assay-specific vs project-level)
- Instrument model configuration
- Automatic filetype detection from filename extensions
- Library title generation with metadata integration
- Library layout determination (single/paired) from filename presence

## License

This project is licensed under the CC0-1.0 License - see the [LICENSE](LICENSE) file for details.

## Contributing

This project is developed and maintained by NOAA AOML. For questions or contributions, please open an issue or contact the development team.

## Citation

When using FAIRe2NCBI in your research, please cite this repository and acknowledge NOAA AOML's contribution to FAIR data practices in marine environmental genomics.
