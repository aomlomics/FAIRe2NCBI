#!/usr/bin/env python3
"""
FAIRe2BioSample: Convert FAIRe metadata to NCBI BioSample MIMARKS format

This script converts FAIRe FAIReMetadata to NCBI BioSample submission format.
Uses hardcoded field mapping based on actual fuzzy pairing results for deterministic behavior.

Author: [Clement Coclet]
Version: 2.1 (Hardcoded mapping)
"""

import pandas as pd
import os
import re
import sys
import argparse
from datetime import datetime
import subprocess
import warnings

# Try to import yaml, provide fallback if not available
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    print("Warning: PyYAML not installed. Configuration system will be disabled.")
    print("To enable configuration system, install PyYAML: pip install PyYAML")

# Import shared utilities from cli module
try:
    from cli import get_valid_user_choice
except ImportError:
    # Fallback if cli module is not available
    def get_valid_user_choice(prompt, valid_choices, default=None):
        """Fallback function if cli module is not available."""
        while True:
            response = input(prompt).strip().lower()
            if not response and default:
                return default
            if response in valid_choices:
                return response
            print(f"Invalid choice. Please enter one of: {', '.join(valid_choices)}")

from paths import (
    BIOSAMPLE_CONFIG_TEMPLATE_NAME,
    DEFAULT_BIOSAMPLE_TEMPLATE,
    get_docs_path,
    resolve_input_path,
)


def is_bioproject_accession_column(col_name):
    """Check if a column name refers to bioproject_accession"""
    return col_name.replace('_', '').replace('*', '').lower() == 'bioprojectaccession'


def get_config_file_path(output_file_path):
    """
    Generate configuration file path based on output file path.
    
    Args:
        output_file_path (str): Path to the output BioSample metadata file
    
    Returns:
        str: Path to the configuration file
    """
    # Remove extension and add _config.yaml
    base_path = os.path.splitext(output_file_path)[0]
    return f"{base_path}_config.yaml"


def get_config_template_path(template_filename=BIOSAMPLE_CONFIG_TEMPLATE_NAME):
    """Return the path to a config template YAML file in the docs/ directory."""
    return str(get_docs_path(template_filename))


def is_config_template_file(config_file_path, template_filename=BIOSAMPLE_CONFIG_TEMPLATE_NAME):
    """Check whether a config file path refers to the bundled config template."""
    template_path = get_config_template_path(template_filename)
    abs_config_file = os.path.abspath(config_file_path)
    abs_template_path = os.path.abspath(template_path)
    config_filename = os.path.basename(config_file_path)
    template_basename = os.path.basename(template_path)
    return (abs_config_file == abs_template_path) or (config_filename == template_basename)


def prompt_config_source_choice():
    """
    Ask whether to reuse a previous config, start from the template, or run interactively.

    Returns:
        str: One of 'previous', 'template', or 'interactive'
    """
    choice = get_valid_user_choice(
        "Do you want to use a config file from a previous run or use the template? "
        "[previous/template/interactive]: ",
        ['previous', 'template', 'interactive', 'p', 't', 'i'],
        default='interactive'
    )
    if choice in ('p', 'previous'):
        return 'previous'
    if choice in ('t', 'template'):
        return 'template'
    return 'interactive'


def prompt_previous_config_path():
    """Prompt until the user provides an existing config file path."""
    while True:
        config_path = input("Enter path to config file from a previous run: ").strip()
        if config_path and os.path.exists(config_path):
            return config_path
        print("File not found. Please enter a valid path.")




def add_qa(config, question, answer, use_config_file=False):
    """
    Add a question-answer pair to the configuration in chronological order.
    Also updates the structured config format if using a config file.
    
    Args:
        config (dict): Configuration dictionary
        question (str): Question asked
        answer (str): Answer provided
        use_config_file (bool): Whether using existing config file
    """
    if 'qa_pairs' not in config:
        config['qa_pairs'] = []
    
    # Check if this question already exists in the config
    existing_index = None
    for i, qa in enumerate(config['qa_pairs']):
        if qa.get('question', '').strip() == question.strip():
            existing_index = i
            break
    
    # Create the new Q&A pair
    new_qa = {
        'question': question,
        'answer': answer
    }
    
    # If question already exists, replace it
    if existing_index is not None:
        config['qa_pairs'][existing_index] = new_qa
    else:
        # For bioproject accession questions, try to insert in the correct position
        if "Enter bioproject_accession for" in question and "'expedition_id'" in question:
            insert_index = find_bioproject_insertion_position(config['qa_pairs'], question)
            if insert_index is not None:
                config['qa_pairs'].insert(insert_index, new_qa)
            else:
                config['qa_pairs'].append(new_qa)
        else:
            # Add new Q&A pair at the end (chronological order)
            config['qa_pairs'].append(new_qa)
    
    # If using config file, also update the structured format
    if use_config_file:
        update_structured_config(config, question, answer)


def update_structured_config(config, question, answer):
    """
    Update the structured config format with a new question-answer pair.
    
    Args:
        config (dict): Configuration dictionary
        question (str): Question asked
        answer (str): Answer provided
    """
    question = question.strip()
    
    # Map questions to structured sections and update them
    if "Configuration file" in question and "overwrite" in question:
        if 'CONFIGURATION_FILE_HANDLING' not in config:
            config['CONFIGURATION_FILE_HANDLING'] = {}
        config['CONFIGURATION_FILE_HANDLING']['Configuration file PATH already exists. Do you want to overwrite it? [y/N]:'] = answer
    elif "File" in question and "already exists" in question and "Overwrite" in question:
        if 'OUTPUT_FILE_OVERWRITE' not in config:
            config['OUTPUT_FILE_OVERWRITE'] = {}
        config['OUTPUT_FILE_OVERWRITE']['File PATH already exists. Overwrite? [y/N]:'] = answer
    elif "bioproject_accession provided" in question and "manually" in question:
        if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
            config['BIOPROJECT_ACCESSION_HANDLING'] = {}
        config['BIOPROJECT_ACCESSION_HANDLING']['No bioproject_accession provided. Do you want to enter values manually? [y/N]:'] = answer
    elif "same value for all samples" in question:
        if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
            config['BIOPROJECT_ACCESSION_HANDLING'] = {}
        config['BIOPROJECT_ACCESSION_HANDLING']['Do you want to enter the same value for all samples? [y/N]:'] = answer
    elif "value to use for all samples" in question:
        if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
            config['BIOPROJECT_ACCESSION_HANDLING'] = {}
        config['BIOPROJECT_ACCESSION_HANDLING']['Enter the value to use for all samples:'] = answer
    elif "field number" in question and "group samples" in question:
        if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
            config['BIOPROJECT_ACCESSION_HANDLING'] = {}
        config['BIOPROJECT_ACCESSION_HANDLING']['Enter field number (1-X) or field name to group samples:'] = answer
    elif "only specific ones" in question and "[all/specific]" in question:
        if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
            config['BIOPROJECT_ACCESSION_HANDLING'] = {}
        config['BIOPROJECT_ACCESSION_HANDLING'][
            'Do you want to use all values in FIELD, or only specific ones? [all/specific]:'] = answer
    elif "Selected values for field '" in question and "numbers separated by commas" in question:
        m = re.search(r"Selected values for field '([^']+)'", question)
        if m:
            fld = m.group(1)
            if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
                config['BIOPROJECT_ACCESSION_HANDLING'] = {}
            if 'Selected values for FIELD (numbers separated by commas):' not in config['BIOPROJECT_ACCESSION_HANDLING']:
                config['BIOPROJECT_ACCESSION_HANDLING']['Selected values for FIELD (numbers separated by commas):'] = {}
            if not isinstance(config['BIOPROJECT_ACCESSION_HANDLING']['Selected values for FIELD (numbers separated by commas):'], dict):
                config['BIOPROJECT_ACCESSION_HANDLING']['Selected values for FIELD (numbers separated by commas):'] = {}
            config['BIOPROJECT_ACCESSION_HANDLING']['Selected values for FIELD (numbers separated by commas):'][fld] = answer
    elif "Enter bioproject_accession for" in question:
        if 'BIOPROJECT_ACCESSION_HANDLING' not in config:
            config['BIOPROJECT_ACCESSION_HANDLING'] = {}
        if 'Enter bioproject_accession for FIELD = VALUE:' not in config['BIOPROJECT_ACCESSION_HANDLING']:
            config['BIOPROJECT_ACCESSION_HANDLING']['Enter bioproject_accession for FIELD = VALUE:'] = {}
        config['BIOPROJECT_ACCESSION_HANDLING']['Enter bioproject_accession for FIELD = VALUE:'][question] = answer
    elif "[all/blank_only]" in question and "experimentRunMetadata" in question and "associatedSequences" in question:
        if 'EXPERIMENT_RUN_METADATA_FILTER' not in config:
            config['EXPERIMENT_RUN_METADATA_FILTER'] = {}
        config['EXPERIMENT_RUN_METADATA_FILTER'][
            'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:'] = answer
    elif "Column" in question and "empty" in question and "fill it with" in question:
        if 'MANDATORY_FIELDS_HANDLING' not in config:
            config['MANDATORY_FIELDS_HANDLING'] = {}
        if 'Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):' not in config['MANDATORY_FIELDS_HANDLING']:
            config['MANDATORY_FIELDS_HANDLING']['Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):'] = {}
        config['MANDATORY_FIELDS_HANDLING']['Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):'][question] = answer
    elif "Enter unit for" in question and "skip" in question:
        if 'NUMERICAL_COLUMNS_WITH_UNITS' not in config:
            config['NUMERICAL_COLUMNS_WITH_UNITS'] = {}
        if 'Enter unit for COLUMN_NAME (or press Enter to skip):' not in config['NUMERICAL_COLUMNS_WITH_UNITS']:
            config['NUMERICAL_COLUMNS_WITH_UNITS']['Enter unit for COLUMN_NAME (or press Enter to skip):'] = {}
        config['NUMERICAL_COLUMNS_WITH_UNITS']['Enter unit for COLUMN_NAME (or press Enter to skip):'][question] = answer
    elif "add values in the sample_title column" in question:
        if 'SAMPLE_TITLE_GENERATION' not in config:
            config['SAMPLE_TITLE_GENERATION'] = {}
        config['SAMPLE_TITLE_GENERATION']['Do you want to add values in the sample_title column? [y/N]:'] = answer
    elif "use the default parameters" in question and "*sample_name" in question:
        if 'SAMPLE_TITLE_GENERATION' not in config:
            config['SAMPLE_TITLE_GENERATION'] = {}
        config['SAMPLE_TITLE_GENERATION']['Do you want to use the default parameters from the script: *geo_loc_name, *organism, *sample_name? [Y/n]:'] = answer
    elif "Enter column numbers separated by commas" in question and "concatenate" not in question:
        if 'SAMPLE_TITLE_GENERATION' not in config:
            config['SAMPLE_TITLE_GENERATION'] = {}
        config['SAMPLE_TITLE_GENERATION']['Enter column numbers separated by commas (e.g., 1,3,5) or column names separated by commas:'] = answer
    elif "Columns to concatenate" in question:
        if 'SAMPLE_TITLE_GENERATION' not in config:
            config['SAMPLE_TITLE_GENERATION'] = {}
        config['SAMPLE_TITLE_GENERATION']['Columns to concatenate:'] = answer
    elif "add ALL of these columns" in question:
        if 'ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA' not in config:
            config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA'] = {}
        config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Do you want to add ALL of these columns to BioSampleMetadata? [Y/n]:'] = answer
    elif "Enter column numbers separated by commas" in question and "EXCLUDE" in question:
        if 'ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA' not in config:
            config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA'] = {}
        config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Enter column numbers separated by commas (e.g., 1,3,5) to EXCLUDE:'] = answer
    elif "none to exclude none" in question:
        if 'ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA' not in config:
            config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA'] = {}
        config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Or enter none to exclude none (add all):'] = answer
    elif "Columns to exclude" in question:
        if 'ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA' not in config:
            config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA'] = {}
        config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Columns to exclude:'] = answer
    elif "add a column from FAIReMetadata to help resolve duplicates" in question:
        if 'DUPLICATE_ROW_CHECKING' not in config:
            config['DUPLICATE_ROW_CHECKING'] = {}
        config['DUPLICATE_ROW_CHECKING']['Do you want to add a column from FAIReMetadata to help resolve duplicates? [y/N]:'] = answer
    elif "field number" in question and "resolve duplicates" in question:
        if 'DUPLICATE_ROW_CHECKING' not in config:
            config['DUPLICATE_ROW_CHECKING'] = {}
        config['DUPLICATE_ROW_CHECKING']['Enter field number (1-X) or field name to resolve duplicates:'] = answer
    elif "rename the column from" in question:
        if 'DUPLICATE_ROW_CHECKING' not in config:
            config['DUPLICATE_ROW_CHECKING'] = {}
        config['DUPLICATE_ROW_CHECKING']['Do you want to rename the column from FIELD_NAME? [y/N]:'] = answer
    elif "Enter new column name" in question:
        if 'DUPLICATE_ROW_CHECKING' not in config:
            config['DUPLICATE_ROW_CHECKING'] = {}
        config['DUPLICATE_ROW_CHECKING']['Enter new column name (or press Enter to keep FIELD_NAME):'] = answer
    elif "Enter column number" in question and "column name" in question:
        if 'DUPLICATE_ROW_CHECKING' not in config:
            config['DUPLICATE_ROW_CHECKING'] = {}
        config['DUPLICATE_ROW_CHECKING']['Enter column number (1-X) or column name:'] = answer
    elif "continue writing the file despite duplicates" in question:
        if 'DUPLICATE_ROW_CHECKING' not in config:
            config['DUPLICATE_ROW_CHECKING'] = {}
        config['DUPLICATE_ROW_CHECKING']['Do you want to continue writing the file despite duplicates? [y/N]:'] = answer


def find_bioproject_insertion_position(qa_pairs, new_question):
    """
    Find the correct insertion position for bioproject accession questions.
    
    Args:
        qa_pairs (list): List of existing Q&A pairs
        new_question (str): The new question to insert
    
    Returns:
        int or None: Index where to insert, or None to append at end
    """
    # Extract the expedition value from the new question
    import re
    match = re.search(r"'expedition_id'\s*=\s*'([^']+)'", new_question)
    if not match:
        return None
    
    new_expedition = match.group(1)
    
    # Find the position to insert based on expedition order
    expedition_order = ['EX2107', 'EX2201', 'EX2203', 'EX2205', 'EX2206', 'EX2301', 'EX2303']
    
    try:
        new_index = expedition_order.index(new_expedition)
    except ValueError:
        return None
    
    # Find the correct insertion position
    for i, qa in enumerate(qa_pairs):
        question = qa.get('question', '')
        if "Enter bioproject_accession for" in question and "'expedition_id'" in question:
            match = re.search(r"'expedition_id'\s*=\s*'([^']+)'", question)
            if match:
                existing_expedition = match.group(1)
                try:
                    existing_index = expedition_order.index(existing_expedition)
                    if existing_index > new_index:
                        return i
                except ValueError:
                    continue
    
    return None


def add_generated_file(config, file_path, description):
    """
    Add a generated file to the configuration.
    
    Args:
        config (dict): Configuration dictionary
        file_path (str): Path to the generated file
        description (str): Description of what the file contains
    """
    if 'generated_files' not in config:
        config['generated_files'] = []
    
    # Check if this file already exists in the config
    file_exists = any(gf.get('file_path') == file_path for gf in config['generated_files'])
    
    # If file already exists, don't add it again
    if file_exists:
        return
    
    # Add the generated file
    config['generated_files'].append({
        'file_path': file_path,
        'description': description,
        'timestamp': datetime.now().isoformat()
    })


def load_config(config_file_path):
    """
    Load configuration from YAML file.
    
    Args:
        config_file_path (str): Path to the configuration file
    
    Returns:
        dict: Configuration dictionary, empty dict if file doesn't exist
    """
    if not YAML_AVAILABLE:
        print("Warning: YAML not available. Configuration system disabled.")
        return {}
    
    if not os.path.exists(config_file_path):
        return {}
    
    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        print(f"Loaded configuration from: {config_file_path}")
        return config
    except Exception as e:
        print(f"Warning: Could not load configuration file {config_file_path}: {e}")
        return {}


