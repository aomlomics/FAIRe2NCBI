#!/usr/bin/env python3
"""
FAIRe2SRA: Convert FAIRe metadata to NCBI SRA submission format

This script converts FAIRe sample metadata to NCBI SRA submission format.

Author: [Clement Coclet]
Version: 2.0
"""

import pandas as pd
import os
import sys
import argparse
import re
from datetime import datetime
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
        canonical = {str(choice).lower(): choice for choice in valid_choices}
        while True:
            response = input(prompt).strip()
            if not response and default is not None:
                return canonical.get(str(default).lower(), default)
            match = canonical.get(response.lower())
            if match is not None:
                return match
            print(f"Invalid choice. Please enter one of: {', '.join(valid_choices)}")


LIBRARY_FIELD_CHOICE_KEY = (
    'Use default value or choose from allowed values? [DEFAULT/Other]:'
)
LIBRARY_FIELD_CHOICE_KEY_LEGACY = (
    'Use default value or choose from allowed values? [default/Other]:'
)
LIBRARY_FIELD_CHOICE_DEFAULT = 'DEFAULT'
LIBRARY_FIELD_CHOICE_OTHER = 'Other'


def library_field_choice_prompt(field):
    return (
        f"  Use default value or choose from allowed values for {field}? "
        f"[{LIBRARY_FIELD_CHOICE_DEFAULT}/{LIBRARY_FIELD_CHOICE_OTHER}]: "
    )


def normalize_library_field_choice(choice):
    """Normalize saved or typed library-field choice labels."""
    if choice is None:
        return choice
    normalized = str(choice).strip()
    lowered = normalized.lower()
    if lowered == 'default':
        return LIBRARY_FIELD_CHOICE_DEFAULT
    if lowered == 'other':
        return LIBRARY_FIELD_CHOICE_OTHER
    return normalized


def is_library_field_other_choice(choice):
    return normalize_library_field_choice(choice) == LIBRARY_FIELD_CHOICE_OTHER


def get_library_field_choice_values(config):
    """Return library-field choice answers, supporting legacy config keys."""
    section = config.get('LIBRARY_FIELD_CONFIGURATION', {})
    values = section.get(LIBRARY_FIELD_CHOICE_KEY)
    if isinstance(values, dict):
        return values
    legacy_values = section.get(LIBRARY_FIELD_CHOICE_KEY_LEGACY, {})
    return legacy_values if isinstance(legacy_values, dict) else {}


def get_config_file_path(output_file_path):
    """
    Generate configuration file path based on output file path.
    
    Args:
        output_file_path (str): Path to the output SRA metadata file
    
    Returns:
        str: Path to the configuration file
    """
    # Remove extension and add _config.yaml
    base_path = os.path.splitext(output_file_path)[0]
    return f"{base_path}_config.yaml"


from paths import (
    DEFAULT_SRA_TEMPLATE,
    SRA_CONFIG_TEMPLATE_NAME,
    get_docs_path,
    resolve_input_path,
)


def get_config_template_path(template_filename=SRA_CONFIG_TEMPLATE_NAME):
    """Return the path to a config template YAML file in the docs/ directory."""
    return str(get_docs_path(template_filename))


def is_config_template_file(config_file_path, template_filename=SRA_CONFIG_TEMPLATE_NAME):
    """Check whether a config file path refers to the bundled config template."""
    template_path = get_config_template_path(template_filename)
    abs_config_file = os.path.abspath(config_file_path)
    abs_template_path = os.path.abspath(template_path)
    config_filename = os.path.basename(config_file_path)
    template_basename = os.path.basename(template_path)
    return (abs_config_file == abs_template_path) or (config_filename == template_basename)


