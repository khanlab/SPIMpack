from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spimpack.backends.imaris_symlink import LocalImarisSymlinkWriter
from spimpack.models import BidsEntities, DatasetManifest, DatasetSpec, ImageAsset
from spimpack.validation import validate_manifest

_VALID_DD = {"Name": "Demo", "BIDSVersion": "1.9.0", "DatasetType": "raw", "License": "CC0"}


class WriterTests(unittest.TestCase):
    def _manifest(self, source: Path) -> DatasetManifest:
        return DatasetManifest(
            dataset_description=_VALID_DD,
            datasets=[
                DatasetSpec(
                    dataset_id="d1",
                    assets=[
                        ImageAsset(
                            source_ims=source,
                            entities=BidsEntities(
                                subject="01",
                                sample="s01",
                                session="01",
                                acquisition="4x1",
                            ),
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
            # GeneratedBy should be auto-injected
            self.assertTrue(any(e.get("Name") == "SPIMpack" for e in dd["GeneratedBy"]))

            # BIDS path: sub-01/ses-01/micr/sub-01_ses-01_sample-s01_acq-4x1_SPIM.ims
            link = out / "sub-01/ses-01/micr/sub-01_ses-01_sample-s01_acq-4x1_SPIM.ims"
            sidecar = link.with_suffix(".json")
            self.assertTrue(link.is_symlink())
            self.assertTrue(link.resolve().is_file())
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(data["orientation"], "LPS")
            self.assertEqual(data["channel_labels"], ["nuclei", "membrane"])

    def test_writer_creates_relative_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            manifest = self._manifest(source)
            out = root / "out"
            LocalImarisSymlinkWriter(relative_symlinks=True).write(manifest, out)

            link = out / "sub-01/ses-01/micr/sub-01_ses-01_sample-s01_acq-4x1_SPIM.ims"
            self.assertFalse(str(link.readlink()).startswith("/"))

    def test_generated_by_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            manifest = DatasetManifest(
                dataset_description={
                    **_VALID_DD,
                    "GeneratedBy": [{"Name": "SPIMpack", "Version": "0.1.0"}],
                },
                datasets=[
                    DatasetSpec(
                        dataset_id="d1",
                        assets=[
                            ImageAsset(
                                source_ims=source,
                                entities=BidsEntities(subject="01", sample="s01"),
                                orientation="LPS",
                                channel_labels=["ch1"],
                            )
                        ],
                    )
                ],
            )
            out = root / "out"
            LocalImarisSymlinkWriter().write(manifest, out)
            dd = json.loads((out / "dataset_description.json").read_text(encoding="utf-8"))
            spimpack_entries = [e for e in dd["GeneratedBy"] if e.get("Name") == "SPIMpack"]
            self.assertEqual(len(spimpack_entries), 1)