def load_template_config():
    """
    Load the BioSample template configuration file.
    
    Returns:
        dict: Template configuration dictionary, empty dict if template doesn't exist
    """
    if not YAML_AVAILABLE:
        print("Warning: YAML not available. Configuration system disabled.")
        return {}
    
    template_path = get_config_template_path()
    
    if not os.path.exists(template_path):
        print(f"Warning: Template file not found at: {template_path}")
        return {}
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        print(f"Loaded template configuration from: {template_path}")
        return config
    except Exception as e:
        print(f"Warning: Could not load template configuration file {template_path}: {e}")
        return {}


def save_config(config, config_file_path):
    """
    Save configuration to YAML file with structured format matching the questions document.
    
    Args:
        config (dict): Configuration dictionary to save
        config_file_path (str): Path to save the configuration file
    """
    if not YAML_AVAILABLE:
        print("Warning: YAML not available. Configuration not saved.")
        return
    
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
        
        # Get existing Q&A pairs
        existing_qa_pairs = config.get('qa_pairs', [])
        
        # Create structured config matching the exact format from questions document
        # Start with default empty structure
        structured_config = {
            'command': config.get('command', ''),
            'date_time': config.get('date_time', ''),
            'CONFIGURATION_FILE_HANDLING': {
                'Configuration file PATH already exists. Do you want to overwrite it? [y/N]:': ''
            },
            'OUTPUT_FILE_OVERWRITE': {
                'File PATH already exists. Overwrite? [y/N]:': ''
            },
            'BIOPROJECT_ACCESSION_HANDLING': {
                'No bioproject_accession provided. Do you want to enter values manually? [y/N]:': '',
                'Do you want to enter the same value for all samples? [y/N]:': '',
                'Enter the value to use for all samples:': '',
                'Enter field number (1-X) or field name to group samples:': '',
                'Do you want to use all values in FIELD, or only specific ones? [all/specific]:': '',
                'Selected values for FIELD (numbers separated by commas):': {},
                'Enter bioproject_accession for FIELD = VALUE:': {}
            },
            'MANDATORY_FIELDS_HANDLING': {
                'Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):': {}
            },
            'NUMERICAL_COLUMNS_WITH_UNITS': {
                'Enter unit for COLUMN_NAME (or press Enter to skip):': {}
            },
            'DUPLICATE_ROW_CHECKING': {
                'Do you want to add a column from FAIReMetadata to help resolve duplicates? [y/N]:': '',
                'Enter field number (1-X) or field name to resolve duplicates:': '',
                'Do you want to rename the column from FIELD_NAME? [y/N]:': '',
                'Enter new column name (or press Enter to keep FIELD_NAME):': '',
                'Enter column number (1-X) or column name:': '',
                'Do you want to continue writing the file despite duplicates? [y/N]:': ''
            },
            'SAMPLE_TITLE_GENERATION': {
                'Do you want to add values in the sample_title column? [y/N]:': '',
                'Do you want to use the default parameters from the script: *geo_loc_name, *organism, *sample_name? [Y/n]:': '',
                'Enter column numbers separated by commas (e.g., 1,3,5) or column names separated by commas:': '',
                'Columns to concatenate:': ''
            },
            'ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA': {
                'Do you want to add ALL of these columns to BioSampleMetadata? [Y/n]:': '',
                'Enter column numbers separated by commas (e.g., 1,3,5) to EXCLUDE:': '',
                'Or enter none to exclude none (add all):': '',
                'Columns to exclude:': ''
            },
            'EXPERIMENT_RUN_METADATA_FILTER': {
                'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:': ''
            },
            'generated_files': config.get('generated_files', [])
        }
        
        # If config already has structured sections (from template), preserve them
        for section_name in ['CONFIGURATION_FILE_HANDLING', 'OUTPUT_FILE_OVERWRITE', 'BIOPROJECT_ACCESSION_HANDLING', 
                           'MANDATORY_FIELDS_HANDLING', 'NUMERICAL_COLUMNS_WITH_UNITS', 'DUPLICATE_ROW_CHECKING',
                           'SAMPLE_TITLE_GENERATION', 'ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA',
                           'EXPERIMENT_RUN_METADATA_FILTER']:
            if section_name in config and isinstance(config[section_name], dict):
                # Merge existing section data with default structure
                for key, value in config[section_name].items():
                    if key in structured_config[section_name]:
                        if isinstance(value, dict) and isinstance(structured_config[section_name][key], dict):
                            # For nested dictionaries, merge them
                            structured_config[section_name][key].update(value)
                        else:
                            # For simple values, use the existing value
                            structured_config[section_name][key] = value
                    else:
                        # Add new keys that weren't in the default structure
                        structured_config[section_name][key] = value
        
        # Fill in actual answers from existing Q&A pairs
        for qa in existing_qa_pairs:
            question = qa.get('question', '').strip()
            answer = qa.get('answer', '').strip()
            
            # Map questions to structured sections using exact question matching
            if "Configuration file" in question and "overwrite" in question:
                structured_config['CONFIGURATION_FILE_HANDLING']['Configuration file PATH already exists. Do you want to overwrite it? [y/N]:'] = answer
            elif "File" in question and "already exists" in question and "Overwrite" in question:
                structured_config['OUTPUT_FILE_OVERWRITE']['File PATH already exists. Overwrite? [y/N]:'] = answer
            elif "bioproject_accession provided" in question and "manually" in question:
                structured_config['BIOPROJECT_ACCESSION_HANDLING']['No bioproject_accession provided. Do you want to enter values manually? [y/N]:'] = answer
            elif "same value for all samples" in question:
                structured_config['BIOPROJECT_ACCESSION_HANDLING']['Do you want to enter the same value for all samples? [y/N]:'] = answer
            elif "value to use for all samples" in question:
                structured_config['BIOPROJECT_ACCESSION_HANDLING']['Enter the value to use for all samples:'] = answer
            elif "field number" in question and "group samples" in question:
                structured_config['BIOPROJECT_ACCESSION_HANDLING']['Enter field number (1-X) or field name to group samples:'] = answer
            elif "only specific ones" in question and "[all/specific]" in question:
                structured_config['BIOPROJECT_ACCESSION_HANDLING'][
                    'Do you want to use all values in FIELD, or only specific ones? [all/specific]:'] = answer
            elif "Selected values for field '" in question and "numbers separated by commas" in question:
                m = re.search(r"Selected values for field '([^']+)'", question)
                if m:
                    fld = m.group(1)
                    if not isinstance(structured_config['BIOPROJECT_ACCESSION_HANDLING'].get(
                            'Selected values for FIELD (numbers separated by commas):'), dict):
                        structured_config['BIOPROJECT_ACCESSION_HANDLING'][
                            'Selected values for FIELD (numbers separated by commas):'] = {}
                    structured_config['BIOPROJECT_ACCESSION_HANDLING'][
                        'Selected values for FIELD (numbers separated by commas):'][fld] = answer
            elif "Enter bioproject_accession for" in question:
                # Store in the grouping values dictionary
                if not isinstance(structured_config['BIOPROJECT_ACCESSION_HANDLING']['Enter bioproject_accession for FIELD = VALUE:'], dict):
                    structured_config['BIOPROJECT_ACCESSION_HANDLING']['Enter bioproject_accession for FIELD = VALUE:'] = {}
                structured_config['BIOPROJECT_ACCESSION_HANDLING']['Enter bioproject_accession for FIELD = VALUE:'][question] = answer
            elif "[all/blank_only]" in question and "experimentRunMetadata" in question and "associatedSequences" in question:
                structured_config['EXPERIMENT_RUN_METADATA_FILTER'][
                    'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:'] = answer
            elif "Column" in question and "empty" in question and "fill it with" in question:
                # Store in the field values dictionary
                if not isinstance(structured_config['MANDATORY_FIELDS_HANDLING']['Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):'], dict):
                    structured_config['MANDATORY_FIELDS_HANDLING']['Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):'] = {}
                structured_config['MANDATORY_FIELDS_HANDLING']['Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):'][question] = answer
            elif "Enter unit for" in question and "skip" in question:
                # Store in the unit values dictionary
                if not isinstance(structured_config['NUMERICAL_COLUMNS_WITH_UNITS']['Enter unit for COLUMN_NAME (or press Enter to skip):'], dict):
                    structured_config['NUMERICAL_COLUMNS_WITH_UNITS']['Enter unit for COLUMN_NAME (or press Enter to skip):'] = {}
                structured_config['NUMERICAL_COLUMNS_WITH_UNITS']['Enter unit for COLUMN_NAME (or press Enter to skip):'][question] = answer
            elif "add values in the sample_title column" in question:
                structured_config['SAMPLE_TITLE_GENERATION']['Do you want to add values in the sample_title column? [y/N]:'] = answer
            elif "use the default parameters" in question and "*sample_name" in question:
                structured_config['SAMPLE_TITLE_GENERATION']['Do you want to use the default parameters from the script: *geo_loc_name, *organism, *sample_name? [Y/n]:'] = answer
            elif "Enter column numbers separated by commas" in question and "concatenate" not in question:
                structured_config['SAMPLE_TITLE_GENERATION']['Enter column numbers separated by commas (e.g., 1,3,5) or column names separated by commas:'] = answer
            elif "Columns to concatenate" in question:
                structured_config['SAMPLE_TITLE_GENERATION']['Columns to concatenate:'] = answer
            elif "add ALL of these columns" in question:
                structured_config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Do you want to add ALL of these columns to BioSampleMetadata? [Y/n]:'] = answer
            elif "Enter column numbers separated by commas" in question and "EXCLUDE" in question:
                structured_config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Enter column numbers separated by commas (e.g., 1,3,5) to EXCLUDE:'] = answer
            elif "none to exclude none" in question:
                structured_config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Or enter none to exclude none (add all):'] = answer
            elif "Columns to exclude" in question:
                structured_config['ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA']['Columns to exclude:'] = answer
            elif "add a column from FAIReMetadata to help resolve duplicates" in question:
                structured_config['DUPLICATE_ROW_CHECKING']['Do you want to add a column from FAIReMetadata to help resolve duplicates? [y/N]:'] = answer
            elif "field number" in question and "resolve duplicates" in question:
                structured_config['DUPLICATE_ROW_CHECKING']['Enter field number (1-X) or field name to resolve duplicates:'] = answer
            elif "rename the column from" in question:
                structured_config['DUPLICATE_ROW_CHECKING']['Do you want to rename the column from FIELD_NAME? [y/N]:'] = answer
            elif "Enter new column name" in question:
                structured_config['DUPLICATE_ROW_CHECKING']['Enter new column name (or press Enter to keep FIELD_NAME):'] = answer
            elif "Enter column number" in question and "column name" in question:
                structured_config['DUPLICATE_ROW_CHECKING']['Enter column number (1-X) or column name:'] = answer
            elif "continue writing the file despite duplicates" in question:
                structured_config['DUPLICATE_ROW_CHECKING']['Do you want to continue writing the file despite duplicates? [y/N]:'] = answer
        
        # Write config with comments
        write_config_with_comments(structured_config, config_file_path)
        print(f"Configuration saved to: {config_file_path}")
    except Exception as e:
        print(f"Warning: Could not save configuration file {config_file_path}: {e}")


def write_config_with_comments(config, config_file_path):
    """
    Write configuration to YAML file with comments.
    
    Args:
        config (dict): Configuration dictionary to save
        config_file_path (str): Path to save the configuration file
    """
    try:
        with open(config_file_path, 'w', encoding='utf-8') as f:
            # Write header comments
            f.write("# FAIRe2BioSample Configuration File\n")
            f.write("# This file contains all user responses from the FAIRe2BioSample script\n")
            f.write("# Generated automatically - do not edit manually unless you understand the structure\n\n")
            
            # Write command and date_time
            f.write(f"command: {config.get('command', '')}\n")
            f.write(f"date_time: '{config.get('date_time', '')}'\n\n")
            
            # Write sections with comments
            sections = [
                ('CONFIGURATION_FILE_HANDLING', 'CONFIGURATION FILE HANDLING', 'File overwrite prompts'),
                ('OUTPUT_FILE_OVERWRITE', 'OUTPUT FILE OVERWRITE', 'Output file overwrite prompts'),
                ('BIOPROJECT_ACCESSION_HANDLING', 'BIOPROJECT ACCESSION HANDLING', 'Bioproject accession configuration for grouping samples by expedition'),
                ('MANDATORY_FIELDS_HANDLING', 'MANDATORY FIELDS HANDLING', 'Configuration for handling empty mandatory fields (marked with *)'),
                ('NUMERICAL_COLUMNS_WITH_UNITS', 'NUMERICAL COLUMNS WITH UNITS', 'Unit configuration for numerical columns in BioSample metadata'),
                ('DUPLICATE_ROW_CHECKING', 'DUPLICATE ROW CHECKING', 'Configuration for handling duplicate rows in the output'),
                ('SAMPLE_TITLE_GENERATION', 'SAMPLE TITLE GENERATION', 'Configuration for generating sample_title column values'),
                ('ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA', 'ADDITIONAL COLUMNS FROM SAMPLE METADATA', 'Configuration for adding additional columns from FAIReMetadata to BioSampleMetadata'),
                ('EXPERIMENT_RUN_METADATA_FILTER', 'EXPERIMENT RUN METADATA FILTER', 'Optional filter by blank/NA associatedSequences in experimentRunMetadata after bioproject assignment')
            ]
            
            for section_key, section_title, section_desc in sections:
                if section_key in config:
                    f.write(f"# =============================================================================\n")
                    f.write(f"# {section_title}\n")
                    f.write(f"# =============================================================================\n")
                    f.write(f"# {section_desc}\n")
                    f.write(f"{section_key}:\n")
                    
                    section_data = config[section_key]
                    if isinstance(section_data, dict):
                        for key, value in section_data.items():
                            if isinstance(value, dict):
                                # Use double quotes for keys that might contain single quotes
                                if "'" in key:
                                    f.write(f'  "{key}":\n')
                                else:
                                    f.write(f"  '{key}':\n")
                                for sub_key, sub_value in value.items():
                                    # Use double quotes for sub_keys that might contain single quotes
                                    if "'" in sub_key:
                                        f.write(f'    "{sub_key}": "{sub_value}"\n')
                                    else:
                                        f.write(f"    '{sub_key}': '{sub_value}'\n")
                            else:
                                # Use double quotes for keys that might contain single quotes
                                if "'" in key:
                                    f.write(f'  "{key}": "{value}"\n')
                                else:
                                    f.write(f"  '{key}': '{value}'\n")
                    f.write("\n")
            
            # Write generated files section
            if 'generated_files' in config and config['generated_files']:
                f.write("# =============================================================================\n")
                f.write("# GENERATED FILES TRACKING\n")
                f.write("# =============================================================================\n")
                f.write("# List of files created by the script\n")
                f.write("generated_files:\n")
                for file_info in config['generated_files']:
                    f.write(f"- file_path: {file_info.get('file_path', '')}\n")
                    f.write(f"  description: {file_info.get('description', '')}\n")
                    f.write(f"  timestamp: '{file_info.get('timestamp', '')}'\n")
                f.write("\n")
            
            # Write usage notes
            f.write("# =============================================================================\n")
            f.write("# NOTES ON USAGE\n")
            f.write("# =============================================================================\n")
            f.write("# This configuration file contains all user responses from the FAIRe2BioSample script.\n")
            f.write("# \n")
            f.write("# Key sections (in chronological order):\n")
            f.write("# - CONFIGURATION_FILE_HANDLING: File overwrite prompts\n")
            f.write("# - OUTPUT_FILE_OVERWRITE: Output file overwrite prompts\n")
            f.write("# - BIOPROJECT_ACCESSION_HANDLING: Bioproject accession configuration per expedition\n")
            f.write("# - MANDATORY_FIELDS_HANDLING: Handling of empty mandatory fields\n")
            f.write("# - NUMERICAL_COLUMNS_WITH_UNITS: Unit configuration for numerical columns\n")
            f.write("# - DUPLICATE_ROW_CHECKING: Duplicate row resolution settings\n")
            f.write("# - SAMPLE_TITLE_GENERATION: Sample title column generation settings\n")
            f.write("# - ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA: Additional column selection\n")
            f.write("# - EXPERIMENT_RUN_METADATA_FILTER: Filter BioSample rows by experimentRunMetadata associatedSequences\n")
            f.write("# - generated_files: List of files created by the script\n")
            f.write("# \n")
            f.write("# To reuse this configuration:\n")
            f.write("# 1. Run the script with --config_file path/to/this/file.yaml\n")
            f.write("# 2. The script will use saved answers and skip prompts\n")
            f.write("# 3. Only missing answers will prompt for user input\n")
            
    except Exception as e:
        print(f"Warning: Could not write configuration file with comments {config_file_path}: {e}")
        # Fallback to regular YAML dump
        with open(config_file_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, indent=2)