def prompt_config_source_choice():
    """
    Ask whether to reuse a config file from a previous run.

    Returns:
        str: 'previous' or 'template' (template + interactive when answer is No)
    """
    choice = get_valid_user_choice(
        "Do you want to use a config file from a previous run? [y/N]: ",
        ['y', 'yes', 'n', 'no'],
        default='n'
    )
    if choice in ('y', 'yes'):
        return 'previous'
    return 'template'


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
        # Add new Q&A pair at the end (chronological order)
        config['qa_pairs'].append(new_qa)
    
    # If using config file, also update the structured format
    if use_config_file:
        update_structured_config(config, question, answer)


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
    Load the SRA template configuration file.

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
    Save configuration to YAML file with structured format and proper quote handling.
    
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
        
        # Create structured config matching the SRA workflow
        structured_config = {
            'command': config.get('command', ''),
            'date_time': config.get('date_time', ''),
            'CONFIGURATION_FILE_HANDLING': {
                'Configuration file PATH already exists. Do you want to overwrite it? [y/N]:': ''
            },
            'OUTPUT_FILE_OVERWRITE': {
                'File PATH already exists. Overwrite? [y/N]:': ''
            },
            'ASSAY_SELECTION': {
                'Do you want to use all assays or only specific ones? [all/specific]:': '',
                'Selected assays:': ''
            },
            'LIBRARY_FIELD_CONFIGURATION': {
                LIBRARY_FIELD_CHOICE_KEY: {},
                'Enter FIELD_NAME value (number or term):': {}
            },
            'PLATFORM_VALUES_CONFIGURATION': {
                'Which one do you want to use? [Assay/Project]:': {},
                'Enter platform value (number or name):': {}
            },
            'INSTRUMENT_MODEL_VALUES_CONFIGURATION': {
                'Which one do you want to use? [Assay/Project]:': '',
                'No instrument model value found for assay. Do you want to add a value manually? [y/N]:': {},
                'Enter instrument model number or type Other value:': {}
            },
            'EXPERIMENT_RUN_METADATA_FILTER': {
                'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:': ''
            },
            'generated_files': config.get('generated_files', [])
        }
        
        # If config already has structured sections (from template), preserve them
        for section_name in ['CONFIGURATION_FILE_HANDLING', 'OUTPUT_FILE_OVERWRITE', 'ASSAY_SELECTION', 
                           'LIBRARY_FIELD_CONFIGURATION', 'PLATFORM_VALUES_CONFIGURATION', 
                           'INSTRUMENT_MODEL_VALUES_CONFIGURATION', 'EXPERIMENT_RUN_METADATA_FILTER']:
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
            answer = qa.get('answer', '')
            # Only strip if answer is a string
            if isinstance(answer, str):
                answer = answer.strip()
            
            # Map questions to structured sections using exact question matching
            if "Configuration file" in question and "overwrite" in question:
                structured_config['CONFIGURATION_FILE_HANDLING']['Configuration file PATH already exists. Do you want to overwrite it? [y/N]:'] = answer
            elif "File" in question and "already exists" in question and "Overwrite" in question:
                structured_config['OUTPUT_FILE_OVERWRITE']['File PATH already exists. Overwrite? [y/N]:'] = answer
            elif "use all assays or only specific ones" in question:
                structured_config['ASSAY_SELECTION']['Do you want to use all assays or only specific ones? [all/specific]:'] = answer
            elif "Selected assays:" in question:
                structured_config['ASSAY_SELECTION']['Selected assays:'] = answer
            elif "Use default value or choose from allowed values" in question:
                # Store in the field values dictionary
                if not isinstance(structured_config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY], dict):
                    structured_config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY] = {}
                structured_config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY][question] = (
                    normalize_library_field_choice(answer)
                )
            elif "Enter" in question and "value (number or term)" in question:
                # Store in the field values dictionary
                if not isinstance(structured_config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'], dict):
                    structured_config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'] = {}
                structured_config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'][question] = answer
            elif "Which one do you want to use" in question and "Assay/Project" in question:
                # Store in the platform values dictionary - store individual assay questions
                if 'Which one do you want to use? [Assay/Project]:' not in structured_config['PLATFORM_VALUES_CONFIGURATION']:
                    structured_config['PLATFORM_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] = {}
                structured_config['PLATFORM_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'][question] = answer
            elif "Enter platform value" in question:
                # Store in the platform values dictionary
                if not isinstance(structured_config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'], dict):
                    structured_config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'] = {}
                structured_config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'][question] = answer
            elif "No instrument model value found" in question:
                # Store in the instrument model values dictionary
                if not isinstance(structured_config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'], dict):
                    structured_config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'] = {}
                structured_config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'][question] = answer
            elif "Enter instrument model" in question:
                # Store in the instrument model values dictionary
                if not isinstance(structured_config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'], dict):
                    structured_config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'] = {}
                structured_config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'][question] = answer
            elif "[all/blank_only]" in question and "experimentRunMetadata" in question and "associatedSequences" in question:
                structured_config['EXPERIMENT_RUN_METADATA_FILTER'][
                    'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:'] = answer
        
        with open(config_file_path, 'w', encoding='utf-8') as f:
            # Write header comments
            f.write("# FAIRe2SRA Configuration File\n")
            f.write("# This file contains all user responses from the FAIRe2SRA script\n")
            f.write("# Generated automatically - do not edit manually unless you understand the structure\n\n")
            
            # Write command and date_time
            f.write(f"command: {structured_config['command']}\n")
            f.write(f"date_time: '{structured_config['date_time']}'\n\n")
            
            # Write sections with custom quote handling
            sections = [
                ('CONFIGURATION_FILE_HANDLING', 'CONFIGURATION FILE HANDLING', 'File overwrite prompts'),
                ('OUTPUT_FILE_OVERWRITE', 'OUTPUT FILE OVERWRITE', 'Output file overwrite prompts'),
                ('ASSAY_SELECTION', 'ASSAY SELECTION', 'Assay selection and filtering'),
                ('LIBRARY_FIELD_CONFIGURATION', 'LIBRARY FIELD CONFIGURATION', 'Library strategy, source, and selection settings'),
                ('PLATFORM_VALUES_CONFIGURATION', 'PLATFORM VALUES CONFIGURATION', 'Platform value choices per assay'),
                ('INSTRUMENT_MODEL_VALUES_CONFIGURATION', 'INSTRUMENT MODEL VALUES CONFIGURATION', 'Instrument model choices per assay'),
                ('EXPERIMENT_RUN_METADATA_FILTER', 'EXPERIMENT RUN METADATA FILTER', 'Optional filter by blank associatedSequences in experimentRunMetadata after assay selection')
            ]
            
            for section_key, section_title, section_desc in sections:
                if section_key in structured_config:
                    f.write(f"# =============================================================================\n")
                    f.write(f"# {section_title}\n")
                    f.write(f"# =============================================================================\n")
                    if section_desc:
                        f.write(f"# {section_desc}\n")
                    f.write(f"{section_key}:\n")
                    
                    section_data = structured_config[section_key]
                    if isinstance(section_data, dict):
                        for key, value in section_data.items():
                            if isinstance(value, dict):
                                # Use double quotes for keys that might contain single quotes or line breaks
                                if "'" in key or "\n" in key:
                                    # For multi-line keys, clean them up and use double quotes
                                    clean_key = key.replace('\n', ' ').replace('  ', ' ').strip()
                                    f.write(f'  "{clean_key}":\n')
                                else:
                                    f.write(f"  '{key}':\n")
                                for sub_key, sub_value in value.items():
                                    # Use double quotes for sub_keys that might contain single quotes or line breaks
                                    if "'" in sub_key or "\n" in sub_key:
                                        clean_sub_key = sub_key.replace('\n', ' ').replace('  ', ' ').strip()
                                        f.write(f'    "{clean_sub_key}": "{sub_value}"\n')
                                    else:
                                        f.write(f"    '{sub_key}': '{sub_value}'\n")
                            else:
                                # Use double quotes for keys that might contain single quotes or line breaks
                                if "'" in key or "\n" in key:
                                    clean_key = key.replace('\n', ' ').replace('  ', ' ').strip()
                                    f.write(f'  "{clean_key}": "{value}"\n')
                                else:
                                    f.write(f"  '{key}': '{value}'\n")
                    f.write("\n")
            
            # Write generated files section
            if 'generated_files' in structured_config and structured_config['generated_files']:
                f.write("# =============================================================================\n")
                f.write("# GENERATED FILES TRACKING\n")
                f.write("# =============================================================================\n")
                f.write("# List of files created by the script\n")
                f.write("generated_files:\n")
                for file_info in structured_config['generated_files']:
                    f.write(f"- file_path: {file_info.get('file_path', '')}\n")
                    f.write(f"  description: {file_info.get('description', '')}\n")
                    f.write(f"  timestamp: '{file_info.get('timestamp', '')}'\n")
                f.write("\n")
            
            # Add footer comments
            f.write("# =============================================================================\n")
            f.write("# NOTES ON USAGE\n")
            f.write("# =============================================================================\n")
            f.write("# This configuration file contains all user responses from the FAIRe2SRA script.\n")
            f.write("# \n")
            f.write("# Key sections:\n")
            f.write("# - CONFIGURATION_FILE_HANDLING: File overwrite prompts\n")
            f.write("# - OUTPUT_FILE_OVERWRITE: Output file overwrite prompts\n")
            f.write("# - ASSAY_SELECTION: Assay selection and filtering\n")
            f.write("# - LIBRARY_FIELD_CONFIGURATION: Library strategy, source, and selection settings\n")
            f.write("# - PLATFORM_VALUES_CONFIGURATION: Platform value choices per assay\n")
            f.write("# - INSTRUMENT_MODEL_VALUES_CONFIGURATION: Instrument model choices per assay\n")
            f.write("# - EXPERIMENT_RUN_METADATA_FILTER: Filter SRA rows by experimentRunMetadata associatedSequences\n")
            f.write("# - generated_files: List of files created by the script\n")
            f.write("# \n")
            f.write("# To reuse this configuration:\n")
            f.write("# 1. Run the script with --config_file path/to/this/file.yaml\n")
            f.write("# 2. The script will use saved answers and skip prompts\n")
            f.write("# 3. Only missing answers will prompt for user input\n")
        print(f"Configuration saved to: {config_file_path}")
    except Exception as e:
        print(f"Warning: Could not save configuration file {config_file_path}: {e}")


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
    elif "use all assays or only specific ones" in question:
        if 'ASSAY_SELECTION' not in config:
            config['ASSAY_SELECTION'] = {}
        config['ASSAY_SELECTION']['Do you want to use all assays or only specific ones? [all/specific]:'] = answer
    elif "Selected assays:" in question:
        if 'ASSAY_SELECTION' not in config:
            config['ASSAY_SELECTION'] = {}
        config['ASSAY_SELECTION']['Selected assays:'] = answer
    elif "[all/blank_only]" in question and "experimentRunMetadata" in question and "associatedSequences" in question:
        if 'EXPERIMENT_RUN_METADATA_FILTER' not in config:
            config['EXPERIMENT_RUN_METADATA_FILTER'] = {}
        config['EXPERIMENT_RUN_METADATA_FILTER'][
            'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:'] = answer
    elif "Use default value or choose from allowed values" in question:
        if 'LIBRARY_FIELD_CONFIGURATION' not in config:
            config['LIBRARY_FIELD_CONFIGURATION'] = {}
        if LIBRARY_FIELD_CHOICE_KEY not in config['LIBRARY_FIELD_CONFIGURATION']:
            config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY] = {}
        if config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY] is None:
            config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY] = {}
        config['LIBRARY_FIELD_CONFIGURATION'][LIBRARY_FIELD_CHOICE_KEY][question] = (
            normalize_library_field_choice(answer)
        )
    elif "Enter" in question and "value (number or term)" in question:
        if 'LIBRARY_FIELD_CONFIGURATION' not in config:
            config['LIBRARY_FIELD_CONFIGURATION'] = {}
        if 'Enter FIELD_NAME value (number or term):' not in config['LIBRARY_FIELD_CONFIGURATION']:
            config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'] = {}
        if config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'] is None:
            config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'] = {}
        config['LIBRARY_FIELD_CONFIGURATION']['Enter FIELD_NAME value (number or term):'][question] = answer
    elif "Which one do you want to use" in question and "Assay/Project" in question:
        # Check if it's a platform question or instrument model question
        if "platform values" in question:
            if 'PLATFORM_VALUES_CONFIGURATION' not in config:
                config['PLATFORM_VALUES_CONFIGURATION'] = {}
            if 'Which one do you want to use? [Assay/Project]:' not in config['PLATFORM_VALUES_CONFIGURATION']:
                config['PLATFORM_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] = {}
            if config['PLATFORM_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] is None:
                config['PLATFORM_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] = {}
            config['PLATFORM_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'][question] = answer
        elif "instrument model values" in question:
            if 'INSTRUMENT_MODEL_VALUES_CONFIGURATION' not in config:
                config['INSTRUMENT_MODEL_VALUES_CONFIGURATION'] = {}
            if 'Which one do you want to use? [Assay/Project]:' not in config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']:
                config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] = {}
            if config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] is None:
                config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'] = {}
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Which one do you want to use? [Assay/Project]:'][question] = answer
    elif "Enter platform value" in question:
        if 'PLATFORM_VALUES_CONFIGURATION' not in config:
            config['PLATFORM_VALUES_CONFIGURATION'] = {}
        if 'Enter platform value (number or name):' not in config['PLATFORM_VALUES_CONFIGURATION']:
            config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'] = {}
        if config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'] is None:
            config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'] = {}
        config['PLATFORM_VALUES_CONFIGURATION']['Enter platform value (number or name):'][question] = answer
    elif "No instrument model value found" in question:
        if 'INSTRUMENT_MODEL_VALUES_CONFIGURATION' not in config:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION'] = {}
        if 'No instrument model value found for assay. Do you want to add a value manually? [y/N]:' not in config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'] = {}
        if config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'] is None:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'] = {}
        config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['No instrument model value found for assay. Do you want to add a value manually? [y/N]:'][question] = answer
    elif "Enter instrument model" in question and "number" in question:
        if 'INSTRUMENT_MODEL_VALUES_CONFIGURATION' not in config:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION'] = {}
        if 'Enter instrument model number or type Other value:' not in config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'] = {}
        if config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'] is None:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'] = {}
        config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model number or type Other value:'][question] = answer
    elif "Enter instrument model:" in question:
        if 'INSTRUMENT_MODEL_VALUES_CONFIGURATION' not in config:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION'] = {}
        if 'Enter instrument model:' not in config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model:'] = {}
        if config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model:'] is None:
            config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model:'] = {}
        config['INSTRUMENT_MODEL_VALUES_CONFIGURATION']['Enter instrument model:'][question] = answer


def find_answer_in_qa_pairs(config, question):
    """Match saved qa_pairs from YAML (exact or fuzzy for the ERM associatedSequences prompt)."""
    question = question.strip()
    pairs = config.get("qa_pairs")
    if not pairs:
        return None
    for qa in pairs:
        if qa.get("question", "").strip() == question:
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
    elif "use all assays or only specific ones" in question:
        answer = config.get('ASSAY_SELECTION', {}).get('Do you want to use all assays or only specific ones? [all/specific]:', '')
        return answer if answer != '' else None
    elif "Selected assays:" in question:
        answer = config.get('ASSAY_SELECTION', {}).get('Selected assays:', '')
        return answer if answer != '' else None
    elif "[all/blank_only]" in question and "experimentRunMetadata" in question and "associatedSequences" in question:
        answer = config.get('EXPERIMENT_RUN_METADATA_FILTER', {}).get(
            'Do you want to keep all samples in the BioSample output, or only samp_name values that have blank/NA associatedSequences in the experimentRunMetadata sheet? [all/blank_only]:', '')
        if not answer:
            v = config.get('filter_experiment_run_blank_associatedSequences')
            if v is not None and str(v).strip() != '':
                answer = str(v).strip()
        return answer if answer != '' else None
    elif "Use default value or choose from allowed values" in question:
        # Look in the field values dictionary
        field_values = get_library_field_choice_values(config)
        if isinstance(field_values, dict):
            # Try exact match first
            answer = field_values.get(question, '')
            if answer != '':
                return normalize_library_field_choice(answer)
            
            # Try alternative key formats
            # Add trailing space (config file format has trailing space)
            alt_question = f"{question} "
            answer = field_values.get(alt_question, '')
            if answer != '':
                return normalize_library_field_choice(answer)
            
            # Try with leading spaces and trailing space (config file format)
            alt_question = f"  {question} "
            answer = field_values.get(alt_question, '')
            if answer != '':
                return normalize_library_field_choice(answer)
            
            # Try removing trailing space (config file format has no trailing space)
            alt_question = question.rstrip()
            answer = field_values.get(alt_question, '')
            if answer != '':
                return normalize_library_field_choice(answer)
            
            # Try with leading spaces removed
            alt_question = question.strip()
            answer = field_values.get(alt_question, '')
            if answer != '':
                return normalize_library_field_choice(answer)

            # Legacy prompt text stored in older config files
            legacy_question = question.replace('[DEFAULT/Other]:', '[default/Other]:')
            for alt_question in {legacy_question, f"{legacy_question} ", f"  {legacy_question} "}:
                answer = field_values.get(alt_question, '')
                if answer != '':
                    return normalize_library_field_choice(answer)
        return None
    elif "Enter" in question and "value (number or term)" in question:
        # Look in the field values dictionary
        field_values = config.get('LIBRARY_FIELD_CONFIGURATION', {}).get('Enter FIELD_NAME value (number or term):', {})
        if isinstance(field_values, dict):
            # Try exact match first
            answer = field_values.get(question, '')
            if answer != '':
                return answer
            
            # Try alternative key formats
            # Add trailing space (config file format has trailing space)
            alt_question = f"{question} "
            answer = field_values.get(alt_question, '')
            if answer != '':
                return answer
            
            # Try with leading spaces and trailing space (config file format)
            alt_question = f"  {question} "
            answer = field_values.get(alt_question, '')
            if answer != '':
                return answer
            
            # Try removing trailing space (config file format has no trailing space)
            alt_question = question.rstrip()
            answer = field_values.get(alt_question, '')
            if answer != '':
                return answer
        return None
    elif "Which one do you want to use" in question and "Assay/Project" in question:
        # Look in the platform values dictionary - individual assay questions
        platform_values = config.get('PLATFORM_VALUES_CONFIGURATION', {}).get('Which one do you want to use? [Assay/Project]:', {})
        if isinstance(platform_values, dict):
            answer = platform_values.get(question, '')
            return answer if answer != '' else None
        
        # Also check instrument model values
        instrument_values = config.get('INSTRUMENT_MODEL_VALUES_CONFIGURATION', {}).get('Which one do you want to use? [Assay/Project]:', {})
        if isinstance(instrument_values, dict):
            answer = instrument_values.get(question, '')
            return answer if answer != '' else None
    elif "Enter platform value" in question:
        # Look in the platform values dictionary
        platform_values = config.get('PLATFORM_VALUES_CONFIGURATION', {}).get('Enter platform value (number or name):', {})
        if isinstance(platform_values, dict):
            answer = platform_values.get(question, '')
            return answer if answer != '' else None
    elif "No instrument model value found" in question:
        # Look in the instrument model values dictionary
        instrument_values = config.get('INSTRUMENT_MODEL_VALUES_CONFIGURATION', {}).get('No instrument model value found for assay. Do you want to add a value manually? [y/N]:', {})
        if isinstance(instrument_values, dict):
            answer = instrument_values.get(question, '')
            return answer if answer != '' else None
    elif "Enter instrument model" in question and "number" in question:
        # Look in the instrument model values dictionary
        instrument_values = config.get('INSTRUMENT_MODEL_VALUES_CONFIGURATION', {}).get('Enter instrument model number or type Other value:', {})
        if isinstance(instrument_values, dict):
            answer = instrument_values.get(question, '')
            return answer if answer != '' else None
    elif "Enter instrument model:" in question:
        # Look in the instrument model values dictionary
        instrument_values = config.get('INSTRUMENT_MODEL_VALUES_CONFIGURATION', {}).get('Enter instrument model:', {})
        if isinstance(instrument_values, dict):
            answer = instrument_values.get(question, '')
            return answer if answer != '' else None
    
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


def read_faire_sheet_df(faire_file, sheet_name, header=0, keep_default_na=True):
    """
    Read a FAIRe sheet from either:
      - full FAIRe workbook (.xlsx/.xls), selecting `sheet_name`
      - single exported sheet (.tsv), where `sheet_name` is informational.
    Returns None on failure.
    """
    ext = os.path.splitext(str(faire_file))[1].lower()
    if ext == ".tsv":
        try:
            return pd.read_csv(
                faire_file,
                sep="\t",
                header=header,
                keep_default_na=keep_default_na,
            )
        except Exception:
            try:
                return pd.read_csv(
                    faire_file,
                    sep=None,
                    engine="python",
                    header=header,
                    keep_default_na=keep_default_na,
                )
            except Exception:
                return None

    kw = dict(sheet_name=sheet_name, header=header, keep_default_na=keep_default_na)
    try:
        return pd.read_excel(faire_file, engine="openpyxl", **kw)
    except Exception:
        try:
            return pd.read_excel(faire_file, engine="xlrd", **kw)
        except Exception:
            try:
                return pd.read_excel(faire_file, **kw)
            except Exception:
                return None


def get_faire_sheet_source(args, sheet_name):
    """Return sheet-specific path when provided, else fallback to --FAIReMetadata."""
    key_map = {
        "sampleMetadata": "sampleMetadata",
        "projectMetadata": "projectMetadata",
        "experimentRunMetadata": "experimentRunMetadata",
    }
    key = key_map.get(sheet_name)
    if key:
        specific = getattr(args, key, None)
        if specific:
            return specific
    return args.FAIReMetadata


def replace_sample_df_with_erm_blank_associated_rows(faire_path, sample_df, selected_assays):
    """
    After blank_only on experimentRunMetadata associatedSequences: rebuild sample_df from
    the workbook so every row with blank associatedSequences (for selected assays and kept
    samp_name values) becomes one SRA metadata row — all matching filenames are included.
    """
    try:
        from FAIRe2BioSample import _associated_sequences_is_blank, _read_experiment_run_metadata_df
    except ImportError:
        print(
            "Warning: could not import ERM helpers; keeping sample table without ERM row expansion."
        )
        return sample_df
    if sample_df is None or len(sample_df) == 0:
        return sample_df
    if "samp_name" not in sample_df.columns:
        return sample_df
    erm = _read_experiment_run_metadata_df(faire_path)
    if erm is None:
        print("Warning: could not re-read experimentRunMetadata for blank_only filename expansion.")
        return sample_df
    need = {"samp_name", "associatedSequences", "assay_name"}
    if not need.issubset(erm.columns):
        print("Warning: experimentRunMetadata missing columns needed for blank_only expansion.")
        return sample_df
    sn_keep = set(sample_df["samp_name"].astype(str).str.strip())
    m_blank = erm["associatedSequences"].map(_associated_sequences_is_blank)
    m_assay = erm["assay_name"].isin(selected_assays)
    m_sn = (
        erm["samp_name"]
        .map(lambda x: str(x).strip() if pd.notna(x) else "")
        .isin(sn_keep)
    )
    expanded = erm.loc[m_blank & m_assay & m_sn].copy()
    for col in sample_df.columns:
        if col not in expanded.columns:
            expanded[col] = ""
    try:
        expanded = expanded[sample_df.columns].reset_index(drop=True)
    except Exception as e:
        print(f"Warning: could not align expanded experimentRunMetadata rows: {e}")
        return sample_df
    if len(expanded) == 0:
        print(
            "Warning: blank_only — no experimentRunMetadata rows with blank associatedSequences "
            "matched; keeping the filtered sample table."
        )
        return sample_df
    print(
        f"blank_only: building SRA from {len(expanded)} experimentRunMetadata row(s) with blank "
        f"associatedSequences (all filenames for selected assays and kept samples)."
    )
    return expanded


def determine_filetype_from_filename(filename):
    """
    Determine the filetype based on filename extension.
    
    Args:
        filename (str): The filename to analyze
        
    Returns:
        str: The determined filetype or empty string if unknown
    """
    if not filename or pd.isna(filename):
        return ''
    
    filename_str = str(filename).strip().lower()
    
    # Remove compression extensions first (.gz, .bz2, etc.)
    if filename_str.endswith('.gz'):
        filename_str = filename_str[:-3]
    elif filename_str.endswith('.bz2'):
        filename_str = filename_str[:-4]
    elif filename_str.endswith('.zip'):
        filename_str = filename_str[:-4]
    
    # Check for known extensions
    if filename_str.endswith('.fastq') or filename_str.endswith('.fq'):
        return 'fastq'
    elif filename_str.endswith('.bam'):
        return 'bam'
    elif filename_str.endswith('.srf'):
        return 'srf'
    elif filename_str.endswith('.sff'):
        return 'sff'
    elif filename_str.endswith('.h5') or filename_str.endswith('.hdf5'):
        return 'PacBio_HDF5'
    elif filename_str.endswith('.bax.h5') or filename_str.endswith('.bas.h5'):
        return 'PacBio_HDF5'
    elif filename_str.endswith('.fast5') or filename_str.endswith('.fastq.gz'):
        return 'OxfordNanopore_native'
    elif filename_str.endswith('.454') or filename_str.endswith('.sff'):
        return '454_native'
    elif filename_str.endswith('.csfasta') or filename_str.endswith('.qual'):
        return 'SOLiD_native'
    elif filename_str.endswith('.cif') or filename_str.endswith('.cg'):
        return 'CompleteGenomics_native'
    elif filename_str.endswith('.hel'):
        return 'Helicos_native'
    
    # If no specific extension found, try to infer from filename patterns
    if 'fastq' in filename_str or 'fq' in filename_str:
        return 'fastq'
    elif 'bam' in filename_str:
        return 'bam'
    elif 'pacbio' in filename_str or 'pacbio' in filename_str:
        return 'PacBio_HDF5'
    elif 'nanopore' in filename_str or 'ont' in filename_str:
        return 'OxfordNanopore_native'
    elif '454' in filename_str:
        return '454_native'
    elif 'solid' in filename_str:
        return 'SOLiD_native'
    elif 'complete' in filename_str or 'genomics' in filename_str:
        return 'CompleteGenomics_native'
    elif 'helicos' in filename_str:
        return 'Helicos_native'
    
    # Default to fastq if no other pattern is found (most common case)
    return 'fastq'


def read_biosample_file_safe(biosample_file_path):
    """
    Safely read biosample file (Excel, CSV, or TSV) with robust error handling.
    Handles BioSample template files with comment lines at the beginning.
    
    Args:
        biosample_file_path (str): Path to biosample file
    
    Returns:
        pd.DataFrame: DataFrame with biosample data, or None if reading fails
    """
    if not biosample_file_path or not os.path.exists(biosample_file_path):
        return None
    
    # Try Excel first
    if biosample_file_path.endswith('.xlsx') or biosample_file_path.endswith('.xls'):
        try:
            return pd.read_excel(biosample_file_path, engine='openpyxl')
        except Exception as e:
            print(f"Warning: Could not read as Excel file: {e}")
            return None
    
    # For TSV/CSV files, check if it has comment lines (BioSample template format)
    # Read the first few lines to detect comment lines
    try:
        with open(biosample_file_path, 'r', encoding='utf-8') as f:
            first_lines = [f.readline() for _ in range(15)]
        
        # Check if first line starts with '#' (comment line)
        has_comments = first_lines[0].strip().startswith('#') if first_lines else False
        
        # Find the header row (first non-comment line that looks like a header)
        header_row = None
        if has_comments:
            # BioSample template typically has header on line 12 (index 11)
            # But we'll search for the first line that has 'accession' or 'sample_name' or 'bioproject'
            for i, line in enumerate(first_lines):
                line_lower = line.lower()
                if ('accession' in line_lower or 'sample_name' in line_lower or 
                    'bioproject' in line_lower or '*sample_name' in line_lower):
                    header_row = i
                    break
            
            # If not found, default to line 12 (index 11) for BioSample template
            if header_row is None and len(first_lines) >= 12:
                header_row = 11
        else:
            header_row = 0
        
    except Exception:
        # If we can't read lines, default to header=0
        header_row = 0
        has_comments = False
    
    # Try different separators for CSV/TSV files
    biosample_df = None
    last_error = None

    def _looks_like_wrong_delimiter(df, expected_sep_char):
        """
        Detect false-success parses where the entire header landed in one column,
        e.g. reading CSV with sep='\\t' gives one column named 'A,B,C,...'.
        """
        if df is None:
            return True
        if len(df.columns) != 1:
            return False
        header_txt = str(df.columns[0])
        return expected_sep_char in header_txt
    
    # Try tab-separated (TSV) with header row
    for quote_char in [None, '"', "'"]:
        try:
            if quote_char is None:
                biosample_df = pd.read_csv(biosample_file_path, sep='\t', engine='python', 
                                          quoting=3, header=header_row, comment='#')
            else:
                biosample_df = pd.read_csv(biosample_file_path, sep='\t', engine='python', 
                                          quotechar=quote_char, quoting=1, header=header_row, comment='#')
            if _looks_like_wrong_delimiter(biosample_df, ','):
                biosample_df = None
                continue
            break
        except Exception as e:
            last_error = e
            continue
    
    # If tab didn't work, try comma-separated (CSV)
    if biosample_df is None:
        for quote_char in [None, '"', "'"]:
            try:
                if quote_char is None:
                    biosample_df = pd.read_csv(biosample_file_path, sep=',', engine='python', 
                                              quoting=3, header=header_row, comment='#')
                else:
                    biosample_df = pd.read_csv(biosample_file_path, sep=',', engine='python', 
                                              quotechar=quote_char, quoting=1, header=header_row, comment='#')
                if _looks_like_wrong_delimiter(biosample_df, '\t'):
                    biosample_df = None
                    continue
                break
            except Exception as e:
                last_error = e
                continue
    
    # Last resort: try auto-detection with minimal quote handling
    if biosample_df is None:
        try:
            biosample_df = pd.read_csv(biosample_file_path, sep=None, engine='python', 
                                     quoting=3, header=header_row, comment='#')
            # If auto detection still failed with one mixed header column, force fallback handling
            if len(biosample_df.columns) == 1:
                col0 = str(biosample_df.columns[0])
                if ',' in col0 or '\t' in col0:
                    raise ValueError("Auto delimiter detection produced a single mixed header column")
        except Exception as e:
            last_error = e
            # Try with error_bad_lines parameter (older pandas) or on_bad_lines (newer pandas)
            try:
                biosample_df = pd.read_csv(biosample_file_path, sep='\t', error_bad_lines=False, 
                                         warn_bad_lines=False, header=header_row, comment='#')
            except Exception:
                try:
                    biosample_df = pd.read_csv(biosample_file_path, sep='\t', on_bad_lines='skip', 
                                             header=header_row, comment='#')
                except Exception:
                    if last_error:
                        raise last_error
                    raise Exception("Could not read file with any method")
    
    return biosample_df


def read_ncbi_accession_file(ncbi_accession_file_path):
    """
    Read NCBI accession file and extract biosample and/or bioproject information and mappings.
    
    Args:
        ncbi_accession_file_path (str): Path to NCBI accession file
    
    Returns:
        dict: Dictionary with keys:
            - 'df': DataFrame with NCBI accession data
            - 'bioprojects': set of unique bioproject accessions (or None)
            - 'sample_to_bioproject': dict mapping sample_name to bioproject (or None)
            - 'bioproject_col': name of bioproject column (or None)
            - 'biosample_col': name of biosample accession column (or None)
            - 'sample_to_biosample': dict mapping sample_name to biosample accession (or None)
    """
    if not ncbi_accession_file_path or not os.path.exists(ncbi_accession_file_path):
        return {
            'df': None,
            'bioprojects': None,
            'sample_to_bioproject': None,
            'bioproject_col': None,
            'biosample_col': None,
            'sample_to_biosample': None
        }
    
    try:
        # Use the safe reading helper function
        ncbi_df = read_biosample_file_safe(ncbi_accession_file_path)
        
        if ncbi_df is None:
            raise Exception("Could not read NCBI accession file")
        
        # Look for bioproject column (prioritize "bioproject_accession", case-insensitive)
        bioproject_col = None
        # First, try exact match for "bioproject_accession"
        for col in ncbi_df.columns:
            col_lower = str(col).lower().strip()
            if col_lower == 'bioproject_accession':
                bioproject_col = col
                break
        
        # If not found, try other variations
        if bioproject_col is None:
            for col in ncbi_df.columns:
                col_lower = str(col).lower().strip()
                if 'bioproject' in col_lower or ('project' in col_lower and 'sample' not in col_lower and 'accession' in col_lower):
                    bioproject_col = col
                    break
        
        # Look for biosample accession column
        biosample_col = None
        for col in ncbi_df.columns:
            col_lower = str(col).lower().strip()
            if col_lower == 'biosample_accession' or col_lower == 'accession':
                biosample_col = col
                break
        
        # Find sample name column
        sample_name_col = None
        for col in ncbi_df.columns:
            col_lower = str(col).lower().strip()
            if col_lower == 'sample_name' or col_lower == '*sample_name':
                sample_name_col = col
                break
        
        bioprojects = None
        sample_to_bioproject = None
        sample_to_biosample = None
        
        # Extract bioproject information if column found
        if bioproject_col is not None and sample_name_col is not None:
            # Get unique bioproject values
            bioprojects = ncbi_df[bioproject_col].dropna().unique()
            bioprojects = {str(bp).strip() for bp in bioprojects if str(bp).strip() != ''}
            bioprojects = bioprojects if bioprojects else None
            
            # Create mapping from sample_name to bioproject
            sample_to_bioproject = {}
            for i, row in ncbi_df.iterrows():
                sample_name = str(row.get(sample_name_col, '')).strip()
                bioproject = str(row.get(bioproject_col, '')).strip()
                if sample_name and bioproject and sample_name != '' and bioproject != '':
                    sample_to_bioproject[sample_name] = bioproject
        elif bioproject_col is not None:
            print("Warning: bioproject_accession column found but sample_name column not found. Cannot create bioproject mapping.")
        else:
            print("Info: No bioproject_accession column found in NCBI accession file. Continuing without bioproject information.")
        
        # Extract biosample accession information if column found
        if biosample_col is not None and sample_name_col is not None:
            # Create mapping from sample_name to biosample accession
            sample_to_biosample = {}
            for i, row in ncbi_df.iterrows():
                sample_name = str(row.get(sample_name_col, '')).strip()
                biosample = str(row.get(biosample_col, '')).strip()
                if sample_name and biosample and sample_name != '' and biosample != '':
                    sample_to_biosample[sample_name] = biosample
        elif biosample_col is not None:
            print("Warning: biosample_accession/accession column found but sample_name column not found. Cannot create biosample mapping.")
        else:
            print("Info: No biosample_accession/accession column found in NCBI accession file. Continuing without biosample information.")
        
        return {
            'df': ncbi_df,
            'bioprojects': bioprojects,
            'sample_to_bioproject': sample_to_bioproject,
            'bioproject_col': bioproject_col,
            'biosample_col': biosample_col,
            'sample_to_biosample': sample_to_biosample
        }
        
    except Exception as e:
        print(f"Warning: Could not read NCBI accession file: {e}")
        return {
            'df': None,
            'bioprojects': None,
            'sample_to_bioproject': None,
            'bioproject_col': None,
            'biosample_col': None,
            'sample_to_biosample': None
        }


def detect_bioprojects_from_ncbi_file(ncbi_accession_file_path):
    """
    Detect bioproject accessions from NCBI accession file.
    
    Args:
        ncbi_accession_file_path (str): Path to NCBI accession file
    
    Returns:
        set: Set of unique bioproject accessions found, or None if file can't be read or no bioproject column
    """
    ncbi_data = read_ncbi_accession_file(ncbi_accession_file_path)
    return ncbi_data['bioprojects']


def handle_bioproject_selection(config, use_config_file, detected_bioprojects, args):
    """
    Handle bioproject selection and determine file creation strategy.
    
    Args:
        config (dict): Configuration dictionary
        use_config_file (bool): Whether using config file
        detected_bioprojects (set): Set of detected bioproject accessions
        args: Command line arguments
    
    Returns:
        dict: Dictionary with keys:
            - 'strategy': 'separate', 'combined', or 'selected'
            - 'selected_bioprojects': list of selected bioproject accessions (if strategy is 'selected')
            - 'bioprojects': set of all available bioprojects
    """
    print(f"\n" + "="*50)
    print("BIOPROJECT HANDLING")
    print("="*50)
    
    # If no bioprojects detected, proceed with combined file
    if not detected_bioprojects or len(detected_bioprojects) == 0:
        print("No bioproject information detected. Will create a single combined SRA metadata file.")
        return {
            'strategy': 'combined',
            'selected_bioprojects': None,
            'bioprojects': set()
        }
    
    # If only one bioproject, proceed with combined file
    if len(detected_bioprojects) == 1:
        bioproject = list(detected_bioprojects)[0]
        print(f"Single bioproject detected: {bioproject}")
        print("Will create a single combined SRA metadata file.")
        return {
            'strategy': 'combined',
            'selected_bioprojects': None,
            'bioprojects': detected_bioprojects
        }
    
    # Multiple bioprojects detected
    print(f"Multiple bioprojects detected ({len(detected_bioprojects)}):")
    for i, bp in enumerate(sorted(detected_bioprojects), 1):
        print(f"  {i}. {bp}")
    
    # Ask user for strategy
    choice = get_config_value(
        config,
        'bioproject_strategy',
        get_valid_user_choice,
        "\nHow do you want to handle multiple bioprojects and SRA metadata creation?\n  [separate/combined/selected]: ",
        use_config_file,
        "\nHow do you want to handle multiple bioprojects and SRA metadata creation?\n  [separate/combined/selected]: ",
        ["separate", "combined", "selected"],
        default="combined"
    )
    
    if choice == "separate":
        print("Will create one SRA metadata file per bioproject.")
        return {
            'strategy': 'separate',
            'selected_bioprojects': None,
            'bioprojects': detected_bioprojects
        }
    elif choice == "combined":
        print("Will create a single combined SRA metadata file for all bioprojects.")
        return {
            'strategy': 'combined',
            'selected_bioprojects': None,
            'bioprojects': detected_bioprojects
        }
    else:  # selected
        print("\nSelect bioprojects to include (enter numbers separated by commas, e.g., 1,3,5):")
        sorted_bioprojects = sorted(detected_bioprojects)
        
        while True:
            try:
                user_input = get_config_value(
                    config,
                    'selected_bioprojects',
                    input,
                    "Selected bioprojects: ",
                    use_config_file,
                    "Selected bioprojects: "
                ).strip()
                
                if not user_input:
                    print("No bioprojects selected. Using all bioprojects (combined strategy).")
                    return {
                        'strategy': 'combined',
                        'selected_bioprojects': None,
                        'bioprojects': detected_bioprojects
                    }
                
                # Parse user input
                selected_indices = []
                for item in user_input.split(','):
                    item = item.strip()
                    if item.isdigit():
                        idx = int(item) - 1
                        if 0 <= idx < len(sorted_bioprojects):
                            selected_indices.append(idx)
                        else:
                            print(f"Warning: Invalid bioproject number {item}")
                    else:
                        print(f"Warning: '{item}' is not a valid number")
                
                if selected_indices:
                    selected_bioprojects = [sorted_bioprojects[i] for i in selected_indices]
                    print(f"Selected bioprojects: {', '.join(selected_bioprojects)}")
                    return {
                        'strategy': 'selected',
                        'selected_bioprojects': selected_bioprojects,
                        'bioprojects': detected_bioprojects
                    }
                else:
                    print("No valid bioprojects selected. Please try again.")
            except ValueError:
                print("Invalid input. Please enter valid numbers separated by commas.")


def sra_mode(args):
    """
    SRA mode: Convert FAIRe metadata to SRA submission format.
    
    Args:
        args: Parsed command line arguments
    """
    # Suppress pandas PerformanceWarning
    warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)
    
    print("\n" + "="*60)
    print("FAIRE2SRA - SRA MODE")
    print("="*60)

    try:
        original_template = getattr(args, 'SRA_Template', None)
        args.SRA_Template = resolve_input_path(
            original_template,
            default=DEFAULT_SRA_TEMPLATE,
        )
        if original_template is None:
            print(f"Using bundled SRA template: {args.SRA_Template}")
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
        is_template_file = is_config_template_file(args.config_file)
        
        if is_template_file:
            # User provided the template file, treat it as template usage
            print(f"Template file detected: {args.config_file}")
            print("Loading template configuration (template will NOT be modified)")
            template_config = load_config(args.config_file)
            if template_config:
                config = template_config.copy()
                # Generate new config file path based on SRA metadata name
                config_file_path = get_config_file_path(args.SRA_Metadata)
                
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
                # Generate config file path based on SRA metadata name
                config_file_path = get_config_file_path(args.SRA_Metadata)
        else:
            # User provided a custom config file (not template)
            if os.path.exists(args.config_file):
                provided_config = load_config(args.config_file)
                if provided_config:
                    config = provided_config
                    # For custom config files, update the same file (but create new path based on SRA_Metadata for consistency)
                    config_file_path = get_config_file_path(args.SRA_Metadata)
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
                    # Generate config file path based on SRA metadata name
                    config_file_path = get_config_file_path(args.SRA_Metadata)
            else:
                print(f"Warning: Config file {args.config_file} not found")
                config = {}
                # Generate config file path based on SRA metadata name
                config_file_path = get_config_file_path(args.SRA_Metadata)
    else:
        config_source = prompt_config_source_choice()

        if config_source == 'previous':
            args.config_file = prompt_previous_config_path()
            provided_config = load_config(args.config_file)
            if provided_config:
                config = provided_config
                config_file_path = get_config_file_path(args.SRA_Metadata)
                use_config_file = True
                is_template_config = False
                print(f"Using config file from previous run: {args.config_file}")
                print(f"Configuration will be updated in: {config_file_path}")
                config['date_time'] = datetime.now().isoformat()
                print(f"Updated timestamp: {config['date_time']}")
            else:
                print(f"Warning: Could not load config file {args.config_file}")
                print("Falling back to template + interactive prompts.")
                config_source = 'template'

        if config_source == 'template':
            template_config = load_template_config()
            if template_config:
                config = template_config.copy()
                config_file_path = get_config_file_path(args.SRA_Metadata)

                if os.path.exists(config_file_path) and not args.force:
                    overwrite_choice = get_config_value(
                        config,
                        'overwrite_custom_config',
                        get_valid_user_choice,
                        f"Configuration file '{config_file_path}' already exists. Do you want to overwrite it? [y/N]: ",
                        False,
                        f"Configuration file '{config_file_path}' already exists. Do you want to overwrite it? [y/N]: ",
                        ["y", "yes", "n", "no"],
                        default="n"
                    )
                    if overwrite_choice not in ("y", "yes"):
                        print("Aborted by user. No config file will be created.")
                        return
                    print(f"Will overwrite existing config file: {config_file_path}")
                elif os.path.exists(config_file_path) and args.force:
                    print(f"Config file exists. Using --force flag: automatically overwriting {config_file_path}")

                use_config_file = False  # Force interactive answers; template only seeds structure
                is_template_config = True
                print(f"Using template as base. Interactive prompts will update: {config_file_path}")
                print(f"Template file remains unchanged: {get_config_template_path()}")
                config['command'] = ' '.join(sys.argv)
                config['date_time'] = datetime.now().isoformat()
                config['qa_pairs'] = []
                config['generated_files'] = []
            else:
                print("Could not load template. Proceeding with interactive questions.")
                config = {}
                config_file_path = get_config_file_path(args.SRA_Metadata)
                is_template_config = False
                use_config_file = False
    
    # Initialize with basic run info if not present
    if 'command' not in config:
        config['command'] = ' '.join(sys.argv)
        config['date_time'] = datetime.now().isoformat()
        config['qa_pairs'] = []
        config['generated_files'] = []
    
    # Check if output file exists and handle --force
    if os.path.exists(args.SRA_Metadata) and not args.force:
        response = get_config_value(
            config,
            'overwrite_output_file',
            get_valid_user_choice,
            f"File '{args.SRA_Metadata}' already exists. Overwrite? [y/N]: ",
            use_config_file,
            f"File '{args.SRA_Metadata}' already exists. Overwrite? [y/N]: ",
            ["y", "yes", "n", "no"],
            default="n"
        )
        if response not in ('y', 'yes'):
            print('Aborted by user. No file overwritten.')
            return

    # STEP 1: Read SRA template and create SRA metadata structure
    print(f"Reading SRA template from: {args.SRA_Template}")
    try:
        # First, try to read the Excel file to get sheet names
        template_excel = pd.ExcelFile(args.SRA_Template, engine='openpyxl')
        sheet_names = template_excel.sheet_names
        template_excel.close()
        
        # Look for SRA_data sheet (or similar)
        sra_sheet = None
        for sheet in sheet_names:
            if 'sra_data' in sheet.lower() or 'sra' in sheet.lower():
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
        
        # Read the SRA template sheet - first check the structure
        try:
            # Try with header=2 (3rd row) first
            sra_template_df = pd.read_excel(args.SRA_Template, sheet_name=sra_sheet, header=2, engine='openpyxl')
        except Exception as e1:
            try:
                # Try with header=1 (2nd row)
                sra_template_df = pd.read_excel(args.SRA_Template, sheet_name=sra_sheet, header=1, engine='openpyxl')
            except Exception as e2:
                try:
                    # Try with header=0 (1st row)
                    sra_template_df = pd.read_excel(args.SRA_Template, sheet_name=sra_sheet, header=0, engine='openpyxl')
                except Exception as e3:
                    print(f"Error: Could not read SRA template file with any header position")
                    return
        
    except Exception as e:
        print(f"Error reading SRA template file: {e}")
        return

    # Extract allowed values from SRA template for platform and instrument_model
    def extract_allowed_values_from_template(template_df, column_name):
        """
        Extract allowed values for a column from the SRA template.
        Checks for data validation lists or unique values in the template.
        
        Args:
            template_df (pd.DataFrame): The SRA template DataFrame
            column_name (str): Name of the column to extract values for
        
        Returns:
            list: List of allowed values, or None if column not found
        """
        if column_name not in template_df.columns:
            return None
        
        # Get unique non-empty values from the template column
        unique_values = template_df[column_name].dropna().unique()
        unique_values = [str(v).strip() for v in unique_values if str(v).strip() != '']
        
        # Filter out common placeholder values
        filtered_values = []
        for val in unique_values:
            val_lower = val.lower()
            if val_lower not in ['', 'nan', 'none', 'n/a', 'na', 'example', 'placeholder']:
                filtered_values.append(val)
        
        return filtered_values if filtered_values else None
    
    # Extract allowed platform and instrument_model values from template
    template_allowed_platforms = extract_allowed_values_from_template(sra_template_df, 'platform')
    template_allowed_instruments = extract_allowed_values_from_template(sra_template_df, 'instrument_model')
    
    # Fallback to hardcoded lists if template doesn't have values
    if not template_allowed_platforms:
        template_allowed_platforms = [
            '_LS454', 'ABI_SOLID', 'BGISEQ', 'CAPILLARY', 'COMPLETE_GENOMICS',
            'DNBSEQ', 'ELEMENT', 'GENAPSYS', 'GENEMIND', 'HELICOS', 'ILLUMINA',
            'ION_TORRENT', 'OXFORD_NANOPORE', 'PACBIO_SMRT', 'TAPESTRI',
            'ULTIMA', 'VELA_DIAGNOSTICS'
        ]
        print("Info: No platform values found in SRA template. Using standard NCBI platform list.")
    
    if not template_allowed_instruments:
        # Collect all instruments from the hardcoded mapping
        all_instruments = set()
        platform_instruments = {
            '_LS454': ['454 GS', '454 GS 20', '454 GS FLX', '454 GS FLX+', '454 GS FLX Titanium', '454 GS Junior'],
            'ILLUMINA': ['HiSeq X Five', 'HiSeq X Ten', 'Illumina Genome Analyzer', 'Illumina Genome Analyzer II', 'Illumina Genome Analyzer IIx', 'Illumina HiScanSQ', 'Illumina HiSeq 1000', 'Illumina HiSeq 1500', 'Illumina HiSeq 2000', 'Illumina HiSeq 2500', 'Illumina HiSeq 3000', 'Illumina HiSeq 4000', 'Illumina HiSeq X', 'Illumina MiSeq', 'Illumina MiniSeq', 'Illumina NovaSeq 6000', 'Illumina NovaSeq X', 'Illumina NovaSeq X Plus', 'Illumina iSeq 100', 'NextSeq 1000', 'NextSeq 2000', 'NextSeq 500', 'NextSeq 550'],
            'HELICOS': ['Helicos HeliScope'],
            'ABI_SOLID': ['AB 5500 Genetic Analyzer', 'AB 5500xl Genetic Analyzer', 'AB 5500x-Wl Genetic Analyzer', 'AB SOLiD 3 Plus System', 'AB SOLiD 4 System', 'AB SOLiD 4hq System', 'AB SOLiD PI System', 'AB SOLiD System', 'AB SOLiD System 2.0', 'AB SOLiD System 3.0'],
            'COMPLETE_GENOMICS': ['Complete Genomics'],
            'PACBIO_SMRT': ['PacBio RS', 'PacBio RS II', 'Revio', 'Sequel', 'Sequel II', 'Sequel IIe', 'Onso'],
            'ION_TORRENT': ['Ion Torrent PGM', 'Ion Torrent Proton', 'Ion Torrent S5 XL', 'Ion Torrent S5', 'Ion Torrent Genexus', 'Ion GeneStudio S5', 'Ion GeneStudio S5 Plus', 'Ion GeneStudio S5 Prime'],
            'CAPILLARY': ['AB 310 Genetic Analyzer', 'AB 3130 Genetic Analyzer', 'AB 3130xL Genetic Analyzer', 'AB 3500 Genetic Analyzer', 'AB 3500xL Genetic Analyzer', 'AB 3730 Genetic Analyzer', 'AB 3730xL Genetic Analyzer'],
            'OXFORD_NANOPORE': ['GridION', 'MinION', 'PromethION'],
            'BGISEQ': ['BGISEQ-50', 'BGISEQ-500', 'MGISEQ-2000RS'],
            'DNBSEQ': ['DNBSEQ-G400', 'DNBSEQ-G50', 'DNBSEQ-T7', 'DNBSEQ-G400 FAST'],
            'ELEMENT': ['Element AVITI', 'Onso'],
            'GENAPSYS': ['GS111', 'FASTASeq 300'],
            'GENEMIND': ['GenoCare 1600', 'GenoLab M'],
            'TAPESTRI': ['Tapestri'],
            'ULTIMA': ['UG 100'],
            'VELA_DIAGNOSTICS': ['Sentosa SQ301']
        }
        for instruments in platform_instruments.values():
            all_instruments.update(instruments)
        template_allowed_instruments = sorted(list(all_instruments))
        print("Info: No instrument_model values found in SRA template. Using standard NCBI instrument model list.")
    
    # Create SRA_Metadata by copying the template structure
    print(f"\nCreating SRA metadata file: {args.SRA_Metadata}")
    
    # Copy the template structure to create the output file
    # We'll create a new DataFrame with the same columns as the template
    sra_output_df = pd.DataFrame(columns=sra_template_df.columns)
    
    # STEP 2: Read FAIRe metadata and handle assay selection
    erm_src = get_faire_sheet_source(args, "experimentRunMetadata")
    print(f"\nReading sample metadata from: {erm_src}")
    sample_df = read_faire_sheet_df(
        erm_src,
        "experimentRunMetadata",
        header=2,
        keep_default_na=False,
    )
    if sample_df is None:
        print(
            "Error: Could not read experimentRunMetadata. "
            "Provide --FAIReMetadata workbook or --experimentRunMetadata file."
        )
        return

    # STEP 2.5: Detect and handle bioprojects
    ncbi_accession_data = None
    detected_bioprojects = None
    if args.NCBI_accession_number:
        ncbi_accession_data = read_ncbi_accession_file(args.NCBI_accession_number)
        detected_bioprojects = ncbi_accession_data['bioprojects']
    
    bioproject_strategy = handle_bioproject_selection(config, use_config_file, detected_bioprojects, args)
    
    # Store bioproject strategy and NCBI accession data in config for later use
    config['bioproject_strategy'] = bioproject_strategy
    # Store ncbi_accession_data reference for later filtering and merging
    if ncbi_accession_data:
        config['_ncbi_accession_data'] = ncbi_accession_data

    # LIB_ID SELECTION
    if 'lib_id' not in sample_df.columns:
        print("Error: 'lib_id' column not found in experimentRunMetadata sheet.")
        return
    if 'assay_name' not in sample_df.columns:
        print("Error: 'assay_name' column not found in experimentRunMetadata sheet.")
        return

    print(f"\n" + "="*50)
    print("LIB_ID SELECTION")
    print("="*50)

    all_lib_ids = [
        x for x in sample_df['lib_id'].dropna().astype(str).str.strip().unique()
        if x != ""
    ]
    if len(all_lib_ids) == 0:
        print("Error: No valid lib_id values found in experimentRunMetadata.")
        return

    lib_choice = get_config_value(
        config,
        'lib_id_selection_choice',
        get_valid_user_choice,
        "Do you want to use all lib_id (fastq files) or only specific ones? [all/specific]: ",
        use_config_file,
        "Do you want to use all lib_id (fastq files) or only specific ones? [all/specific]: ",
        ["all", "specific"],
        default="all"
    )

    selected_lib_ids = all_lib_ids
    if lib_choice == "specific":
        selectable_cols = [c for c in ['samp_name', 'assay_name', 'seq_run_id'] if c in sample_df.columns]
        if not selectable_cols:
            print("Error: None of the selection columns are available: samp_name, assay_name, seq_run_id.")
            return

        print("Select column to define the lib_id subset:")
        for i, col in enumerate(selectable_cols, 1):
            extra = " (warning: this may include many samples)" if col == "samp_name" else ""
            print(f"  {i}. {col}{extra}")

        while True:
            raw_select_col = get_config_value(
                config,
                'lib_id_selection_column',
                input,
                f"Which column do you want to use to select lib_id? "
                f"(number 1-{len(selectable_cols)} or name [{'/'.join(selectable_cols)}], default {selectable_cols[0]}): ",
                use_config_file,
                f"Which column do you want to use to select lib_id? "
                f"(number 1-{len(selectable_cols)} or name [{'/'.join(selectable_cols)}], default {selectable_cols[0]}): ",
            ).strip()

            if not raw_select_col:
                select_col = selectable_cols[0]
                break

            if raw_select_col.isdigit():
                idx = int(raw_select_col) - 1
                if 0 <= idx < len(selectable_cols):
                    select_col = selectable_cols[idx]
                    break
                print(f"Invalid choice. Please enter a number between 1 and {len(selectable_cols)}.")
                continue

            if raw_select_col in selectable_cols:
                select_col = raw_select_col
                break

            print(
                f"Invalid choice. Please enter one of: {', '.join(selectable_cols)} "
                f"or a number between 1 and {len(selectable_cols)}."
            )
        if select_col == "samp_name":
            print("Warning: selecting by samp_name can represent many samples/lib_id values.")

        selectable_vals = [
            x for x in sample_df[select_col].dropna().astype(str).str.strip().unique()
            if x != ""
        ]
        if len(selectable_vals) == 0:
            print(f"Error: No valid values found in '{select_col}'.")
            return

        print(f"\nAvailable values in '{select_col}':")
        for i, val in enumerate(selectable_vals, 1):
            print(f"  {i}. {val}")
        print("\nEnter value numbers separated by commas (e.g., 1,3,5):")

        while True:
            user_input = get_config_value(
                config,
                f'lib_id_selected_values_input_{select_col}',
                input,
                f"Selected {select_col} values: ",
                use_config_file,
                f"Selected {select_col} values: "
            ).strip()

            if not user_input:
                print("No values selected. Using all lib_id values.")
                break

            selected_indices = []
            for item in user_input.split(','):
                item = item.strip()
                if item.isdigit():
                    idx = int(item) - 1
                    if 0 <= idx < len(selectable_vals):
                        selected_indices.append(idx)
                    else:
                        print(f"Warning: Invalid value number {item}")
                else:
                    print(f"Warning: '{item}' is not a valid number")

            if selected_indices:
                selected_values = [selectable_vals[i] for i in selected_indices]
                selected_lib_ids = [
                    x for x in sample_df[sample_df[select_col].astype(str).str.strip().isin(selected_values)]
                    ['lib_id'].dropna().astype(str).str.strip().unique()
                    if x != ""
                ]
                print(f"Selected {select_col} values: {', '.join(selected_values)}")
                break
            else:
                print("No valid values selected. Please try again.")

    # Filter sample_df to include only selected lib_id
    sample_df = sample_df[sample_df['lib_id'].astype(str).str.strip().isin(set(selected_lib_ids))]
    if len(sample_df) == 0:
        print("Error: No rows matched the selected lib_id criteria.")
        return
    selected_assays = [
        x for x in sample_df['assay_name'].dropna().astype(str).str.strip().unique()
        if x != ""
    ]
    if len(selected_assays) == 0:
        print("Error: No valid assay_name values found after lib_id selection.")
        return
    print(f"Processing {len(sample_df)} rows from {len(set(selected_lib_ids))} selected lib_id values across {len(selected_assays)} assays.")

    try:
        from FAIRe2BioSample import apply_experiment_run_metadata_associated_sequences_filter
    except ImportError:
        apply_experiment_run_metadata_associated_sequences_filter = None
    if apply_experiment_run_metadata_associated_sequences_filter:
        sample_df, sra_output_df = apply_experiment_run_metadata_associated_sequences_filter(
            erm_src,
            sample_df,
            sra_output_df,
            config,
            use_config_file,
            get_config_value_fn=get_config_value,
        )

    # Set only when apply_experiment_run_metadata_associated_sequences_filter actually applied blank_only
    sra_erm_blank_only = bool(config.get("_faire_erm_blank_only_rows_applied"))
    if sra_erm_blank_only and len(sample_df) > 0:
        sample_df = replace_sample_df_with_erm_blank_associated_rows(
            erm_src, sample_df, selected_assays
        )
    config.pop("_faire_erm_blank_only_rows_applied", None)
    
    # Read sampleMetadata sheet for organism and geo_loc_name information
    sample_meta_src = get_faire_sheet_source(args, "sampleMetadata")
    sample_metadata_df = read_faire_sheet_df(sample_meta_src, "sampleMetadata", header=2)
    if sample_metadata_df is None:
        print(
            "Warning: Could not read sampleMetadata "
            "(expected --FAIReMetadata workbook or --sampleMetadata)."
        )
        sample_metadata_df = None
    
    # Function to create title for each library_ID
    def create_library_title(lib_id, assay_name, sample_df, sample_metadata_df):
        """Create title for a specific library_ID using sampleMetadata fields."""
        try:
            # Find the sample row that matches this lib_id
            sample_row = sample_df[sample_df['lib_id'] == lib_id]
            
            if len(sample_row) == 0:
                return f"{lib_id}: {assay_name} metabarcoding"
            
            sample_row = sample_row.iloc[0]  # Get the first (and should be only) row
            samp_name = sample_row.get('samp_name', 'NA')
            
            # Clean up samp_name
            if pd.isna(samp_name) or str(samp_name).strip() == '':
                samp_name = 'NA'
            else:
                samp_name = str(samp_name).strip()
            
            # Get organism and geo_loc_name from sampleMetadata sheet
            organism = 'NA'
            geo_loc_name = 'NA'
            
            if sample_metadata_df is not None and samp_name != 'NA':
                # Check if samp_name column exists
                if 'samp_name' not in sample_metadata_df.columns:
                    # Try to find a similar column name
                    possible_name_columns = [col for col in sample_metadata_df.columns if 'name' in col.lower() or 'sample' in col.lower()]
                    if possible_name_columns:
                        name_column = possible_name_columns[0]
                    else:
                        name_column = None
                else:
                    name_column = 'samp_name'
                
                if name_column:
                    # Find the row in sampleMetadata that matches this samp_name
                    sample_metadata_row = sample_metadata_df[sample_metadata_df[name_column] == samp_name]
                    
                    if len(sample_metadata_row) > 0:
                        sample_metadata_row = sample_metadata_row.iloc[0]
                        
                        # Get organism and geo_loc_name
                        organism_val = sample_metadata_row.get('organism', 'NA')
                        geo_loc_val = sample_metadata_row.get('geo_loc_name', 'NA')
                    
                    # Clean up the values
                    if pd.isna(organism_val) or str(organism_val).strip() == '':
                        organism = 'NA'
                    else:
                        organism = str(organism_val).strip()
                    
                    if pd.isna(geo_loc_val) or str(geo_loc_val).strip() == '':
                        geo_loc_name = 'NA'
                    else:
                        geo_loc_name = str(geo_loc_val).strip()
            
            # Create the title
            title = f"{samp_name}: {assay_name} metabarcoding of {organism} in {geo_loc_name}"
            
            return title
            
        except Exception as e:
            print(f"Warning: Error creating title for library_ID '{lib_id}': {e}")
            return f"{lib_id}: {assay_name} metabarcoding"
    
    # Show title creation preview
    print(f"\n" + "="*50)
    print("TITLE CREATION")
    print("="*50)
    
    # Determine which fields are being used
    fields_used = []
    if sample_metadata_df is not None:
        if 'samp_name' in sample_metadata_df.columns:
            fields_used.append('samp_name')
        if 'organism' in sample_metadata_df.columns:
            fields_used.append('organism')
        if 'geo_loc_name' in sample_metadata_df.columns:
            fields_used.append('geo_loc_name')
    
    if fields_used:
        print(f"Creating titles for each library_ID using assay_name and sampleMetadata fields: {', '.join(fields_used)}")
    else:
        print("Using fields: None (fallback to basic titles)")
    
    # Count successful title creations
    successful_titles = 0
    total_lib_ids = len(sample_df['lib_id'].unique())
    
    for lib_id in sample_df['lib_id'].unique():
        sample_row = sample_df[sample_df['lib_id'] == lib_id].iloc[0]
        assay_name = sample_row['assay_name']
        try:
            title = create_library_title(lib_id, assay_name, sample_df, sample_metadata_df)
            if title and title != f"{lib_id}: {assay_name} metabarcoding":
                successful_titles += 1
        except:
            pass  # Silently handle errors
    
    print(f"Successfully created {successful_titles} library titles with full metadata.")
    
    # Check if required columns exist in SRA template
    required_sra_columns = ['library_ID', 'filename', 'filename2', 'library_layout', 'library_strategy', 'library_source', 'library_selection', 'platform']
    missing_sra_columns = [col for col in required_sra_columns if col not in sra_output_df.columns]
    if missing_sra_columns:
        print(f"\nWarning: Missing required SRA columns: {missing_sra_columns}")
        print("Some mappings may not work correctly.")
    
    # Check if required columns exist in FAIRe metadata
    required_faire_columns = ['lib_id', 'filename', 'filename2']
    missing_faire_columns = [col for col in required_faire_columns if col not in sample_df.columns]
    if missing_faire_columns:
        print(f"\nError: Missing required FAIRe columns: {missing_faire_columns}")
        return
    
    # Read project metadata for platform and instrument_model information
    try:
        project_src = get_faire_sheet_source(args, "projectMetadata")
        project_df = read_faire_sheet_df(project_src, "projectMetadata", header=0)
        if project_df is None:
            raise ValueError("projectMetadata could not be read")
        
        # Find platform row in term_name column (column 3)
        platform_row = None
        for idx, row in project_df.iterrows():
            if str(row.iloc[2]).strip().lower() == 'platform':  # column 3 (index 2)
                platform_row = row
                break
        
        if platform_row is None:
            project_platform = None
        else:
            project_platform = str(platform_row.iloc[3]).strip()  # column 4 (index 3) - project_level
            # Check if the value is actually empty/null/nan
            if not project_platform or project_platform.lower() in ['nan', 'none', '']:
                project_platform = None
        
        # Find instrument row in term_name column (column 3)
        instrument_row = None
        for idx, row in project_df.iterrows():
            term_name = str(row.iloc[2]).strip().lower()
            if term_name == 'instrument' or term_name == 'instrument_model':  # column 3 (index 2)
                instrument_row = row
                break
        
        if instrument_row is None:
            project_instrument_model = None
        else:
            project_instrument_model = str(instrument_row.iloc[3]).strip()  # column 4 (index 3) - project_level
            # Check if the value is actually empty/null/nan
            if not project_instrument_model or project_instrument_model.lower() in ['nan', 'none', '']:
                project_instrument_model = None
            
    except Exception as e:
        print(f"Warning: Could not read projectMetadata sheet: {e}")
        project_platform = None
        project_instrument_model = None
    
    # Function to get allowed values for library fields
    def get_allowed_values(field_name):
        """Get allowed values for a specific field from the predefined lists."""
        # Hardcoded allowed values from NCBI SRA standards
        allowed_values = {
            'library_strategy': [
                'WGA', 'WGS', 'WXS', 'RNA-Seq', 'miRNA-Seq', 'WCS', 'CLONE', 'POOLCLONE', 
                'AMPLICON', 'CLONEEND', 'FINISHING', 'ChIP-Seq', 'MNase-Seq', 
                'DNase-Hypersensitivity', 'Bisulfite-Seq', 'Tn-Seq', 'EST', 'FL-cDNA', 
                'CTS', 'MRE-Seq', 'MeDIP-Seq', 'MBD-Seq', 'Synthetic-Long-Read', 
                'ATAC-seq', 'ChIA-PET', 'FAIRE-seq', 'Hi-C', 'ncRNA-Seq', 'RAD-Seq', 
                'RIP-Seq', 'SELEX', 'ssRNA-seq', 'Targeted-Capture', 
                'Tethered Chromatin Conformation Capture', 'DIP-Seq', 'GBS', 
                'Inverse rRNA', 'NOMe-Seq', 'Ribo-seq', 'VALIDATION', 'OTHER'
            ],
            'library_source': [
                'GENOMIC', 'TRANSCRIPTOMIC', 'METAGENOMIC', 'METATRANSCRIPTOMIC', 
                'SYNTHETIC', 'VIRAL RNA', 'GENOMIC SINGLE CELL', 
                'TRANSCRIPTOMIC SINGLE CELL', 'OTHER'
            ],
            'library_selection': [
                'RANDOM', 'PCR', 'RANDOM PCR', 'RT-PCR', 'HMPR', 'MF', 'CF-S', 'CF-M', 
                'CF-H', 'CF-T', 'MDA', 'MSLL', 'cDNA', 'ChIP', 'MNase', 'DNAse', 
                'Hybrid Selection', 'Reduced Representation', 'Restriction Digest', 
                '5-methylcytidine antibody', 'MBD2 protein methyl-CpG binding domain', 
                'CAGE', 'RACE', 'size fractionation', 'Padlock probes capture method', 
                'other', 'unspecified', 'cDNA_oligo_dT', 'cDNA_randomPriming', 
                'Inverse rRNA', 'Oligo-dT', 'PolyA', 'repeat fractionation'
            ]
        }
        
        return allowed_values.get(field_name, [])
    
    # Ask user for library field preferences
    library_fields = {
        'library_strategy': 'AMPLICON',
        'library_source': 'METAGENOMIC', 
        'library_selection': 'PCR'
    }
    
    print(f"\n" + "="*50)
    print("LIBRARY FIELD CONFIGURATION")
    print("="*50)
    for field, default_value in library_fields.items():
        print(f"\n{field.replace('_', ' ').title()}:")
        print(f"  Default value: {default_value}")
        
        choice = normalize_library_field_choice(get_config_value(
            config,
            f'library_field_{field}_choice',
            get_valid_user_choice,
            library_field_choice_prompt(field),
            use_config_file,
            library_field_choice_prompt(field),
            [LIBRARY_FIELD_CHOICE_DEFAULT, LIBRARY_FIELD_CHOICE_OTHER],
            default=LIBRARY_FIELD_CHOICE_DEFAULT
        ))
        
        if is_library_field_other_choice(choice):
            print(f"  Reading allowed values from SRA template...")
            allowed_values = get_allowed_values(field)
            
            if allowed_values:
                print(f"  Allowed values for {field}:")
                for i, val in enumerate(allowed_values, 1):
                    print(f"    {i:2d}. {val}")
                
                while True:
                    try:
                        user_input = get_config_value(
                            config,
                            f'library_field_{field}_value',
                            input,
                            f"  Enter {field} value (number or term): ",
                            use_config_file,
                            f"  Enter {field} value (number or term): "
                        ).strip()
                        
                        # Check if input is a number
                        if user_input.isdigit():
                            idx = int(user_input) - 1
                            if 0 <= idx < len(allowed_values):
                                selected_value = allowed_values[idx]
                                library_fields[field] = selected_value
                                print(f"  Selected: {selected_value}")
                                break
                            else:
                                print(f"  Error: Number {user_input} is out of range (1-{len(allowed_values)})")
                        # Check if input is a term
                        elif user_input in allowed_values:
                            library_fields[field] = user_input
                            print(f"  Selected: {user_input}")
                            break
                        else:
                            print(f"  Error: '{user_input}' is not a valid number or term.")
                            print(f"  Please enter a number (1-{len(allowed_values)}) or choose from: {', '.join(allowed_values)}")
                    except KeyboardInterrupt:
                        print("\nOperation cancelled by user.")
                        return
            else:
                print(f"  Warning: No allowed values found for {field}, using default.")
        else:
            print(f"  Using default value: {default_value}")
    
    # Function to get platform value for a single assay
    def get_assay_platform(assay_name):
        """Get platform value for a specific assay."""
        try:
            # Find the platform row in projectMetadata
            platform_row_idx = None
            for idx, row in project_df.iterrows():
                if str(row.iloc[2]).strip().lower() == 'platform':  # column 3 (index 2)
                    platform_row_idx = idx
                    break
            
            if platform_row_idx is not None:
                platform_row = project_df.iloc[platform_row_idx]
                
                # Look for the assay column in the projectMetadata sheet
                for col_idx, col_name in enumerate(project_df.columns):
                    if str(col_name).strip() == assay_name:
                        # Found the assay column, get platform value from that column
                        assay_platform = str(platform_row.iloc[col_idx]).strip()
                        if assay_platform and assay_platform.lower() not in ['nan', 'none', '']:
                            return assay_platform
                        break
        except Exception as e:
            print(f"Warning: Error reading platform for assay '{assay_name}': {e}")
        
        return None
    
    # Function to get instrument_model value for a single assay
    def get_assay_instrument_model(assay_name):
        """Get instrument_model value for a specific assay."""
        # First, prefer values directly provided in experimentRunMetadata (column: instrument)
        if 'instrument' in sample_df.columns and 'assay_name' in sample_df.columns:
            vals = []
            assay_rows = sample_df[sample_df['assay_name'] == assay_name]
            for v in assay_rows['instrument'].tolist():
                s = str(v).strip() if pd.notna(v) else ''
                if s and s.lower() not in ['nan', 'none', '']:
                    vals.append(s)
            vals = list(dict.fromkeys(vals))
            if len(vals) == 1:
                return vals[0]
            if len(vals) > 1:
                print(
                    f"Warning: multiple instrument values found in experimentRunMetadata for assay '{assay_name}'. "
                    f"Using first value: {vals[0]}"
                )
                return vals[0]

        try:
            # Find the instrument row in projectMetadata
            instrument_row_idx = None
            for idx, row in project_df.iterrows():
                term_name = str(row.iloc[2]).strip().lower()
                if term_name == 'instrument' or term_name == 'instrument_model':  # column 3 (index 2)
                    instrument_row_idx = idx
                    break
            
            if instrument_row_idx is not None:
                instrument_row = project_df.iloc[instrument_row_idx]
                
                # Look for the assay column in the projectMetadata sheet
                for col_idx, col_name in enumerate(project_df.columns):
                    if str(col_name).strip() == assay_name:
                        # Found the assay column, get instrument_model value from that column
                        assay_instrument_model = str(instrument_row.iloc[col_idx]).strip()
                        if assay_instrument_model and assay_instrument_model.lower() not in ['nan', 'none', '']:
                            return assay_instrument_model
                        break
        except Exception as e:
            print(f"Warning: Error reading instrument_model for assay '{assay_name}': {e}")
        
        return None
    
    # Function to get user input for platform
    def get_user_platform():
        """Get platform value from user with suggestions."""
        allowed_platforms = [
            '_LS454', 'ABI_SOLID', 'BGISEQ', 'CAPILLARY', 'COMPLETE_GENOMICS',
            'DNBSEQ', 'ELEMENT', 'GENAPSYS', 'GENEMIND', 'HELICOS', 'ILLUMINA',
            'ION_TORRENT', 'OXFORD_NANOPORE', 'PACBIO_SMRT', 'TAPESTRI',
            'ULTIMA', 'VELA_DIAGNOSTICS'
        ]
        
        print("Suggested platforms:")
        for i, platform in enumerate(allowed_platforms, 1):
            print(f"  {i:2d}. {platform}")
        
        while True:
            try:
                user_input = get_config_value(
                    config,
                    'platform_value_input',
                    input,
                    "Enter platform value (number or name): ",
                    use_config_file,
                    "Enter platform value (number or name): "
                ).strip()
                
                # Check if input is a number
                if user_input.isdigit():
                    idx = int(user_input) - 1
                    if 0 <= idx < len(allowed_platforms):
                        return allowed_platforms[idx]
                    else:
                        print(f"Error: Number {user_input} is out of range (1-{len(allowed_platforms)})")
                # Check if input is a platform name
                elif user_input.upper() in [p.upper() for p in allowed_platforms]:
                    # Find the exact case match
                    for platform in allowed_platforms:
                        if platform.upper() == user_input.upper():
                            return platform
                else:
                    print(f"Error: '{user_input}' is not a valid platform.")
                    print(f"Please enter a number (1-{len(allowed_platforms)}) or choose from: {', '.join(allowed_platforms)}")
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                return None
    
    # Function to create assay description from projectMetadata
    def create_assay_description(assay_name):
        """Create description for a specific assay using projectMetadata fields."""
        try:
            # Define the fields we need to look for
            fields_to_find = {
                'target_gene': None,
                'target_subfragment': None,
                'pcr_primer_name_forward': None,
                'pcr_primer_forward': None,
                'pcr_primer_name_reverse': None,
                'pcr_primer_reverse': None,
                'nucl_acid_amp': None
            }
            
            # Find each field in the projectMetadata
            for field_name in fields_to_find.keys():
                for idx, row in project_df.iterrows():
                    if str(row.iloc[2]).strip().lower() == field_name.lower():  # column 3 (index 2)
                        # Found the field row, now look for the assay column
                        for col_idx, col_name in enumerate(project_df.columns):
                            if str(col_name).strip() == assay_name:
                                # Found the assay column, get the value
                                field_value = str(row.iloc[col_idx]).strip()
                                if field_value and field_value.lower() not in ['nan', 'none', '']:
                                    fields_to_find[field_name] = field_value
                                else:
                                    fields_to_find[field_name] = 'NA'
                                break
                        break
            
            # Create the description
            description = f"Metabarcoding of {fields_to_find['target_gene'] or 'NA'} gene {fields_to_find['target_subfragment'] or 'NA'} region using PCR primers {fields_to_find['pcr_primer_name_forward'] or 'NA'} ({fields_to_find['pcr_primer_forward'] or 'NA'}) and {fields_to_find['pcr_primer_name_reverse'] or 'NA'} ({fields_to_find['pcr_primer_reverse'] or 'NA'}) using protocol at {fields_to_find['nucl_acid_amp'] or 'NA'}"
            
            return description
            
        except Exception as e:
            print(f"Warning: Error creating description for assay '{assay_name}': {e}")
            return "NA"
    
    # Function to get user input for instrument_model
    def get_user_instrument_model(platform_value=None):
        """Get instrument_model value from user with platform-specific suggestions."""
        # Platform to instrument mapping
        platform_instruments = {
            '_LS454': ['454 GS', '454 GS 20', '454 GS FLX', '454 GS FLX+', '454 GS FLX Titanium', '454 GS Junior'],
            'ILLUMINA': ['HiSeq X Five', 'HiSeq X Ten', 'Illumina Genome Analyzer', 'Illumina Genome Analyzer II', 'Illumina Genome Analyzer IIx', 'Illumina HiScanSQ', 'Illumina HiSeq 1000', 'Illumina HiSeq 1500', 'Illumina HiSeq 2000', 'Illumina HiSeq 2500', 'Illumina HiSeq 3000', 'Illumina HiSeq 4000', 'Illumina HiSeq X', 'Illumina MiSeq', 'Illumina MiniSeq', 'Illumina NovaSeq 6000', 'Illumina NovaSeq X', 'Illumina NovaSeq X Plus', 'Illumina iSeq 100', 'NextSeq 1000', 'NextSeq 2000', 'NextSeq 500', 'NextSeq 550'],
            'HELICOS': ['Helicos HeliScope'],
            'ABI_SOLID': ['AB 5500 Genetic Analyzer', 'AB 5500xl Genetic Analyzer', 'AB 5500x-Wl Genetic Analyzer', 'AB SOLiD 3 Plus System', 'AB SOLiD 4 System', 'AB SOLiD 4hq System', 'AB SOLiD PI System', 'AB SOLiD System', 'AB SOLiD System 2.0', 'AB SOLiD System 3.0'],
            'COMPLETE_GENOMICS': ['Complete Genomics'],
            'PACBIO_SMRT': ['PacBio RS', 'PacBio RS II', 'Revio', 'Sequel', 'Sequel II', 'Sequel IIe', 'Onso'],
            'ION_TORRENT': ['Ion Torrent PGM', 'Ion Torrent Proton', 'Ion Torrent S5 XL', 'Ion Torrent S5', 'Ion Torrent Genexus', 'Ion GeneStudio S5', 'Ion GeneStudio S5 Plus', 'Ion GeneStudio S5 Prime'],
            'CAPILLARY': ['AB 310 Genetic Analyzer', 'AB 3130 Genetic Analyzer', 'AB 3130xL Genetic Analyzer', 'AB 3500 Genetic Analyzer', 'AB 3500xL Genetic Analyzer', 'AB 3730 Genetic Analyzer', 'AB 3730xL Genetic Analyzer'],
            'OXFORD_NANOPORE': ['GridION', 'MinION', 'PromethION'],
            'BGISEQ': ['BGISEQ-50', 'BGISEQ-500', 'MGISEQ-2000RS'],
            'DNBSEQ': ['DNBSEQ-G400', 'DNBSEQ-G50', 'DNBSEQ-T7', 'DNBSEQ-G400 FAST'],
            'ELEMENT': ['Element AVITI', 'Onso'],
            'GENAPSYS': ['GS111', 'FASTASeq 300'],
            'GENEMIND': ['GenoCare 1600', 'GenoLab M'],
            'TAPESTRI': ['Tapestri'],
            'ULTIMA': ['UG 100'],
            'VELA_DIAGNOSTICS': ['Sentosa SQ301']
        }
        
        if platform_value and platform_value in platform_instruments:
            print(f"\nSuggested instrument models for platform '{platform_value}':")
            for i, instrument in enumerate(platform_instruments[platform_value], 1):
                print(f"  {i:2d}. {instrument}")
            
            while True:
                try:
                    user_input = get_config_value(
                        config,
                        f'instrument_model_input_{platform_value}',
                        input,
                        f"\nEnter instrument model number (1-{len(platform_instruments[platform_value])}) or type Other value: ",
                        use_config_file,
                        f"\nEnter instrument model number (1-{len(platform_instruments[platform_value])}) or type Other value: "
                    ).strip()
                    
                    # Check if input is a number
                    if user_input.isdigit():
                        idx = int(user_input) - 1
                        if 0 <= idx < len(platform_instruments[platform_value]):
                            selected_instrument = platform_instruments[platform_value][idx]
                            print(f"Selected: {selected_instrument}")
                            return selected_instrument
                        else:
                            print(f"Error: Number {user_input} is out of range (1-{len(platform_instruments[platform_value])})")
                    else:
                        # Other input
                        if user_input:
                            print(f"Using Other instrument model: {user_input}")
                            return user_input
                        else:
                            print("Instrument model cannot be empty. Please enter a value.")
                except KeyboardInterrupt:
                    print("\nOperation cancelled by user.")
                    return None
        else:
            # No platform value or platform not in mapping, show all options
            print("Available instrument models by platform:")
            for platform, instruments in platform_instruments.items():
                print(f"\n{platform}:")
                for instrument in instruments:
                    print(f"  - {instrument}")
            
            print("\nEnter instrument model value:")
            while True:
                try:
                    user_input = get_config_value(
                        config,
                        'instrument_model_Other_input',
                        input,
                        "Enter instrument model: ",
                        use_config_file,
                        "Enter instrument model: "
                    ).strip()
                    if user_input:
                        return user_input
                    else:
                        print("Instrument model cannot be empty. Please enter a value.")
                except KeyboardInterrupt:
                    print("\nOperation cancelled by user.")
                    return None
    
    platform_value = None
    instrument_model_value = None
    
    # Process platform configuration for all assays
    final_platform_values = {}
    
    print(f"\n" + "="*50)
    print("PLATFORM VALUES CONFIGURATION")
    print("="*50)
    if project_platform:
        print(f"Project-level platform: {project_platform}")
    else:
        print("Project-level platform: Not found")
    
    # Check if we have different platform values across assays
    assay_platforms = {}
    has_different_platforms = False
        
    for assay in selected_assays:
        assay_platform = get_assay_platform(assay)
        assay_platforms[assay] = assay_platform
        if assay_platform and project_platform and assay_platform != project_platform:
            has_different_platforms = True
    
    # If we have different platform values, ask user for each assay
    if has_different_platforms:
        print(f"\nDifferent platform values found across assays:")
        for assay in selected_assays:
            assay_platform = assay_platforms[assay]
        if assay_platform:
                print(f"  {assay}: {assay_platform}")
        else:
                print(f"  {assay}: Not found")
        print()
        
        # Ask user for each assay individually
        for assay in selected_assays:
            assay_platform = assay_platforms[assay]
            if assay_platform and project_platform and assay_platform != project_platform:
                # Ask individual question for this assay
                choice = get_config_value(
                    config,
                    f'platform_choice_{assay}',
                    get_valid_user_choice,
                    f"Assay '{assay}' has different platform values:\n    Assay-specific: {assay_platform}\n    Project-level: {project_platform}\n  Which one do you want to use? [Assay/Project]: ",
                    use_config_file,
                    f"Assay '{assay}' has different platform values:\n    Assay-specific: {assay_platform}\n    Project-level: {project_platform}\n  Which one do you want to use? [Assay/Project]: ",
                    ["assay", "project"],
                    default="assay"
                )
                
                if choice == "assay":
                    print(f"  Using assay-specific platform for '{assay}': {assay_platform}")
                    final_platform_values[assay] = assay_platform
                else:
                    print(f"  Using project-level platform for '{assay}': {project_platform}")
                    final_platform_values[assay] = project_platform
            else:
                # Use available values
                if assay_platform:
                    final_platform_values[assay] = assay_platform
                elif project_platform:
                    final_platform_values[assay] = project_platform
                else:
                    print(f"  No platform value found for assay '{assay}'. Please enter platform value:")
                    user_platform = get_user_platform()
                    if user_platform:
                        final_platform_values[assay] = user_platform
                    else:
                        print("Operation cancelled by user.")
                        return
    else:
        # No different platforms, use available values
        for assay in selected_assays:
            assay_platform = assay_platforms[assay]
            if assay_platform and project_platform and assay_platform == project_platform:
                print(f"  Platform value '{assay_platform}' used for assay '{assay}' (same as project-level)")
                final_platform_values[assay] = assay_platform
            elif assay_platform:
                print(f"  Platform value '{assay_platform}' used for assay '{assay}' (assay-specific only)")
                final_platform_values[assay] = assay_platform
            elif project_platform:
                print(f"  Platform value '{project_platform}' used for assay '{assay}' (project-level only)")
                final_platform_values[assay] = project_platform
            else:
                print(f"  No platform value found for assay '{assay}'. Please enter platform value:")
                user_platform = get_user_platform()
                if user_platform:
                    final_platform_values[assay] = user_platform
                else:
                    print("Operation cancelled by user.")
                    return
    
    # For single assay, use the single value; for multiple assays, we'll handle them individually in mapping
    if len(selected_assays) == 1:
        platform_value = list(final_platform_values.values())[0]
        print(f"\nFinal platform value: {platform_value}")
    else:
        # For multiple assays, we'll use the individual values during mapping
        platform_value = None  # Will be handled per assay during mapping
        print(f"\nFinal platform values determined:")
        for assay, platform in final_platform_values.items():
            print(f"  {assay}: {platform}")
    
    if not final_platform_values:
        print("No platform value determined. Exiting.")
        return

    # Pre-check instrument values per selected lib_id in experimentRunMetadata.
    # If missing, optionally let user provide values before assay-level prompts.
    selected_lib_ids = [
        x for x in sample_df['lib_id'].dropna().astype(str).str.strip().unique()
        if x != ""
    ]
    if 'instrument' in sample_df.columns and selected_lib_ids:
        print(f"\n" + "="*50)
        print("LIB_ID INSTRUMENT PRE-CHECK")
        print("="*50)
        missing_lib_ids = []
        for lib_id in selected_lib_ids:
            vals = sample_df[sample_df['lib_id'].astype(str).str.strip() == lib_id]['instrument'].tolist()
            has_value = False
            for v in vals:
                s = str(v).strip() if pd.notna(v) else ''
                if s and s.lower() not in ['nan', 'none', '']:
                    has_value = True
                    break
            if not has_value:
                missing_lib_ids.append(lib_id)

        if missing_lib_ids:
            print(f"Missing instrument value for {len(missing_lib_ids)} selected lib_id values.")
            fill_missing = get_config_value(
                config,
                'instrument_missing_libid_fill_choice',
                get_valid_user_choice,
                "Do you want to provide instrument values for missing lib_id entries? [y/N]: ",
                use_config_file,
                "Do you want to provide instrument values for missing lib_id entries? [y/N]: ",
                ["y", "yes", "n", "no"],
                default="n"
            )
            if fill_missing in ("y", "yes"):
                for lib_id in missing_lib_ids:
                    user_val = get_config_value(
                        config,
                        f'instrument_value_for_libid_{lib_id}',
                        input,
                        f"Enter instrument value for lib_id '{lib_id}' (or press Enter to skip): ",
                        use_config_file,
                        f"Enter instrument value for lib_id '{lib_id}' (or press Enter to skip): "
                    ).strip()
                    if user_val:
                        sample_df.loc[
                            sample_df['lib_id'].astype(str).str.strip() == lib_id, 'instrument'
                        ] = user_val
        else:
            print("Instrument value found for each selected lib_id in experimentRunMetadata.")
    
    # Process instrument model configuration for all assays
    final_instrument_model_values = {}
    
    print(f"\n" + "="*50)
    print("INSTRUMENT MODEL VALUES CONFIGURATION")
    print("="*50)
    if project_instrument_model:
        print(f"Project-level instrument model: {project_instrument_model}")
    else:
        print("Project-level instrument model: Not found")
    
    # Check if we have different instrument model values across assays
    assay_instrument_models = {}
    has_different_instrument_models = False
    
    for assay in selected_assays:
        assay_instrument_model = get_assay_instrument_model(assay)
        assay_instrument_models[assay] = assay_instrument_model
        
        # Check if values are different and both are valid
        assay_valid = assay_instrument_model and str(assay_instrument_model).lower() not in ['nan', 'none', '']
        project_valid = project_instrument_model and str(project_instrument_model).lower() not in ['nan', 'none', '']
        
        if assay_valid and project_valid and assay_instrument_model != project_instrument_model:
            has_different_instrument_models = True
    
    # If we have different instrument model values, ask user for each assay
    if has_different_instrument_models:
        print(f"\nDifferent instrument model values found across assays:")
        for assay in selected_assays:
            assay_instrument_model = assay_instrument_models[assay]
            if assay_instrument_model and str(assay_instrument_model).lower() not in ['nan', 'none', '']:
                print(f"  {assay}: {assay_instrument_model}")
            else:
                print(f"  {assay}: Not found")
        print()
        
        # Ask user for each assay individually
        for assay in selected_assays:
            assay_instrument_model = assay_instrument_models[assay]
            assay_valid = assay_instrument_model and str(assay_instrument_model).lower() not in ['nan', 'none', '']
            project_valid = project_instrument_model and str(project_instrument_model).lower() not in ['nan', 'none', '']
            
            if assay_valid and project_valid and assay_instrument_model != project_instrument_model:
                # Ask individual question for this assay
                choice = get_config_value(
                    config,
                    f'instrument_model_choice_{assay}',
                    get_valid_user_choice,
                    f"Assay '{assay}' has different instrument model values:\n    Assay-specific: {assay_instrument_model}\n    Project-level: {project_instrument_model}\n  Which one do you want to use? [Assay/Project]: ",
                    use_config_file,
                    f"Assay '{assay}' has different instrument model values:\n    Assay-specific: {assay_instrument_model}\n    Project-level: {project_instrument_model}\n  Which one do you want to use? [Assay/Project]: ",
                    ["assay", "project"],
                    default="assay"
                )
                
                if choice == "assay":
                    print(f"  Using assay-specific instrument model for '{assay}': {assay_instrument_model}")
                    final_instrument_model_values[assay] = assay_instrument_model
                else:
                    print(f"  Using project-level instrument model for '{assay}': {project_instrument_model}")
                    final_instrument_model_values[assay] = project_instrument_model
            else:
                # Use available values
                if assay_valid:
                    final_instrument_model_values[assay] = assay_instrument_model
                elif project_valid:
                    final_instrument_model_values[assay] = project_instrument_model
                else:
                    # No valid values, check if we need manual entry
                    assay_platform = final_platform_values.get(assay, project_platform)
                    if assay_platform and str(assay_platform).lower() not in ['nan', 'none', '']:
                        choice = get_config_value(
                            config,
                            f'instrument_model_manual_{assay}',
                            get_valid_user_choice,
                            f"  No instrument model value found for assay '{assay}'. Do you want to add a value manually? [y/N]: ",
                            use_config_file,
                            f"  No instrument model value found for assay '{assay}'. Do you want to add a value manually? [y/N]: ",
                            ["y", "yes", "n", "no"],
                            default="n"
                        )
                        
                        if choice in ("y", "yes"):
                            print(f"  Platform for assay '{assay}': {assay_platform}")
                            user_instrument_model = get_user_instrument_model(assay_platform)
                            if user_instrument_model:
                                final_instrument_model_values[assay] = user_instrument_model
                            else:
                                print("Operation cancelled by user.")
                                return
                        else:
                            final_instrument_model_values[assay] = ''
                    else:
                        final_instrument_model_values[assay] = ''
    else:
        # No different instrument models, use available values
        for assay in selected_assays:
            assay_instrument_model = assay_instrument_models[assay]
            assay_valid = assay_instrument_model and str(assay_instrument_model).lower() not in ['nan', 'none', '']
            project_valid = project_instrument_model and str(project_instrument_model).lower() not in ['nan', 'none', '']
            
            if assay_valid and project_valid and assay_instrument_model == project_instrument_model:
                print(f"  Instrument model value '{assay_instrument_model}' used for assay '{assay}' (same as project-level)")
                final_instrument_model_values[assay] = assay_instrument_model
            elif assay_valid:
                print(f"  Instrument model value '{assay_instrument_model}' used for assay '{assay}' (assay-specific only)")
                final_instrument_model_values[assay] = assay_instrument_model
            elif project_valid:
                print(f"  Instrument model value '{project_instrument_model}' used for assay '{assay}' (project-level only)")
                final_instrument_model_values[assay] = project_instrument_model
            else:
                # No valid values, check if we need manual entry
                assay_platform = final_platform_values.get(assay, project_platform)
                if assay_platform and str(assay_platform).lower() not in ['nan', 'none', '']:
                    choice = get_config_value(
                        config,
                        f'instrument_model_manual_{assay}',
                        get_valid_user_choice,
                        f"  No instrument model value found for assay '{assay}'. Do you want to add a value manually? [y/N]: ",
                        use_config_file,
                        f"  No instrument model value found for assay '{assay}'. Do you want to add a value manually? [y/N]: ",
                        ["y", "yes", "n", "no"],
                        default="n"
                    )
                    
                    if choice in ("y", "yes"):
                        print(f"  Platform for assay '{assay}': {assay_platform}")
                        user_instrument_model = get_user_instrument_model(assay_platform)
                        if user_instrument_model:
                            final_instrument_model_values[assay] = user_instrument_model
                        else:
                            print("Operation cancelled by user.")
                            return
                    else:
                        final_instrument_model_values[assay] = ''
                else:
                    final_instrument_model_values[assay] = ''
    
    # For single assay, use the single value; for multiple assays, we'll handle them individually in mapping
    if len(selected_assays) == 1:
        instrument_model_value = list(final_instrument_model_values.values())[0]
        print(f"\nFinal instrument model value: {instrument_model_value}")
    else:
        # For multiple assays, we'll use the individual values during mapping
        instrument_model_value = None  # Will be handled per assay during mapping
        print(f"\nFinal instrument model values determined:")
        for assay, instrument_model in final_instrument_model_values.items():
            print(f"  {assay}: {instrument_model}")
    
    if not final_instrument_model_values:
        print("No instrument model value determined. Exiting.")
        return
    
    # Validate platform and instrument values against SRA template
    def validate_and_correct_value(value, allowed_values, value_type, config, use_config_file, assay_name=None, platform_value=None):
        """
        Validate a value against allowed values from SRA template and prompt user if mismatch.
        
        Args:
            value (str): The value to validate
            allowed_values (list): List of allowed values from template
            value_type (str): Type of value ('platform' or 'instrument_model')
            config (dict): Configuration dictionary
            use_config_file (bool): Whether using config file
            assay_name (str): Optional assay name for context
            platform_value (str): Optional platform value to filter instrument options
        
        Returns:
            str: Validated/corrected value
        """
        if not value or str(value).strip() == '':
            return value
        
        value_str = str(value).strip()
        
        # If no allowed values from template, skip validation
        if not allowed_values:
            return value_str
        
        # For instrument_model, filter by platform if platform is known
        filtered_allowed_values = allowed_values
        if value_type == 'instrument_model' and platform_value:
            # Filter instruments by platform
            platform_instruments_map = {
                '_LS454': ['454 GS', '454 GS 20', '454 GS FLX', '454 GS FLX+', '454 GS FLX Titanium', '454 GS Junior'],
                'ILLUMINA': ['HiSeq X Five', 'HiSeq X Ten', 'Illumina Genome Analyzer', 'Illumina Genome Analyzer II', 'Illumina Genome Analyzer IIx', 'Illumina HiScanSQ', 'Illumina HiSeq 1000', 'Illumina HiSeq 1500', 'Illumina HiSeq 2000', 'Illumina HiSeq 2500', 'Illumina HiSeq 3000', 'Illumina HiSeq 4000', 'Illumina HiSeq X', 'Illumina MiSeq', 'Illumina MiniSeq', 'Illumina NovaSeq 6000', 'Illumina NovaSeq X', 'Illumina NovaSeq X Plus', 'Illumina iSeq 100', 'NextSeq 1000', 'NextSeq 2000', 'NextSeq 500', 'NextSeq 550'],
                'HELICOS': ['Helicos HeliScope'],
                'ABI_SOLID': ['AB 5500 Genetic Analyzer', 'AB 5500xl Genetic Analyzer', 'AB 5500x-Wl Genetic Analyzer', 'AB SOLiD 3 Plus System', 'AB SOLiD 4 System', 'AB SOLiD 4hq System', 'AB SOLiD PI System', 'AB SOLiD System', 'AB SOLiD System 2.0', 'AB SOLiD System 3.0'],
                'COMPLETE_GENOMICS': ['Complete Genomics'],
                'PACBIO_SMRT': ['PacBio RS', 'PacBio RS II', 'Revio', 'Sequel', 'Sequel II', 'Sequel IIe', 'Onso'],
                'ION_TORRENT': ['Ion Torrent PGM', 'Ion Torrent Proton', 'Ion Torrent S5 XL', 'Ion Torrent S5', 'Ion Torrent Genexus', 'Ion GeneStudio S5', 'Ion GeneStudio S5 Plus', 'Ion GeneStudio S5 Prime'],
                'CAPILLARY': ['AB 310 Genetic Analyzer', 'AB 3130 Genetic Analyzer', 'AB 3130xL Genetic Analyzer', 'AB 3500 Genetic Analyzer', 'AB 3500xL Genetic Analyzer', 'AB 3730 Genetic Analyzer', 'AB 3730xL Genetic Analyzer'],
                'OXFORD_NANOPORE': ['GridION', 'MinION', 'PromethION'],
                'BGISEQ': ['BGISEQ-50', 'BGISEQ-500', 'MGISEQ-2000RS'],
                'DNBSEQ': ['DNBSEQ-G400', 'DNBSEQ-G50', 'DNBSEQ-T7', 'DNBSEQ-G400 FAST'],
                'ELEMENT': ['Element AVITI', 'Onso'],
                'GENAPSYS': ['GS111', 'FASTASeq 300'],
                'GENEMIND': ['GenoCare 1600', 'GenoLab M'],
                'TAPESTRI': ['Tapestri'],
                'ULTIMA': ['UG 100'],
                'VELA_DIAGNOSTICS': ['Sentosa SQ301']
            }
            
            # Find matching platform (case-insensitive)
            platform_key = None
            for key in platform_instruments_map.keys():
                if key.lower() == platform_value.lower():
                    platform_key = key
                    break
            
            if platform_key and platform_key in platform_instruments_map:
                # Filter allowed values to only show instruments for this platform
                platform_specific_instruments = platform_instruments_map[platform_key]
                # Intersect with template allowed values (case-insensitive)
                filtered_allowed_values = []
                template_lower = [str(v).lower() for v in allowed_values]
                for inst in platform_specific_instruments:
                    if inst.lower() in template_lower:
                        # Find the exact case match from template
                        for template_val in allowed_values:
                            if template_val.lower() == inst.lower():
                                filtered_allowed_values.append(template_val)
                                break
                
                # If no intersection, use all template values
                if not filtered_allowed_values:
                    filtered_allowed_values = allowed_values
                    print(f"Info: Platform '{platform_value}' instruments not found in template. Showing all template instruments.")
                else:
                    print(f"Info: Filtering instruments for platform '{platform_value}'")
            else:
                # Platform not in mapping, use all template values
                filtered_allowed_values = allowed_values
        
        # Check if value matches (case-insensitive)
        value_lower = value_str.lower()
        allowed_lower = [str(v).lower() for v in filtered_allowed_values]
        
        if value_lower in allowed_lower:
            # Value matches, return as-is
            return value_str
        
        # Value doesn't match - show options and ask user
        assay_context = f" for assay '{assay_name}'" if assay_name else ""
        print(f"\n" + "="*50)
        print(f"VALIDATION: {value_type.upper()} VALUE{assay_context}")
        print("="*50)
        print(f"Value from FAIRe metadata: '{value_str}'")
        print(f"This value is not found in the SRA template allowed values.")
        if value_type == 'instrument_model' and platform_value and len(filtered_allowed_values) < len(allowed_values):
            print(f"\nShowing instruments for platform '{platform_value}':")
        else:
            print(f"\nAllowed {value_type} values from SRA template:")
        for i, allowed_val in enumerate(filtered_allowed_values, 1):
            print(f"  {i:2d}. {allowed_val}")
        
        while True:
            try:
                user_input = get_config_value(
                    config,
                    f'{value_type}_validation_{value_str}_{assay_name or "global"}',
                    input,
                    f"\nEnter {value_type} value (number 1-{len(filtered_allowed_values)}, exact value, or press Enter to keep '{value_str}'): ",
                    use_config_file,
                    f"\nEnter {value_type} value (number 1-{len(filtered_allowed_values)}, exact value, or press Enter to keep '{value_str}'): "
                ).strip()
                
                if not user_input:
                    print(f"Keeping original value: {value_str}")
                    return value_str
                
                # Check if input is a number
                if user_input.isdigit():
                    idx = int(user_input) - 1
                    if 0 <= idx < len(filtered_allowed_values):
                        selected_value = filtered_allowed_values[idx]
                        print(f"Selected: {selected_value}")
                        return selected_value
                    else:
                        print(f"Error: Number {user_input} is out of range (1-{len(filtered_allowed_values)})")
                # Check if input matches an allowed value (case-insensitive)
                elif user_input.lower() in allowed_lower:
                    # Find the exact case match
                    for allowed_val in filtered_allowed_values:
                        if allowed_val.lower() == user_input.lower():
                            print(f"Selected: {allowed_val}")
                            return allowed_val
                else:
                    print(f"Error: '{user_input}' is not in the allowed values list.")
                    print(f"Please enter a number (1-{len(filtered_allowed_values)}), one of the allowed values, or press Enter to keep the original value.")
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                return value_str
    
    # Validate platform values against SRA template
    print(f"\n" + "="*50)
    print("VALIDATING PLATFORM VALUES AGAINST SRA TEMPLATE")
    print("="*50)
    
    # Check if all platform values are the same
    unique_platform_values = set()
    for platform_val in final_platform_values.values():
        if platform_val and str(platform_val).strip() != '':
            unique_platform_values.add(str(platform_val).strip())
    
    validated_platform_values = {}
    
    # If all platforms are the same, ask once
    if len(unique_platform_values) == 1:
        common_platform = list(unique_platform_values)[0]
        print(f"All assays have the same platform value: '{common_platform}'")
        validated_platform = validate_and_correct_value(
            common_platform,
            template_allowed_platforms,
            'platform',
            config,
            use_config_file,
            None  # No specific assay since all are the same
        )
        # Apply to all assays
        for assay in final_platform_values.keys():
            validated_platform_values[assay] = validated_platform
    else:
        # Different platforms per assay, ask for each
        for assay, platform_val in final_platform_values.items():
            if platform_val and str(platform_val).strip() != '':
                validated_platform = validate_and_correct_value(
                    platform_val,
                    template_allowed_platforms,
                    'platform',
                    config,
                    use_config_file,
                    assay if len(selected_assays) > 1 else None
                )
                validated_platform_values[assay] = validated_platform
            else:
                validated_platform_values[assay] = platform_val
    
    final_platform_values = validated_platform_values
    
    # Update single platform_value if only one assay
    if len(selected_assays) == 1:
        platform_value = list(final_platform_values.values())[0]
    
    # Validate instrument_model values against SRA template
    print(f"\n" + "="*50)
    print("VALIDATING INSTRUMENT MODEL VALUES AGAINST SRA TEMPLATE")
    print("="*50)
    
    # Check if all instrument values are the same
    unique_instrument_values = set()
    for instrument_val in final_instrument_model_values.values():
        if instrument_val and str(instrument_val).strip() != '':
            unique_instrument_values.add(str(instrument_val).strip())
    
    validated_instrument_values = {}
    
    # If all instruments are the same, ask once
    if len(unique_instrument_values) == 1:
        common_instrument = list(unique_instrument_values)[0]
        print(f"All assays have the same instrument model value: '{common_instrument}'")
        
        # Get the platform value for this assay (use first available)
        platform_for_validation = None
        for assay in final_instrument_model_values.keys():
            if assay in final_platform_values:
                platform_for_validation = final_platform_values[assay]
                break
        
        validated_instrument = validate_and_correct_value(
            common_instrument,
            template_allowed_instruments,
            'instrument_model',
            config,
            use_config_file,
            None,  # No specific assay since all are the same
            platform_for_validation  # Pass platform to filter instruments
        )
        # Apply to all assays
        for assay in final_instrument_model_values.keys():
            validated_instrument_values[assay] = validated_instrument
    else:
        # Different instruments per assay, ask for each
        for assay, instrument_val in final_instrument_model_values.items():
            if instrument_val and str(instrument_val).strip() != '':
                # Get platform value for this assay
                platform_for_validation = final_platform_values.get(assay, None)
                
                validated_instrument = validate_and_correct_value(
                    instrument_val,
                    template_allowed_instruments,
                    'instrument_model',
                    config,
                    use_config_file,
                    assay if len(selected_assays) > 1 else None,
                    platform_for_validation  # Pass platform to filter instruments
                )
                validated_instrument_values[assay] = validated_instrument
            else:
                validated_instrument_values[assay] = instrument_val
    
    final_instrument_model_values = validated_instrument_values
    
    # Update single instrument_model_value if only one assay
    if len(selected_assays) == 1:
        instrument_model_value = list(final_instrument_model_values.values())[0]
    
    # Add rows for each sample and perform mapping
    for i, sample_row in sample_df.iterrows():
        # Create a new row with empty values for all SRA template columns
        new_row = pd.Series([''] * len(sra_template_df.columns), index=sra_template_df.columns)
        
        # 1. Copy lib_id to library_ID
        if 'lib_id' in sample_df.columns and 'library_ID' in sra_output_df.columns:
            new_row['library_ID'] = sample_row['lib_id']
        
        # 2. Copy filename columns (all template slots when blank_only includes every ERM row with blank associatedSequences)
        if sra_erm_blank_only:
            for fn_col in ('filename', 'filename2', 'filename3', 'filename4'):
                if fn_col in sample_df.columns and fn_col in sra_output_df.columns:
                    new_row[fn_col] = sample_row[fn_col]
        else:
            if 'filename' in sample_df.columns and 'filename' in sra_output_df.columns:
                new_row['filename'] = sample_row['filename']
            
            if 'filename2' in sample_df.columns and 'filename2' in sra_output_df.columns:
                new_row['filename2'] = sample_row['filename2']
        
        # 3. Determine library_layout based on filename and filename2
        if 'library_layout' in sra_output_df.columns:
            has_filename = pd.notna(sample_row.get('filename', '')) and str(sample_row.get('filename', '')).strip() != ''
            has_filename2 = pd.notna(sample_row.get('filename2', '')) and str(sample_row.get('filename2', '')).strip() != ''
            
            if has_filename and has_filename2:
                new_row['library_layout'] = 'paired'
            elif has_filename:
                new_row['library_layout'] = 'single'
            else:
                new_row['library_layout'] = ''  # No files available
        
        # 4. Set library strategy, source, and selection values
        if 'library_strategy' in sra_output_df.columns:
            new_row['library_strategy'] = library_fields['library_strategy']
        
        if 'library_source' in sra_output_df.columns:
            new_row['library_source'] = library_fields['library_source']
        
        if 'library_selection' in sra_output_df.columns:
            new_row['library_selection'] = library_fields['library_selection']
        
        # 5. Set platform value
        if 'platform' in sra_output_df.columns:
            if len(selected_assays) == 1:
                # Single assay - use the single platform value
                new_row['platform'] = platform_value
            else:
                # Multiple assays - use the platform value for this specific assay
                assay_name = sample_row['assay_name']
                if assay_name in final_platform_values:
                    new_row['platform'] = final_platform_values[assay_name]
                else:
                    # Fallback to project platform if available
                    new_row['platform'] = project_platform if project_platform else ''
        
        # 6. Set instrument_model value
        if 'instrument_model' in sra_output_df.columns:
            if len(selected_assays) == 1:
                # Single assay - use the single instrument_model value
                new_row['instrument_model'] = instrument_model_value
            else:
                # Multiple assays - use the instrument_model value for this specific assay
                assay_name = sample_row['assay_name']
                if assay_name in final_instrument_model_values:
                    new_row['instrument_model'] = final_instrument_model_values[assay_name]
                else:
                    # Fallback to project instrument_model if available
                    new_row['instrument_model'] = project_instrument_model if project_instrument_model else ''
        
        # 7. Determine filetype based on filename extension
        if 'filetype' in sra_output_df.columns:
            # Check filename first, then filename2 if filename is empty
            filename_to_check = sample_row.get('filename', '')
            if not filename_to_check or pd.isna(filename_to_check) or str(filename_to_check).strip() == '':
                filename_to_check = sample_row.get('filename2', '')
            
            filetype = determine_filetype_from_filename(filename_to_check)
            new_row['filetype'] = filetype
        
        # 8. Create description for the assay
        if 'description' in sra_output_df.columns:
            assay_name = sample_row['assay_name']
            description = create_assay_description(assay_name)
            new_row['description'] = description
        
        # 9. Set design_description using the created description
        if 'design_description' in sra_output_df.columns:
            assay_name = sample_row['assay_name']
            design_description = create_assay_description(assay_name)
            new_row['design_description'] = design_description
        
        # 10. Create title for the library
        if 'title' in sra_output_df.columns:
            lib_id = sample_row.get('lib_id', '')
            assay_name = sample_row['assay_name']
            title = create_library_title(lib_id, assay_name, sample_df, sample_metadata_df)
            new_row['title'] = title
        
        # Add the row to the output DataFrame
        sra_output_df = pd.concat([sra_output_df, pd.DataFrame([new_row])], ignore_index=True)
    
    # Handle biosample_accession merging if provided
    if args.NCBI_accession_number:
        print(f"\n" + "="*50)
        print("BIOSAMPLE ACCESSION MERGING")
        print("="*50)
        
        # Use already-read ncbi_accession_data if available, otherwise read it
        if ncbi_accession_data and ncbi_accession_data['df'] is not None:
            print(f"Using previously read NCBI accession table from: {args.NCBI_accession_number}")
            ncbi_df = ncbi_accession_data['df']
            accession_col = ncbi_accession_data.get('biosample_col')
            sample_name_col = None
            # Find sample name column
            for col in ncbi_df.columns:
                col_lower = str(col).lower().strip()
                if col_lower == 'sample_name' or col_lower == '*sample_name':
                    sample_name_col = col
                    break
        else:
            print(f"Reading NCBI accession table from: {args.NCBI_accession_number}")
            ncbi_df = read_biosample_file_safe(args.NCBI_accession_number)
            if ncbi_df is None:
                print(f"Warning: Could not read NCBI accession file: {args.NCBI_accession_number}")
                print("Continuing without biosample accession merging.")
                ncbi_df = None
                accession_col = None
                sample_name_col = None
        
        # Only proceed with merging if we have the required data
        if ncbi_df is not None:
            try:
                # Check required columns (handle variations in column names)
                def _norm_col_name(col_name):
                    return (
                        str(col_name)
                        .lower()
                        .strip()
                        .replace("_", "")
                        .replace(".", "")
                        .replace(" ", "")
                        .replace("*", "")
                    )

                if accession_col is None:
                    for col in ncbi_df.columns:
                        norm = _norm_col_name(col)
                        if norm in ('accession', 'biosampleaccession'):
                            accession_col = col
                            break

                if sample_name_col is None:
                    for col in ncbi_df.columns:
                        norm = _norm_col_name(col)
                        if norm in ('samplename', 'biosamplename'):
                            sample_name_col = col
                            break

                available_cols = [str(c) for c in ncbi_df.columns]

                # If still missing, ask user to choose from existing columns
                if accession_col is None:
                    print("Info: could not auto-detect accession column from: accession, biosample_accession, Accession.")
                    print(f"Available columns: {', '.join(available_cols)}")
                    for i, c in enumerate(available_cols, 1):
                        print(f"  {i}. {c}")
                    while True:
                        user_acc_col = get_config_value(
                            config,
                            "biosample_accession_column_choice",
                            input,
                            "Which column should be used for BioSample accession? (number or exact column name): ",
                            use_config_file,
                            "Which column should be used for BioSample accession? (number or exact column name): ",
                        ).strip()
                        if user_acc_col.isdigit():
                            idx = int(user_acc_col) - 1
                            if 0 <= idx < len(available_cols):
                                accession_col = available_cols[idx]
                                break
                        elif user_acc_col in available_cols:
                            accession_col = user_acc_col
                            break
                        print("Invalid selection. Please enter a valid number or existing column name.")

                if sample_name_col is None:
                    print("Info: could not auto-detect sample name column from: sample_name, *sample_name, BioSample.name.")
                    print(f"Available columns: {', '.join(available_cols)}")
                    for i, c in enumerate(available_cols, 1):
                        print(f"  {i}. {c}")
                    while True:
                        user_name_col = get_config_value(
                            config,
                            "biosample_sample_name_column_choice",
                            input,
                            "Which column should be used for sample name matching? (number or exact column name): ",
                            use_config_file,
                            "Which column should be used for sample name matching? (number or exact column name): ",
                        ).strip()
                        if user_name_col.isdigit():
                            idx = int(user_name_col) - 1
                            if 0 <= idx < len(available_cols):
                                sample_name_col = available_cols[idx]
                                break
                        elif user_name_col in available_cols:
                            sample_name_col = user_name_col
                            break
                        print("Invalid selection. Please enter a valid number or existing column name.")

                # Check if we have both required columns
                if accession_col is None or sample_name_col is None:
                    print("Continuing without biosample accession merging.")
                else:
                    # Proceed with merging
                    # Add samp_name column from sample_df to sra_output_df
                    print("Adding samp_name column from FAIReMetadata to SRA_Metadata...")
                    # Create a mapping from lib_id to samp_name
                    lib_id_to_samp_name = {}
                    for i, sample_row in sample_df.iterrows():
                        lib_id = sample_row.get('lib_id', '')
                        samp_name = sample_row.get('samp_name', '')
                        if lib_id and pd.notna(samp_name) and str(samp_name).strip() != '':
                            lib_id_to_samp_name[lib_id] = str(samp_name).strip()
                    
                    # Map samp_name to sra_output_df using library_ID
                    sra_output_df['samp_name'] = sra_output_df['library_ID'].map(lib_id_to_samp_name)
                    
                    # Show how many samples have samp_name
                    samples_with_samp_name = sra_output_df['samp_name'].notna().sum()
                    print(f"Added samp_name to {samples_with_samp_name} out of {len(sra_output_df)} samples")
                    
                    # Update existing biosample_accession column with values from NCBI accession table
                    print("Updating biosample_accession column in SRA_Metadata...")
                    
                    # Check if biosample_accession column exists in SRA_Metadata
                    if 'biosample_accession' not in sra_output_df.columns:
                        print("Warning: 'biosample_accession' column not found in SRA_Metadata. Creating it.")
                        sra_output_df['biosample_accession'] = ''
                    
                    # Create a mapping from sample_name to accession from the NCBI accession table
                    sample_name_to_accession = {}
                    for i, row in ncbi_df.iterrows():
                        sample_name = row.get(sample_name_col, '')
                        accession = row.get(accession_col, '')
                        if pd.notna(sample_name) and str(sample_name).strip() != '' and pd.notna(accession) and str(accession).strip() != '':
                            sample_name_to_accession[str(sample_name).strip()] = str(accession).strip()
                    
                    print(f"Created mapping for {len(sample_name_to_accession)} sample names to accessions")
                    
                    # Update biosample_accession column using samp_name to match with sample_name
                    # Use samp_name to look up the accession (vectorized operation)
                    # Clean samp_name values and map to accessions
                    sra_output_df['samp_name_clean'] = sra_output_df['samp_name'].apply(
                        lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != '' else ''
                    )
                    
                    # Map accessions using the cleaned samp_name
                    # Create a Series with mapped accessions
                    mapped_accessions = sra_output_df['samp_name_clean'].map(sample_name_to_accession)
                    
                    # Update biosample_accession: use mapped value if available, otherwise keep existing value
                    # Only update rows where we have a match
                    mask = mapped_accessions.notna()
                    sra_output_df.loc[mask, 'biosample_accession'] = mapped_accessions[mask]
                    
                    # Count how many were updated
                    updated_count = int(mask.sum())
                    
                    # Remove temporary columns
                    sra_output_df = sra_output_df.drop(columns=['samp_name', 'samp_name_clean'], errors='ignore')
                    
                    # Show update statistics
                    if 'biosample_accession' in sra_output_df.columns:
                        biosample_col = sra_output_df['biosample_accession']
                        samples_with_accession = int(biosample_col.notna().sum())
                        
                        print(f"Successfully updated biosample accessions for {updated_count} samples")
                        print(f"Total samples with biosample accessions: {samples_with_accession} out of {len(sra_output_df)} samples")
                        
                        if samples_with_accession < len(sra_output_df):
                            missing_count = len(sra_output_df) - samples_with_accession
                            print(f"Warning: {missing_count} samples do not have matching biosample accessions")
                    else:
                        print("Warning: 'biosample_accession' column not found after update")
                        print(f"Available columns: {list(sra_output_df.columns)}")
                        
            except Exception as e:
                print(f"Warning: Error processing NCBI accession file: {e}")
                import traceback
                traceback.print_exc()
                print("Continuing without biosample accession merging.")
    
    # Show filetype distribution summary
    if 'filetype' in sra_output_df.columns:
        print(f"\n" + "="*50)
        print("FILETYPE DISTRIBUTION SUMMARY")
        print("="*50)
        filetype_counts = sra_output_df['filetype'].value_counts()
        unique_filetypes = list(filetype_counts.index)
        print(f"Unique filetype values used: {', '.join(unique_filetypes)}")
        print("\nFiletype distribution:")
        for filetype, count in filetype_counts.items():
            percentage = (count / len(sra_output_df)) * 100
            print(f"  {filetype}: {count} samples ({percentage:.1f}%)")
        
        # Show samples with unknown filetypes
        unknown_filetypes = sra_output_df[sra_output_df['filetype'] == '']
        if len(unknown_filetypes) > 0:
            print(f"\nWarning: {len(unknown_filetypes)} samples have unknown filetypes (empty filenames or unrecognized extensions)")
            if len(unknown_filetypes) <= 10:  # Show details if not too many
                print("Samples with unknown filetypes:")
                for idx, row in unknown_filetypes.iterrows():
                    filename = row.get('filename', '') or row.get('filename2', '')
                    print(f"  Row {idx+1}: '{filename}'")
    
    # Show description creation preview
    print(f"\n" + "="*50)
    print("DESCRIPTION CREATION")
    print("="*50)
    print("Creating descriptions for each assay using projectMetadata fields:")
    for assay in selected_assays:
        description = create_assay_description(assay)
        print(f"\n{assay}:")
        print(f"  {description}")
    
    # Detect and filter empty/corrupted fastq files if requested
    empty_files_to_remove = set()
    if args.filter_fastq:
        print(f"\n" + "="*50)
        print("FILTERING EMPTY/CORRUPTED FASTQ FILES")
        print("="*50)
        filter_list_path = f"{os.path.splitext(args.SRA_Metadata)[0]}_empty_corrupted_fastq_files.txt"
        empty_files_to_remove = detect_empty_corrupted_fastq_files(args.filter_fastq, filter_list_path)
    
    # Write the SRA metadata file(s) based on bioproject strategy
    print(f"\n" + "="*50)
    print("WRITING SRA METADATA")
    print("="*50)
    
    # Show mapping results
    print(f"Created SRA metadata with {len(sra_output_df)} rows and {len(sra_output_df.columns)} columns")
    print(f"Successfully mapped metadata for {len(sample_df)} samples")
    
    # Filter out rows with empty/corrupted fastq filenames if detected
    if empty_files_to_remove:
        print(f"\nFiltering out rows containing empty/corrupted fastq files...")
        sra_output_df = filter_rows_by_filenames(sra_output_df, empty_files_to_remove)
        print(f"After filtering: {len(sra_output_df)} rows remaining")
    
    # Get bioproject strategy and NCBI accession data
    bioproject_strategy = config.get('bioproject_strategy', {'strategy': 'combined'})
    ncbi_accession_data = config.get('_ncbi_accession_data')
    
    # Create mapping from library_ID to bioproject if we have NCBI accession data
    lib_id_to_bioproject = None
    if ncbi_accession_data and ncbi_accession_data.get('sample_to_bioproject') and 'library_ID' in sra_output_df.columns:
        # First, create mapping from samp_name to bioproject
        samp_name_to_bioproject = ncbi_accession_data['sample_to_bioproject']
        
        # Then, create mapping from lib_id to samp_name from sample_df
        lib_id_to_samp_name = {}
        for i, sample_row in sample_df.iterrows():
            lib_id = sample_row.get('lib_id', '')
            samp_name = sample_row.get('samp_name', '')
            if lib_id and pd.notna(samp_name) and str(samp_name).strip() != '':
                lib_id_to_samp_name[str(lib_id).strip()] = str(samp_name).strip()
        
        # Combine to get lib_id to bioproject mapping
        lib_id_to_bioproject = {}
        for lib_id, samp_name in lib_id_to_samp_name.items():
            if samp_name in samp_name_to_bioproject:
                lib_id_to_bioproject[lib_id] = samp_name_to_bioproject[samp_name]
    
    # Determine base output file path and extension
    base_output_path = args.SRA_Metadata
    output_file_lower = base_output_path.lower()
    
    # Determine extension
    if output_file_lower.endswith('.tsv'):
        ext = '.tsv'
    elif output_file_lower.endswith('.csv'):
        ext = '.csv'
    elif output_file_lower.endswith('.xlsx'):
        ext = '.xlsx'
    elif output_file_lower.endswith('.xls'):
        ext = '.xls'
    else:
        ext = '.tsv'  # Default to TSV
    
    base_path_no_ext = os.path.splitext(base_output_path)[0]
    
    try:
        # Optional explicit split by BioProject file (overrides other bioproject strategies)
        if args.split_by_BioProject:
            print(f"\n" + "="*50)
            print("SPLIT SRA OUTPUT BY BIOPROJECT")
            print("="*50)

            split_file_path = args.split_by_BioProject
            if split_file_path == '__USE_NCBI_ACCESSION__':
                if args.NCBI_accession_number:
                    split_file_path = args.NCBI_accession_number
                    print("Using --NCBI_accession_number file for split_by_BioProject.")
                else:
                    print(
                        "Error: --split_by_BioProject was requested without a file path, "
                        "but --NCBI_accession_number is not provided."
                    )
                    return
            split_df = None
            if (
                args.NCBI_accession_number
                and os.path.abspath(split_file_path) == os.path.abspath(args.NCBI_accession_number)
                and ncbi_accession_data
                and ncbi_accession_data.get('df') is not None
            ):
                split_df = ncbi_accession_data['df']
                print(f"Using previously read split table from: {split_file_path}")
            else:
                print(f"Reading split table from: {split_file_path}")
                split_df = read_biosample_file_safe(split_file_path)

            if split_df is None or len(split_df.columns) == 0:
                print("Warning: Could not read split_by_BioProject table. Writing single combined output file.")
                print(f"\nOutput file path: {os.path.abspath(base_output_path)}")
                write_sra_file(sra_output_df, base_output_path, ext)
                add_generated_file(config, base_output_path, "SRA metadata file")
            else:
                def _norm_col_name(col_name):
                    return (
                        str(col_name)
                        .lower()
                        .strip()
                        .replace("_", "")
                        .replace(".", "")
                        .replace(" ", "")
                        .replace("*", "")
                    )

                split_cols = [str(c) for c in split_df.columns]
                bioproject_col = None
                sample_name_col = None

                for col in split_df.columns:
                    n = _norm_col_name(col)
                    if bioproject_col is None and n in ('bioproject', 'bioprojectaccession'):
                        bioproject_col = col
                    if sample_name_col is None and n in ('biosamplename', 'samplename'):
                        sample_name_col = col

                if bioproject_col is None:
                    print("Info: 'BioProject' column not auto-detected in split table.")
                    print(f"Available columns: {', '.join(split_cols)}")
                    for i, c in enumerate(split_cols, 1):
                        print(f"  {i}. {c}")
                    while True:
                        user_bp_col = get_config_value(
                            config,
                            "split_bioproject_column_choice",
                            input,
                            "Which column should be used as BioProject? (number or exact column name): ",
                            use_config_file,
                            "Which column should be used as BioProject? (number or exact column name): ",
                        ).strip()
                        if user_bp_col.isdigit():
                            idx = int(user_bp_col) - 1
                            if 0 <= idx < len(split_cols):
                                bioproject_col = split_cols[idx]
                                break
                        elif user_bp_col in split_cols:
                            bioproject_col = user_bp_col
                            break
                        print("Invalid selection. Please enter a valid number or existing column name.")

                if sample_name_col is None:
                    print("Info: sample name column not auto-detected (expected BioSample.name/sample_name).")
                    print(f"Available columns: {', '.join(split_cols)}")
                    for i, c in enumerate(split_cols, 1):
                        print(f"  {i}. {c}")
                    while True:
                        user_sn_col = get_config_value(
                            config,
                            "split_sample_name_column_choice",
                            input,
                            "Which column should be used for sample name matching? (number or exact column name): ",
                            use_config_file,
                            "Which column should be used for sample name matching? (number or exact column name): ",
                        ).strip()
                        if user_sn_col.isdigit():
                            idx = int(user_sn_col) - 1
                            if 0 <= idx < len(split_cols):
                                sample_name_col = split_cols[idx]
                                break
                        elif user_sn_col in split_cols:
                            sample_name_col = user_sn_col
                            break
                        print("Invalid selection. Please enter a valid number or existing column name.")

                # Build lib_id -> samp_name from experimentRunMetadata
                lib_id_to_samp_name = {}
                for _, sample_row in sample_df.iterrows():
                    lib_id = sample_row.get('lib_id', '')
                    samp_name = sample_row.get('samp_name', '')
                    if pd.notna(lib_id) and pd.notna(samp_name):
                        lib_str = str(lib_id).strip()
                        sn_str = str(samp_name).strip()
                        if lib_str and sn_str:
                            lib_id_to_samp_name[lib_str] = sn_str

                # Build samp_name -> bioproject from split file
                sample_to_bioproject = {}
                for _, row in split_df.iterrows():
                    sn = row.get(sample_name_col, '')
                    bp = row.get(bioproject_col, '')
                    if pd.notna(sn) and pd.notna(bp):
                        sn_str = str(sn).strip()
                        bp_str = str(bp).strip()
                        if sn_str and bp_str:
                            sample_to_bioproject[sn_str] = bp_str

                # Create lib_id -> bioproject map using samp_name as bridge
                split_lib_to_bp = {}
                for lib_id, samp_name in lib_id_to_samp_name.items():
                    if samp_name in sample_to_bioproject:
                        split_lib_to_bp[lib_id] = sample_to_bioproject[samp_name]

                if not split_lib_to_bp:
                    print("Warning: No lib_id could be mapped to BioProject using samp_name -> BioSample.name mapping.")
                    print("Writing single combined output file instead.")
                    print(f"\nOutput file path: {os.path.abspath(base_output_path)}")
                    write_sra_file(sra_output_df, base_output_path, ext)
                    add_generated_file(config, base_output_path, "SRA metadata file")
                else:
                    sra_output_df['_bioproject'] = sra_output_df['library_ID'].astype(str).str.strip().map(split_lib_to_bp)
                    mapped_bps = sorted([bp for bp in sra_output_df['_bioproject'].dropna().astype(str).str.strip().unique() if bp])
                    split_fastq_root = args.fastq_folder if args.fastq_folder else args.filter_fastq
                    split_fastq_index = build_fastq_basename_index(split_fastq_root) if split_fastq_root else {}

                    if not mapped_bps:
                        print("Warning: No SRA rows have a mapped BioProject after library_ID matching.")
                        print("Writing single combined output file instead.")
                        print(f"\nOutput file path: {os.path.abspath(base_output_path)}")
                        write_sra_file(sra_output_df.drop(columns=['_bioproject'], errors='ignore'), base_output_path, ext)
                        add_generated_file(config, base_output_path, "SRA metadata file")
                    else:
                        print(f"Found {len(mapped_bps)} BioProject value(s) in split mapping.")
                        for bp in mapped_bps:
                            bp_df = sra_output_df[sra_output_df['_bioproject'] == bp].copy()
                            bp_df = bp_df.drop(columns=['_bioproject'], errors='ignore')
                            safe_bp = re.sub(r"[^A-Za-z0-9._-]", "_", str(bp))
                            bp_filename = f"{base_path_no_ext}_{safe_bp}{ext}"
                            print(f"\nWriting SRA metadata for BioProject {bp}: {os.path.abspath(bp_filename)}")
                            print(f"  {len(bp_df)} samples")
                            write_sra_file(bp_df, bp_filename, ext)
                            add_generated_file(config, bp_filename, f"SRA metadata file for BioProject {bp}")

                            # Create fastq folder for this split group
                            if split_fastq_root:
                                safe_col = re.sub(r"[^A-Za-z0-9._-]", "_", str(bioproject_col))
                                folder_name = f"{safe_col}_{safe_bp}"
                                folder_path = os.path.join(split_fastq_root, folder_name)
                                os.makedirs(folder_path, exist_ok=True)
                                print(f"  Created/updated fastq split folder: {folder_path}")
                                link_stats = symlink_split_fastq_files(bp_df, split_fastq_root, folder_path, split_fastq_index)
                                print(
                                    "  Fastq symlink summary: "
                                    f"linked={link_stats['linked']}, "
                                    f"missing={link_stats['missing']}, "
                                    f"skipped_existing={link_stats['skipped_existing']}, "
                                    f"errors={link_stats['errors']}, "
                                    f"ignored_non_fastq={link_stats['ignored_non_fastq']}"
                                )

                        # Optional file for unmapped rows to avoid silent data loss
                        unmapped_df = sra_output_df[sra_output_df['_bioproject'].isna()].copy()
                        if len(unmapped_df) > 0:
                            unmapped_df = unmapped_df.drop(columns=['_bioproject'], errors='ignore')
                            unmapped_filename = f"{base_path_no_ext}_NO_BioProject_MATCH{ext}"
                            print(f"\nWriting unmapped rows: {os.path.abspath(unmapped_filename)}")
                            print(f"  {len(unmapped_df)} samples")
                            write_sra_file(unmapped_df, unmapped_filename, ext)
                            add_generated_file(config, unmapped_filename, "SRA metadata rows without BioProject match")

                        sra_output_df = sra_output_df.drop(columns=['_bioproject'], errors='ignore')

            # split_by_BioProject mode finishes writing here
            pass

        else:
            strategy = bioproject_strategy.get('strategy', 'combined')

            if strategy == 'combined':
                # Write single combined file
                print(f"\nOutput file path: {os.path.abspath(base_output_path)}")
                write_sra_file(sra_output_df, base_output_path, ext)
                add_generated_file(config, base_output_path, "SRA metadata file")

            elif strategy == 'separate':
                # Write one file per bioproject
                if not lib_id_to_bioproject:
                    print("Warning: Cannot map samples to bioprojects. Writing single combined file instead.")
                    write_sra_file(sra_output_df, base_output_path, ext)
                    add_generated_file(config, base_output_path, "SRA metadata file")
                else:
                    bioprojects = bioproject_strategy.get('bioprojects', set())
                    if not bioprojects:
                        print("Warning: No bioprojects found. Writing single combined file instead.")
                        write_sra_file(sra_output_df, base_output_path, ext)
                        add_generated_file(config, base_output_path, "SRA metadata file")
                    else:
                        # Add bioproject column to sra_output_df for filtering
                        sra_output_df['_bioproject'] = sra_output_df['library_ID'].map(lib_id_to_bioproject)

                        for bioproject in sorted(bioprojects):
                            # Filter rows for this bioproject
                            bp_df = sra_output_df[sra_output_df['_bioproject'] == bioproject].copy()
                            bp_df = bp_df.drop(columns=['_bioproject'], errors='ignore')

                            if len(bp_df) == 0:
                                print(f"Warning: No samples found for bioproject {bioproject}. Skipping.")
                                continue

                            # Create filename with bioproject identifier
                            bp_filename = f"{base_path_no_ext}_{bioproject}{ext}"
                            print(f"\nWriting SRA metadata for bioproject {bioproject}: {os.path.abspath(bp_filename)}")
                            print(f"  {len(bp_df)} samples")
                            write_sra_file(bp_df, bp_filename, ext)
                            add_generated_file(config, bp_filename, f"SRA metadata file for bioproject {bioproject}")

                        # Remove temporary bioproject column
                        sra_output_df = sra_output_df.drop(columns=['_bioproject'], errors='ignore')

            elif strategy == 'selected':
                # Write file(s) for selected bioprojects only
                selected_bioprojects = bioproject_strategy.get('selected_bioprojects', [])
                if not selected_bioprojects:
                    print("Warning: No bioprojects selected. Writing single combined file instead.")
                    write_sra_file(sra_output_df, base_output_path, ext)
                    add_generated_file(config, base_output_path, "SRA metadata file")
                else:
                    if not lib_id_to_bioproject:
                        print("Warning: Cannot map samples to bioprojects. Writing single combined file instead.")
                        write_sra_file(sra_output_df, base_output_path, ext)
                        add_generated_file(config, base_output_path, "SRA metadata file")
                    else:
                        # Filter to only selected bioprojects
                        sra_output_df['_bioproject'] = sra_output_df['library_ID'].map(lib_id_to_bioproject)
                        filtered_df = sra_output_df[sra_output_df['_bioproject'].isin(selected_bioprojects)].copy()
                        filtered_df = filtered_df.drop(columns=['_bioproject'], errors='ignore')

                        if len(filtered_df) == 0:
                            print("Warning: No samples found for selected bioprojects. Writing empty file.")

                        print(f"\nOutput file path: {os.path.abspath(base_output_path)}")
                        print(f"  Filtered to {len(filtered_df)} samples from {len(selected_bioprojects)} bioproject(s)")
                        write_sra_file(filtered_df, base_output_path, ext)
                        add_generated_file(config, base_output_path, f"SRA metadata file for selected bioprojects: {', '.join(selected_bioprojects)}")

                        # Remove temporary bioproject column
                        sra_output_df = sra_output_df.drop(columns=['_bioproject'], errors='ignore')
            else:
                # Fallback to combined
                print(f"\nOutput file path: {os.path.abspath(base_output_path)}")
                write_sra_file(sra_output_df, base_output_path, ext)
                add_generated_file(config, base_output_path, "SRA metadata file")
            
    except Exception as e:
        print(f"Error writing SRA metadata file(s): {e}\n")
        import traceback
        traceback.print_exc()
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


