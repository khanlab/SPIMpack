from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spimpack.models import BidsEntities, DatasetManifest, DatasetSpec, ImageAsset
from spimpack.validation import ValidationError, validate_manifest

_VALID_DD = {"Name": "Demo", "BIDSVersion": "1.9.0", "DatasetType": "raw", "License": "CC0"}


def _valid_asset(ims: Path, *, orientation_string_xyz: str = "LPS") -> ImageAsset:
    return ImageAsset(
        source_ims=ims,
        entities=BidsEntities(subject="01", sample="s01"),
        orientation_string_xyz=orientation_string_xyz,
        sample_staining=["ch1"],
    )


class ValidationTests(unittest.TestCase):
    def test_missing_orientation_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description=_VALID_DD,
                datasets=[
                    DatasetSpec(
                        dataset_id="d1",
                        assets=[_valid_asset(ims, orientation_string_xyz="")],
                    )
                ],
            )
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

    def test_missing_required_dataset_description_fields_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description={"Name": "Demo"},
                datasets=[DatasetSpec(dataset_id="d1", assets=[_valid_asset(ims)])],
            )
            with self.assertRaises(ValidationError) as ctx:
                validate_manifest(manifest)
            self.assertIn("BIDSVersion", str(ctx.exception))

    def test_invalid_bids_entity_label_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description=_VALID_DD,
                datasets=[
                    DatasetSpec(
                        dataset_id="d1",
                        assets=[
                            ImageAsset(
                                source_ims=ims,
                                entities=BidsEntities(subject="01-bad!", sample="s01"),
                                orientation_string_xyz="LPS",
                                sample_staining=["ch1"],
                            )
                        ],
                    )
                ],
            )
            with self.assertRaises(ValidationError) as ctx:
                validate_manifest(manifest)
            self.assertIn("subject", str(ctx.exception))

    def test_invalid_dataset_type_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description={**_VALID_DD, "DatasetType": "unknown"},
                datasets=[DatasetSpec(dataset_id="d1", assets=[_valid_asset(ims)])],
            )
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

    def test_authors_must_be_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description={**_VALID_DD, "Authors": "Not A List"},
                datasets=[DatasetSpec(dataset_id="d1", assets=[_valid_asset(ims)])],
            )
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

    def test_required_microscopy_fields_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ims = Path(tmp) / "source.ims"
            ims.write_text("x", encoding="utf-8")
            manifest = DatasetManifest(
                dataset_description={**_VALID_DD, "RequiredMicroscopyFields": ["Species"]},
                datasets=[
                    DatasetSpec(
                        dataset_id="d1",
                        assets=[
                            ImageAsset(
                                source_ims=ims,
                                entities=BidsEntities(subject="01", sample="s01"),
                                orientation_string_xyz="LPS",
                                sample_staining=["ch1"],
                                metadata={},
                            )
                        ],
                    )
                ],
            )
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

