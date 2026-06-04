from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_DATASET_DESCRIPTION_FIELDS = ("Name", "BIDSVersion", "DatasetType", "License")

#: Names of ImageAsset attributes that are written directly to the JSON sidecar.
SIDECAR_ASSET_FIELDS = ("orientation_string_xyz", "sample_staining")

#: TSV columns that are required and map to ImageAsset / dataset fields (not entities, not sidecar).
REQUIRED_CORE_TSV_COLUMNS = ("dataset_id", "source_ims", "orientation_string_xyz", "sample_staining")

#: Path pattern used by pybids build_path for BIDS microscopy assets.
BIDS_MICR_PATTERN = (
    "sub-{subject}/[ses-{session}/]micr/"
    "sub-{subject}[_ses-{session}][_sample-{sample}][_acq-{acquisition}]_{suffix}{extension}"
)


@dataclass(frozen=True)
class EntityDef:
    """Definition of a BIDS entity used in filenames and TSV columns."""

    long_name: str   # used in BidsEntities and pybids build_path
    short_name: str  # used as TSV column header (e.g. 'sub', 'ses', 'acq')
    required: bool


#: Ordered BIDS entity definitions for SPIM microscopy data.
BIDS_ENTITY_DEFS: tuple[EntityDef, ...] = (
    EntityDef("subject", "sub", True),
    EntityDef("sample", "sample", True),
    EntityDef("session", "ses", False),
    EntityDef("acquisition", "acq", False),
)


@dataclass(frozen=True)
class BidsEntities:
    """BIDS entities that uniquely identify one image asset within a dataset."""

    subject: str
    sample: str
    session: str | None = None
    acquisition: str | None = None


@dataclass(frozen=True)
class ImageAsset:
    """A source microscopy image and its required sidecar metadata."""

    source_ims: Path
    entities: BidsEntities
    orientation_string_xyz: str
    sample_staining: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetSpec:
    """A logical dataset package with one or more image assets."""

    dataset_id: str
    assets: list[ImageAsset]


@dataclass(frozen=True)
class DatasetManifest:
    """Top-level package manifest consumed by writer backends."""

    dataset_description: dict[str, Any]
    datasets: list[DatasetSpec]
