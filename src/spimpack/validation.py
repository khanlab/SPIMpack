from __future__ import annotations

from pathlib import Path

from .models import (
    REQUIRED_DATASET_DESCRIPTION_FIELDS,
    REQUIRED_SIDECAR_FIELDS,
    DatasetManifest,
)


class ValidationError(ValueError):
    """Raised when manifest metadata are missing or inconsistent."""


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

        if not dataset.bids_subdir:
            raise ValidationError(f"dataset {dataset.dataset_id} missing bids_subdir")
        if Path(dataset.bids_subdir).is_absolute():
            raise ValidationError(
                f"dataset {dataset.dataset_id} bids_subdir must be a relative path"
            )

        for asset in dataset.assets:
            if not asset.output_prefix:
                raise ValidationError(
                    f"dataset {dataset.dataset_id} has asset missing output_prefix"
                )
            if not asset.source_ims:
                raise ValidationError(
                    f"dataset {dataset.dataset_id} has asset missing source_ims"
                )
            if not asset.source_ims.exists():
                raise ValidationError(f"source_ims does not exist: {asset.source_ims}")

            missing_sidecar = []
            for key in REQUIRED_SIDECAR_FIELDS:
                value = getattr(asset, key)
                if not value:
                    missing_sidecar.append(key)
            for key in extra_required:
                if not asset.metadata.get(key):
                    missing_sidecar.append(key)

            if missing_sidecar:
                raise ValidationError(
                    f"asset {asset.output_prefix} missing required sidecar metadata: "
                    f"{', '.join(missing_sidecar)}"
                )