def detect_empty_corrupted_fastq_files(fastq_folder, output_txt_path):
    """
    Scan fastq folder recursively, detect empty/corrupted FASTQ files, write filename list.

    Returns:
        set: basenames of empty/corrupted files
    """
    import gzip

    def _is_target_fastq(path):
        lower = str(path).lower()
        return lower.endswith(".fastq") or lower.endswith(".fq") or lower.endswith(".fastq.gz") or lower.endswith(".fq.gz")

    def _looks_bad(path):
        try:
            if os.path.getsize(path) == 0:
                return True
            if str(path).lower().endswith(".gz"):
                try:
                    with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
                        chunk = f.read(4096)
                        if not chunk:
                            return True
                except (gzip.BadGzipFile, OSError, UnicodeDecodeError):
                    return True
            else:
                with open(path, "rb") as f:
                    chunk = f.read(4096)
                    if not chunk:
                        return True
            return False
        except Exception:
            return True

    bad_files = []
    for root, _, files in os.walk(fastq_folder):
        for fn in files:
            full = os.path.join(root, fn)
            if not _is_target_fastq(full):
                continue
            if _looks_bad(full):
                bad_files.append(os.path.basename(full))

    bad_set = set(bad_files)
    try:
        with open(output_txt_path, "w", encoding="utf-8") as f:
            if bad_files:
                for fn in sorted(bad_set):
                    f.write(f"{fn}\n")
            else:
                f.write("# No empty/corrupted fastq files found\n")
        print(f"Wrote empty/corrupted fastq filename list to: {output_txt_path}")
    except Exception as e:
        print(f"Warning: Could not write empty/corrupted fastq list: {e}")

    print(f"Detected {len(bad_set)} empty/corrupted fastq file(s) in: {fastq_folder}")
    return bad_set


