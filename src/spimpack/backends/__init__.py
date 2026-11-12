from __future__ import annotations

from .base import BackendWriter
from .mind import MindManifestWriter
from .symlink import SymlinkWriter

BACKENDS = (SymlinkWriter.name, MindManifestWriter.name)


def get_writer(
    name: str,
    *,
    relative_symlinks: bool = False,
    convert_to_ome_zarr: bool = False,
) -> BackendWriter:
    if name == SymlinkWriter.name:
        return SymlinkWriter(relative_symlinks=relative_symlinks)
    if name == MindManifestWriter.name:
        return MindManifestWriter(convert_to_ome_zarr=convert_to_ome_zarr)
    raise ValueError(f"unsupported backend: {name}")
