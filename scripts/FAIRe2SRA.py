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
        while True:
            response = input(prompt).strip().lower()
            if not response and default:
                return default
            if response in valid_choices:
                return response
            print(f"Invalid choice. Please enter one of: {', '.join(valid_choices)}")


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
                'Use default value or choose from allowed values? [default/Other]:': {},
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
            'generated_files': config.get('generated_files', [])
        }
        
        # If config already has structured sections (from template), preserve them
        for section_name in ['CONFIGURATION_FILE_HANDLING', 'OUTPUT_FILE_OVERWRITE', 'ASSAY_SELECTION', 
                           'LIBRARY_FIELD_CONFIGURATION', 'PLATFORM_VALUES_CONFIGURATION', 
                           'INSTRUMENT_MODEL_VALUES_CONFIGURATION']:
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
                if not isinstance(structured_config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'], dict):
                    structured_config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'] = {}
                structured_config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'][question] = answer
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
                ('INSTRUMENT_MODEL_VALUES_CONFIGURATION', 'INSTRUMENT MODEL VALUES CONFIGURATION', 'Instrument model choices per assay')
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
    elif "Use default value or choose from allowed values" in question:
        if 'LIBRARY_FIELD_CONFIGURATION' not in config:
            config['LIBRARY_FIELD_CONFIGURATION'] = {}
        if 'Use default value or choose from allowed values? [default/Other]:' not in config['LIBRARY_FIELD_CONFIGURATION']:
            config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'] = {}
        if config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'] is None:
            config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'] = {}
        config['LIBRARY_FIELD_CONFIGURATION']['Use default value or choose from allowed values? [default/Other]:'][question] = answer
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
    elif "Use default value or choose from allowed values" in question:
        # Look in the field values dictionary
        field_values = config.get('LIBRARY_FIELD_CONFIGURATION', {}).get('Use default value or choose from allowed values? [default/Other]:', {})
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
            
            # Try with leading spaces removed
            alt_question = question.strip()
            answer = field_values.get(alt_question, '')
            if answer != '':
                return answer
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
        if saved_answer is not None:
            print(f"{question} {saved_answer}")
            add_qa(config, question, saved_answer, use_config_file)
            return saved_answer
    
    # Always prompt user and save the answer
    value = prompt_func(*args, **kwargs)
    add_qa(config, question, value, use_config_file)
    return value


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
    
    # Initialize config and determine config file handling strategy
    config = {}
    use_config_file = False
    config_file_path = None
    is_template_config = False
    
    # Handle config file logic based on user input
    if args.config_file:
        # Check if the provided config file is the template
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, 'SRA_Metadata_Config_Template.yaml')
        
        # Check if the provided config file is the template (handle both absolute and relative paths)
        abs_config_file = os.path.abspath(args.config_file)
        abs_template_path = os.path.abspath(template_path)
        
        # Also check if the filename matches the template filename
        config_filename = os.path.basename(args.config_file)
        template_filename = os.path.basename(template_path)
        
        is_template_file = (abs_config_file == abs_template_path) or (config_filename == template_filename)
        
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
        # No config file provided, generate config file path based on SRA metadata name
        config_file_path = get_config_file_path(args.SRA_Metadata)
    
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

    # Create SRA_Metadata by copying the template structure
    print(f"\nCreating SRA metadata file: {args.SRA_Metadata}")
    
    # Copy the template structure to create the output file
    # We'll create a new DataFrame with the same columns as the template
    sra_output_df = pd.DataFrame(columns=sra_template_df.columns)
    
    # STEP 2: Read FAIRe metadata and handle assay selection
    print(f"\nReading sample metadata from: {args.FAIReMetadata}")
    try:
        sample_df = pd.read_excel(args.FAIReMetadata, sheet_name='experimentRunMetadata', header=2, engine='openpyxl')
    except Exception as e:
        print(f"Warning: Could not read with openpyxl engine: {e}")
        try:
            sample_df = pd.read_excel(args.FAIReMetadata, sheet_name='experimentRunMetadata', header=2, engine='xlrd')
        except Exception as e2:
            print(f"Warning: Could not read with xlrd engine: {e2}")
            try:
                sample_df = pd.read_excel(args.FAIReMetadata, sheet_name='experimentRunMetadata', header=2)
            except Exception as e3:
                print(f"Error: Could not read Excel file: {e3}")
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
        print(f"\n" + "="*50)
        print("ASSAY SELECTION")
        print("="*50)
        print(f"Single assay found: \"{unique_assays[0]}\"")
        selected_assays = unique_assays
    else:
        print(f"\n" + "="*50)
        print("ASSAY SELECTION")
        print("="*50)
        print(f"Multiple assays found in 'assay_name' column:")
        for i, assay in enumerate(unique_assays, 1):
            print(f"  {i}. {assay}")
        
        # Ask user for preference
        choice = get_config_value(
            config,
            'assay_selection_choice',
            get_valid_user_choice,
            "\nDo you want to use all assays or only specific ones? [all/specific]: ",
            use_config_file,
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
                    user_input = get_config_value(
                        config,
                        'selected_assays_input',
                        input,
                        "Selected assays: ",
                        use_config_file,
                        "Selected assays: "
                    ).strip()
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
    
    # Read sampleMetadata sheet for organism and geo_loc_name information
    try:
        sample_metadata_df = pd.read_excel(args.FAIReMetadata, sheet_name='sampleMetadata', header=2, engine='openpyxl')
    except Exception as e:
        print(f"Warning: Could not read sampleMetadata sheet: {e}")
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
        project_df = pd.read_excel(args.FAIReMetadata, sheet_name='projectMetadata', header=0, engine='openpyxl')
        
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
        
        # Find seq_kit row in term_name column (column 3)
        seq_kit_row = None
        for idx, row in project_df.iterrows():
            if str(row.iloc[2]).strip().lower() == 'seq_kit':  # column 3 (index 2)
                seq_kit_row = row
                break
        
        if seq_kit_row is None:
            project_instrument_model = None
        else:
            project_instrument_model = str(seq_kit_row.iloc[3]).strip()  # column 4 (index 3) - project_level
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
        
        choice = get_config_value(
            config,
            f'library_field_{field}_choice',
            get_valid_user_choice,
            f"  Use default value or choose from allowed values for {field}? [default/Other]: ",
            use_config_file,
            f"  Use default value or choose from allowed values for {field}? [default/Other]: ",
            ["default", "Other"],
            default="default"
        )
        
        if choice == "Other":
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
        try:
            # Find the seq_kit row in projectMetadata
            seq_kit_row_idx = None
            for idx, row in project_df.iterrows():
                if str(row.iloc[2]).strip().lower() == 'seq_kit':  # column 3 (index 2)
                    seq_kit_row_idx = idx
                    break
            
            if seq_kit_row_idx is not None:
                seq_kit_row = project_df.iloc[seq_kit_row_idx]
                
                # Look for the assay column in the projectMetadata sheet
                for col_idx, col_name in enumerate(project_df.columns):
                    if str(col_name).strip() == assay_name:
                        # Found the assay column, get instrument_model value from that column
                        assay_instrument_model = str(seq_kit_row.iloc[col_idx]).strip()
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
    
    # Add rows for each sample and perform mapping
    for i, sample_row in sample_df.iterrows():
        # Create a new row with empty values for all SRA template columns
        new_row = pd.Series([''] * len(sra_template_df.columns), index=sra_template_df.columns)
        
        # 1. Copy lib_id to library_ID
        if 'lib_id' in sample_df.columns and 'library_ID' in sra_output_df.columns:
            new_row['library_ID'] = sample_row['lib_id']
        
        # 2. Copy filename and filename2 values
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
    
    # Write the SRA metadata file
    print(f"\n" + "="*50)
    print("WRITING SRA METADATA")
    print("="*50)
    
    # Show mapping results
    print(f"Created SRA metadata with {len(sra_output_df)} rows and {len(sra_output_df.columns)} columns")
    print(f"Successfully mapped metadata for {len(sample_df)} samples")
    
    print(f"\nOutput file path: {os.path.abspath(args.SRA_Metadata)}")
    try:
        sra_output_df.to_excel(args.SRA_Metadata, index=False, engine='openpyxl')
        print(f"Successfully wrote SRA metadata to: {args.SRA_Metadata}\n")
        # Track the generated SRA metadata file
        add_generated_file(config, args.SRA_Metadata, "SRA metadata file")
    except Exception as e:
        print(f"Error writing SRA metadata file: {e}\n")
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
            print(f"Template file remains unchanged: {args.config_file}")
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


def main():
    """Main function to handle command line arguments and run SRA mode."""
    parser = argparse.ArgumentParser(
        description="FAIRe2SRA: Convert FAIRe metadata to NCBI SRA submission format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SRA Mode Arguments:
  --FAIReMetadata PATH       Path to FAIRe metadata Excel file (.xlsx) [required]
  --SRA_Template PATH        Path to SRA template file (.xlsx) [required]
  --SRA_Metadata PATH        Output Excel file for SRA metadata [required]
  --config_file PATH         Path to YAML configuration file for automated responses [optional]
  --force                    Overwrite output files without prompting [optional]

Examples:
  # SRA mode with config file
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Template sra_template.xlsx --SRA_Metadata sra_output.xlsx --config_file config.yaml
  
  # SRA mode without config file
  python FAIRe2SRA.py --FAIReMetadata data.xlsx --SRA_Template sra_template.xlsx --SRA_Metadata sra_output.xlsx
        """
    )
    
    # Required arguments
    parser.add_argument('--FAIReMetadata', type=str, required=True,
                       help='Path to FAIRe metadata Excel file (.xlsx) [required]')
    parser.add_argument('--SRA_Template', type=str, required=True,
                       help='Path to SRA template file (.xlsx) [required]')
    parser.add_argument('--SRA_Metadata', type=str, required=True,
                       help='Output Excel file for SRA metadata [required]')
    
    # Optional arguments
    parser.add_argument('--force', action='store_true',
                       help='Overwrite output files without prompting [optional]')
    parser.add_argument('--config_file', type=str,
                       help='Path to YAML configuration file to use for automated responses [optional]')
    
    args = parser.parse_args()
    
    # Check if files exist
    for file_arg in ['FAIReMetadata', 'SRA_Template']:
        file_path = getattr(args, file_arg)
        if not os.path.exists(file_path):
            parser.error(f"File not found: {file_path}")
    
    # Run SRA mode
    sra_mode(args)


if __name__ == '__main__':
    main()
