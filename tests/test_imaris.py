from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path

import h5py
import numpy as np
from zarrnii import ZarrNii

from spimpack.backends.symlink import SymlinkWriter
from spimpack.imaris import imaris_sidecar_fields, read_pixel_size_mm
from spimpack.models import BidsEntities, DatasetManifest, DatasetSpec, ImageAsset

_VALID_DD = {"Name": "Demo", "BIDSVersion": "1.9.0", "DatasetType": "raw", "License": "CC0"}

#: Distinct size per axis so any X/Y/Z ordering mix-up shows up.
_SHAPE_ZYX = (4, 5, 6)


def _write_ims(path: Path) -> list[float]:
    """Write an anisotropic .ims file; return its voxel size [X, Y, Z] in mm, read from the header."""
    img = ZarrNii.from_darr(
        np.zeros((1, *_SHAPE_ZYX), dtype="uint16"),
        spacing=(4.0, 2.0, 1.0),
        axes_order="ZYX",
    )
    img.to_imaris(str(path))

    def attr(attrs, key: str) -> float:
        return float(b"".join(attrs[key]).decode())

    with h5py.File(path, "r") as f:
        attrs = f["DataSetInfo/Image"].attrs
        unit = b"".join(attrs["Unit"]).decode()
        assert unit == "um", unit
        return [
            (attr(attrs, f"ExtMax{i}") - attr(attrs, f"ExtMin{i}")) / attr(attrs, dim) / 1000.0
            for i, dim in enumerate(("X", "Y", "Z"))
        ]


class ImarisPixelSizeTests(unittest.TestCase):
    def test_read_pixel_size_is_xyz_in_mm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw.ims"
            expected = _write_ims(path)
            # sanity: the fixture really is anisotropic, so ordering matters
            self.assertEqual(len(set(expected)), 3)
            pixel_size = read_pixel_size_mm(path)
            for got, want in zip(pixel_size, expected, strict=True):
                self.assertAlmostEqual(got, want, places=9)

    def test_unreadable_file_warns_and_returns_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.ims"
            path.write_text("not an imaris file", encoding="utf-8")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.assertEqual(imaris_sidecar_fields(path), {})
            self.assertTrue(any("PixelSize" in str(w.message) for w in caught))

    def _write_dataset(self, root: Path, source: Path, metadata: dict) -> dict:
        manifest = DatasetManifest(
            dataset_description=_VALID_DD,
            datasets=[
                DatasetSpec(
                    dataset_id="d1",
                    assets=[
                        ImageAsset(
                            spim_path=source,
                            entities=BidsEntities(subject="01", sample="s01"),
                            orientation_string_xyz="LPS",
                            sample_staining=["nuclei"],
                            metadata=metadata,
                        )
                    ],
                )
            ],
        )
        out = root / "out"
        SymlinkWriter().write(manifest, out)
        sidecar = out / "sub-01/micr/sub-01_sample-s01_SPIM.json"
        return json.loads(sidecar.read_text(encoding="utf-8"))

    def test_sidecar_includes_pixel_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            expected = _write_ims(source)
            data = self._write_dataset(root, source, {})
            self.assertEqual(data["PixelSizeUnits"], "mm")
            for got, want in zip(data["PixelSize"], expected, strict=True):
                self.assertAlmostEqual(got, want, places=9)

    def test_manifest_metadata_overrides_pixel_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            _write_ims(source)
            data = self._write_dataset(root, source, {"PixelSize": [9.0, 9.0, 9.0]})
            self.assertEqual(data["PixelSize"], [9.0, 9.0, 9.0])
            self.assertEqual(data["PixelSizeUnits"], "mm")


if __name__ == "__main__":
    unittest.main()