def find_answer_in_structured_config(config, question):
    """
    Find answer for a question in the structured config format.
    
    Args:
        config (dict): Configuration dictionary
        question (str): Question being asked
    
    Returns:
        str or None: Answer if found, None otherwise
    """
    question = question.strip()
    
    # Map questions to structured sections based on the YAML format
    if "Configuration file" in question and "overwrite" in question:
        answer = config.get('CONFIGURATION_FILE_HANDLING', {}).get('Configuration file PATH already exists. Do you want to overwrite it? [y/N]:', '')
        return answer if answer != '' else None
    elif "File" in question and "already exists" in question and "Overwrite" in question:
        answer = config.get('OUTPUT_FILE_OVERWRITE', {}).get('File PATH already exists. Overwrite? [y/N]:', '')
        return answer if answer != '' else None
    elif "bioproject_accession provided" in question and "manually" in question:
        answer = config.get('BIOPROJECT_ACCESSION_HANDLING', {}).get('No bioproject_accession provided. Do you want to enter values manually? [y/N]:', '')
        return answer if answer != '' else None
    elif "same value for all samples" in question:
        answer = config.get('BIOPROJECT_ACCESSION_HANDLING', {}).get('Do you want to enter the same value for all samples? [y/N]:', '')
        return answer if answer != '' else None
    elif "value to use for all samples" in question:
        answer = config.get('BIOPROJECT_ACCESSION_HANDLING', {}).get('Enter the value to use for all samples:', '')
        return answer if answer != '' else None
    elif "field number" in question and "group samples" in question:
        answer = config.get('BIOPROJECT_ACCESSION_HANDLING', {}).get('Enter field number (1-X) or field name to group samples:', '')
        return answer if answer != '' else None
    elif "only specific ones" in question and "[all/specific]" in question:
        bih = config.get('BIOPROJECT_ACCESSION_HANDLING') or {}
        answer = bih.get(
            'Do you want to use all values in FIELD, or only specific ones? [all/specific]:', '')
        if not answer:
            # Alternate YAML spellings / hand-edited configs
            for k, v in bih.items():
                if not isinstance(v, str) or not str(v).strip():
                    continue
                if 'all values in FIELD' in k and 'only specific' in k:
                    answer = v
                    break
        if not answer:
            fm = re.search(r"values in '([^']+)'", question)
            if fm:
                fk = f"bioproject_use_all_values_{fm.group(1)}"
                top = config.get(fk)
                if top is not None and str(top).strip() != '':
                    answer = str(top).strip()
        return answer if answer != '' else None
    elif "Selected values for field '" in question and "numbers separated by commas" in question:
        m = re.search(r"Selected values for field '([^']+)'", question)
        if m:
            fld = m.group(1)
            per_field = config.get('BIOPROJECT_ACCESSION_HANDLING', {}).get(
                'Selected values for FIELD (numbers separated by commas):', {})
            if isinstance(per_field, dict):
                answer = per_field.get(fld, '')
                return answer if answer != '' else None
        return None
    elif "Enter bioproject_accession for" in question:
        # Look in the grouping values dictionary
        grouping_values = config.get('BIOPROJECT_ACCESSION_HANDLING', {}).get('Enter bioproject_accession for FIELD = VALUE:', {})
        if isinstance(grouping_values, dict):
            answer = grouping_values.get(question, '')
            return answer if answer != '' else None
    elif "[all/blank_only]" in question and "experimentRunMetadata" in question and "associatedSequences" in question:
        answer = config.get('EXPERIMENT_RUN_METADATA_FILTER', {}).get(
            'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:', '')
        if not answer:
            v = config.get('filter_experiment_run_blank_associatedSequences')
            if v is not None and str(v).strip() != '':
                answer = str(v).strip()
        return answer if answer != '' else None
    elif "Column" in question and "empty" in question and "fill it with" in question:
        # Look in the field values dictionary
        field_values = config.get('MANDATORY_FIELDS_HANDLING', {}).get('Column FIELD_NAME is empty. Do you want to fill it with not collected, not applicable, or missing? (Or enter any other value, or leave blank to skip):', {})
        if isinstance(field_values, dict):
            answer = field_values.get(question, '')
            return answer if answer != '' else None
    elif "Enter unit for" in question and "skip" in question:
        # Look in the unit values dictionary
        unit_values = config.get('NUMERICAL_COLUMNS_WITH_UNITS', {}).get('Enter unit for COLUMN_NAME (or press Enter to skip):', {})
        if isinstance(unit_values, dict):
            answer = unit_values.get(question, '')
            return answer if answer != '' else None
    elif "add values in the sample_title column" in question:
        answer = config.get('SAMPLE_TITLE_GENERATION', {}).get('Do you want to add values in the sample_title column? [y/N]:', '')
        return answer if answer != '' else None
    elif "use the default parameters" in question and "*sample_name" in question:
        answer = config.get('SAMPLE_TITLE_GENERATION', {}).get('Do you want to use the default parameters from the script: *geo_loc_name, *organism, *sample_name? [Y/n]:', '')
        return answer if answer != '' else None
    elif "Enter column numbers separated by commas" in question and "concatenate" not in question:
        answer = config.get('SAMPLE_TITLE_GENERATION', {}).get('Enter column numbers separated by commas (e.g., 1,3,5) or column names separated by commas:', '')
        return answer if answer != '' else None
    elif "Columns to concatenate" in question:
        answer = config.get('SAMPLE_TITLE_GENERATION', {}).get('Columns to concatenate:', '')
        return answer if answer != '' else None
    elif "add ALL of these columns" in question:
        answer = config.get('ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA', {}).get('Do you want to add ALL of these columns to BioSampleMetadata? [Y/n]:', '')
        return answer if answer != '' else None
    elif "Enter column numbers separated by commas" in question and "EXCLUDE" in question:
        answer = config.get('ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA', {}).get('Enter column numbers separated by commas (e.g., 1,3,5) to EXCLUDE:', '')
        return answer if answer != '' else None
    elif "none to exclude none" in question:
        answer = config.get('ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA', {}).get('Or enter none to exclude none (add all):', '')
        return answer if answer != '' else None
    elif "Columns to exclude" in question:
        answer = config.get('ADDITIONAL_COLUMNS_FROM_SAMPLE_METADATA', {}).get('Columns to exclude:', '')
        return answer if answer != '' else None
    elif "add a column from FAIReMetadata to help resolve duplicates" in question:
        answer = config.get('DUPLICATE_ROW_CHECKING', {}).get('Do you want to add a column from FAIReMetadata to help resolve duplicates? [y/N]:', '')
        return answer if answer != '' else None
    elif "field number" in question and "resolve duplicates" in question:
        answer = config.get('DUPLICATE_ROW_CHECKING', {}).get('Enter field number (1-X) or field name to resolve duplicates:', '')
        return answer if answer != '' else None
    elif "rename the column from" in question:
        answer = config.get('DUPLICATE_ROW_CHECKING', {}).get('Do you want to rename the column from FIELD_NAME? [y/N]:', '')
        return answer if answer != '' else None
    elif "Enter new column name" in question:
        answer = config.get('DUPLICATE_ROW_CHECKING', {}).get('Enter new column name (or press Enter to keep FIELD_NAME):', '')
        return answer if answer != '' else None
    elif "Enter column number" in question and "column name" in question:
        answer = config.get('DUPLICATE_ROW_CHECKING', {}).get('Enter column number (1-X) or column name:', '')
        return answer if answer != '' else None
    elif "continue writing the file despite duplicates" in question:
        answer = config.get('DUPLICATE_ROW_CHECKING', {}).get('Do you want to continue writing the file despite duplicates? [y/N]:', '')
        return answer if answer != '' else None
    
    return None


def find_answer_in_qa_pairs(config, question):
    """
    Match saved qa_pairs from YAML (exact or fuzzy for dynamic prompts).
    """
    question = question.strip()
    pairs = config.get("qa_pairs")
    if not pairs:
        return None
    for qa in pairs:
        if qa.get("question", "").strip() == question:
            a = qa.get("answer", "")
            if str(a).strip() != "":
                return str(a).strip()
    # Dynamic prompt: all vs specific values for a grouping field (count in text may differ)
    if "only specific ones" in question and "[all/specific]" in question:
        field_m = re.search(r"values in '([^']+)'", question)
        field = field_m.group(1) if field_m else None
        for qa in pairs:
            q = qa.get("question", "")
            if "only specific ones" not in q or "[all/specific]" not in q:
                continue
            if field and field in q:
                a = qa.get("answer", "")
                if str(a).strip() != "":
                    return str(a).strip()
        for qa in pairs:
            q = qa.get("question", "")
            if "only specific ones" in q and "[all/specific]" in q:
                a = qa.get("answer", "")
                if str(a).strip() != "":
                    return str(a).strip()
    if "[all/blank_only]" in question and "experimentRunMetadata" in question:
        for qa in pairs:
            q = qa.get("question", "")
            if (
                "[all/blank_only]" in q
                and "experimentRunMetadata" in q
                and "associatedSequences" in q
            ):
                a = qa.get("answer", "")
                if str(a).strip() != "":
                    return str(a).strip()
    return None


def get_config_value(config, key, prompt_func, question, use_config_file, *args, **kwargs):
    """
    Get value from config or prompt user if not found.
    
    Args:
        config (dict): Configuration dictionary
        key (str): Configuration key
        prompt_func (callable): Function to prompt user if value not in config
        question (str): Question being asked
        use_config_file (bool): Whether to use saved config values (only when --config_file provided)
        *args, **kwargs: Arguments to pass to prompt_func
    
    Returns:
        Any: Value from config or user input
    """
    if not YAML_AVAILABLE:
        # If YAML not available, always prompt user
        return prompt_func(*args, **kwargs)
    
    # Only use saved config values if config file was provided
    if use_config_file:
        # Try to find answer in structured config format
        saved_answer = find_answer_in_structured_config(config, question)
        if saved_answer is None:
            saved_answer = find_answer_in_qa_pairs(config, question)
        if saved_answer is None and key:
            v = config.get(key)
            if v is not None and str(v).strip() != "":
                saved_answer = str(v).strip()
        if saved_answer is not None:
            print(f"{question} {saved_answer}")
            add_qa(config, question, saved_answer, use_config_file)
            if key:
                config[key] = saved_answer
            return saved_answer
    
    # Always prompt user and save the answer
    value = prompt_func(*args, **kwargs)
    add_qa(config, question, value, use_config_file)
    if key:
        config[key] = value
    return value







# FAIRe / MIMARKS fields that should never receive automatic unit handling
NON_MEASUREMENT_FAIRE_COLUMNS = frozenset({
    'samp_name',
    'materialSampleID',
    'library_ID',
    'biosample_accession',
    'geo_loc_name',
    'organism',
    'eventDate',
    'sample_type',
    'short_name',
    'filter_name',
    'sample_derived_from',
    'sample_composed_of',
})

NON_MEASUREMENT_MIMARKS_COLUMNS = frozenset({
    '*sample_name',
    'sample_title',
    '*organism',
    '*geo_loc_name',
    '*lat_lon',
    '*collection_date',
    'bioproject_accession',
    'source_material_id',
})


def _cleaned_string_is_numeric(clean_value):
    """Return True if a letter-stripped string represents a plain numeric value."""
    if not clean_value:
        return False

    # Python float() accepts underscores as digit separators (e.g. 9_20190715)
    if '_' in clean_value:
        return False

    # Reject strings that still contain letters (e.g. hyphenated IDs)
    if re.search(r'[a-zA-Z]', clean_value):
        return False

    try:
        float(clean_value)
        return True
    except (ValueError, TypeError):
        return False


def is_numerical_column(df, column):
    """
    Check if a column contains numerical values.
    
    Args:
        df (pd.DataFrame): The dataframe containing the column
        column (str): Column name to check
    
    Returns:
        bool: True if column contains numerical values, False otherwise
    """
    if column not in df.columns:
        return False
    
    # Get non-null values from the column
    values = df[column].dropna()
    if len(values) == 0:
        return False
    
    # Check if at least one value is numeric
    for value in values:
        # Skip empty strings and None values
        if pd.isna(value) or str(value).strip() == '':
            continue
        
        try:
            # Try to convert to float, but also check if it's already a number
            if isinstance(value, (int, float)):
                return True
            else:
                # Remove common non-numeric characters that might be in the string
                clean_value = str(value).strip()
                # Remove common prefixes/suffixes that might indicate units
                clean_value = re.sub(r'^[a-zA-Z\s]*', '', clean_value)
                clean_value = re.sub(r'[a-zA-Z\s]*$', '', clean_value)
                clean_value = clean_value.strip()
                
                if _cleaned_string_is_numeric(clean_value):
                    return True
        except (ValueError, TypeError):
            continue
    
    # If no numeric values found, return False
    return False


def find_unit_column(sample_df, numerical_column):
    """
    Find the corresponding unit column for a numerical column.
    
    Args:
        sample_df (pd.DataFrame): The FAIReMetadata dataframe
        numerical_column (str): The numerical column name
    
    Returns:
        tuple: (unit_column_name, unit_value) or (None, None) if not found
    """
    # Check if there's a column with "_unit" suffix
    unit_column = f"{numerical_column}_unit"
    if unit_column in sample_df.columns:
        # Get the most common non-null unit value
        unit_values = sample_df[unit_column].dropna()
        if len(unit_values) > 0:
            most_common_unit = unit_values.mode().iloc[0] if len(unit_values.mode()) > 0 else unit_values.iloc[0]
            return unit_column, str(most_common_unit)
    
    # Also check for common unit column patterns
    common_unit_patterns = [
        f"{numerical_column}_units",
        f"{numerical_column}_unit_of_measure",
        f"{numerical_column}_measurement_unit"
    ]
    
    for pattern in common_unit_patterns:
        if pattern in sample_df.columns:
            unit_values = sample_df[pattern].dropna()
            if len(unit_values) > 0:
                most_common_unit = unit_values.mode().iloc[0] if len(unit_values.mode()) > 0 else unit_values.iloc[0]
                return pattern, str(most_common_unit)
    
    return None, None


