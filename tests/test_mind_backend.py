"""Tests for the MIND backend, which writes an ingest manifest instead of a dataset on disk."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
from zarrnii import ZarrNii

from spimpack.backends import get_writer
from spimpack.backends.mind import MANIFEST_NAME, MindManifestWriter
from spimpack.bids_source import load_bids_source, plan_bids_merge
from spimpack.cli import main
from spimpack.models import BidsEntities, DatasetManifest, DatasetSpec, ImageAsset
from spimpack.validation import ValidationError

try:
    import mind_ingest
except ImportError:  # the manifest is still written, just not validated
    mind_ingest = None

_VALID_DD = {"Name": "Demo", "BIDSVersion": "1.9.0", "DatasetType": "raw", "License": "CC0"}


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _image(path: Path) -> Path:
    """A small image with voxel size X=1, Y=2, Z=4 mm, as OME-Zarr or Imaris by extension."""
    img = ZarrNii.from_darr(np.zeros((1, 4, 5, 6), dtype="uint16"), spacing=(4.0, 2.0, 1.0), axes_order="ZYX")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if path.suffix == ".ims":
            img.to_imaris(str(path))
        else:
            img.to_ome_zarr(str(path))
    return path


def _manifest(source: Path, session: str | None = None, **metadata) -> DatasetManifest:
    asset = ImageAsset(
        spim_path=source,
        entities=BidsEntities(subject="01", sample="brain", session=session),
        orientation_string_xyz="RPI",
        sample_staining=["Abeta", "YoPro"],
        metadata=metadata,
    )
    return DatasetManifest(dataset_description=_VALID_DD, datasets=[DatasetSpec(dataset_id="d1", assets=[asset])])


def _by_path(entries: list[dict]) -> dict[str, dict]:
    return {entry["path"]: entry for entry in entries}


class MindBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_ome_zarr_image(self) -> None:
        source = _image(self.root / "raw.ome.zarr")
        document = MindManifestWriter().build(_manifest(source))

        self.assertEqual(document["manifest_version"], 1)
        self.assertEqual(document["profiles"], ["spim"])
        self.assertEqual(document["generated_by"]["name"], "SPIMpack")

        metadata = _by_path(document["metadata"])
        self.assertEqual(
            sorted(metadata),
            ["dataset_description.json", "samples.json", "samples.tsv", "sub-01/micr/sub-01_sample-brain_SPIM.json"],
        )
        self.assertEqual(metadata["dataset_description.json"]["content"]["Name"], "Demo")
        self.assertEqual(
            metadata["samples.tsv"]["rows"],
            [{"participant_id": "sub-01", "sample_id": "sample-brain", "sample_type": "tissue"}],
        )
        sidecar = metadata["sub-01/micr/sub-01_sample-brain_SPIM.json"]["content"]
        # the pixel size is read from the OME-Zarr metadata, in X, Y, Z order
        self.assertEqual(sidecar["PixelSize"], [1.0, 2.0, 4.0])
        self.assertEqual(sidecar["PixelSizeUnits"], "mm")
        self.assertEqual(sidecar["OrientationStringXYZ"], "RPI")

        (image,) = document["files"]
        self.assertEqual(image["path"], "sub-01/micr/sub-01_sample-brain_SPIM.ome.zarr")
        self.assertTrue(image["directory"])
        self.assertEqual(image["source"], str(source.resolve()))
        files = [p for p in source.rglob("*") if p.is_file()]
        self.assertEqual(image["objects"], len(files))
        self.assertEqual(image["size"], sum(p.stat().st_size for p in files))
        self.assertNotIn("convert", image)

    def test_directories_need_not_be_measured(self) -> None:
        source = _image(self.root / "raw.ome.zarr")
        (image,) = MindManifestWriter(measure_directories=False).build(_manifest(source))["files"]
        self.assertNotIn("size", image)
        self.assertNotIn("objects", image)

    def test_imaris_image_is_listed_as_is_or_for_conversion(self) -> None:
        source = _image(self.root / "raw.ims")
        (as_is,) = MindManifestWriter().build(_manifest(source))["files"]
        self.assertEqual(as_is["path"], "sub-01/micr/sub-01_sample-brain_SPIM.ims")
        self.assertEqual(as_is["size"], source.stat().st_size)
        self.assertNotIn("directory", as_is)

        document = MindManifestWriter(convert_to_ome_zarr=True).build(_manifest(source))
        (converted,) = document["files"]
        self.assertEqual(
            converted,
            {
                "path": "sub-01/micr/sub-01_sample-brain_SPIM.ome.zarr",
                "directory": True,
                "source": str(source.resolve()),
                "convert": True,
            },
        )
        # the sidecar, with the pixel size read from the Imaris header, keeps its path
        sidecar = _by_path(document["metadata"])["sub-01/micr/sub-01_sample-brain_SPIM.json"]["content"]
        self.assertEqual(sidecar["PixelSizeUnits"], "mm")

    def test_conversion_leaves_ome_zarr_sources_alone(self) -> None:
        source = _image(self.root / "raw.ome.zarr")
        (image,) = MindManifestWriter(convert_to_ome_zarr=True).build(_manifest(source))["files"]
        self.assertNotIn("convert", image)
        self.assertIn("size", image)

    def test_merged_bids_source(self) -> None:
        mri = self.root / "mri"
        _touch(mri / "dataset_description.json", json.dumps({"Name": "MRI", "BIDSVersion": "1.8.0"}))
        _touch(mri / "participants.tsv", "participant_id\tage\nsub-01\t5\n")
        _touch(mri / "README", "mri readme")
        _touch(mri / ".bidsignore", "extra/\n")
        _touch(mri / "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.nii.gz", "nifti")
        _touch(mri / "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.bval", "0 1000")
        _touch(mri / "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.bvec", "0 1")
        _touch(mri / "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.json", json.dumps({"EchoTime": 0.08}))
        _touch(mri / "sub-01/ses-invivo/sub-01_ses-invivo_scans.tsv", "filename\ndwi/sub-01_ses-invivo_dwi.nii.gz\n")
        _touch(mri / "derivatives/pipeline/x.txt")

        manifest = _manifest(_image(self.root / "raw.ome.zarr"), session="exvivo")
        plan = plan_bids_merge(manifest, [load_bids_source(mri)])
        document = MindManifestWriter().build(manifest, plan)

        metadata = _by_path(document["metadata"])
        self.assertEqual(metadata["README"], {"path": "README", "format": "text", "text": "mri readme"})
        self.assertEqual(metadata[".bidsignore"]["text"], "extra/\n")
        self.assertEqual(metadata["participants.tsv"]["rows"], [{"participant_id": "sub-01", "age": "5"}])
        self.assertEqual(
            metadata["sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.json"]["content"], {"EchoTime": 0.08}
        )
        self.assertEqual(
            metadata["sub-01/ses-invivo/sub-01_ses-invivo_scans.tsv"]["rows"],
            [{"filename": "dwi/sub-01_ses-invivo_dwi.nii.gz"}],
        )

        files = _by_path(document["files"])
        self.assertEqual(
            sorted(files),
            [
                "sub-01/ses-exvivo/micr/sub-01_ses-exvivo_sample-brain_SPIM.ome.zarr",
                "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.bval",
                "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.bvec",
                "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.nii.gz",
            ],
        )
        nifti = files["sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.nii.gz"]
        self.assertEqual(nifti["size"], len("nifti"))
        self.assertEqual(nifti["source"], str(mri / "sub-01/ses-invivo/dwi/sub-01_ses-invivo_dwi.nii.gz"))
        self.assertFalse(any(path.startswith("derivatives") for path in [*files, *metadata]))

        if mind_ingest is not None:
            checked = mind_ingest.IngestManifest.model_validate(document)
            errors = [i for i in mind_ingest.validate_manifest(checked) if i.severity == "error"]
            self.assertEqual(errors, [])
            # the four dwi files, differing only by extension, each get a node of their own
            tree = mind_ingest.build_tree(checked, "demo")
            dwi = [node.label for node in tree.nodes if node.parent == "sub-01/ses-invivo/dwi"]
            self.assertEqual(len(dwi), len(set(dwi)))
            self.assertEqual(len(dwi), 4)

    def test_write(self) -> None:
        out = self.root / "out"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            get_writer("mind").write(_manifest(_image(self.root / "raw.ome.zarr")), out)
        self.assertEqual([p.name for p in out.iterdir()], [MANIFEST_NAME])
        document = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(document["files"]), 1)

    @unittest.skipIf(mind_ingest is None, "mind-ingest is not installed")
    def test_invalid_dataset_is_refused(self) -> None:
        # not a real Imaris file, so no pixel size can be read, and BIDS requires one
        source = _touch(self.root / "fake.ims", "not imaris")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with self.assertRaisesRegex(ValidationError, "PixelSize is required"):
                MindManifestWriter().write(_manifest(source), self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_cli(self) -> None:
        source = _image(self.root / "raw.ims")
        _touch(
            self.root / "manifest.yml",
            "dataset_description:\n  Name: Demo\n  BIDSVersion: 1.9.0\n  DatasetType: raw\n  License: CC0\n",
        )
        _touch(
            self.root / "scans.tsv",
            "subject\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
            f"01\tbrain\t{source}\tRPI\tAbeta;YoPro\n",
        )
        out = self.root / "out"
        argv = ["package", "--manifest", str(self.root / "manifest.yml"), "--output-dir", str(out)]
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.assertEqual(main([*argv, "--backend", "mind", "--convert-to-ome-zarr"]), 0)
        (image,) = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["files"]
        self.assertTrue(image["convert"])
        self.assertTrue(image["path"].endswith("_SPIM.ome.zarr"))


if __name__ == "__main__":
    unittest.main()
