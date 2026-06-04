from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from .models import (
    BIDS_ENTITY_DEFS,
    REQUIRED_CORE_TSV_COLUMNS,
    BidsEntities,
    DatasetManifest,
    DatasetSpec,
    ImageAsset,
)


# Derive column sets from the single source of truth in models.py
_REQUIRED_ENTITY_COLUMNS = tuple(ed.short_name for ed in BIDS_ENTITY_DEFS if ed.required)
_OPTIONAL_ENTITY_COLUMNS = tuple(ed.short_name for ed in BIDS_ENTITY_DEFS if not ed.required)
_ALL_ENTITY_SHORT_NAMES = frozenset(ed.short_name for ed in BIDS_ENTITY_DEFS)

REQUIRED_TSV_COLUMNS = _REQUIRED_ENTITY_COLUMNS + REQUIRED_CORE_TSV_COLUMNS


def _parse_channels(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    items = [v.strip() for v in str(raw).replace(",", ";").split(";")]
    return [v for v in items if v]


def _entities_from_row(row: dict[str, str]) -> BidsEntities:
    """Build BidsEntities from a TSV row using short entity column names."""
    kwargs: dict[str, str | None] = {}
    for ed in BIDS_ENTITY_DEFS:
        kwargs[ed.long_name] = row.get(ed.short_name) or None
    return BidsEntities(**kwargs)  # type: ignore[arg-type]


def _entities_from_dict(asset: dict[str, Any]) -> BidsEntities:
    """Build BidsEntities from a YAML asset dict using long entity names."""
    kwargs: dict[str, str | None] = {}
    for ed in BIDS_ENTITY_DEFS:
        kwargs[ed.long_name] = asset.get(ed.long_name) or None
    return BidsEntities(**kwargs)  # type: ignore[arg-type]


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
    """Extract sidecar metadata from a TSV row.

    Columns that are BIDS entity short names or core required columns are skipped.
    Remaining columns whose names start with an uppercase letter (PascalCase) are
    treated as JSON sidecar metadata and preserved as-is.
    """
    skip = _ALL_ENTITY_SHORT_NAMES | set(REQUIRED_CORE_TSV_COLUMNS)
    metadata: dict[str, Any] = {}
    for key in fieldnames:
        value = row.get(key)
        if key in skip or value in (None, ""):
            continue
        if key and key[0].isupper():
            metadata[key] = value
    return metadata