def is_fastq_file_name(name):
    """Return True for fastq/fq (optionally gzipped) names."""
    lower = str(name).lower()
    return lower.endswith(".fastq") or lower.endswith(".fq") or lower.endswith(".fastq.gz") or lower.endswith(".fq.gz")


def build_fastq_basename_index(source_root):
    """
    Build basename->fullpath index for fastq files under source_root.
    If duplicate basenames exist, first occurrence is used.
    """
    index = {}
    duplicates = set()
    for root, _, files in os.walk(source_root):
        for fn in files:
            if not is_fastq_file_name(fn):
                continue
            full = os.path.join(root, fn)
            if fn in index:
                duplicates.add(fn)
                continue
            index[fn] = full
    if duplicates:
        print(f"Warning: {len(duplicates)} duplicate fastq basename(s) found under {source_root}. First match is used.")
    return index


def split_cell_file_values(value):
    """Split one metadata cell to file entries (supports ; or , separated values)."""
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = [text]
    if ";" in text:
        parts = [p.strip() for p in text.split(";")]
    elif "," in text:
        parts = [p.strip() for p in text.split(",")]
    cleaned = []
    for p in parts:
        p = p.strip().strip('"').strip("'")
        if p:
            cleaned.append(p)
    return cleaned


def symlink_split_fastq_files(bp_df, source_root, target_folder, source_index):
    """
    Create absolute symlinks for fastq files referenced by filename columns in target_folder.
    Uses source_root + direct relative path, absolute path, then basename index fallback.
    """
    filename_cols = [c for c in ["filename", "filename2", "filename3", "filename4"] if c in bp_df.columns]
    if not filename_cols:
        return {"linked": 0, "missing": 0, "skipped_existing": 0, "errors": 0, "ignored_non_fastq": 0}

    linked = 0
    missing = 0
    skipped_existing = 0
    errors = 0
    ignored_non_fastq = 0
    seen_targets = set()

    for _, row in bp_df.iterrows():
        for col in filename_cols:
            for raw_name in split_cell_file_values(row.get(col, "")):
                base = os.path.basename(raw_name)
                if not base:
                    continue
                if not is_fastq_file_name(base):
                    ignored_non_fastq += 1
                    continue

                # Avoid duplicate symlinks within same split folder
                if base in seen_targets:
                    continue
                seen_targets.add(base)

                src_path = None
                if os.path.isabs(raw_name) and os.path.exists(raw_name):
                    src_path = raw_name
                else:
                    rel_candidate = os.path.join(source_root, raw_name)
                    if os.path.exists(rel_candidate):
                        src_path = rel_candidate
                    else:
                        src_path = source_index.get(base)

                if not src_path or not os.path.exists(src_path):
                    missing += 1
                    continue

                dst_path = os.path.join(target_folder, base)
                abs_src = os.path.abspath(src_path)
                if abs_src == os.path.abspath(dst_path):
                    skipped_existing += 1
                    continue
                if os.path.exists(dst_path):
                    skipped_existing += 1
                    continue

                try:
                    os.symlink(abs_src, dst_path)
                    linked += 1
                except Exception:
                    errors += 1

    return {
        "linked": linked,
        "missing": missing,
        "skipped_existing": skipped_existing,
        "errors": errors,
        "ignored_non_fastq": ignored_non_fastq,
    }


