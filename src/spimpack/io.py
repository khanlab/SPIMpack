from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from .models import BidsEntities, DatasetManifest, DatasetSpec, ImageAsset


REQUIRED_TSV_COLUMNS = (
    "dataset_id",
    "subject",
    "sample",
    "spim_path",
    "orientation_string_xyz",
    "sample_staining",
)
OPTIONAL_TSV_ENTITY_COLUMNS = ("session", "acquisition")


def _parse_channels(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    items = [v.strip() for v in str(raw).replace(",", ";").split(";")]
    return [v for v in items if v]


def _entities_from_row(row: dict[str, str]) -> BidsEntities:
    return BidsEntities(
        subject=row["subject"],
        sample=row["sample"],
        session=row.get("session") or None,
        acquisition=row.get("acquisition") or None,
    )


def _entities_from_dict(asset: dict[str, Any]) -> BidsEntities:
    return BidsEntities(
        subject=asset["subject"],
        sample=asset["sample"],
        session=asset.get("session") or None,
        acquisition=asset.get("acquisition") or None,
    )


def load_manifest(path: Path) -> DatasetManifest:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    dataset_description = raw.get("dataset_description", {})
    datasets: dict[str, DatasetSpec] = {}

    for dataset in raw.get("datasets", []):
        dataset_id = dataset["dataset_id"]
        assets = [
            ImageAsset(
                spim_path=Path(asset["spim_path"]).expanduser(),
                entities=_entities_from_dict(asset),
                orientation_string_xyz=asset["orientation_string_xyz"],
                sample_staining=_parse_channels(asset["sample_staining"]),
                metadata=asset.get("metadata", {}),
            )
            for asset in dataset.get("assets", [])
        ]
        datasets[dataset_id] = DatasetSpec(dataset_id=dataset_id, assets=assets)

    tsv_path = raw.get("datasets_tsv")
    if tsv_path:
        tsv_manifest = (path.parent / tsv_path).resolve()
        with tsv_manifest.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            fieldnames = reader.fieldnames or []
            missing = [c for c in REQUIRED_TSV_COLUMNS if c not in fieldnames]
            if missing:
                raise ValueError(
                    f"datasets_tsv missing required columns: {', '.join(missing)}"
                )
            for row in reader:
                dataset_id = row["dataset_id"]
                asset = ImageAsset(
                    spim_path=Path(row["spim_path"]).expanduser(),
                    entities=_entities_from_row(row),
                    orientation_string_xyz=row["orientation_string_xyz"],
                    sample_staining=_parse_channels(row["sample_staining"]),
                    metadata=_parse_row_metadata(row, fieldnames),
                )
                existing = datasets.get(dataset_id)
                if existing:
                    datasets[dataset_id] = DatasetSpec(
                        dataset_id=existing.dataset_id,
                        assets=[*existing.assets, asset],
                    )
                else:
                    datasets[dataset_id] = DatasetSpec(
                        dataset_id=dataset_id,
                        assets=[asset],
                    )

    return DatasetManifest(dataset_description=dataset_description, datasets=list(datasets.values()))


def _parse_row_metadata(row: dict[str, str], fieldnames: list[str]) -> dict[str, Any]:
    skip = set(REQUIRED_TSV_COLUMNS) | set(OPTIONAL_TSV_ENTITY_COLUMNS)
    metadata: dict[str, Any] = {}
    for key in fieldnames:
        value = row.get(key)
        if key in skip or value in (None, ""):
            continue
        metadata[key] = value
    return metadata