def handle_numerical_columns_with_units(sample_df, output_df, mapping, config, use_config_file):
    """
    Handle units for numerical columns in BioSampleMetadata.
    
    Args:
        sample_df (pd.DataFrame): The original FAIReMetadata dataframe
        output_df (pd.DataFrame): The output BioSample metadata dataframe
        mapping (dict): The column mapping dictionary
        config (dict): Configuration dictionary for saving user choices
    
    Returns:
        pd.DataFrame: Updated output dataframe with units added to numerical values
    """
    print("\n=== Processing numerical columns and their units ===")
    
    # Identify numerical columns in BioSampleMetadata that have corresponding columns in FAIReMetadata
    numerical_columns_to_process = []
    
    for mimarks_col, (sample_col, _) in mapping.items():
        if mimarks_col in NON_MEASUREMENT_MIMARKS_COLUMNS:
            continue
        if isinstance(sample_col, tuple):
            continue
        if sample_col in NON_MEASUREMENT_FAIRE_COLUMNS:
            continue
        if sample_col and sample_col in sample_df.columns:
            if is_numerical_column(sample_df, sample_col):
                numerical_columns_to_process.append((mimarks_col, sample_col))
    
    if not numerical_columns_to_process:
        print("No numerical columns found to process.")
        return output_df
    
    print(f"Found {len(numerical_columns_to_process)} numerical columns to process:")
    for mimarks_col, sample_col in numerical_columns_to_process:
        print(f"  {mimarks_col} <- {sample_col}")
    
    # Process each numerical column
    for mimarks_col, sample_col in numerical_columns_to_process:
        print(f"\nProcessing: {mimarks_col} (from {sample_col})")
        
        # Find corresponding unit column
        unit_column, unit_value = find_unit_column(sample_df, sample_col)
        
        if unit_column and unit_value:
            print(f"  Found unit column: {unit_column} = {unit_value}")
            
            # Add units to numerical values
            for i, value in enumerate(output_df[mimarks_col]):
                if pd.notna(value) and str(value).strip() and str(value) != 'not collected':
                    try:
                        # Check if value is already numeric
                        float(str(value))
                        # Add unit to the value
                        output_df.at[i, mimarks_col] = f"{value} {unit_value}"
                    except ValueError:
                        # Value is not numeric, leave as is
                        continue
        else:
            print(f"  No unit column found for {sample_col}")
            
            # Ask user for unit
            unit_input = get_config_value(
                config,
                f'unit_for_{sample_col}',
                input,
                f"  Enter unit for {sample_col} (or press Enter to skip): ",
                use_config_file,
                f"  Enter unit for {sample_col} (or press Enter to skip): "
            ).strip()
            
            if not unit_input:
                print(f"  Skipping unit addition for {sample_col}")
            else:
                # Validate unit input - allow common unit characters including spaces, parentheses, superscripts, and Greek letters
                if re.match(r'^[a-zA-Z0-9/%°\s()²³⁻¹⁻²⁻³µαβγδεθλπσφω]+$', unit_input):
                    print(f"  Adding unit '{unit_input}' to {sample_col}")
                    
                    # Add units to numerical values
                    for i, value in enumerate(output_df[mimarks_col]):
                        if pd.notna(value) and str(value).strip() and str(value) != 'not collected':
                            try:
                                # Check if value is already numeric
                                float(str(value))
                                # Add unit to the value
                                output_df.at[i, mimarks_col] = f"{value} {unit_input}"
                            except ValueError:
                                # Value is not numeric, leave as is
                                continue
                else:
                    print("  Invalid unit format. Please use only letters, numbers, /, %, °, spaces, parentheses, superscripts, and Greek letters (e.g., mg/L, %, °C, m², mol/L, µm, α, β, γ)")
    
    print("=== Finished processing numerical columns and units ===\n")
    return output_df


def find_grouping_fields(df, exclude_columns=None):
    """
    Find fields in the dataframe that are suitable for grouping samples.
    These fields should have a reasonable number of unique values (not too many, not too few).
    
    Args:
        df (pd.DataFrame): The dataframe to check for grouping fields
        exclude_columns (list): List of column names to exclude from checking
    
    Returns:
        list: List of column names that are suitable for grouping
    """
    if exclude_columns is None:
        exclude_columns = []
    
    # Find columns that exist in the dataframe
    existing_exclude_cols = [col for col in exclude_columns if col in df.columns]
    
    grouping_fields = []
    total_samples = len(df)
    
    for col in df.columns:
        if col in existing_exclude_cols:
            continue
        
        # Get non-null values from the column
        values = df[col].dropna()
        if len(values) == 0:
            continue
        
        # Convert all values to strings for consistent comparison
        str_values = [str(v).strip() for v in values if str(v).strip() != '']
        
        if len(str_values) == 0:
            continue
        
        # Check uniqueness characteristics
        unique_values = set(str_values)
        total_values = len(str_values)
        unique_count = len(unique_values)
        
        # Calculate uniqueness ratio
        uniqueness_ratio = unique_count / total_values if total_values > 0 else 0
        
        # A field is suitable for grouping if:
        # 1. It has at least 2 unique values (for grouping to make sense)
        # 2. It has no more than 20 unique values (not too many different values)
        # 3. It has at least 50% coverage (not too many missing values)
        coverage_ratio = total_values / total_samples if total_samples > 0 else 0
        
        if (unique_count >= 2 and 
            unique_count <= 20 and 
            coverage_ratio >= 0.5):
            grouping_fields.append((col, unique_count, total_values, uniqueness_ratio, coverage_ratio))
    
    # Sort by number of unique values (ascending) to show simpler groupings first
    grouping_fields.sort(key=lambda x: x[1])
    
    return grouping_fields


def find_unique_fields(df, exclude_columns=None):
    """
    Find fields in the dataframe that have unique values for each sample (no duplicates).
    These fields can help resolve duplicates in the output.
    
    This function works with any data type (text, numbers, dates, IDs, etc.) by converting
    all values to strings for comparison. It identifies fields that have enough unique
    values to distinguish between samples.
    
    Args:
        df (pd.DataFrame): The dataframe to check for unique fields
        exclude_columns (list): List of column names to exclude from checking
    
    Returns:
        list: List of column names that have unique values for each sample
    """
    if exclude_columns is None:
        exclude_columns = []  # Don't exclude any columns by default
    
    # Find columns that exist in the dataframe
    existing_exclude_cols = [col for col in exclude_columns if col in df.columns]
    
    unique_fields = []
    total_samples = len(df)
    
    for col in df.columns:
        if col in existing_exclude_cols:
            continue
        
        # Get non-null values from the column
        values = df[col].dropna()
        if len(values) == 0:
            continue
        
        # Convert all values to strings for consistent comparison (works with any data type)
        str_values = [str(v).strip() for v in values if str(v).strip() != '']
        
        if len(str_values) == 0:
            continue
        
        # Check if we have unique values for each sample
        unique_values = set(str_values)
        total_values = len(str_values)
        unique_count = len(unique_values)
        
        # Only include fields with 100% unique values (no duplicates at all)
        if unique_count == total_values and total_values > 0:
            unique_fields.append(col)
    
    return unique_fields


def check_duplicate_rows(df, exclude_columns=None):
    """
    Check for duplicate rows in the dataframe, excluding specified columns.
    
    Args:
        df (pd.DataFrame): The dataframe to check for duplicates
        exclude_columns (list): List of column names to exclude from duplicate checking
    
    Returns:
        tuple: (has_duplicates, duplicate_info) where duplicate_info contains details about duplicates
    """
    if exclude_columns is None:
        exclude_columns = ['*sample_name', 'sample_title', 'description']
    
    # Find columns that exist in the dataframe
    existing_exclude_cols = [col for col in exclude_columns if col in df.columns]
    
    # Create a copy of the dataframe without the excluded columns
    df_check = df.drop(columns=existing_exclude_cols, errors='ignore')
    
    # Get sample name column
    sample_name_col = '*sample_name' if '*sample_name' in df.columns else 'sample_name'
    
    # Use pandas duplicated() to find duplicate rows
    pandas_duplicates = df_check.duplicated(keep=False)
    pandas_duplicate_indices = pandas_duplicates[pandas_duplicates].index.tolist()
    
    # Create a mapping of row content to row indices using the duplicate rows
    content_to_indices = {}
    duplicate_groups = []
    
    for idx in pandas_duplicate_indices:
        # Create a normalized tuple of the row content (excluding the excluded columns)
        raw_values = df_check.iloc[idx].values
        normalized_values = []
        
        for val in raw_values:
            # Normalize NaN values
            if pd.isna(val):
                normalized_values.append('NAN')
            else:
                # Convert to string for consistent comparison
                normalized_values.append(str(val))
        
        row_content = tuple(normalized_values)
        if row_content not in content_to_indices:
            content_to_indices[row_content] = []
        content_to_indices[row_content].append(idx)
    
    # Create sample lists for groups with more than one row
    for row_content, indices in content_to_indices.items():
        if len(indices) > 1:  # Only include groups with more than one row
            # Replace row numbers with sample names
            sample_names = []
            for row_idx in indices:
                if sample_name_col in df.columns:
                    sample_name = df.iloc[row_idx][sample_name_col]
                    sample_name_str = str(sample_name) if pd.notna(sample_name) else 'N/A'
                    sample_names.append(sample_name_str)
                else:
                    sample_names.append(f"Row_{row_idx + 1}")
            
            sample_names.sort()  # Sort for consistent output
            duplicate_groups.append(sample_names)
    
    if duplicate_groups:
        duplicate_info = {
            'total_duplicate_rows': sum(len(group) for group in duplicate_groups),
            'duplicate_groups': duplicate_groups,
            'duplicate_indices': pandas_duplicate_indices,
            'excluded_columns': existing_exclude_cols,
            'duplicate_sample_lists': duplicate_groups
        }
        return True, duplicate_info
    else:
        return False, None


def format_lat_lon(lat, lon):
    """
    Format latitude and longitude values for BioSample metadata.
    
    Args:
        lat (float): Latitude value
        lon (float): Longitude value
    
    Returns:
        str: Formatted string like "25.574 N 84.843 W"
    """
    # Format latitude
    if lat < 0:
        lat_formatted = f"{abs(lat):.3f} S"
    else:
        lat_formatted = f"{lat:.3f} N"
    
    # Format longitude
    if lon < 0:
        lon_formatted = f"{abs(lon):.3f} W"
    else:
        lon_formatted = f"{lon:.3f} E"
    
    return f"{lat_formatted} {lon_formatted}"


def generate_sample_titles(output_df, sample_df, config, use_config_file):
    """
    Generate sample_title column values by concatenating values from selected columns.
    
    Args:
        output_df (pd.DataFrame): The output BioSample metadata DataFrame
        sample_df (pd.DataFrame): The input FAIReMetadata DataFrame
        config (dict): Configuration dictionary for saving user choices
    
    Returns:
        pd.DataFrame: Updated output DataFrame with sample_title values
    """
    print("\n" + "="*50)
    print("SAMPLE TITLE GENERATION")
    print("="*50)
    
    # sample_title column already exists in BioSample metadata
    sample_title_col = 'sample_title'
    print(f"Using sample_title column: {sample_title_col}")
    
    # Ask user if they want to add values in the sample_title column
    add_title_choice = get_config_value(
        config,
        'add_sample_title',
        get_valid_user_choice,
        "\nDo you want to add values in the sample_title column? [y/N]: ",
        use_config_file,
        "\nDo you want to add values in the sample_title column? [y/N]: ",
        ["y", "yes", "n", "no", ""],
        default="n"
    )
    
    if add_title_choice not in ("y", "yes"):
        print("Sample title column left blank.")
        return output_df
    
    # Ask if user wants to use default parameters
    default_choice = get_config_value(
        config,
        'use_default_sample_title_columns',
        get_valid_user_choice,
        "Do you want to use the default parameters from the script: *geo_loc_name, *organism, *sample_name? [Y/n]: ",
        use_config_file,
        "Do you want to use the default parameters from the script: *geo_loc_name, *organism, *sample_name? [Y/n]: ",
        ["y", "yes", "n", "no", ""],
        default="y"
    )
    
    if default_choice in ("n", "no"):
        # Show available columns
        print(f"\nAvailable columns in BioSampleMetadata:")
        for i, col in enumerate(output_df.columns, 1):
            print(f"  {i:2d}. {col}")
        
        # Get user's choice of columns
        print("\nEnter column numbers separated by commas (e.g., 1,3,5) or column names separated by commas:")
        user_input = get_config_value(
            config,
            'custom_sample_title_columns',
            input,
            "Columns to concatenate: ",
            use_config_file,
            "Columns to concatenate: "
        ).strip()
        
        # Parse user input
        selected_cols = []
        if user_input:
            for item in user_input.split(','):
                item = item.strip()
                if item.isdigit():
                    col_idx = int(item) - 1
                    if 0 <= col_idx < len(output_df.columns):
                        selected_cols.append(output_df.columns[col_idx])
                    else:
                        print(f"Warning: Invalid column number {item}")
                else:
                    if item in output_df.columns:
                        selected_cols.append(item)
                    else:
                        print(f"Warning: Column '{item}' not found")
            
            if not selected_cols:
                print("No valid columns selected. Using default columns.")
                selected_cols = ['*geo_loc_name', '*organism', '*sample_name']
    else:
        # Use default columns
        selected_cols = ['*geo_loc_name', '*organism', '*sample_name']
        print("Using default columns for sample_title generation.")
    
    print(f"\nColumns selected for sample_title: {', '.join(selected_cols)}")
    
    # Generate sample_title values
    sample_titles = []
    for i in range(len(output_df)):
        title_parts = []
        for col in selected_cols:
            if col in output_df.columns:
                value = str(output_df.iloc[i][col]) if pd.notna(output_df.iloc[i][col]) else ''
                if value and value.lower() != 'nan':
                    title_parts.append(value)
        
        if title_parts:
            sample_title = " ".join(title_parts)
        else:
            sample_title = "missing"
        
        sample_titles.append(sample_title)
    
    # Update the sample_title column
    output_df[sample_title_col] = sample_titles
    print(f"Generated sample_title values using columns: {', '.join(selected_cols)}")
    
    return output_df


def add_additional_columns(output_df, sample_df, mapping, config, use_config_file):
    """
    Identify and add additional columns from FAIReMetadata to BioSampleMetadata.
    
    Args:
        output_df (pd.DataFrame): The output BioSample metadata DataFrame
        sample_df (pd.DataFrame): The input FAIReMetadata DataFrame
        mapping (dict): The mapping dictionary used for column pairing
        config (dict): Configuration dictionary for saving user choices
    
    Returns:
        pd.DataFrame: Updated output DataFrame with additional columns
    """
    print("\n" + "="*50)
    print("ADDITIONAL COLUMNS FROM SAMPLE METADATA")
    print("="*50)
    
    # Get all columns from sample_df
    all_sample_cols = list(sample_df.columns)
    
    # Get columns that are already mapped/used
    used_cols = set()
    for mimarks_col, (sample_col, warn) in mapping.items():
        if isinstance(sample_col, str):
            used_cols.add(sample_col)
        elif isinstance(sample_col, tuple):
            # For tuple columns like lat_lon, add both source columns
            used_cols.update(sample_col)
    
    # Find unused columns that are not empty
    unused_cols = []
    for col in all_sample_cols:
        if col not in used_cols:
            # Check if column has any non-empty values
            non_empty_values = sample_df[col].dropna()
            non_empty_values = non_empty_values[non_empty_values.astype(str).str.strip() != '']
            if len(non_empty_values) > 0:
                unused_cols.append(col)
    
    if not unused_cols:
        print("No additional columns found to add.")
        return output_df
    
    print(f"Found {len(unused_cols)} additional columns from FAIReMetadata:")
    for i, col in enumerate(unused_cols, 1):
        # Show sample values for context
        sample_values = sample_df[col].dropna().head(3).tolist()
        sample_values = [str(v) for v in sample_values if str(v).strip() != '']
        sample_str = ", ".join(sample_values[:2])
        if len(sample_values) > 2:
            sample_str += f" (+{len(sample_values)-2} more)"
        print(f"  {i:2d}. {col} (e.g., {sample_str})")
    
    # Ask user if they want to add ALL columns
    add_choice = get_config_value(
        config,
        'add_all_additional_columns',
        get_valid_user_choice,
        f"\nDo you want to add ALL of these columns to BioSampleMetadata? [Y/n]: ",
        use_config_file,
        f"\nDo you want to add ALL of these columns to BioSampleMetadata? [Y/n]: ",
        ["y", "yes", "n", "no", ""],
        default="y"
    )
    
    if add_choice in ("n", "no"):
        # User wants to select which columns to exclude
        print(f"\nEnter column numbers separated by commas (e.g., 1,3,5) to EXCLUDE:")
        print("Or enter 'none' to exclude none (add all):")
        user_input = get_config_value(
            config,
            'excluded_additional_columns',
            input,
            "Columns to exclude: ",
            use_config_file,
            "Columns to exclude: "
        ).strip()
        
        if user_input.lower() == 'none':
            selected_cols = unused_cols
        else:
            # Parse user input for columns to exclude
            exclude_cols = []
            if user_input:
                for item in user_input.split(','):
                    item = item.strip()
                    if item.isdigit():
                        col_idx = int(item) - 1
                        if 0 <= col_idx < len(unused_cols):
                            exclude_cols.append(unused_cols[col_idx])
                        else:
                            print(f"Warning: Invalid column number {item}")
                    else:
                        print(f"Warning: '{item}' is not a valid column number")
            
            # Select all columns except excluded ones
            selected_cols = [col for col in unused_cols if col not in exclude_cols]
            
            if not selected_cols:
                print("All columns excluded. No additional columns added.")
                return output_df
    else:
        # User wants to add all columns
        selected_cols = unused_cols
    
    # Removed verbose column addition message
    
    # Add selected columns to output_df efficiently
    new_columns_data = {}
    
    for col in selected_cols:
        # Map sample names to get correct values
        if 'samp_name' in sample_df.columns and '*sample_name' in output_df.columns:
            # Create mapping from sample name to column value
            sample_to_value = {}
            for i, row in sample_df.iterrows():
                sample_name = str(row['samp_name']) if pd.notna(row['samp_name']) else ''
                col_value = str(row[col]) if pd.notna(row[col]) else ''
                if sample_name and col_value and col_value.lower() != 'nan':
                    sample_to_value[sample_name] = col_value
            
            # Map values to output_df using sample names
            col_values = []
            for sample_name in output_df['*sample_name']:
                sample_name_str = str(sample_name) if pd.notna(sample_name) else ''
                col_values.append(sample_to_value[sample_name_str] if sample_name_str in sample_to_value else '')
            
            new_columns_data[col] = col_values
        else:
            # Fallback: just copy the column as-is (assuming same order)
            if len(sample_df) == len(output_df):
                new_columns_data[col] = sample_df[col].fillna('')
            else:
                print(f"Warning: Could not map column '{col}' - different row counts")
                new_columns_data[col] = [''] * len(output_df)
    
    # Add all new columns at once to avoid fragmentation
    for col, values in new_columns_data.items():
        output_df[col] = values
    
    # Removed verbose success message
    
    return output_df


