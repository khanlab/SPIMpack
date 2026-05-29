from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spimpack.models import DatasetManifest, DatasetSpec, ImageAsset
from spimpack.validation import ValidationError, validate_manifest


class ValidationTests(unittest.TestCase):
    def test_missing_orientation_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description={"Name": "Demo", "BIDSVersion": "1.10.0"},
                datasets=[
                    DatasetSpec(
                        dataset_id="d1",
                        bids_subdir="sub-01/ses-01/micr",
                        assets=[
                            ImageAsset(
                                source_ims=ims,
                                output_prefix="sub-01_ses-01",
                                orientation="",
                                channel_labels=["ch1"],
                            )
                        ],
                    )
                ],
            )
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

    def test_required_microscopy_fields_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description={
                    "Name": "Demo",
                    "BIDSVersion": "1.10.0",
                    "RequiredMicroscopyFields": ["Species"],
                },
                datasets=[
                    DatasetSpec(
                        dataset_id="d1",
                        bids_subdir="sub-01/ses-01/micr",
                        assets=[
                            ImageAsset(
                                source_ims=ims,
                                output_prefix="sub-01_ses-01",
                                orientation="LPS",
                                channel_labels=["ch1"],
                                metadata={},
                            )
                        ],
                    )
                ],
            )
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

