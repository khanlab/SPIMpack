from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_DATASET_DESCRIPTION_FIELDS = ("Name", "BIDSVersion", "DatasetType", "License")
REQUIRED_SIDECAR_FIELDS = ("orientation_string_xyz", "sample_staining")

#: Path pattern used by pybids build_path for BIDS microscopy assets.
BIDS_MICR_PATTERN = (
    "sub-{subject}/[ses-{session}/]micr/"
    "sub-{subject}[_ses-{session}][_sample-{sample}][_acq-{acquisition}]_{suffix}{extension}"
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

    spim_path: Path
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
