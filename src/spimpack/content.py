"""What a packaged dataset consists of, independent of how a backend materialises it.

Every backend (symlinks, a MIND ingest manifest, an object store) writes the same dataset: generated JSON,
TSV and text files, plus the source files that are linked or uploaded at a BIDS path.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spimpack import __version__
from spimpack.imaris import image_sidecar_fields
from spimpack.layout import asset_relpaths
from spimpack.models import DatasetManifest, ImageAsset, ParticipantSpec
from spimpack.samples import SAMPLES_COLUMNS, SAMPLES_JSON, spim_sample_rows

if TYPE_CHECKING:
    from spimpack.bids_source import MergePlan

_SPIMPACK_GENERATED_BY = {
    "Name": "SPIMpack",
    "Version": __version__,
    "CodeURL": "https://github.com/khanlab/SPIMpack",
}


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, str]]  # one cell per column, already rendered as text


@dataclass
class DatasetContent:
    """Files of the output dataset, keyed by posix path relative to its root."""

    json_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    tables: dict[str, Table] = field(default_factory=dict)
    text_files: dict[str, str] = field(default_factory=dict)
    #: SPIM images: BIDS path -> the asset whose (resolved) source it is
    images: dict[str, ImageAsset] = field(default_factory=dict)
    #: files of merged BIDS sources: BIDS path -> absolute source path, not resolved
    links: dict[str, Path] = field(default_factory=dict)


def build_dataset_description(user_desc: dict) -> dict:
    """Return the final dataset_description dict with defaults and SPIMpack GeneratedBy entry."""
    desc = copy.deepcopy(user_desc)
    desc.setdefault("BIDSVersion", "1.9.0")
    desc.setdefault("DatasetType", "raw")

    generated_by = desc.get("GeneratedBy", [])
    spimpack_entries = [e for e in generated_by if e.get("Name") == "SPIMpack"]
    if not spimpack_entries:
        desc["GeneratedBy"] = [*generated_by, _SPIMPACK_GENERATED_BY]
    return desc


def sidecar_for(asset: ImageAsset) -> dict[str, Any]:
    """Sidecar of a SPIM image. Values from the manifest take precedence over ones read from the image."""
    return {
        **image_sidecar_fields(asset.spim_path),
        "OrientationStringXYZ": asset.orientation_string_xyz,
        "SampleStaining": asset.sample_staining,
        **asset.metadata,
    }


def _participants_table(
    participants: list[ParticipantSpec], columns: list[str] | None, missing: str
) -> Table:
    metadata_columns: list[str] = list(columns or [])
    for participant in participants:
        for key in participant.metadata:
            if key not in metadata_columns:
                metadata_columns.append(key)
    rows = []
    for participant in participants:
        row = {"participant_id": participant.participant_id}
        for key in metadata_columns:
            value = participant.metadata.get(key, "")
            row[key] = str(value) if value not in (None, "") else missing
        rows.append(row)
    return Table(["participant_id", *metadata_columns], rows)


def _samples_table(columns: list[str], rows: list[dict[str, str]]) -> Table:
    return Table(columns, [{c: row.get(c) or "n/a" for c in columns} for row in rows])


def build_content(manifest: DatasetManifest, plan: MergePlan | None = None) -> DatasetContent:
    """Everything the output dataset holds; with *plan*, including the merged BIDS sources."""
    content = DatasetContent()
    user_desc = plan.dataset_description if plan else manifest.dataset_description
    content.json_files["dataset_description.json"] = build_dataset_description(user_desc)

    if plan is not None:
        if plan.participants:
            content.tables["participants.tsv"] = _participants_table(
                plan.participants, plan.participants_columns, "n/a"
            )
        if plan.participants_json:
            content.json_files["participants.json"] = plan.participants_json
        if plan.bidsignore:
            content.text_files[".bidsignore"] = "\n".join(plan.bidsignore) + "\n"
        content.tables["samples.tsv"] = _samples_table(plan.samples_columns, plan.samples)
        content.json_files["samples.json"] = plan.samples_json
        for rel, source in plan.links.items():
            # Source dataset files are linked by path, not resolved, so links
            # point into the source dataset rather than wherever it points.
            content.links[rel] = Path(os.path.abspath(source))
    else:
        if manifest.participants:
            content.tables["participants.tsv"] = _participants_table(manifest.participants, None, "")
        samples = spim_sample_rows(manifest)
        if samples:
            content.tables["samples.tsv"] = _samples_table(SAMPLES_COLUMNS, samples)
            content.json_files["samples.json"] = SAMPLES_JSON

    for dataset in manifest.datasets:
        for asset in dataset.assets:
            image_rel, sidecar_rel = asset_relpaths(asset)
            content.images[image_rel] = asset
            content.json_files[sidecar_rel] = sidecar_for(asset)
    return content
