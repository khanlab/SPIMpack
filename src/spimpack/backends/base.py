from __future__ import annotations

from pathlib import Path
from typing import Protocol

from spimpack.models import DatasetManifest


class BackendWriter(Protocol):
    name: str

    def write(self, manifest: DatasetManifest, output_dir: Path) -> None:
        ...
