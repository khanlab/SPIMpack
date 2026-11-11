"""Metadata read lazily from Imaris (``.ims``) source files."""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

#: Factors to millimeters for the spatial units zarrnii may report.
_TO_MM = {"millimeter": 1.0, "micrometer": 1e-3, "nanometer": 1e-6}


def is_imaris(path: Path) -> bool:
    return path.name.lower().endswith(".ims")


def read_pixel_size_mm(path: Path) -> list[float]:
    """Return the full-resolution voxel size as ``[X, Y, Z]`` in millimeters.

    zarrnii normalises spatial units to millimeters on import; the reported
    unit is still checked so a change there cannot silently rescale values.

    The image is opened lazily with zarrnii (only the header is read). Spacing
    is looked up by axis name, so the result is in BIDS ``PixelSize`` order
    (X, Y, Z) regardless of zarrnii's internal (Z, Y, X) axis ordering.
    """
    from zarrnii import ZarrNii

    img = ZarrNii.from_imaris(str(path))
    units = img.ngff_image.axes_units or {}
    pixel_size = []
    for axis in ("x", "y", "z"):
        unit = units.get(axis) or "millimeter"
        if unit not in _TO_MM:
            raise ValueError(f"unsupported spatial unit {unit!r} for axis {axis}")
        # 6 significant digits drops float noise from the unit conversion
        pixel_size.append(float(f"{img.scale[axis] * _TO_MM[unit]:.6g}"))
    return pixel_size


def imaris_sidecar_fields(path: Path) -> dict[str, Any]:
    """Sidecar fields derived from an Imaris file; empty (with a warning) if unreadable."""
    try:
        pixel_size = read_pixel_size_mm(path)
    except Exception as exc:  # noqa: BLE001 - unreadable files should not abort packaging
        warnings.warn(f"could not read PixelSize from {path}: {exc}", stacklevel=2)
        return {}
    return {"PixelSize": pixel_size, "PixelSizeUnits": "mm"}
