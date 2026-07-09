from __future__ import annotations

import tempfile
import unittest
import warnings
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
                "sub\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"01\ts01\t{source}\tLPS\tc1\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(_VALID_DD + "scans_tsv: scans.tsv\n", encoding="utf-8")

            manifest = load_manifest(manifest_path)
            self.assertEqual(len(manifest.datasets), 1)
            self.assertEqual(len(manifest.datasets[0].assets), 1)

    def test_legacy_datasets_tsv_fallback_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            (root / "datasets.tsv").write_text(
                "sub\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"01\ts01\t{source}\tLPS\tc1\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(_VALID_DD + "datasets_tsv: datasets.tsv\n", encoding="utf-8")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                manifest = load_manifest(manifest_path)
            self.assertEqual(len(manifest.datasets), 1)
            self.assertTrue(any("datasets_tsv is deprecated" in str(w.message) for w in caught))

    def test_both_files_present_prefers_scans_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            (root / "scans.tsv").write_text(
                "sub\tsample\tspim_path\torientation_string_xyz\tsample_staining\tSpecies\n"
                f"01\ts01\t{source}\tLPS\tc1\tmouse\n",
                encoding="utf-8",
            )
            (root / "datasets.tsv").write_text(
                "sub\tsample\tspim_path\torientation_string_xyz\tsample_staining\tSpecies\n"
                f"01\ts01\t{source}\tLPS\tc1\trat\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(_VALID_DD, encoding="utf-8")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                manifest = load_manifest(manifest_path)
            self.assertEqual(manifest.datasets[0].assets[0].metadata["Species"], "mouse")
            self.assertTrue(any("Both scans.tsv and deprecated datasets.tsv exist" in str(w.message) for w in caught))

    def test_dataset_id_column_is_ignored_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.ims"
            source.write_text("ims", encoding="utf-8")
            (root / "scans.tsv").write_text(
                "dataset_id\tsub\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"d1\t01\ts01\t{source}\tLPS\tc1\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.yml"
            manifest_path.write_text(_VALID_DD + "scans_tsv: scans.tsv\n", encoding="utf-8")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                manifest = load_manifest(manifest_path)
            self.assertEqual(len(manifest.datasets[0].assets), 1)
            self.assertTrue(any("dataset_id column in scan manifests is deprecated" in str(w.message) for w in caught))

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
                "participant_id\tsub\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"
                f"sub-01\t01\ts01\t{source}\tLPS\tc1\n",
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
