"""
FAIRe2NCBI package

A package for converting FAIRe metadata to NCBI submission formats.
"""

__version__ = "2.0"
__author__ = "Clement Coclet"

from .cli import main, create_parser, validate_biosample_args, validate_sra_args

__all__ = [
    'main',
    'create_parser', 
    'validate_biosample_args',
    'validate_sra_args'
]
