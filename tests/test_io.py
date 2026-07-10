"""Tests for manifest IO loading and participants/scans TSV parsing."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spimpack.io import load_manifest

_VALID_DD = "dataset_description:\n  Name: Demo\n  BIDSVersion: 1.9.0\n  DatasetType: raw\n  License: CC0\n"


class IoTests(unittest.TestCase):
    def test_scans_tsv_is_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            (root / "scans.tsv").write_text(
                "subject\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"01\ts01\t{source}\tLPS\tc1\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(_VALID_DD + "scans_tsv: scans.tsv\n", encoding="utf-8")

            manifest = load_manifest(manifest_path)
            self.assertEqual(len(manifest.datasets), 1)
            self.assertEqual(len(manifest.datasets[0].assets), 1)

    def test_participants_metadata_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            (root / "participants.tsv").write_text(
                "participant_id\tsex\tage\nsub-01\tF\t10\n",
                encoding="utf-8",
            )
            (root / "scans.tsv").write_text(
                "subject\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"01\ts01\t{source}\tLPS\tc1\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(
                _VALID_DD + "scans_tsv: scans.tsv\nparticipants_tsv: participants.tsv\n",
                encoding="utf-8",
            )

            manifest = load_manifest(manifest_path)
            self.assertEqual(len(manifest.participants), 1)
            self.assertEqual(manifest.participants[0].participant_id, "sub-01")
            self.assertEqual(manifest.participants[0].metadata["sex"], "F")

    def test_short_entity_columns_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            (root / "scans.tsv").write_text(
                "sub\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"01\ts01\t{source}\tLPS\tc1\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(_VALID_DD + "scans_tsv: scans.tsv\n", encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_manifest(manifest_path)
            self.assertEqual(
                str(ctx.exception),
                "scans_tsv missing required columns: subject",
            )
