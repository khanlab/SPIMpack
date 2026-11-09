from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from spimpack.models import DatasetManifest

if TYPE_CHECKING:
    from spimpack.bids_source import MergePlan


class BackendWriter(Protocol):
    name: str

    def write(
        self,
        manifest: DatasetManifest,
        output_dir: Path,
        plan: MergePlan | None = None,
    ) -> None:
        """Write the SPIM dataset; with *plan*, also materialise the merged BIDS sources."""
        ...
