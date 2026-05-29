from __future__ import annotations

from .imaris_symlink import LocalImarisSymlinkWriter


def get_writer(name: str, *, relative_symlinks: bool = False):
    if name == LocalImarisSymlinkWriter.name:
        return LocalImarisSymlinkWriter(relative_symlinks=relative_symlinks)
    raise ValueError(f"unsupported backend: {name}")
