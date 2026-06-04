from __future__ import annotations

import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from spimpack.cli import main

_VALID_DD = "dataset_description:\n  Name: Demo\n  BIDSVersion: 1.9.0\n  DatasetType: raw\n  License: CC0\n"


class CliTests(unittest.TestCase):
    def test_cli_packages_from_yaml_and_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            tsv = root / "datasets.tsv"
            tsv.write_text(
                "\t".join(
                    [
                        "dataset_id",
                        "sub",
                        "ses",
                        "sample",
                        "acq",
                        "source_ims",
                        "orientation_string_xyz",
                        "sample_staining",
                        "Species",
                    ]
                )
                + "\n"
                + "\t".join(
                    [
                        "demo",
                        "01",
                        "01",
                        "s01",
                        "4x1",
                        str(source),
                        "LPS",
                        "c1;c2",
                        "mouse",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.yml"
            manifest.write_text(_VALID_DD + "datasets_tsv: datasets.tsv\n", encoding="utf-8")

            out = root / "out"
            rc = main(
                [
                    "package",
                    "--manifest",
                    str(manifest),
                    "--output-dir",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0)

            # Path should be BIDS: sub-01/ses-01/micr/sub-01_ses-01_sample-s01_acq-4x1_SPIM.json
            sidecar = json.loads(
                (out / "sub-01/ses-01/micr/sub-01_ses-01_sample-s01_acq-4x1_SPIM.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(sidecar["Species"], "mouse")

            dd = json.loads((out / "dataset_description.json").read_text(encoding="utf-8"))
            self.assertTrue(any(e.get("Name") == "SPIMpack" for e in dd["GeneratedBy"]))

    def test_cli_prints_summary_after_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            tsv = root / "datasets.tsv"
            tsv.write_text(
                "\t".join(
                    ["dataset_id", "sub", "ses", "sample", "source_ims", "orientation_string_xyz", "sample_staining"]
                )
                + "\n"
                + "\t".join(["ds1", "01", "01", "s01", str(source), "LPS", "c1"])
                + "\n"
                + "\t".join(["ds1", "02", "01", "s01", str(source), "LPS", "c1"])
                + "\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.yml"
            manifest.write_text(_VALID_DD + "datasets_tsv: datasets.tsv\n", encoding="utf-8")

            out = root / "out"
            captured = io.StringIO()
            with unittest.mock.patch("sys.stdout", captured):
                rc = main(["package", "--manifest", str(manifest), "--output-dir", str(out)])

            self.assertEqual(rc, 0)
            output = captured.getvalue()
            self.assertIn("Packaging complete", output)
            self.assertIn(str(out), output)
            self.assertIn("Datasets         : 1", output)   # 1 dataset (ds1)
            self.assertIn("Subjects         : 2", output)   # 2 subjects (01, 02)
            self.assertIn("Scans            : 2", output)   # 2 scans total