# experimentRunMetadata optional filter (after bioproject grouping); must match YAML keys
EXP_RUN_ASSOC_FILTER_QUESTION = (
    "Do you want to keep all samples in the BioSample output, or only samp_name values "
    "that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]: "
)


def _read_faire_sheet_df(faire_path, sheet_name, header=0, keep_default_na=True):
    """
    Read a FAIRe sheet from either:
      - full FAIRe workbook (.xlsx/.xls), selecting `sheet_name`
      - single exported sheet file (.tsv), where `sheet_name` is informational.
    Returns None on failure.
    """
    ext = os.path.splitext(str(faire_path))[1].lower()
    if ext == ".tsv":
        try:
            return pd.read_csv(
                faire_path,
                sep="\t",
                header=header,
                keep_default_na=keep_default_na,
            )
        except Exception:
            try:
                return pd.read_csv(
                    faire_path,
                    sep=None,
                    engine="python",
                    header=header,
                    keep_default_na=keep_default_na,
                )
            except Exception:
                return None

    _kw = dict(sheet_name=sheet_name, header=header, keep_default_na=keep_default_na)
    try:
        return pd.read_excel(faire_path, engine="openpyxl", **_kw)
    except Exception:
        try:
            return pd.read_excel(faire_path, engine="xlrd", **_kw)
        except Exception:
            try:
                return pd.read_excel(faire_path, **_kw)
            except Exception:
                return None


def _get_faire_sheet_source(args, sheet_name):
    """
    Return the path to use for a requested sheet:
      - specific sheet argument path when provided
      - otherwise --FAIReMetadata workbook path
    """
    key_map = {
        "sampleMetadata": "sampleMetadata",
        "projectMetadata": "projectMetadata",
        "experimentRunMetadata": "experimentRunMetadata",
    }
    specific_key = key_map.get(sheet_name)
    if specific_key:
        specific = getattr(args, specific_key, None)
        if specific:
            return specific
    return args.FAIReMetadata


def _read_experiment_run_metadata_df(faire_path):
    """
    Read experimentRunMetadata sheet (column headers on row 3). Returns None on failure.

    keep_default_na=False: pandas otherwise maps Excel text 'NA' / 'N/A' to float NaN,
    which would be misclassified as blank associatedSequences.
    """
    return _read_faire_sheet_df(
        faire_path,
        "experimentRunMetadata",
        header=2,
        keep_default_na=False,
    )


def _associated_sequences_is_blank(val):
    """
    True only for missing or empty associatedSequences cells.
    Literal 'NA' / 'N/A' (including after Excel import) are not blank.
    """
    if isinstance(val, str):
        st = val.strip()
        if st.upper() in ("NA", "N/A"):
            return False
    if pd.isna(val):
        return True
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return True
    if s.upper() in ("NA", "N/A"):
        return False
    return False


def apply_experiment_run_metadata_associated_sequences_filter(
    faire_path, sample_df, output_df, config, use_config_file, *, get_config_value_fn=None
):
    """
    Optionally restrict sample_df / output_df to samp_names for which every
    experimentRunMetadata row with that samp_name has blank (empty) associatedSequences.
    Literal 'NA' is not blank. Duplicate samp_name rows: all must be blank for the name to qualify.

    get_config_value_fn: optional callable (same signature as this module's get_config_value).
    Pass SRA's get_config_value when calling from FAIRe2SRA so prompts and YAML map to the SRA config.
    """
    gc = get_config_value_fn if get_config_value_fn is not None else get_config_value
    config.pop("_faire_erm_blank_only_rows_applied", None)
    print("\n" + "=" * 50)
    print("FILTER BY EXPERIMENT RUN METADATA (associatedSequences)")
    print("=" * 50)

    erm = _read_experiment_run_metadata_df(faire_path)
    if erm is None:
        print("Skipping: could not read experimentRunMetadata sheet from FAIRe workbook.")
        return sample_df, output_df
    if "samp_name" not in erm.columns or "associatedSequences" not in erm.columns:
        print(
            "Skipping: experimentRunMetadata must contain 'samp_name' and 'associatedSequences'."
        )
        return sample_df, output_df

    erm = erm.copy()
    erm["_sn"] = erm["samp_name"].map(
        lambda x: str(x).strip() if pd.notna(x) else ""
    )
    erm["_blank"] = erm["associatedSequences"].map(_associated_sequences_is_blank)
    # blank_only: a samp_name qualifies only if EVERY row with that name has blank
    # associatedSequences. Literal "NA" is not blank. Example: 3 duplicate rows with
    # (NA, NA, blank) -> not all blank -> this samp_name is excluded (samples removed).
    all_blank_per_name = erm.groupby("_sn", sort=False)["_blank"].all()
    keep_set = {
        n
        for n, every_blank in all_blank_per_name.items()
        if every_blank and n != "" and str(n).lower() != "nan"
    }

    if not keep_set:
        print(
            "No samp_name has only blank (empty) associatedSequences on every experimentRunMetadata "
            "row for that name; keeping all samples."
        )
        return sample_df, output_df

    print(
        "Note: 'blank' means empty/missing cells only; literal NA is not blank. "
        "Duplicate samp_name: every row must be blank — e.g. 3 rows with (NA, NA, blank) "
        "does not qualify; blank_only excludes that samp_name entirely."
    )

    choice = gc(
        config,
        "filter_experiment_run_blank_associatedSequences",
        get_valid_user_choice,
        EXP_RUN_ASSOC_FILTER_QUESTION,
        use_config_file,
        EXP_RUN_ASSOC_FILTER_QUESTION,
        ["all", "blank_only"],
        default="all",
    )
    if choice != "blank_only":
        print("Keeping all samples (no filter by experimentRunMetadata associatedSequences).")
        return sample_df, output_df

    if "samp_name" not in sample_df.columns:
        print("Skipping blank_only filter: sample_df has no 'samp_name' column.")
        return sample_df, output_df

    before_s = len(sample_df)
    before_o = len(output_df) if output_df is not None else 0
    sample_df = sample_df[
        sample_df["samp_name"].astype(str).str.strip().isin(keep_set)
    ].copy()
    sample_df = sample_df.reset_index(drop=True)
    valid = set(sample_df["samp_name"].astype(str).str.strip())

    if output_df is not None and len(output_df) > 0:
        if "*sample_name" in output_df.columns or "sample_name" in output_df.columns:
            sample_name_col = "*sample_name" if "*sample_name" in output_df.columns else "sample_name"
            output_df = output_df[
                output_df[sample_name_col].astype(str).str.strip().isin(valid)
            ].copy()
            output_df = output_df.reset_index(drop=True)
        elif "samp_name" in output_df.columns:
            output_df = output_df[
                output_df["samp_name"].astype(str).str.strip().isin(valid)
            ].copy()
            output_df = output_df.reset_index(drop=True)
        elif "library_ID" in output_df.columns and "lib_id" in sample_df.columns:
            valid_lib = set(sample_df["lib_id"].astype(str).str.strip())
            output_df = output_df[
                output_df["library_ID"].astype(str).str.strip().isin(valid_lib)
            ].copy()
            output_df = output_df.reset_index(drop=True)
        else:
            print(
                "Warning: output_df could not be aligned to filtered sample_df "
                "(expected *sample_name/sample_name, samp_name, or library_ID + lib_id)."
            )
    # len(output_df)==0: e.g. SRA before rows are built — only sample_df is filtered

    after_o = len(output_df) if output_df is not None else 0
    print(
        f"Kept only samp_name where all experimentRunMetadata rows for that name have blank "
        f"associatedSequences (literal NA excluded): "
        f"{before_s} -> {len(sample_df)} samples, {before_o} -> {after_o} output rows."
    )
    config["_faire_erm_blank_only_rows_applied"] = True
    return sample_df, output_df


