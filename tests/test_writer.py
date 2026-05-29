from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spimpack.backends.imaris_symlink import LocalImarisSymlinkWriter
from spimpack.models import DatasetManifest, DatasetSpec, ImageAsset
from spimpack.validation import validate_manifest


class WriterTests(unittest.TestCase):
    def _manifest(self, source: Path) -> DatasetManifest:
        return DatasetManifest(
            dataset_description={"Name": "Demo", "BIDSVersion": "1.10.0"},
            datasets=[
                DatasetSpec(
                    dataset_id="d1",
                    bids_subdir="sub-01/ses-01/micr",
                    assets=[
                        ImageAsset(
                            source_ims=source,
                            output_prefix="sub-01_ses-01",
                            orientation="LPS",
                            channel_labels=["nuclei", "membrane"],
                            metadata={"Magnification": "4x"},
                        )
                    ],
                )
            ],
        )

    def test_writer_creates_files_with_absolute_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            manifest = self._manifest(source)
            validate_manifest(manifest)

            out = root / "out"
            LocalImarisSymlinkWriter().write(manifest, out)

            dd = json.loads((out / "dataset_description.json").read_text(encoding="utf-8"))
            self.assertEqual(dd["Name"], "Demo")

            base = out / "sub-01/ses-01/micr/sub-01_ses-01_SPIM"
            link = base.with_suffix(".ims")
            sidecar = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))

            self.assertTrue(link.is_symlink())
            self.assertTrue(link.resolve().is_file())
            self.assertEqual(sidecar["orientation"], "LPS")
            self.assertEqual(sidecar["channel_labels"], ["nuclei", "membrane"])

    def test_writer_creates_relative_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            manifest = self._manifest(source)
            out = root / "out"
            LocalImarisSymlinkWriter(relative_symlinks=True).write(manifest, out)

            link = out / "sub-01/ses-01/micr/sub-01_ses-01_SPIM.ims"
            self.assertFalse(str(link.readlink()).startswith("/"))