def filter_rows_by_filenames(df, filenames_to_remove):
    """
    Filter out rows from DataFrame where any filename column contains a filename from the removal list.
    
    Args:
        df (pd.DataFrame): DataFrame to filter
        filenames_to_remove (set): Set of filenames to remove
    
    Returns:
        pd.DataFrame: Filtered DataFrame with rows removed
    """
    if not filenames_to_remove or len(filenames_to_remove) == 0:
        return df
    
    # Columns to check for filenames
    filename_columns = ['filename', 'filename2', 'filename3', 'filename4', 'assembly', 'fasta_file']
    
    # Find which columns exist in the DataFrame
    existing_filename_cols = [col for col in filename_columns if col in df.columns]
    
    if not existing_filename_cols:
        print("Warning: No filename columns found in SRA metadata. Cannot filter by filenames.")
        return df
    
    # Create a mask for rows to keep (True = keep, False = remove)
    mask = pd.Series([True] * len(df), index=df.index)
    
    # Check each filename column
    for col in existing_filename_cols:
        # Check if any value in this column matches a filename to remove
        # Compare basenames (extract filename from full path if needed)
        col_values = df[col].astype(str).apply(lambda x: os.path.basename(str(x)) if pd.notna(x) and str(x).strip() != '' else '')
        
        # Check if any value matches a filename to remove
        matches = col_values.isin(filenames_to_remove)
        mask = mask & ~matches  # Remove rows that match
    
    # Count how many rows will be removed
    rows_to_remove = (~mask).sum()
    
    if rows_to_remove > 0:
        print(f"Removing {rows_to_remove} rows containing filenames from empty/corrupted fastq detection")
        print(f"  Rows before filtering: {len(df)}")
        print(f"  Rows after filtering: {len(df) - rows_to_remove}")
        
        # Show some examples of removed filenames
        removed_examples = []
        for col in existing_filename_cols:
            col_values = df[col].astype(str).apply(lambda x: os.path.basename(str(x)) if pd.notna(x) and str(x).strip() != '' else '')
            matches = col_values.isin(filenames_to_remove)
            if matches.any():
                example_filenames = col_values[matches].head(5).tolist()
                removed_examples.extend(example_filenames)
        
        if removed_examples:
            print(f"  Example removed filenames: {', '.join(removed_examples[:5])}")
    else:
        print("No rows found matching filenames from empty/corrupted fastq detection")
    
    # Return filtered DataFrame
    return df[mask].copy()


