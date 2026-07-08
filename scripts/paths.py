"""Shared path helpers for bundled repo files and user inputs."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

NCBI_BIOSAMPLE_TEMPLATE_NAME = "NCBI_BioSample_Metadata_Template.tsv"
NCBI_SRA_TEMPLATE_NAME = "NCBI_SRA_Metadata_Template.xlsx"
BIOSAMPLE_CONFIG_TEMPLATE_NAME = "BioSample_config_file_template.yaml"
SRA_CONFIG_TEMPLATE_NAME = "SRA_config_file_template.yaml"
MIXS_YAML_NAME = "mixs.yaml"

DEFAULT_BIOSAMPLE_TEMPLATE = DOCS_DIR / NCBI_BIOSAMPLE_TEMPLATE_NAME
DEFAULT_SRA_TEMPLATE = DOCS_DIR / NCBI_SRA_TEMPLATE_NAME
DEFAULT_MIXS_YAML = DOCS_DIR / MIXS_YAML_NAME


def get_docs_path(filename: str) -> Path:
    """Return the path to a file in the repo docs/ directory."""
    return DOCS_DIR / filename


def resolve_input_path(path=None, *, default=None) -> str:
    """
    Resolve a user-provided file path or fall back to a bundled default.

    Resolution order for explicit paths:
      1. Absolute path
      2. Relative to current working directory
      3. Relative to repo root
      4. Relative to repo docs/
      5. Basename match in repo docs/
    """
    if path is None:
        if default is None:
            raise ValueError("No path provided and no default available.")
        default_path = Path(default)
        if not default_path.is_file():
            raise FileNotFoundError(f"Default bundled file not found: {default_path}")
        return str(default_path.resolve())

    candidate_path = Path(path).expanduser()
    candidates = []

    if candidate_path.is_absolute():
        candidates.append(candidate_path)
    else:
        candidates.extend([
            Path.cwd() / candidate_path,
            REPO_ROOT / candidate_path,
            DOCS_DIR / candidate_path,
            DOCS_DIR / candidate_path.name,
        ])

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    raise FileNotFoundError(f"File not found: {path}")
