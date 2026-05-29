from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_DATASET_DESCRIPTION_FIELDS = ("Name", "BIDSVersion")
REQUIRED_SIDECAR_FIELDS = ("orientation", "channel_labels")


@dataclass(frozen=True)
class ImageAsset:
    """A source microscopy image and its required sidecar metadata."""

    source_ims: Path
    output_prefix: str
    orientation: str
    channel_labels: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetSpec:
    """A logical dataset package with one or more image assets."""

    dataset_id: str
    bids_subdir: str
    assets: list[ImageAsset]


@dataclass(frozen=True)
class DatasetManifest:
    """Top-level package manifest consumed by writer backends."""

    dataset_description: dict[str, Any]
    datasets: list[DatasetSpec]
