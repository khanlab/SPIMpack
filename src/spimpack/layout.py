"""Output path helpers shared by writers and merge planning."""
from __future__ import annotations

from pathlib import Path

from bids.layout.writing import build_path

from .models import BIDS_ENTITY_DEFS, BIDS_MICR_PATTERN, ImageAsset


def bids_extension(source: Path) -> str:
    """Extension for the BIDS symlink, derived from the source asset name.

    Compound `.ome.*` names collapse to the plain format extension for files
    (e.g. `x.ome.ims` -> `.ims`), but `.ome.zarr` stores keep the full form.
    """
    name = source.name.lower()
    if name.endswith(".ome.zarr"):
        return ".ome.zarr"
    if name.endswith(".zarr"):
        return ".zarr"
    return source.suffix or ".ims"


def asset_relpaths(asset: ImageAsset) -> tuple[str, str]:
    """Return ``(image_relpath, sidecar_relpath)`` for an asset, relative to the dataset root."""
    entities: dict[str, str] = {
        ed.long_name: getattr(asset.entities, ed.long_name)
        for ed in BIDS_ENTITY_DEFS
        if getattr(asset.entities, ed.long_name)
    }
    entities["suffix"] = "SPIM"
    image = build_path({**entities, "extension": bids_extension(asset.spim_path)}, [BIDS_MICR_PATTERN])
    sidecar = build_path({**entities, "extension": ".json"}, [BIDS_MICR_PATTERN])
    return image, sidecar
