from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from .models import DatasetManifest, DatasetSpec, ImageAsset


REQUIRED_TSV_COLUMNS = (
    "dataset_id",
    "bids_subdir",
    "source_ims",
    "output_prefix",
    "orientation",
    "channel_labels",
)


def _parse_channels(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    items = [v.strip() for v in str(raw).replace(",", ";").split(";")]
    return [v for v in items if v]


def load_manifest(path: Path) -> DatasetManifest:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    dataset_description = raw.get("dataset_description", {})
    datasets: dict[str, DatasetSpec] = {}

    for dataset in raw.get("datasets", []):
        dataset_id = dataset["dataset_id"]
        assets = [
            ImageAsset(
                source_ims=Path(asset["source_ims"]).expanduser(),
                output_prefix=asset["output_prefix"],
                orientation=asset["orientation"],
                channel_labels=_parse_channels(asset["channel_labels"]),
                metadata=asset.get("metadata", {}),
            )
            for asset in dataset.get("assets", [])
        ]
        datasets[dataset_id] = DatasetSpec(
            dataset_id=dataset_id,
            bids_subdir=dataset["bids_subdir"],
            assets=assets,
        )

    tsv_path = raw.get("datasets_tsv")
    if tsv_path:
        tsv_manifest = (path.parent / tsv_path).resolve()
        with tsv_manifest.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            missing = [c for c in REQUIRED_TSV_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(
                    f"datasets_tsv missing required columns: {', '.join(missing)}"
                )
            for row in reader:
                dataset_id = row["dataset_id"]
                asset = ImageAsset(
                    source_ims=Path(row["source_ims"]).expanduser(),
                    output_prefix=row["output_prefix"],
                    orientation=row["orientation"],
                    channel_labels=_parse_channels(row["channel_labels"]),
                    metadata=_parse_row_metadata(row),
                )
                existing = datasets.get(dataset_id)
                if existing:
                    if existing.bids_subdir != row["bids_subdir"]:
                        raise ValueError(
                            f"dataset {dataset_id} has inconsistent bids_subdir values"
                        )
                    datasets[dataset_id] = DatasetSpec(
                        dataset_id=existing.dataset_id,
                        bids_subdir=existing.bids_subdir,
                        assets=[*existing.assets, asset],
                    )
                else:
                    datasets[dataset_id] = DatasetSpec(
                        dataset_id=dataset_id,
                        bids_subdir=row["bids_subdir"],
                        assets=[asset],
                    )

    return DatasetManifest(dataset_description=dataset_description, datasets=list(datasets.values()))


def _parse_row_metadata(row: dict[str, str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in row.items():
        if key in REQUIRED_TSV_COLUMNS or value in (None, ""):
            continue
        metadata[key] = value
    return metadata
