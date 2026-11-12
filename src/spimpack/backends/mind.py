"""Write a MIND ingest manifest: the dataset described for upload instead of materialised on disk.

The manifest (``ingest_manifest.json``) is what the MIND server validates before any data moves: JSON, TSV
and text files travel inside it, and every other file is listed with where to find it. Its format is defined
by the ``mind-ingest`` package; when that package is installed, the manifest is validated before it is written.
"""
from __future__ import annotations

import csv
import io
import json
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spimpack import __version__
from spimpack.content import build_content
from spimpack.models import DatasetManifest

if TYPE_CHECKING:
    from spimpack.bids_source import MergePlan

MANIFEST_NAME = "ingest_manifest.json"
MANIFEST_VERSION = 1
#: Lab profile the MIND server checks the dataset against, on top of BIDS.
PROFILE = "spim"
#: JSON and TSV files of merged BIDS sources above this size are uploaded instead of inlined.
MAX_INLINE = 16 << 20
#: Text files BIDS defines at the dataset root.
_ROOT_TEXT = ("README", "CHANGES", "LICENSE", "CITATION")


def _is_ome_zarr(path: Path) -> bool:
    return path.name.lower().endswith(".ome.zarr")


def _tree_size(root: Path) -> tuple[int, int]:
    """(total bytes, number of files) under a directory, following symlinks."""
    size = count = 0
    for dirpath, _, filenames in os.walk(root, followlinks=True):
        for name in filenames:
            size += os.stat(os.path.join(dirpath, name)).st_size
            count += 1
    return size, count


def _data_file(rel: str, source: Path, measure_directories: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": rel, "source": str(source)}
    if source.is_dir():
        entry["directory"] = True
        if measure_directories:
            entry["size"], entry["objects"] = _tree_size(source)
    else:
        entry["size"] = source.stat().st_size
    return entry


def _read_table(source: Path) -> dict[str, Any]:
    text = source.read_text(encoding="utf-8-sig")
    lines = [line for line in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE) if line]
    columns = lines[0] if lines else []
    for number, line in enumerate(lines[1:], start=2):
        if len(line) != len(columns):
            raise ValueError(f"{source}: line {number} has {len(line)} cells, the header has {len(columns)}")
    return {"columns": columns, "rows": [dict(zip(columns, line)) for line in lines[1:]]}


class MindManifestWriter:
    name = "mind"

    def __init__(self, *, convert_to_ome_zarr: bool = False, measure_directories: bool = True) -> None:
        """convert_to_ome_zarr: list images that are not OME-Zarr (.ims, .ozx) under an ``.ome.zarr`` path,
        marked for conversion while they are uploaded, instead of as files in their source format.

        measure_directories: record the size and file count of each OME-Zarr store. Walking a very large
        store on network storage is slow; the manifest is valid without them.
        """
        self.convert_to_ome_zarr = convert_to_ome_zarr
        self.measure_directories = measure_directories

    def build(self, manifest: DatasetManifest, plan: MergePlan | None = None) -> dict[str, Any]:
        """The ingest manifest as plain data."""
        content = build_content(manifest, plan)
        metadata: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []

        for rel, data in content.json_files.items():
            metadata.append({"path": rel, "format": "json", "content": data})
        for rel, table in content.tables.items():
            metadata.append({"path": rel, "format": "tsv", "columns": table.columns, "rows": table.rows})
        for rel, text in content.text_files.items():
            metadata.append({"path": rel, "format": "text", "text": text})

        # files of merged BIDS sources: small JSON/TSV and root text files travel inline, like generated ones
        for rel, source in content.links.items():
            name = rel.rsplit("/", 1)[-1]
            inline = source.is_file() and source.stat().st_size <= MAX_INLINE
            if inline and name.endswith(".json"):
                metadata.append({"path": rel, "format": "json", "content": json.loads(source.read_text("utf-8-sig"))})
            elif inline and name.endswith(".tsv"):
                metadata.append({"path": rel, "format": "tsv", **_read_table(source)})
            elif inline and "/" not in rel and name.split(".")[0] in _ROOT_TEXT:
                metadata.append({"path": rel, "format": "text", "text": source.read_text("utf-8-sig")})
            else:
                files.append(_data_file(rel, source, self.measure_directories))

        for rel, asset in content.images.items():
            source = asset.spim_path.resolve()
            if self.convert_to_ome_zarr and not _is_ome_zarr(source):
                stem = rel[: rel.rindex("_SPIM") + len("_SPIM")]
                # the sidecar keeps its path: only the image's extension changes
                files.append({"path": f"{stem}.ome.zarr", "directory": True, "source": str(source), "convert": True})
            else:
                files.append(_data_file(rel, source, self.measure_directories))

        return {
            "manifest_version": MANIFEST_VERSION,
            "profiles": [PROFILE],
            "generated_by": {"name": "SPIMpack", "version": __version__},
            "metadata": sorted(metadata, key=lambda entry: entry["path"]),
            "files": sorted(files, key=lambda entry: entry["path"]),
        }

    def write(
        self,
        manifest: DatasetManifest,
        output_dir: Path,
        plan: MergePlan | None = None,
    ) -> None:
        document = self.build(manifest, plan)
        check_manifest(document)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / MANIFEST_NAME
        target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def check_manifest(document: dict[str, Any]) -> None:
    """Validate with mind-ingest if it is installed: errors raise, warnings are passed on as warnings."""
    try:
        from mind_ingest import IngestManifest, validate_manifest
    except ImportError:
        warnings.warn("mind-ingest is not installed: the ingest manifest was not validated", stacklevel=2)
        return
    from spimpack.validation import ValidationError

    issues = validate_manifest(IngestManifest.model_validate(document))
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        listed = "\n".join(f"  - {issue.path or '-'}: {issue.message}" for issue in errors)
        raise ValidationError(f"the dataset is not valid for MIND:\n{listed}")
    for issue in issues:
        warnings.warn(f"{issue.path or '-'}: {issue.message}", stacklevel=2)
