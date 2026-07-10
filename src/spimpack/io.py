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
    ParticipantSpec,
    participant_id_with_prefix,
    participant_label_from_id,
)


# Derive column sets from the single source of truth in models.py
_REQUIRED_ENTITY_COLUMNS = tuple(ed.long_name for ed in BIDS_ENTITY_DEFS if ed.required)
_OPTIONAL_ENTITY_COLUMNS = tuple(ed.long_name for ed in BIDS_ENTITY_DEFS if not ed.required)
_ALL_ENTITY_COLUMNS = frozenset(ed.long_name for ed in BIDS_ENTITY_DEFS)

REQUIRED_TSV_COLUMNS = _REQUIRED_ENTITY_COLUMNS + REQUIRED_CORE_TSV_COLUMNS


def _parse_channels(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    items = [v.strip() for v in str(raw).replace(",", ";").split(";")]
    return [v for v in items if v]


def _entities_from_row(row: dict[str, str]) -> BidsEntities:
    """Build BidsEntities from a TSV row using long entity column names."""
    kwargs: dict[str, str | None] = {}
    for ed in BIDS_ENTITY_DEFS:
        kwargs[ed.long_name] = row.get(ed.long_name) or None
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

    for index, dataset in enumerate(raw.get("datasets", []), start=1):
        dataset_id = dataset.get("dataset_id") or f"dataset-{index}"
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

    participants = _load_participants(path, raw)

    scans_tsv_path = _resolve_scans_tsv(path, raw)
    if scans_tsv_path:
        scan_assets = _load_scan_assets(scans_tsv_path, participants)
        if scan_assets:
            datasets["scans"] = DatasetSpec(dataset_id="scans", assets=scan_assets)

    return DatasetManifest(
        dataset_description=dataset_description,
        datasets=list(datasets.values()),
        participants=participants,
    )


def _resolve_scans_tsv(manifest_path: Path, raw_manifest: dict[str, Any]) -> Path | None:
    scans_tsv = raw_manifest.get("scans_tsv")
    if scans_tsv:
        return _resolve_manifest_table_path(manifest_path, scans_tsv, "scans_tsv")
    scans_default = manifest_path.parent / "scans.tsv"
    if scans_default.exists():
        return scans_default.resolve()
    return None


def _load_scan_assets(
    scans_tsv_path: Path,
    participants: list[ParticipantSpec],
) -> list[ImageAsset]:
    with scans_tsv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = reader.fieldnames or []
        missing = [c for c in REQUIRED_TSV_COLUMNS if c not in fieldnames]
        if missing:
            raise ValueError(
                f"scans_tsv missing required columns: {', '.join(missing)}"
            )

        participant_map = {
            participant_label_from_id(p.participant_id): p for p in participants
        }

        scan_assets: list[ImageAsset] = []
        for scan_row in reader:
            if participant_map:
                scan_subject = (scan_row.get("subject") or "").strip()
                if scan_subject not in participant_map:
                    raise ValueError(
                        f"scan subject sub-{scan_subject} is not listed in participants.tsv"
                    )

            scan_assets.append(
                ImageAsset(
                    spim_path=Path(scan_row["spim_path"]).expanduser(),
                    entities=_entities_from_row(scan_row),
                    orientation_string_xyz=scan_row["orientation_string_xyz"],
                    sample_staining=_parse_channels(scan_row["sample_staining"]),
                    metadata=_parse_row_metadata(scan_row, fieldnames),
                )
            )

    return scan_assets


def _load_participants(manifest_path: Path, raw_manifest: dict[str, Any]) -> list[ParticipantSpec]:
    participants_tsv = raw_manifest.get("participants_tsv")
    if participants_tsv:
        participants_path = _resolve_manifest_table_path(
            manifest_path, participants_tsv, "participants_tsv"
        )
    else:
        default_path = manifest_path.parent / "participants.tsv"
        if not default_path.exists():
            return []
        participants_path = default_path.resolve()

    with participants_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = reader.fieldnames or []
        if "participant_id" not in fieldnames:
            raise ValueError("participants_tsv missing required column: participant_id")

        participants: list[ParticipantSpec] = []
        participant_ids: set[str] = set()
        for participant_row in reader:
            participant_id = (participant_row.get("participant_id") or "").strip()
            if not participant_id:
                raise ValueError("participants.tsv row is missing participant_id")
            normalized_id = participant_id_with_prefix(participant_id)
            if normalized_id in participant_ids:
                raise ValueError(f"duplicate participant_id in participants.tsv: {participant_id}")
            participant_ids.add(normalized_id)

            metadata = {
                key: value
                for key, value in participant_row.items()
                if key != "participant_id" and value not in (None, "")
            }
            participants.append(
                ParticipantSpec(participant_id=normalized_id, metadata=metadata)
            )
        return participants


def _resolve_manifest_table_path(
    manifest_path: Path,
    table_path: str,
    manifest_key: str,
) -> Path:
    relative_path = Path(table_path)
    if relative_path.is_absolute():
        raise ValueError(f"{manifest_key} must be a relative path next to the manifest")

    manifest_dir = manifest_path.parent.resolve()
    resolved = (manifest_dir / relative_path).resolve()
    try:
        resolved.relative_to(manifest_dir)
    except ValueError as exc:
        raise ValueError(
            f"{manifest_key} must resolve inside the manifest directory"
        ) from exc
    return resolved


def _parse_row_metadata(row: dict[str, str], fieldnames: list[str]) -> dict[str, Any]:
    """Extract sidecar metadata from a TSV row.

    Columns that are BIDS entity names or core required columns are skipped.
    Remaining columns whose names start with an uppercase letter (PascalCase) are
    treated as JSON sidecar metadata and preserved as-is.
    """
    skip = _ALL_ENTITY_COLUMNS | set(REQUIRED_CORE_TSV_COLUMNS)
    metadata: dict[str, Any] = {}
    for key in fieldnames:
        value = row.get(key)
        if key in skip or value in (None, ""):
            continue
        if key and key[0].isupper():
            metadata[key] = value
    return metadata
