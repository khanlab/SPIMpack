from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from bids.layout.writing import build_path

from spimpack import __version__
from spimpack.models import BIDS_ENTITY_DEFS, BIDS_MICR_PATTERN, DatasetManifest

_SPIMPACK_GENERATED_BY = {
    "Name": "SPIMpack",
    "Version": __version__,
    "CodeURL": "https://github.com/khanlab/SPIMpack",
}


class SymlinkWriter:
    name = "symlink"

    def __init__(self, *, relative_symlinks: bool = False) -> None:
        self.relative_symlinks = relative_symlinks

    def write(self, manifest: DatasetManifest, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        dataset_description = _build_dataset_description(manifest.dataset_description)
        dataset_description_path = output_dir / "dataset_description.json"
        dataset_description_path.write_text(
            json.dumps(dataset_description, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        for dataset in manifest.datasets:
            for asset in dataset.assets:
                # Build entity dict for pybids path builder using BIDS_ENTITY_DEFS
                bids_entities: dict[str, str] = {
                    ed.long_name: getattr(asset.entities, ed.long_name)
                    for ed in BIDS_ENTITY_DEFS
                    if getattr(asset.entities, ed.long_name)
                }
                bids_entities["suffix"] = "SPIM"
                bids_entities["extension"] = ".ims"

                rel_path = build_path(bids_entities, [BIDS_MICR_PATTERN])
                link_path = output_dir / rel_path
                json_path = link_path.with_suffix(".json")
                link_path.parent.mkdir(parents=True, exist_ok=True)

                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()

                target = asset.source_ims.resolve()
                if self.relative_symlinks:
                    target = Path(os.path.relpath(target, link_path.parent.resolve()))
                link_path.symlink_to(target)

                sidecar = {
                    "OrientationStringXYZ": asset.orientation_string_xyz,
                    "SampleStaining": asset.sample_staining,
                    **asset.metadata,
                }
                json_path.write_text(
                    json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )


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
