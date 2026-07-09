from __future__ import annotations

import io
import json
import tempfile
import unittest
import unittest.mock
import warnings
from pathlib import Path

from spimpack.cli import main

_VALID_DD = "dataset_description:\n  Name: Demo\n  BIDSVersion: 1.9.0\n  DatasetType: raw\n  License: CC0\n"


class CliTests(unittest.TestCase):
    def test_cli_packages_from_yaml_and_scans_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            scans = root / "scans.tsv"
            scans.write_text(
                "\t".join(
                    [
                        "sub",
                        "ses",
                        "sample",
                        "acq",
                        "spim_path",
                        "orientation_string_xyz",
                        "sample_staining",
                        "Species",
                    ]
                )
                + "\n"
                + "\t".join(
                    [
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
            manifest.write_text(_VALID_DD + "scans_tsv: scans.tsv\n", encoding="utf-8")

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

    def test_cli_legacy_datasets_tsv_still_works_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            datasets = root / "datasets.tsv"
            datasets.write_text(
                "\t".join(
                    ["sub", "sample", "spim_path", "orientation_string_xyz", "sample_staining"]
                )
                + "\n"
                + "\t".join(["01", "s01", str(source), "LPS", "c1"])
                + "\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.yml"
            manifest.write_text(_VALID_DD + "datasets_tsv: datasets.tsv\n", encoding="utf-8")

            out = root / "out"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                rc = main(["package", "--manifest", str(manifest), "--output-dir", str(out)])

            self.assertEqual(rc, 0)
            messages = [str(w.message) for w in caught]
            self.assertTrue(any("datasets_tsv is deprecated" in message for message in messages))

    def test_cli_prefers_scans_tsv_when_both_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            (root / "scans.tsv").write_text(
                "\t".join(
                    ["sub", "sample", "spim_path", "orientation_string_xyz", "sample_staining", "Species"]
                )
                + "\n"
                + "\t".join(["01", "s01", str(source), "LPS", "c1", "mouse"])
                + "\n",
                encoding="utf-8",
            )
            (root / "datasets.tsv").write_text(
                "\t".join(
                    ["sub", "sample", "spim_path", "orientation_string_xyz", "sample_staining", "Species"]
                )
                + "\n"
                + "\t".join(["01", "s01", str(source), "LPS", "c1", "rat"])
                + "\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.yml"
            manifest.write_text(_VALID_DD, encoding="utf-8")

            out = root / "out"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                rc = main(["package", "--manifest", str(manifest), "--output-dir", str(out)])

            self.assertEqual(rc, 0)
            messages = [str(w.message) for w in caught]
            self.assertTrue(any("Both scans.tsv and deprecated datasets.tsv exist" in message for message in messages))
            sidecar = json.loads(
                (out / "sub-01/micr/sub-01_sample-s01_SPIM.json").read_text(encoding="utf-8")
            )
            self.assertEqual(sidecar["Species"], "mouse")

    def test_cli_prints_summary_after_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            scans = root / "scans.tsv"
            scans.write_text(
                "\t".join(["sub", "ses", "sample", "spim_path", "orientation_string_xyz", "sample_staining"])
                + "\n"
                + "\t".join(["01", "01", "s01", str(source), "LPS", "c1"])
                + "\n"
                + "\t".join(["02", "01", "s01", str(source), "LPS", "c1"])
                + "\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.yml"
            manifest.write_text(_VALID_DD + "scans_tsv: scans.tsv\n", encoding="utf-8")

            out = root / "out"
            captured = io.StringIO()
            with unittest.mock.patch("sys.stdout", captured):
                rc = main(["package", "--manifest", str(manifest), "--output-dir", str(out)])

            self.assertEqual(rc, 0)
            output = captured.getvalue()
            self.assertIn("Packaging complete", output)
            self.assertIn(str(out), output)
            self.assertIn("Datasets         : 1", output)
            self.assertIn("Subjects         : 2", output)
            self.assertIn("Scans            : 2", output)

    def test_cli_writes_participants_from_participants_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")

            (root / "participants.tsv").write_text(
                "participant_id\tsex\tage\tgenotype\nsub-01\tF\t10\twt\n",
                encoding="utf-8",
            )
            (root / "scans.tsv").write_text(
                "\t".join(
                    [
                        "participant_id",
                        "sub",
                        "sample",
                        "spim_path",
                        "orientation_string_xyz",
                        "sample_staining",
                    ]
                )
                + "\n"
                + "\t".join(["sub-01", "01", "s01", str(source), "LPS", "c1"])
                + "\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.yml"
            manifest.write_text(
                _VALID_DD + "scans_tsv: scans.tsv\nparticipants_tsv: participants.tsv\n",
                encoding="utf-8",
            )

            out = root / "out"
            rc = main(["package", "--manifest", str(manifest), "--output-dir", str(out)])
            self.assertEqual(rc, 0)
            participants_out = (out / "participants.tsv").read_text(encoding="utf-8")
            self.assertIn("participant_id\tsex\tage\tgenotype", participants_out)
            self.assertIn("sub-01\tF\t10\twt", participants_out)