def write_sra_file(df, file_path, ext):
    """
    Write SRA metadata DataFrame to file based on extension.
    
    Args:
        df (pd.DataFrame): DataFrame to write
        file_path (str): Output file path
        ext (str): File extension (.tsv, .csv, .xlsx, .xls)
    """
    if ext == '.tsv':
        df.to_csv(file_path, index=False, sep='\t')
    elif ext == '.csv':
        df.to_csv(file_path, index=False, sep=',')
    elif ext in ('.xlsx', '.xls'):
        df.to_excel(file_path, index=False, engine='openpyxl')
    else:
        # Default to TSV
        df.to_csv(file_path, index=False, sep='\t')
    
    print(f"Successfully wrote SRA metadata to: {file_path}")


def main():
    """Main function to handle command line arguments and run SRA mode."""
    parser = argparse.ArgumentParser(
        description="FAIRe2SRA: Convert FAIRe metadata to NCBI SRA submission format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SRA Mode Arguments:
  --FAIReMetadata PATH       Path to FAIRe metadata Excel file (.xlsx)
  --projectMetadata PATH
  --sampleMetadata PATH
  --experimentRunMetadata PATH
                             Individual FAIRe sheet files (.tsv). Use either --FAIReMetadata OR all three sheet arguments.
  --SRA_Template PATH        Path to SRA template file (.xlsx) [optional; defaults to bundled template]
  --SRA_Metadata PATH        Output file for SRA metadata (.tsv format required) [required]
  --config_file PATH         Path to YAML configuration file for automated responses [optional]
  --NCBI_accession_number PATH Path to table with NCBI accession numbers (biosample and/or bioproject) [optional]
  --filter-fastq PATH        Path to fastq folder; detect empty/corrupted files and filter SRA rows [optional]
  --split_by_BioProject [PATH]
                             Path to table used to split output by BioProject [optional]. If no PATH is passed, uses --NCBI_accession_number.
  --fastq_folder PATH        Path to fastq folder used to create per-group subfolders when splitting [optional]
  --force                    Overwrite output files without prompting [optional]

Examples:
  # SRA mode with config file
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --config_file config.yaml
  
  # SRA mode without config file
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv
  
  # SRA mode with NCBI accession numbers
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --NCBI_accession_number ncbi_accessions.tsv

  # SRA mode with fastq filtering
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --filter-fastq /path/to/fastq_folder
  
  # SRA mode split output by BioProject
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Metadata sra_output.tsv --split_by_BioProject BioSample_attributes.csv --fastq_folder /path/to/fastq_folder
        """
    )
    
    # FAIRe metadata input arguments (either workbook or all 3 sheet files)
    parser.add_argument('--FAIReMetadata', type=str,
                       help='Path to FAIRe metadata Excel file (.xlsx)')
    parser.add_argument('--projectMetadata', type=str,
                       help='Path to projectMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    parser.add_argument('--sampleMetadata', type=str,
                       help='Path to sampleMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    parser.add_argument('--experimentRunMetadata', type=str,
                       help='Path to experimentRunMetadata sheet (.tsv) (required if FAIReMetadata not provided)')
    parser.add_argument('--SRA_Template', type=str,
                       help='Path to SRA template file (.xlsx) [optional; defaults to bundled template]')
    parser.add_argument('--SRA_Metadata', type=str, required=True,
                       help='Output file for SRA metadata (.tsv format required) [required]')
    
    # Optional arguments
    parser.add_argument('--force', action='store_true',
                       help='Overwrite output files without prompting [optional]')
    parser.add_argument('--config_file', type=str,
                       help='Path to YAML configuration file to use for automated responses [optional]')
    parser.add_argument('--NCBI_accession_number', type=str,
                       help='Path to table with NCBI accession numbers (biosample and/or bioproject accessions) [optional]')
    parser.add_argument('--filter-fastq', type=str, default=None,
                       help='Path to fastq folder to scan for empty/corrupted files and filter SRA rows [optional]')
    parser.add_argument(
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
    parser.add_argument('--fastq_folder', type=str, default=None,
                       help='Path to fastq folder used to create split-group subfolders when --split_by_BioProject is used [optional]')
    
    args = parser.parse_args()
    
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
    
    # Check if NCBI_accession_number file exists if provided
    if args.NCBI_accession_number and not os.path.exists(args.NCBI_accession_number):
        parser.error(f"File not found: {args.NCBI_accession_number}")

    # Check filter-fastq folder exists if provided
    if args.filter_fastq and not os.path.isdir(args.filter_fastq):
        parser.error(f"Folder not found: {args.filter_fastq}")

    # Check split_by_BioProject settings
    if args.split_by_BioProject:
        if args.split_by_BioProject == '__USE_NCBI_ACCESSION__':
            if not args.NCBI_accession_number:
                parser.error(
                    "--split_by_BioProject was provided without a file path, but --NCBI_accession_number was not provided. "
                    "Provide --NCBI_accession_number or pass a file path to --split_by_BioProject."
                )
        elif not os.path.exists(args.split_by_BioProject):
            parser.error(f"File not found: {args.split_by_BioProject}")

        # split mode requires a fastq folder source from --fastq_folder or --filter-fastq
        if not args.fastq_folder and not args.filter_fastq:
            parser.error(
                "--split_by_BioProject requires --fastq_folder or --filter-fastq."
            )

    # Check fastq_folder exists if provided
    if args.fastq_folder and not os.path.isdir(args.fastq_folder):
        parser.error(f"Folder not found: {args.fastq_folder}")
    
    # Run SRA mode
    sra_mode(args)


if __name__ == '__main__':
    main()
