from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spimpack.cli import main


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
                        "bids_subdir",
                        "source_ims",
                        "output_prefix",
                        "orientation",
                        "channel_labels",
                        "Species",
                    ]
                )
                + "\n"
                + "\t".join(
                    [
                        "demo",
                        "sub-01/ses-01/micr",
                        str(source),
                        "sub-01_ses-01",
                        "LPS",
                        "c1;c2",
                        "mouse",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.yml"
            manifest.write_text(
                """
dataset_description:
  Name: Demo
  BIDSVersion: 1.10.0
datasets_tsv: datasets.tsv
""".strip()
                + "\n",
                encoding="utf-8",
            )

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

            sidecar = json.loads(
                (out / "sub-01/ses-01/micr/sub-01_ses-01_SPIM.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(sidecar["Species"], "mouse")
