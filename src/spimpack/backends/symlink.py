from __future__ import annotations

import copy
import csv
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from spimpack import __version__
from spimpack.imaris import imaris_sidecar_fields, is_imaris
from spimpack.layout import asset_relpaths
from spimpack.models import DatasetManifest, ParticipantSpec
from spimpack.samples import SAMPLES_COLUMNS, SAMPLES_JSON, spim_sample_rows

if TYPE_CHECKING:
    from spimpack.bids_source import MergePlan

_SPIMPACK_GENERATED_BY = {
    "Name": "SPIMpack",
    "Version": __version__,
    "CodeURL": "https://github.com/khanlab/SPIMpack",
}


class SymlinkWriter:
    name = "symlink"

    def __init__(self, *, relative_symlinks: bool = False) -> None:
        self.relative_symlinks = relative_symlinks

    def write(
        self,
        manifest: DatasetManifest,
        output_dir: Path,
        plan: MergePlan | None = None,
    ) -> None:
        if plan is not None:
            ensure_empty_output_dir(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        user_desc = plan.dataset_description if plan else manifest.dataset_description
        _write_json(output_dir / "dataset_description.json", _build_dataset_description(user_desc))

        if plan is not None:
            _write_participants_tsv(
                plan.participants, output_dir, columns=plan.participants_columns, missing="n/a"
            )
            if plan.participants_json:
                _write_json(output_dir / "participants.json", plan.participants_json)
            if plan.bidsignore:
                (output_dir / ".bidsignore").write_text(
                    "\n".join(plan.bidsignore) + "\n", encoding="utf-8"
                )
            _write_tsv(output_dir / "samples.tsv", plan.samples_columns, plan.samples)
            _write_json(output_dir / "samples.json", plan.samples_json)
            for rel, source in plan.links.items():
                # Source dataset files are linked by path, not resolved, so links
                # point into the source dataset rather than wherever it points.
                self._link(output_dir / rel, Path(os.path.abspath(source)))
        else:
            _write_participants_tsv(manifest.participants, output_dir)
            samples = spim_sample_rows(manifest)
            if samples:
                _write_tsv(output_dir / "samples.tsv", SAMPLES_COLUMNS, samples)
                _write_json(output_dir / "samples.json", SAMPLES_JSON)

        for dataset in manifest.datasets:
            for asset in dataset.assets:
                image_rel, sidecar_rel = asset_relpaths(asset)
                self._link(output_dir / image_rel, asset.spim_path.resolve())
                # Values from the manifest take precedence over ones read from the image.
                sidecar = {
                    **(imaris_sidecar_fields(asset.spim_path) if is_imaris(asset.spim_path) else {}),
                    "OrientationStringXYZ": asset.orientation_string_xyz,
                    "SampleStaining": asset.sample_staining,
                    **asset.metadata,
                }
                _write_json(output_dir / sidecar_rel, sidecar)

    def _link(self, link_path: Path, target: Path) -> None:
        link_path.parent.mkdir(parents=True, exist_ok=True)
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        if self.relative_symlinks:
            target = Path(os.path.relpath(target, link_path.parent.resolve()))
        link_path.symlink_to(target)


def ensure_empty_output_dir(output_dir: Path) -> None:
    """Merged datasets are always built into a fresh directory."""
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError(
            f"output directory {output_dir} is not empty; when merging with existing "
            "BIDS datasets, write to a new or empty directory"
        )


def _write_tsv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) or "n/a" for c in columns})


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_dataset_description(user_desc: dict) -> dict:
    """Return the final dataset_description dict with defaults and SPIMpack GeneratedBy entry."""
    desc = copy.deepcopy(user_desc)
    desc.setdefault("BIDSVersion", "1.9.0")
    desc.setdefault("DatasetType", "raw")

    generated_by = desc.get("GeneratedBy", [])
    spimpack_entries = [e for e in generated_by if e.get("Name") == "SPIMpack"]
    if not spimpack_entries:
        desc["GeneratedBy"] = [*generated_by, _SPIMPACK_GENERATED_BY]
    return desc


def _write_participants_tsv(
    participants: list[ParticipantSpec],
    output_dir: Path,
    *,
    columns: list[str] | None = None,
    missing: str = "",
) -> None:
    if not participants:
        return

    metadata_columns: list[str] = list(columns or [])
    for participant in participants:
        for key in participant.metadata:
            if key not in metadata_columns:
                metadata_columns.append(key)

    participants_path = output_dir / "participants.tsv"
    with participants_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["participant_id", *metadata_columns],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for participant in participants:
            row = {"participant_id": participant.participant_id}
            for key in metadata_columns:
                value = participant.metadata.get(key, "")
                row[key] = value if value not in (None, "") else missing
            writer.writerow(row)
