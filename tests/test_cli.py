from __future__ import annotations

import json
import tempfile
import unittest
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
                        "orientation",
                        "channel_labels",
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
