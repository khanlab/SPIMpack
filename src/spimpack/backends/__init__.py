from __future__ import annotations

from .base import BackendWriter
from .symlink import SymlinkWriter


def get_writer(name: str, *, relative_symlinks: bool = False) -> BackendWriter:
    if name == SymlinkWriter.name:
        return SymlinkWriter(relative_symlinks=relative_symlinks)
    raise ValueError(f"unsupported backend: {name}")
