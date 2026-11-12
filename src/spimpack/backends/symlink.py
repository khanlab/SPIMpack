from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from spimpack.content import Table, build_content
from spimpack.models import DatasetManifest

if TYPE_CHECKING:
    from spimpack.bids_source import MergePlan


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

        content = build_content(manifest, plan)
        for rel, data in content.json_files.items():
            _write_json(output_dir / rel, data)
        for rel, table in content.tables.items():
            _write_tsv(output_dir / rel, table)
        for rel, text in content.text_files.items():
            (output_dir / rel).write_text(text, encoding="utf-8")
        for rel, source in content.links.items():
            self._link(output_dir / rel, source)
        for rel, asset in content.images.items():
            self._link(output_dir / rel, asset.spim_path.resolve())

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


def _write_tsv(path: Path, table: Table) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=table.columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(table.rows)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
