from __future__ import annotations

import json
import os
from pathlib import Path

from spimpack.models import DatasetManifest


class LocalImarisSymlinkWriter:
    name = "local-imaris-symlink"

    def __init__(self, *, relative_symlinks: bool = False) -> None:
        self.relative_symlinks = relative_symlinks

    def write(self, manifest: DatasetManifest, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        dataset_description_path = output_dir / "dataset_description.json"
        dataset_description_path.write_text(
            json.dumps(manifest.dataset_description, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        for dataset in manifest.datasets:
            target_dir = output_dir / dataset.bids_subdir
            target_dir.mkdir(parents=True, exist_ok=True)

            for asset in dataset.assets:
                stem = f"{asset.output_prefix}_SPIM"
                link_path = target_dir / f"{stem}.ims"
                json_path = target_dir / f"{stem}.json"

                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()

                target = asset.source_ims.resolve()
                if self.relative_symlinks:
                    target = Path(
                        _relative_path(from_path=link_path.parent.resolve(), to_path=target)
                    )
                link_path.symlink_to(target)

                sidecar = {
                    "orientation": asset.orientation,
                    "channel_labels": asset.channel_labels,
                    **asset.metadata,
                }
                json_path.write_text(
                    json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )


def _relative_path(*, from_path: Path, to_path: Path) -> str:
    return os.path.relpath(to_path, from_path)
