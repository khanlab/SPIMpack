"""Pure-Python helpers for generating manifest YAML and datasets TSV content.

These functions are decoupled from Streamlit so they can be tested independently.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

import yaml

from spimpack.models import (
    BIDS_ENTITY_DEFS,
    REQUIRED_CORE_TSV_COLUMNS,
    REQUIRED_DATASET_DESCRIPTION_FIELDS,
)

_BIDS_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")
_VALID_DATASET_TYPES = {"raw", "derivative"}

# Derive required/optional entity column names from the single source of truth.
_REQUIRED_ENTITY_COLUMNS: tuple[str, ...] = tuple(
    ed.short_name for ed in BIDS_ENTITY_DEFS if ed.required
)
_OPTIONAL_ENTITY_COLUMNS: tuple[str, ...] = tuple(
    ed.short_name for ed in BIDS_ENTITY_DEFS if not ed.required
)

#: All TSV columns that must be present for a valid row.
REQUIRED_TSV_COLUMNS: tuple[str, ...] = _REQUIRED_ENTITY_COLUMNS + REQUIRED_CORE_TSV_COLUMNS

#: Default column order used when creating an empty table or writing a new TSV.
DEFAULT_TSV_COLUMNS: tuple[str, ...] = (
    ("dataset_id",)
    + _REQUIRED_ENTITY_COLUMNS
    + _OPTIONAL_ENTITY_COLUMNS
    + ("spim_path", "orientation_string_xyz", "sample_staining")
)


def validate_form(
    dataset_description: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[str]:
    """Return a list of human-readable validation error messages.

    Parameters
    ----------
    dataset_description:
        Mapping that will become the ``dataset_description`` block of the manifest.
    rows:
        Non-empty rows from the datasets table (fully-blank rows should be
        filtered out by the caller before passing here).

    Returns
    -------
    list[str]
        Empty list means the form is valid.
    """
    errors: list[str] = []

    # Required dataset description fields
    for field in REQUIRED_DATASET_DESCRIPTION_FIELDS:
        if not str(dataset_description.get(field, "")).strip():
            errors.append(f"Dataset description: '{field}' is required.")

    # DatasetType value
    dataset_type = str(dataset_description.get("DatasetType", "")).strip()
    if dataset_type and dataset_type not in _VALID_DATASET_TYPES:
        errors.append(
            f"DatasetType must be one of: {', '.join(sorted(_VALID_DATASET_TYPES))}."
        )

    # Authors must be a list if provided
    authors = dataset_description.get("Authors")
    if authors is not None and not isinstance(authors, list):
        errors.append("Authors must be a list.")

    # At least one row
    if not rows:
        errors.append("At least one dataset row is required.")

    for i, row in enumerate(rows, start=1):
        # Required columns must be non-empty
        for col in REQUIRED_TSV_COLUMNS:
            if not str(row.get(col, "")).strip():
                errors.append(f"Row {i}: '{col}' is required.")

        # BIDS entity labels must be alphanumeric
        for ed in BIDS_ENTITY_DEFS:
            val = str(row.get(ed.short_name, "")).strip()
            if val and not _BIDS_LABEL_RE.match(val):
                errors.append(
                    f"Row {i}: '{ed.short_name}' must contain only letters and numbers"
                    f" (got {val!r})."
                )

    return errors


def generate_manifest_yaml(
    dataset_description: dict[str, Any],
    tsv_filename: str = "datasets.tsv",
) -> str:
    """Return YAML text for a ``manifest.yml`` file.

    Parameters
    ----------
    dataset_description:
        Mapping that becomes the ``dataset_description`` block.
    tsv_filename:
        Relative filename reference written as ``datasets_tsv``.
    """
    manifest: dict[str, Any] = {
        "dataset_description": {
            k: v
            for k, v in dataset_description.items()
            if v is not None and v != "" and v != []
        },
        "datasets_tsv": tsv_filename,
    }
    return yaml.dump(manifest, default_flow_style=False, allow_unicode=True, sort_keys=False)


def generate_tsv(
    rows: list[dict[str, Any]],
    extra_columns: list[str] | None = None,
) -> str:
    """Return tab-separated text for a ``datasets.tsv`` file.

    Parameters
    ----------
    rows:
        Non-empty row dicts.  The function determines column order automatically.
    extra_columns:
        Additional PascalCase sidecar-metadata column names to include even if
        no row carries a value for them yet.

    Returns
    -------
    str
        Complete TSV content including header line.
    """
    extra_cols: list[str] = list(extra_columns or [])
    known = set(DEFAULT_TSV_COLUMNS)

    # Collect extra columns seen in rows but not in the default set
    for row in rows:
        for key in row:
            if key not in known and key not in extra_cols:
                extra_cols.append(key)

    columns = list(DEFAULT_TSV_COLUMNS) + extra_cols

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=columns,
        delimiter="\t",
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in columns})
    return output.getvalue()
