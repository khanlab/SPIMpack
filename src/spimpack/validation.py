from __future__ import annotations

import re

from .models import (
    REQUIRED_DATASET_DESCRIPTION_FIELDS,
    SIDECAR_ASSET_FIELDS,
    BidsEntities,
    DatasetManifest,
)

_BIDS_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")
_VALID_DATASET_TYPES = {"raw", "derivative"}


class ValidationError(ValueError):
    """Raised when manifest metadata are missing or inconsistent."""


def _validate_bids_label(value: str, field_name: str) -> None:
    """Raise ValidationError if *value* is not a valid BIDS label (alphanumeric only)."""
    if not _BIDS_LABEL_RE.match(value):
        raise ValidationError(
            f"BIDS entity '{field_name}' value {value!r} must contain only letters and numbers"
        )


def _validate_entities(entities: BidsEntities) -> None:
    _validate_bids_label(entities.subject, "subject (sub)")
    _validate_bids_label(entities.sample, "sample (sample)")
    if entities.session is not None:
        _validate_bids_label(entities.session, "session (ses)")
    if entities.acquisition is not None:
        _validate_bids_label(entities.acquisition, "acquisition (acq)")


def validate_manifest(manifest: DatasetManifest) -> None:
    missing_top = [
        key
        for key in REQUIRED_DATASET_DESCRIPTION_FIELDS
        if not manifest.dataset_description.get(key)
    ]
    if missing_top:
        raise ValidationError(
            f"dataset_description missing required fields: {', '.join(missing_top)}"
        )

    dataset_type = manifest.dataset_description.get("DatasetType", "")
    if dataset_type and dataset_type not in _VALID_DATASET_TYPES:
        raise ValidationError(
            f"dataset_description DatasetType must be one of {sorted(_VALID_DATASET_TYPES)}, "
            f"got {dataset_type!r}"
        )

    authors = manifest.dataset_description.get("Authors")
    if authors is not None and not isinstance(authors, list):
        raise ValidationError("dataset_description Authors must be a list")

    extra_required = manifest.dataset_description.get("RequiredMicroscopyFields", [])
    if extra_required and not isinstance(extra_required, list):
        raise ValidationError("dataset_description.RequiredMicroscopyFields must be a list")

    dataset_ids: set[str] = set()
    for dataset in manifest.datasets:
        if not dataset.dataset_id:
            raise ValidationError("dataset_id is required for each dataset")
        if dataset.dataset_id in dataset_ids:
            raise ValidationError(f"duplicate dataset_id: {dataset.dataset_id}")
        dataset_ids.add(dataset.dataset_id)

        for asset in dataset.assets:
            if not asset.spim_path:
                raise ValidationError(
                    f"dataset {dataset.dataset_id} has asset missing spim_path"
                )
            if not asset.spim_path.exists():
                raise ValidationError(f"spim_path does not exist: {asset.spim_path}")

            _validate_entities(asset.entities)

            missing_sidecar = []
            for key in SIDECAR_ASSET_FIELDS:
                value = getattr(asset, key)
                if not value:
                    missing_sidecar.append(key)
            for key in extra_required:
                if not asset.metadata.get(key):
                    missing_sidecar.append(key)

            if missing_sidecar:
                raise ValidationError(
                    f"asset sub-{asset.entities.subject} missing required sidecar metadata: "
                    f"{', '.join(missing_sidecar)}"
                )