def biosample_mode(args):
    """
    BioSample mode: Convert FAIRe metadata to BioSample MIMARKS format.
    
    Args:
        args: Parsed command line arguments
    """
    # Suppress pandas PerformanceWarning
    warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)
    
    print("\n" + "="*60)
    print("FAIRE2NCBI - BIOSAMPLE MODE")
    print("="*60)

    try:
        original_template = getattr(args, 'BioSample_Template', None)
        args.BioSample_Template = resolve_input_path(
            original_template,
            default=DEFAULT_BIOSAMPLE_TEMPLATE,
        )
        if original_template is None:
            print(f"Using bundled BioSample template: {args.BioSample_Template}")
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return
    
    # Initialize config and determine config file handling strategy
    config = {}
    use_config_file = False
    config_file_path = None
    is_template_config = False
    
    # Handle config file logic based on user input
    if args.config_file:
        # Check if the provided config file is the template
        is_template_file = is_config_template_file(args.config_file)
        
        if is_template_file:
            # User provided the template file, treat it as template usage
            print(f"Template file detected: {args.config_file}")
            print("Loading template configuration (template will NOT be modified)")
            template_config = load_config(args.config_file)
            if template_config:
                config = template_config.copy()
                # Generate new config file path based on BioSample metadata name
                config_file_path = get_config_file_path(args.BioSample_Metadata)
                
                # Check if the target config file already exists
                if os.path.exists(config_file_path) and not args.force:
                    overwrite_choice = get_config_value(
                        config,
                        'overwrite_custom_config',
                        get_valid_user_choice,
                        f"Configuration file '{config_file_path}' already exists. Do you want to overwrite it? [y/N]: ",
                        False,  # Don't use config file for this decision since we're creating it
                        f"Configuration file '{config_file_path}' already exists. Do you want to overwrite it? [y/N]: ",
                        ["y", "yes", "n", "no"],
                        default="n"
                    )
                    if overwrite_choice not in ("y", "yes"):
                        print("Aborted by user. No config file will be created.")
                        return
                    else:
                        print(f"Will overwrite existing config file: {config_file_path}")
                elif os.path.exists(config_file_path) and args.force:
                    print(f"Config file exists. Using --force flag: automatically overwriting {config_file_path}")
                
                use_config_file = True
                is_template_config = True
                print(f"Using template configuration. Will create new config file: {config_file_path}")
                print(f"Template file will remain unchanged: {args.config_file}")
                # Update command and timestamp
                config['command'] = ' '.join(sys.argv)
                config['date_time'] = datetime.now().isoformat()
                config['qa_pairs'] = []
                config['generated_files'] = []
            else:
                print("Could not load template. Proceeding with interactive questions.")
                config = {}
                # Generate config file path based on BioSample metadata name
                config_file_path = get_config_file_path(args.BioSample_Metadata)
        else:
            # User provided a custom config file (not template)
            if os.path.exists(args.config_file):
                provided_config = load_config(args.config_file)
                if provided_config:
                    config = provided_config
                    # For custom config files, update the same file (but create new path based on BioSample_Metadata for consistency)
                    config_file_path = get_config_file_path(args.BioSample_Metadata)
                    use_config_file = True
                    is_template_config = False
                    print(f"Using provided custom config file: {args.config_file}")
                    print(f"Configuration will be updated in: {config_file_path}")
                    # Update date_time but keep existing answers
                    config['date_time'] = datetime.now().isoformat()
                    print(f"Updated timestamp: {config['date_time']}")
                else:
                    print(f"Warning: Could not load config file {args.config_file}")
                    config = {}
                    # Generate config file path based on BioSample metadata name
                    config_file_path = get_config_file_path(args.BioSample_Metadata)
            else:
                print(f"Warning: Config file {args.config_file} not found")
                config = {}
                # Generate config file path based on BioSample metadata name
                config_file_path = get_config_file_path(args.BioSample_Metadata)
    else:
        config_source = prompt_config_source_choice()

        if config_source == 'previous':
            args.config_file = prompt_previous_config_path()
            provided_config = load_config(args.config_file)
            if provided_config:
                config = provided_config
                config_file_path = get_config_file_path(args.BioSample_Metadata)
                use_config_file = True
                is_template_config = False
                print(f"Using config file from previous run: {args.config_file}")
                print(f"Configuration will be updated in: {config_file_path}")
                config['date_time'] = datetime.now().isoformat()
                print(f"Updated timestamp: {config['date_time']}")
            else:
                print(f"Warning: Could not load config file {args.config_file}")
                config = {}
                config_file_path = get_config_file_path(args.BioSample_Metadata)
        elif config_source == 'template':
            # Load template configuration
            template_config = load_template_config()
            if template_config:
                config = template_config.copy()
                config_file_path = get_config_file_path(args.BioSample_Metadata)

                if os.path.exists(config_file_path) and not args.force:
                    overwrite_choice = get_valid_user_choice(
                        f"Custom config file already exists: {config_file_path}\nDo you want to overwrite it? [y/N]: ",
                        ["y", "yes", "n", "no"],
                        default="n"
                    )
                    if overwrite_choice not in ("y", "yes"):
                        print("Aborted by user. No config file will be created.")
                        return
                    print(f"Will overwrite existing config file: {config_file_path}")
                elif os.path.exists(config_file_path) and args.force:
                    print(f"Config file exists. Using --force flag: automatically overwriting {config_file_path}")

                use_config_file = True
                is_template_config = True
                print(f"Using template configuration. Will create new config file: {config_file_path}")
                config['command'] = ' '.join(sys.argv)
                config['date_time'] = datetime.now().isoformat()
                config['qa_pairs'] = []
                config['generated_files'] = []
            else:
                print("Could not load template. Proceeding with interactive questions.")
                config = {}
                config_file_path = get_config_file_path(args.BioSample_Metadata)
        else:
            print("Proceeding with interactive questions. Will create custom config file.")
            config = {}
            config_file_path = get_config_file_path(args.BioSample_Metadata)
    
    # Initialize with basic run info if not present
    if 'command' not in config:
        config['command'] = ' '.join(sys.argv)
        config['date_time'] = datetime.now().isoformat()
        config['qa_pairs'] = []
        config['generated_files'] = []
    
    # Check if output file exists and handle --force
    # If --config_file is provided, automatically overwrite without prompting
    if os.path.exists(args.BioSample_Metadata) and not args.force and not args.config_file:
        response = get_config_value(
            config,
            'overwrite_output_file',
            get_valid_user_choice,
            f"File '{args.BioSample_Metadata}' already exists. Overwrite? [y/N]: ",
            use_config_file,
            f"File '{args.BioSample_Metadata}' already exists. Overwrite? [y/N]: ",
            ["y", "yes", "n", "no"],
            default="n"
        )
        if response not in ('y', 'yes'):
            print('Aborted by user. No file overwritten.')
            return
    elif os.path.exists(args.BioSample_Metadata) and args.config_file and not args.force:
        print(f"Output file '{args.BioSample_Metadata}' exists. Using --config_file mode: automatically overwriting.")

    # Read sampleMetadata from full workbook (.xlsx) or a single sheet file (.tsv)
    sample_meta_src = _get_faire_sheet_source(args, "sampleMetadata")
    print(f"Reading sampleMetadata from: {sample_meta_src}")
    sample_df = _read_faire_sheet_df(sample_meta_src, "sampleMetadata", header=2)
    if sample_df is None:
        print(
            "Error: Could not read sampleMetadata. "
            "Provide --FAIReMetadata workbook or --sampleMetadata file."
        )
        return

    sample_cols = list(sample_df.columns)

    # Read MIMARKS template header from the 12th line (index 11)
    print(f"Reading BioSample template from: {args.BioSample_Template}")
    try:
        with open(args.BioSample_Template, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if len(lines) < 12:
            print(f"Error: Template file must have at least 12 lines. Found {len(lines)} lines.")
            return
            
        mimarks_columns = lines[11].strip().split('\t')
    except FileNotFoundError:
        print(f"Error: Template file '{args.BioSample_Template}' not found.")
        return
    except Exception as e:
        print(f"Error reading template file: {e}")
        return

    print("\n" + "="*50)
    print("PAIRING BioSampleMetadata and FAIReMetadata")
    print("="*50)
    
    # Hardcoded mapping based on actual fuzzy pairing results from previous runs
    # This replaces the fuzzy matching algorithm with deterministic field pairing
    hardcoded_mapping = {
        '*sample_name': 'samp_name',
        'sample_title': None,
        'bioproject_accession': None,
        '*organism': 'organism',
        '*collection_date': 'eventDate',
        '*depth': 'maximumDepthInMeters',
        '*env_broad_scale': 'env_broad_scale',
        '*env_local_scale': 'env_local_scale',
        '*env_medium': 'env_medium',
        '*geo_loc_name': 'geo_loc_name',
        '*lat_lon': ('decimalLatitude', 'decimalLongitude'),
        'alkalinity': 'tot_alkalinity',
        'alkalinity_method': None,
        'alkyl_diethers': None,
        'altitude': None,
        'aminopept_act': None,
        'ammonium': 'ammonium',
        'atmospheric_data': None,
        'bac_prod': None,
        'bac_resp': None,
        'bacteria_carb_prod': None,
        'biomass': None,
        'bishomohopanol': None,
        'bromide': None,
        'calcium': None,
        'carb_nitro_ratio': None,
        'chem_administration': None,
        'chloride': None,
        'chlorophyll': 'chlorophyll',
        'collection_method': 'samp_collect_method',
        'conduc': None,
        'density': None,
        'diether_lipids': None,
        'diss_carb_dioxide': None,
        'diss_hydrogen': None,
        'diss_inorg_carb': 'diss_inorg_carb',
        'diss_inorg_nitro': 'diss_inorg_nitro',
        'diss_inorg_phosp': None,
        'diss_org_carb': 'diss_org_carb',
        'diss_org_nitro': 'diss_org_nitro',
        'diss_oxygen': 'diss_oxygen',
        'down_par': None,
        'elev': 'elev',
        'fluor': None,
        'glucosidase_act': None,
        'isolation_source': None,
        'light_intensity': 'light_intensity',
        'magnesium': None,
        'mean_frict_vel': None,
        'mean_peak_frict_vel': None,
        'misc_param': None,
        'n_alkanes': None,
        'neg_cont_type': 'neg_cont_type',
        'nitrate': 'nitrate',
        'nitrite': 'nitrite',
        'nitro': 'nitro',
        'omics_observ_id': None,
        'org_carb': 'org_carb',
        'org_matter': 'org_matter',
        'org_nitro': 'org_nitro',
        'organism_count': None,
        'oxy_stat_samp': None,
        'part_org_carb': 'part_org_carb',
        'part_org_nitro': 'part_org_nitro',
        'perturbation': None,
        'petroleum_hydrocarb': None,
        'ph': 'ph',
        'phaeopigments': None,
        'phosphate': 'phosphate',
        'phosplipid_fatt_acid': None,
        'photon_flux': None,
        'pos_cont_type': 'pos_cont_type',
        'potassium': None,
        'pressure': 'pressure',
        'primary_prod': None,
        'redox_potential': None,
        'rel_to_oxygen': None,
        'salinity': 'salinity',
        'samp_collect_device': 'samp_collect_device',
        'samp_mat_process': 'samp_mat_process',
        'samp_size': 'samp_size',
        'samp_store_dur': 'samp_store_dur',
        'samp_store_loc': 'samp_store_loc',
        'samp_store_temp': 'samp_store_temp',
        'samp_vol_we_dna_ext': 'samp_vol_we_dna_ext',
        'silicate': 'silicate',
        'size_frac': 'size_frac',
        'size_frac_low': 'size_frac_low',
        'size_frac_up': None,
        'sodium': None,
        'soluble_react_phosp': None,
        'source_material_id': None,
        'sulfate': None,
        'sulfide': None,
        'suspend_part_matter': 'suspend_part_matter',
        'temp': 'temp',
        'tidal_stage': 'tidal_stage',
        'tot_depth_water_col': 'tot_depth_water_col',
        'tot_diss_nitro': 'tot_diss_nitro',
        'tot_inorg_nitro': 'tot_inorg_nitro',
        'tot_nitro': 'tot_nitro',
        'tot_part_carb': 'tot_part_carb',
        'tot_phosp': None,
        'turbidity': 'turbidity',
        'water_current': 'water_current',
        'description': None
    }
    
    # Create mapping dictionary and output columns list
    mapping = {}
    output_columns = []
    assigned_sample_cols = set()

    # Apply hardcoded mapping
    for mimarks_col in mimarks_columns:
        if mimarks_col in hardcoded_mapping:
            sample_col = hardcoded_mapping[mimarks_col]
            if sample_col is not None:
                # Check if the sample column exists in the dataframe
                if isinstance(sample_col, str) and sample_col in sample_df.columns:
                    mapping[mimarks_col] = (sample_col, None)
                    assigned_sample_cols.add(sample_col)
                elif isinstance(sample_col, tuple) and all(col in sample_df.columns for col in sample_col):
                    # Handle tuple columns like lat_lon
                    mapping[mimarks_col] = (sample_col, None)
                    assigned_sample_cols.update(sample_col)
                else:
                    # Column not found in dataframe, set to None
                    mapping[mimarks_col] = (None, None)
            else:
                # Column mapped to None (like sample_title), set to None
                mapping[mimarks_col] = (None, None)
        else:
            # Column not in hardcoded mapping, set to None
            mapping[mimarks_col] = (None, None)

    # Handle bioproject_accession if provided as argument
    if args.bioproject_accession is not None:
        for mimarks_col in mimarks_columns:
            if is_bioproject_accession_column(mimarks_col):
                mapping[mimarks_col] = ('bioproject_accession', None)
                break

    print('Final column mapping:')
    for k, (v, warn) in mapping.items():
        print(f"{k:30} --> {v}")

    final_columns = []
    for mimarks_col in mimarks_columns:
        sample_col, warn = mapping[mimarks_col]
        # Never add WARNING_ for bioproject_accession
        if warn == 'WARNING' and not is_bioproject_accession_column(mimarks_col):
            final_columns.append(f'WARNING_{mimarks_col}')
        else:
            final_columns.append(mimarks_col)

    output_df = pd.DataFrame(columns=final_columns)

    for mimarks_col, out_col in zip(mimarks_columns, final_columns):
        sample_col, warn = mapping[mimarks_col]
        if mimarks_col == '*lat_lon' and isinstance(sample_col, tuple):
            lat_vals = sample_df['decimalLatitude'] if 'decimalLatitude' in sample_df.columns else pd.Series(['']*len(sample_df))
            lon_vals = sample_df['decimalLongitude'] if 'decimalLongitude' in sample_df.columns else pd.Series(['']*len(sample_df))
            combined = []
            for lat, lon in zip(lat_vals, lon_vals):
                lat_str = str(lat).strip()
                lon_str = str(lon).strip()
                # 1. If both are empty
                if not lat_str and not lon_str:
                    combined.append('')
                # 2. If both are non-numeric and identical
                elif lat_str and lon_str and lat_str == lon_str:
                    try:
                        float(lat_str)
                        float(lon_str)
                        combined.append(f"{lat_str} {lon_str}")
                    except Exception:
                        combined.append(lat_str)
                # 3. If both are numeric
                else:
                    try:
                        lat_f = float(lat_str)
                        lon_f = float(lon_str)
                        # Use the format_lat_lon function to format properly
                        combined.append(format_lat_lon(lat_f, lon_f))
                    except Exception:
                        combined.append('')
            output_df[out_col] = combined
        elif sample_col and isinstance(sample_col, str) and sample_col in sample_df.columns:
            # Handle NaN values properly - leave them blank
            col_values = sample_df[sample_col].fillna('')
            # Also replace any string 'nan' values with blank
            col_values = col_values.replace('nan', '')
            output_df[out_col] = col_values
        else:
            output_df[out_col] = ''

    # Overwrite bioproject_accession column if argument is provided
    if args.bioproject_accession is not None:
        for col in output_df.columns:
            if is_bioproject_accession_column(col):
                output_df[col] = args.bioproject_accession
        # Also, rename any such column to 'bioproject_accession' (remove WARNING_ prefix)
        new_columns = []
        for col in output_df.columns:
            norm_col = col.replace('_', '').replace('*', '').lower()
            if norm_col.startswith('warning') and is_bioproject_accession_column(norm_col[len('warning'):]):
                new_columns.append('bioproject_accession')
            else:
                new_columns.append(col)
        output_df.columns = new_columns
    else:
        # Interactive logic for bioproject_accession if not provided
        print("\n" + "="*50)
        print("BIOPROJECT ACCESSION HANDLING")
        print("="*50)
        bioproject_col = None
        for col in output_df.columns:
            if is_bioproject_accession_column(col):
                bioproject_col = col
                break
        if bioproject_col is not None:
            response = get_config_value(
                config, 
                'bioproject_manual_entry',
                get_valid_user_choice,
                "No bioproject_accession provided. Do you want to enter values manually? [y/N]: ",
                use_config_file,
                "No bioproject_accession provided. Do you want to enter values manually? [y/N]: ",
                ["y", "yes", "n", "no"],
                default="n"
            )
            if response in ("y", "yes"):
                same_for_all = get_config_value(
                    config,
                    'bioproject_same_for_all',
                    get_valid_user_choice,
                    "Do you want to enter the same value for all samples? [y/N]: ",
                    use_config_file,
                    "Do you want to enter the same value for all samples? [y/N]: ",
                    ["y", "yes", "n", "no"],
                    default="n"
                )
                if same_for_all in ("y", "yes"):
                    value = get_config_value(
                        config,
                        'bioproject_single_value',
                        input,
                        "Enter the value to use for all samples: ",
                        use_config_file,
                        "Enter the value to use for all samples: "
                    ).strip()
                    output_df[bioproject_col] = value
                else:
                    # Find suitable grouping fields in FAIReMetadata
                    print("\n" + "="*50)
                    print("FINDING SUITABLE GROUPING FIELDS")
                    print("="*50)
                    
                    grouping_fields = find_grouping_fields(sample_df)
                    
                    if grouping_fields:
                        print(f"\nFound {len(grouping_fields)} fields suitable for grouping samples:")
                        for i, (col, unique_count, total_values, uniqueness_ratio, coverage_ratio) in enumerate(grouping_fields, 1):
                            print(f"  {i:2d}. {col} ({unique_count} unique values)")
                        
                        # Let user select a grouping field
                        def get_grouping_field_choice():
                            while True:
                                try:
                                    field_choice = input(f"\nEnter field number (1-{len(grouping_fields)}) or field name to group samples: ").strip()
                                    
                                    # Try to parse as number first
                                    if field_choice.isdigit():
                                        field_idx = int(field_choice) - 1
                                        if 0 <= field_idx < len(grouping_fields):
                                            return grouping_fields[field_idx][0]
                                        else:
                                            print(f"Invalid field number. Please enter a number between 1 and {len(grouping_fields)}")
                                    else:
                                        # Try to find field by name
                                        for col, _, _, _, _ in grouping_fields:
                                            if col == field_choice:
                                                return col
                                        print(f"Field '{field_choice}' not found in grouping fields list. Please enter a valid field name or number.")
                                except ValueError:
                                    print("Invalid input. Please enter a valid field number or name.")
                        
                        selected_field = get_config_value(
                            config,
                            'bioproject_grouping_field',
                            get_grouping_field_choice,
                            f"Enter field number (1-{len(grouping_fields)}) or field name to group samples: ",
                            use_config_file
                        )
                        
                        print(f"Selected grouping field: {selected_field}")
                        
                        # Show unique values in the selected field
                        unique_values = sample_df[selected_field].dropna().unique()
                        unique_values = [str(v).strip() for v in unique_values if str(v).strip() != '']
                        unique_values.sort()
                        
                        print(f"\nUnique values in '{selected_field}':")
                        for i, value in enumerate(unique_values, 1):
                            print(f"  {i:2d}. {value}")
                        
                        # Ask user if they want to use all values or only some
                        use_all_choice = get_config_value(
                            config,
                            f'bioproject_use_all_values_{selected_field}',
                            get_valid_user_choice,
                            f"\nDo you want to use all {len(unique_values)} values in '{selected_field}', or only specific ones? [all/specific]: ",
                            use_config_file,
                            f"\nDo you want to use all {len(unique_values)} values in '{selected_field}', or only specific ones? [all/specific]: ",
                            ["all", "specific"],
                            default="all"
                        )
                        
                        # Filter unique_values based on user choice
                        selected_values = unique_values
                        if use_all_choice == "specific":
                            # Check if we have saved selected values in config
                            config_selected_key = f'bioproject_selected_values_{selected_field}'
                            saved_selected_values = None
                            
                            if use_config_file and config_selected_key in config:
                                # Try to restore from config
                                saved_vals = config[config_selected_key]
                                if isinstance(saved_vals, list):
                                    # Filter to only include values that still exist
                                    saved_selected_values = [v for v in saved_vals if v in unique_values]
                                    if saved_selected_values:
                                        print(f"Using saved selected values: {', '.join(saved_selected_values)}")
                                        selected_values = saved_selected_values
                            
                            if not saved_selected_values:
                                sel_q = (
                                    f"Selected values for field '{selected_field}' "
                                    f"(numbers separated by commas): "
                                )

                                def prompt_selected_value_indices():
                                    while True:
                                        try:
                                            user_input = input(sel_q).strip()
                                            if not user_input:
                                                print("No values selected. Using all values.")
                                                return ""
                                            selected_indices = []
                                            for item in user_input.split(","):
                                                item = item.strip()
                                                if item.isdigit():
                                                    idx = int(item) - 1
                                                    if 0 <= idx < len(unique_values):
                                                        selected_indices.append(idx)
                                                    else:
                                                        print(f"Warning: Invalid value number {item}")
                                                else:
                                                    print(f"Warning: '{item}' is not a valid number")
                                            if selected_indices:
                                                selected_vals = [unique_values[i] for i in selected_indices]
                                                print(f"Selected values: {', '.join(selected_vals)}")
                                                return user_input
                                            print("No valid values selected. Please try again.")
                                        except ValueError:
                                            print("Invalid input. Please enter valid numbers separated by commas.")

                                raw_sel = get_config_value(
                                    config,
                                    f"bioproject_selected_indices_{selected_field}",
                                    prompt_selected_value_indices,
                                    sel_q,
                                    use_config_file,
                                )
                                if raw_sel == "" or raw_sel is None:
                                    selected_values = list(unique_values)
                                else:
                                    sel_str = raw_sel if isinstance(raw_sel, str) else str(raw_sel)
                                    idx_list = []
                                    for item in sel_str.split(","):
                                        item = item.strip()
                                        if item.isdigit():
                                            idx = int(item) - 1
                                            if 0 <= idx < len(unique_values):
                                                idx_list.append(idx)
                                    selected_values = (
                                        [unique_values[i] for i in idx_list] if idx_list else list(unique_values)
                                    )

                                # Save selected values to config (runtime key for this run; structured YAML via get_config_value / add_qa)
                                if use_config_file:
                                    config[config_selected_key] = selected_values
                        else:
                            print(f"Using all {len(unique_values)} values.")
                        
                        # If specific values were selected, filter samples to only include those matching selected values
                        if use_all_choice == "specific" and selected_values != unique_values:
                            print(f"\nFiltering samples to only include those with '{selected_field}' in: {', '.join(selected_values)}")
                            
                            # Filter sample_df to only include rows where selected_field matches one of selected_values
                            original_sample_count = len(sample_df)
                            sample_df = sample_df[sample_df[selected_field].astype(str).str.strip().isin(selected_values)].copy()
                            sample_df = sample_df.reset_index(drop=True)  # Reset index after filtering
                            filtered_sample_count = len(sample_df)
                            print(f"Filtered from {original_sample_count} to {filtered_sample_count} samples.")
                            
                            # Filter output_df to only include rows corresponding to filtered samples
                            sample_name_col = '*sample_name' if '*sample_name' in output_df.columns else 'sample_name'
                            if sample_name_col in output_df.columns and 'samp_name' in sample_df.columns:
                                # Get list of sample names that should be kept
                                valid_sample_names = set(sample_df['samp_name'].astype(str).str.strip())
                                
                                # Filter output_df
                                original_output_count = len(output_df)
                                output_df = output_df[output_df[sample_name_col].astype(str).str.strip().isin(valid_sample_names)].copy()
                                output_df = output_df.reset_index(drop=True)  # Reset index after filtering
                                filtered_output_count = len(output_df)
                                print(f"Filtered output from {original_output_count} to {filtered_output_count} rows.")
                            else:
                                print("Warning: Could not filter output_df - sample name columns not found.")
                        
                        # Get bioproject accession for each selected value
                        value_to_bioproject = {}
                        config_key = f'bioproject_values_{selected_field}'
                        
                        if config_key in config:
                            # Use saved values, but only for selected values
                            saved_values = config[config_key]
                            value_to_bioproject = {val: saved_values.get(val, '') for val in selected_values}
                            print(f"Using saved bioproject values for field '{selected_field}'")
                        else:
                            # Get values from user
                            for value in selected_values:
                                def get_bioproject_input():
                                    while True:
                                        bioproject_val = input(f"Enter bioproject_accession for '{selected_field}' = '{value}': ").strip()
                                        if bioproject_val:
                                            return bioproject_val
                                        else:
                                            print("Bioproject accession cannot be empty. Please enter a value.")
                                
                                bioproject_val = get_config_value(
                                    config,
                                    f'bioproject_value_{selected_field}_{value}',
                                    get_bioproject_input,
                                    f"Enter bioproject_accession for '{selected_field}' = '{value}': ",
                                    use_config_file
                                )
                                value_to_bioproject[value] = bioproject_val
                            
                            # Save the values to config
                            config[config_key] = value_to_bioproject
                        
                        # Map sample names to bioproject accession values
                        sample_name_col = '*sample_name' if '*sample_name' in output_df.columns else 'sample_name'
                        if sample_name_col in output_df.columns and 'samp_name' in sample_df.columns:
                            # Create mapping from sample names to selected field values
                            sample_to_field_value = {}
                            for i, row in sample_df.iterrows():
                                field_value = str(row[selected_field]).strip() if pd.notna(row[selected_field]) else ''
                                if field_value and field_value in value_to_bioproject:
                                    sample_to_field_value[str(row['samp_name'])] = field_value
                            
                            # Assign bioproject_accession for each sample in output_df
                            bioproject_values = []
                            for sname in output_df[sample_name_col]:
                                field_value = sample_to_field_value.get(str(sname), '')
                                bioproject_val = value_to_bioproject.get(field_value, '')
                                bioproject_values.append(bioproject_val)
                            
                            output_df[bioproject_col] = bioproject_values
                            print(f"Successfully assigned bioproject_accession values based on '{selected_field}' grouping.")
                            sample_df, output_df = (
                                apply_experiment_run_metadata_associated_sequences_filter(
                                    _get_faire_sheet_source(args, "experimentRunMetadata"),
                                    sample_df,
                                    output_df,
                                    config,
                                    use_config_file,
                                )
                            )
                            config.pop("_faire_erm_blank_only_rows_applied", None)
                        else:
                            print("Could not find sample name columns for mapping. bioproject_accession will remain blank.")
                    else:
                        print("No suitable grouping fields found in FAIReMetadata. bioproject_accession will remain blank.")
            else:
                print("bioproject_accession will remain blank.")

    # Check for empty mandatory columns (those starting with '*')
    mandatory_warnings = []
    for col in output_df.columns:
        if col.startswith('*'):
            if output_df[col].replace('', pd.NA).isna().all():
                mandatory_warnings.append(col)
    if mandatory_warnings:
        print("\n# Fields with an asterisk (*) are mandatory. Your submission will fail if any mandatory fields are not completed. If information is unavailable for any mandatory field, please enter 'not collected', 'not applicable' or 'missing' as appropriate.")
        print("\033[91mThe following mandatory columns are empty in your output:")
        for col in mandatory_warnings:
            print(f"  {col}")
        print("\033[0m")
        # Prompt user for each empty mandatory column
        for col in mandatory_warnings:
            config_key = f'mandatory_field_{col}'
            fill_value = get_config_value(
                config,
                config_key,
                input,
                f"Column '{col}' is empty. Do you want to fill it with 'not collected', 'not applicable', or 'missing'? (Or enter any other value, or leave blank to skip): ",
                use_config_file,
                f"Column '{col}' is empty. Do you want to fill it with 'not collected', 'not applicable', or 'missing'? (Or enter any other value, or leave blank to skip): "
            ).strip()
            if fill_value:
                output_df[col] = fill_value

    # Only fill 'not collected' for mandatory fields (columns starting with '*')
    for col in output_df.columns:
        if col.startswith('*'):
            output_df[col] = output_df[col].replace('', 'not collected')

    # Handle units for numerical columns
    print("\n" + "="*50)
    print("HANDLING NUMERICAL COLUMNS WITH UNITS")
    print("="*50)
    
    output_df = handle_numerical_columns_with_units(sample_df, output_df, mapping, config, use_config_file)
    
    # Check for duplicate rows before writing the output file
    print("\n" + "="*50)
    print("DUPLICATE ROW CHECKING")
    print("="*50)
    
    has_duplicates, duplicate_info = check_duplicate_rows(output_df)
    if has_duplicates:
        print(f"\n# Duplicate rows detected in the output file (excluding columns: {', '.join(duplicate_info['excluded_columns'])}).")
        print(f"Total duplicate rows: {duplicate_info['total_duplicate_rows']}")
        print("\nSample names for all duplicate rows:")
        if 'duplicate_sample_lists' in duplicate_info and duplicate_info['duplicate_sample_lists']:
            # Display grouped duplicates using the lists from check_duplicate_rows
            for group_num, sample_list in enumerate(duplicate_info['duplicate_sample_lists'], 1):
                print(f"  Group {group_num}: [{', '.join(sample_list)}]")
        else:
            # Fallback: show individual duplicate rows
            sample_name_col = '*sample_name' if '*sample_name' in output_df.columns else 'sample_name'
            if sample_name_col in output_df.columns:
                print("  Individual duplicate rows:")
                # Sort by row index for better readability
                sorted_indices = sorted(duplicate_info['duplicate_indices'])
                for idx in sorted_indices:
                    sample_name = output_df.iloc[idx][sample_name_col]
                    sample_name_str = str(sample_name) if pd.notna(sample_name) else 'N/A'
                    print(f"    Row {idx + 1}: {sample_name_str}")
            else:
                print("  No sample name column found in output dataframe")
        print("\033[91mPlease review and resolve these duplicates before submitting your file.\033[0m")
        
        # First, check for fields in FAIReMetadata that have only unique values
        print("\n" + "="*50)
        print("ANALYZING UNIQUE FIELDS IN SAMPLE METADATA")
        print("="*50)
        
        unique_fields = find_unique_fields(sample_df)
        
        if unique_fields:
            print(f"\nFound {len(unique_fields)} fields with 100% unique values (no duplicates):")
            for i, col in enumerate(unique_fields, 1):
                # Show sample values for context
                sample_values = sample_df[col].dropna().head(3).tolist()
                sample_values = [str(v) for v in sample_values if str(v).strip() != '']
                sample_str = ", ".join(sample_values[:2])
                if len(sample_values) > 2:
                    sample_str += f" (+{len(sample_values)-2} more)"
                
                print(f"  {i:2d}. {col} (e.g., {sample_str})")
            
            # Ask user which field to use
            def get_unique_field_choice():
                while True:
                    try:
                        col_choice = input(f"\nEnter field number (1-{len(unique_fields)}) or field name to resolve duplicates: ").strip()
                        
                        # Try to parse as number first
                        if col_choice.isdigit():
                            col_idx = int(col_choice) - 1
                            if 0 <= col_idx < len(unique_fields):
                                return unique_fields[col_idx]
                            else:
                                print(f"Invalid field number. Please enter a number between 1 and {len(unique_fields)}")
                        else:
                            # Try to find field by name
                            if col_choice in unique_fields:
                                return col_choice
                            else:
                                print(f"Field '{col_choice}' not found in unique fields list. Please enter a valid field name or number.")
                    except ValueError:
                        print("Invalid input. Please enter a valid field number or name.")
            
            selected_col = get_config_value(
                config,
                'duplicate_resolution_field',
                get_unique_field_choice,
                f"\nEnter field number (1-{len(unique_fields)}) or field name to resolve duplicates: ",
                use_config_file
            )
            
            print(f"Selected field: {selected_col}")
            
            # Ask user if they want to rename the column
            rename_choice = get_config_value(
                config,
                f'rename_duplicate_field_{selected_col}',
                get_valid_user_choice,
                f"Do you want to rename the column from '{selected_col}'? [y/N]: ",
                use_config_file,
                f"Do you want to rename the column from '{selected_col}'? [y/N]: ",
                ["y", "yes", "n", "no", ""],
                default="n"
            )
            
            if rename_choice in ("y", "yes"):
                new_name_q = f"Enter new column name (or press Enter to keep '{selected_col}'): "
                new_col_name = get_config_value(
                    config,
                    f'duplicate_new_col_name_{selected_col}',
                    input,
                    new_name_q,
                    use_config_file,
                    new_name_q,
                ).strip()
                if not new_col_name:
                    new_col_name = selected_col
            else:
                new_col_name = selected_col
            
            # Add the column to output_df
            sample_name_col = '*sample_name' if '*sample_name' in output_df.columns else 'sample_name'
            if sample_name_col in output_df.columns and 'samp_name' in sample_df.columns:
                        # Create mapping from sample names to selected column values
                        sample_to_value = {}
                        for i, row in sample_df.iterrows():
                            sample_to_value[str(row['samp_name'])] = str(row[selected_col]) if pd.notna(row[selected_col]) else ''
                        
                        # Add new column to output_df
                        new_values = []
                        for sample_name in output_df[sample_name_col]:
                            value = sample_to_value.get(str(sample_name), '')
                            new_values.append(value)
                        
                        output_df[new_col_name] = new_values
                        print(f"Added column '{new_col_name}' with values from '{selected_col}'")
                        
                        # Re-check for duplicates
                        print("\nRe-checking for duplicates after adding new column...")
                        has_duplicates, duplicate_info = check_duplicate_rows(output_df)
                        if has_duplicates:
                            print(f"\n# Duplicate rows detected after adding column (excluding columns: {', '.join(duplicate_info['excluded_columns'])}).")
                            print(f"Total duplicate rows: {duplicate_info['total_duplicate_rows']}")
                            print("\nSample names for all duplicate rows:")
                            if 'duplicate_sample_lists' in duplicate_info and duplicate_info['duplicate_sample_lists']:
                                for group_num, sample_list in enumerate(duplicate_info['duplicate_sample_lists'], 1):
                                    print(f"  Group {group_num}: [{', '.join(sample_list)}]")
                            else:
                                print("  No duplicate groups found")
                        else:
                            print("No duplicates found after adding the new column!")
            else:
                print("Could not map sample names. Column not added.")
        else:
            # No unique fields found, show all available columns
            print(f"\nNo fields with 100% unique values found in FAIReMetadata.")
            print("Showing all available columns:")
            for i, col in enumerate(sample_df.columns, 1):
                print(f"  {i:2d}. {col}")
                
            def get_fallback_column_choice():
                while True:
                    try:
                        col_choice = input(
                            f"\nEnter column number (1-{len(sample_df.columns)}) or column name: "
                        ).strip()
                        if col_choice.isdigit():
                            col_idx = int(col_choice) - 1
                            if 0 <= col_idx < len(sample_df.columns):
                                return sample_df.columns[col_idx]
                            print(
                                f"Invalid column number. Please enter a number between 1 and {len(sample_df.columns)}"
                            )
                        elif col_choice in sample_df.columns:
                            return col_choice
                        print(f"Column '{col_choice}' not found. Please enter a valid column name or number.")
                    except ValueError:
                        print("Invalid input. Please enter a valid column number or name.")

            selected_col = get_config_value(
                config,
                'duplicate_fallback_column',
                get_fallback_column_choice,
                f"\nEnter column number (1-{len(sample_df.columns)}) or column name: ",
                use_config_file,
            )

            print(f"Selected column: {selected_col}")

            rename_choice = get_config_value(
                config,
                f'rename_duplicate_field_fallback_{selected_col}',
                get_valid_user_choice,
                f"Do you want to rename the column from '{selected_col}'? [y/N]: ",
                use_config_file,
                f"Do you want to rename the column from '{selected_col}'? [y/N]: ",
                ["y", "yes", "n", "no", ""],
                default="n",
            )

            if rename_choice in ("y", "yes"):
                new_name_q_fb = f"Enter new column name (or press Enter to keep '{selected_col}'): "
                new_col_name = get_config_value(
                    config,
                    f'duplicate_new_col_name_fallback_{selected_col}',
                    input,
                    new_name_q_fb,
                    use_config_file,
                    new_name_q_fb,
                ).strip()
                if not new_col_name:
                    new_col_name = selected_col
            else:
                new_col_name = selected_col
            
            # Add the column to output_df
            sample_name_col = '*sample_name' if '*sample_name' in output_df.columns else 'sample_name'
            if sample_name_col in output_df.columns and 'samp_name' in sample_df.columns:
                # Create mapping from sample names to selected column values
                sample_to_value = {}
                for i, row in sample_df.iterrows():
                    sample_to_value[str(row['samp_name'])] = str(row[selected_col]) if pd.notna(row[selected_col]) else ''
                
                # Add new column to output_df
                new_values = []
                for sample_name in output_df[sample_name_col]:
                    value = sample_to_value.get(str(sample_name), '')
                    new_values.append(value)
                
                output_df[new_col_name] = new_values
                print(f"Added column '{new_col_name}' with values from '{selected_col}'")
                
                # Re-check for duplicates
                print("\nRe-checking for duplicates after adding new column...")
                has_duplicates, duplicate_info = check_duplicate_rows(output_df)
                if has_duplicates:
                    print(f"\n# Duplicate rows detected after adding column (excluding columns: {', '.join(duplicate_info['excluded_columns'])}).")
                    print(f"Total duplicate rows: {duplicate_info['total_duplicate_rows']}")
                    print("\nSample names for all duplicate rows:")
                    if 'duplicate_sample_lists' in duplicate_info and duplicate_info['duplicate_sample_lists']:
                        for group_num, sample_list in enumerate(duplicate_info['duplicate_sample_lists'], 1):
                            print(f"  Group {group_num}: [{', '.join(sample_list)}]")
                    else:
                        print("  No duplicate groups found")
                else:
                    print("No duplicates found after adding the new column!")
            else:
                print("Could not map sample names. Column not added.")
        
        # Check if duplicates still exist after resolution attempt
        has_duplicates, duplicate_info = check_duplicate_rows(output_df)
        if has_duplicates:
            # Ask user if they want to add a column to resolve duplicates
            add_column_choice = get_config_value(
                config,
                'add_column_to_resolve_duplicates',
                get_valid_user_choice,
                "Do you want to add a column from FAIReMetadata to help resolve duplicates? [y/N]: ",
                use_config_file,
                "Do you want to add a column from FAIReMetadata to help resolve duplicates? [y/N]: ",
                ["y", "yes", "n", "no"],
                default="n"
            )
            
            if add_column_choice in ("y", "yes"):
                # User chose to add a column - this logic is handled above
                pass
            else:
                # User chose not to add a column, ask if they want to continue despite duplicates
                continue_response = get_config_value(
                        config,
                        'continue_despite_duplicates',
                        get_valid_user_choice,
                        "Do you want to continue writing the file despite duplicates? [y/N]: ",
                        use_config_file,
                        "Do you want to continue writing the file despite duplicates? [y/N]: ",
                        ["y", "yes", "n", "no"],
                        default="n"
                    )
                if continue_response not in ("y", "yes"):
                    print("Aborted by user. No file written.")
                    return
        else:
            # No duplicates found, continue normally
            print("No duplicates found. Continuing with file generation.")

    # Generate sample_title column
    output_df = generate_sample_titles(output_df, sample_df, config, use_config_file)

    # Add additional columns from FAIReMetadata
    output_df = add_additional_columns(output_df, sample_df, mapping, config, use_config_file)
    
    # Write output TSV with header and comments (write all lines before the header line)
    print("\n" + "="*50)
    print("WRITING OUTPUT FILE")
    print("="*50)
    
    print(f"Output file path: {os.path.abspath(args.BioSample_Metadata)}")
    try:
        with open(args.BioSample_Metadata, 'w', encoding='utf-8') as out_f:
            for i in range(11):  # Write comment lines (lines 0-10)
                out_f.write(lines[i])
            # Write header and data
            output_df.to_csv(out_f, sep='\t', index=False)
        print(f"Successfully wrote BioSample metadata to: {args.BioSample_Metadata}")
        # Track the generated BioSample metadata file
        add_generated_file(config, args.BioSample_Metadata, "BioSample metadata file")
    except Exception as e:
        print(f"Error writing output file: {e}")
        return
    
    # Save configuration file
    if config_file_path:
        # Update timestamp before saving
        config['date_time'] = datetime.now().isoformat()
        
        if use_config_file and args.config_file and not is_template_config:
            # When using existing custom config file, update it (not the original template)
            save_config(config, config_file_path)
            print(f"Updated configuration file: {config_file_path}")
            print(f"Final timestamp: {config['date_time']}")
            # Track the generated configuration file
            add_generated_file(config, config_file_path, "Updated configuration file with Q&A pairs")
        elif use_config_file and is_template_config:
            # When using template, ALWAYS create new config file (NEVER overwrite template)
            save_config(config, config_file_path)
            print(f"Created new configuration file from template: {config_file_path}")
            print(f"Template file remains unchanged: {get_config_template_path()}")
            print(f"Final timestamp: {config['date_time']}")
            # Track the generated configuration file
            add_generated_file(config, config_file_path, "Configuration file created from template with Q&A pairs")
        else:
            # Normal case: save new config file (interactive mode)
            save_config(config, config_file_path)
            print(f"Created new configuration file: {config_file_path}")
            print(f"Final timestamp: {config['date_time']}")
            # Track the generated configuration file
            add_generated_file(config, config_file_path, "Configuration file with Q&A pairs")


def sra_mode(args):
    """
    SRA mode: Convert FAIRe metadata to SRA submission format.
    
    Args:
        args: Parsed command line arguments
    """
    print("\n" + "="*60)
    print("FAIRE2NCBI - SRA MODE")
    print("="*60)
    
    # Check if output file exists and handle --force
    if os.path.exists(args.SRA_Metadata) and not args.force:
        response = get_valid_user_choice(
            f"File '{args.SRA_Metadata}' already exists. Overwrite? [y/N]: ",
            ["y", "yes", "n", "no"],
            default="n"
        )
        if response not in ('y', 'yes'):
            print('Aborted by user. No file overwritten.')
            return

    # Read experimentRunMetadata from full workbook (.xlsx) or a single sheet file (.tsv)
    erm_src = _get_faire_sheet_source(args, "experimentRunMetadata")
    print(f"Reading experimentRunMetadata from: {erm_src}")
    sample_df = _read_faire_sheet_df(erm_src, "experimentRunMetadata", header=2)
    if sample_df is None:
        print(
            "Error: Could not read experimentRunMetadata. "
            "Provide --FAIReMetadata workbook or --experimentRunMetadata file."
        )
        return

    # Check for assay_name column and handle multiple assays
    if 'assay_name' not in sample_df.columns:
        print("Error: 'assay_name' column not found in experimentRunMetadata sheet.")
        return
    
    # Get unique assay names
    unique_assays = sample_df['assay_name'].dropna().unique()
    unique_assays = [assay for assay in unique_assays if str(assay).strip() != '']
    
    if len(unique_assays) == 0:
        print("Error: No valid assay names found in 'assay_name' column.")
        return
    elif len(unique_assays) == 1:
        print(f"Single assay found: \"{unique_assays[0]}\"")
        selected_assays = unique_assays
    else:
        print(f"Multiple assays found in 'assay_name' column:")
        for i, assay in enumerate(unique_assays, 1):
            print(f"  {i}. {assay}")
        
        # Ask user for preference
        choice = get_valid_user_choice(
            "\nDo you want to use all assays or only specific ones? [all/specific]: ",
            ["all", "specific"],
            default="all"
        )
        
        if choice == "all":
            selected_assays = unique_assays
            print(f"Using all {len(selected_assays)} assays.")
        else:
            # Let user select specific assays
            print("\nEnter assay numbers separated by commas (e.g., 1,3,5):")
            while True:
                try:
                    user_input = input("Selected assays: ").strip()
                    if not user_input:
                        print("No assays selected. Using all assays.")
                        selected_assays = unique_assays
                        break
                    
                    # Parse user input
                    selected_indices = []
                    for item in user_input.split(','):
                        item = item.strip()
                        if item.isdigit():
                            idx = int(item) - 1
                            if 0 <= idx < len(unique_assays):
                                selected_indices.append(idx)
                            else:
                                print(f"Warning: Invalid assay number {item}")
                        else:
                            print(f"Warning: '{item}' is not a valid number")
                    
                    if selected_indices:
                        selected_assays = [unique_assays[i] for i in selected_indices]
                        print(f"Selected assays: {', '.join(selected_assays)}")
                        break
                    else:
                        print("No valid assays selected. Please try again.")
                except ValueError:
                    print("Invalid input. Please enter valid numbers separated by commas.")
    
    # Filter sample_df to include only selected assays
    sample_df = sample_df[sample_df['assay_name'].isin(selected_assays)]
    print(f"Processing {len(sample_df)} samples with selected assays.")

    # Read SRA template - determine sheet name from template file
    print(f"Reading SRA template from: {args.SRA_Template}")
    try:
        # First, try to read the Excel file to get sheet names
        template_excel = pd.ExcelFile(args.SRA_Template, engine='openpyxl')
        sheet_names = template_excel.sheet_names
        template_excel.close()
        
        # Look for SRA_metadata_acc sheet (or similar)
        sra_sheet = None
        for sheet in sheet_names:
            if 'sra_metadata_acc' in sheet.lower() or 'sra' in sheet.lower():
                sra_sheet = sheet
                break
        
        if sra_sheet is None:
            # If no SRA sheet found, try the second sheet
            if len(sheet_names) >= 2:
                sra_sheet = sheet_names[1]  # Second sheet (index 1)
                print(f"Using second sheet: '{sra_sheet}'")
            else:
                print(f"Error: No suitable SRA sheet found. Available sheets: {sheet_names}")
                return
        else:
            print(f"Using SRA sheet: '{sra_sheet}'")
        
        # Read the SRA template sheet
        sra_template_df = pd.read_excel(args.SRA_Template, sheet_name=sra_sheet, header=2, engine='openpyxl')
        
    except Exception as e:
        print(f"Error reading SRA template file: {e}")
        return

    print(f"SRA template loaded with {len(sra_template_df)} rows and {len(sra_template_df.columns)} columns")
    
    # Create SRA_Metadata by copying the template structure
    print(f"\nCreating SRA metadata file: {args.SRA_Metadata}")
    
    # Copy the template structure to create the output file
    # We'll create a new DataFrame with the same columns as the template
    sra_output_df = pd.DataFrame(columns=sra_template_df.columns)
    
    # Add rows for each sample (one row per sample)
    for i, sample_row in sample_df.iterrows():
        # Create a new row with empty values for all SRA template columns
        new_row = pd.Series([''] * len(sra_template_df.columns), index=sra_template_df.columns)
        sra_output_df = pd.concat([sra_output_df, pd.DataFrame([new_row])], ignore_index=True)
    
    print(f"Created SRA metadata with {len(sra_output_df)} rows and {len(sra_output_df.columns)} columns")
    
    # Now work on the SRA_Metadata (sra_output_df) without modifying the template
    print("\n" + "="*50)
    print("PROCESSING SRA METADATA")
    print("="*50)
    
    # Display available columns for mapping
    print(f"\nAvailable columns in SRA template:")
    for i, col in enumerate(sra_output_df.columns, 1):
        print(f"  {i:2d}. {col}")
    
    print(f"\nAvailable columns in FAIRe metadata:")
    for i, col in enumerate(sample_df.columns, 1):
        print(f"  {i:2d}. {col}")
    
    print("SRA mode is under development.")
    print("This mode will convert FAIRe metadata to SRA submission format.")
    print("\nFeatures planned:")
    print("  - Convert FAIReMetadata to SRA format")
    print("  - Handle sequencing run information")
    print("  - Generate SRA submission templates")
    print("  - Validate SRA metadata requirements")
    print("\nPlease use the BioSample mode for now.")
    
    # Write the SRA metadata file
    print(f"\nWriting SRA metadata to: {args.SRA_Metadata}")
    try:
        sra_output_df.to_excel(args.SRA_Metadata, index=False, engine='openpyxl')
        print(f"Successfully wrote SRA metadata to: {args.SRA_Metadata}")
    except Exception as e:
        print(f"Error writing SRA metadata file: {e}")
        return


def main():
    """Main function to handle command line arguments and mode selection."""
    parser = argparse.ArgumentParser(
        description="FAIRe2NCBI: Convert FAIRe metadata to NCBI submission formats.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
BioSample Mode Arguments:
  --FAIReMetadata PATH       Path to FAIRe metadata Excel file (.xlsx)
  --projectMetadata PATH
  --sampleMetadata PATH
  --experimentRunMetadata PATH
                             Individual FAIRe sheet files (.tsv). Use either --FAIReMetadata OR all three sheet arguments.
  --BioSample_Template PATH   Path to MIMARKS template file (.tsv) [optional; defaults to bundled template]
  --BioSample_Metadata PATH   Output TSV file for BioSample metadata [required]
  --bioproject_accession ID  Bioproject accession to use for all samples [optional]
  --config_file PATH         Path to YAML configuration file for automated responses [optional]
  --force                    Overwrite output files without prompting [optional]

SRA Mode Arguments:
  --FAIReMetadata PATH       Path to FAIRe metadata Excel file (.xlsx)
  --projectMetadata PATH
  --sampleMetadata PATH
  --experimentRunMetadata PATH
                             Individual FAIRe sheet files (.tsv). Use either --FAIReMetadata OR all three sheet arguments.
  --SRA_Template PATH        Path to SRA template file (.tsv) [optional; defaults to bundled template]
  --SRA_Metadata PATH        Output TSV file for SRA metadata [required]
  --force                    Overwrite output files without prompting [optional]

Examples:
  # BioSample mode with bioproject accession (optional)
  python FAIRe2NCBI.py BioSample --FAIReMetadata data.xlsx --BioSample_Metadata output.tsv --bioproject_accession PRJNA123456
  
  # SRA mode
  python FAIRe2NCBI.py SRA --FAIReMetadata data.xlsx --SRA_Template sra_template.tsv --SRA_Metadata sra_output.tsv
        """
    )
    
    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('BioSample', nargs='?', const=True,
                           help='BioSample mode: Convert to BioSample MIMARKS format')
    mode_group.add_argument('SRA', nargs='?', const=True,
                           help='SRA mode: Convert to SRA submission format')
    
    # BioSample mode arguments
    parser.add_argument('--FAIReMetadata', type=str,
                       help='Path to FAIRe metadata Excel file (.xlsx)')
    parser.add_argument('--projectMetadata', type=str,
                       help='Path to projectMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    parser.add_argument('--sampleMetadata', type=str,
                       help='Path to sampleMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    parser.add_argument('--experimentRunMetadata', type=str,
                       help='Path to experimentRunMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    parser.add_argument('--BioSample_Template', type=str,
                       help='Path to MIMARKS template file (.tsv) [optional; defaults to bundled template]')
    parser.add_argument('--BioSample_Metadata', type=str,
                       help='Output TSV file for BioSample metadata [required for BioSample mode]')
    parser.add_argument('--bioproject_accession', type=str,
                       help='Bioproject accession to use for all samples [optional for BioSample mode]')
    
    # SRA mode arguments
    parser.add_argument('--SRA_Template', type=str,
                       help='Path to SRA template file (.tsv) [optional; defaults to bundled template]')
    parser.add_argument('--SRA_Metadata', type=str,
                       help='Output TSV file for SRA metadata [required for SRA mode]')
    
    # Common arguments
    parser.add_argument('--force', action='store_true',
                       help='Overwrite output files without prompting [optional for both modes]')
    parser.add_argument('--config_file', type=str,
                       help='Path to YAML configuration file to use for automated responses [optional]')
    
    args = parser.parse_args()
    
    # Determine which mode was selected
    selected_mode = None
    if args.BioSample is not None:
        selected_mode = 'BioSample'
    elif args.SRA is not None:
        selected_mode = 'SRA'
    
    # Validate mode-specific arguments based on selected mode
    if selected_mode == 'BioSample':
        # BioSample mode validation
        required_args = ['BioSample_Metadata']
        missing_args = [arg for arg in required_args if not getattr(args, arg)]
        if missing_args:
            parser.error(f"BioSample mode requires: --{', --'.join(missing_args)}")

        has_workbook = bool(args.FAIReMetadata)
        sheet_args = [
            args.projectMetadata,
            args.sampleMetadata,
            args.experimentRunMetadata,
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
        
        # Check if input files exist (template resolved inside biosample_mode)
        if has_workbook:
            if not os.path.exists(args.FAIReMetadata):
                parser.error(f"File not found: {args.FAIReMetadata}")
        else:
            for p in sheet_args:
                if not os.path.exists(p):
                    parser.error(f"File not found: {p}")
        
        biosample_mode(args)
        
    elif selected_mode == 'SRA':
        # SRA mode validation
        required_args = ['SRA_Metadata']
        missing_args = [arg for arg in required_args if not getattr(args, arg)]
        if missing_args:
            parser.error(f"SRA mode requires: --{', --'.join(missing_args)}")

        has_workbook = bool(args.FAIReMetadata)
        sheet_args = [
            args.projectMetadata,
            args.sampleMetadata,
            args.experimentRunMetadata,
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
        
        # Check if input files exist (template resolved inside sra_mode)
        if has_workbook:
            if not os.path.exists(args.FAIReMetadata):
                parser.error(f"File not found: {args.FAIReMetadata}")
        else:
            for p in sheet_args:
                if not os.path.exists(p):
                    parser.error(f"File not found: {p}")
        
        sra_mode(args)
    
    else:
        parser.error("Please specify a mode: BioSample or SRA")


if __name__ == '__main__':
    main()