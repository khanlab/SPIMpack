"""Tests for the recommended BIDS microscopy sidecar fields (scans.tsv columns and UI helpers)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from spimpack.io import load_manifest
from spimpack.models import MICROSCOPE_PRESETS, SPIM_SIDECAR_FIELDS, parse_sidecar_value
from spimpack.validation import ValidationError, validate_manifest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "spimpack" / "ui"))

from generate import (  # noqa: E402
    DEFAULT_TSV_COLUMNS,
    MICROSCOPE_CUSTOM,
    MICROSCOPE_NOT_SET,
    MICROSCOPE_OPTIONS,
    SIDECAR_TSV_COLUMNS,
    generate_tsv,
    microscope_fields,
    microscope_option,
    validate_form,
)

_VALID_DD = {"Name": "Demo", "BIDSVersion": "1.9.0", "DatasetType": "raw", "License": "CC0"}
_DD_YAML = "dataset_description:\n  Name: Demo\n  BIDSVersion: 1.9.0\n  DatasetType: raw\n  License: CC0\n"
_ROW = {
    "subject": "01",
    "sample": "s01",
    "spim_path": "/data/raw/sub01.ims",
    "orientation_string_xyz": "LPS",
    "sample_staining": "nuclei",
}


def _load(root: Path, extra_header: str, extra_values: str):
    source = root / "raw.ims"
    source.write_text("ims", encoding="utf-8")
    (root / "scans.tsv").write_text(
        f"subject\tsample\tspim_path\torientation_string_xyz\tsample_staining\t{extra_header}\n"
        f"01\ts01\t{source}\tLPS\tc1;c2\t{extra_values}\n",
        encoding="utf-8",
    )
    manifest_path = root / "manifest.yml"
    manifest_path.write_text(_DD_YAML + "scans_tsv: scans.tsv\n", encoding="utf-8")
    return load_manifest(manifest_path)


class SidecarFieldDefTests(unittest.TestCase):
    def test_multi_fields_split_on_semicolon(self) -> None:
        self.assertEqual(parse_sidecar_value("SamplePrimaryAntibody", "a; b"), ["a", "b"])
        self.assertEqual(parse_sidecar_value("SamplePrimaryAntibody", "a"), "a")

    def test_single_value_fields_kept_verbatim(self) -> None:
        self.assertEqual(parse_sidecar_value("BodyPartDetails", "a; b"), "a; b")
        self.assertEqual(parse_sidecar_value("Species", "a;b"), "a;b")

    def test_choice_defaults_are_valid(self) -> None:
        for field_def in SPIM_SIDECAR_FIELDS:
            if field_def.choices and field_def.default:
                self.assertIn(field_def.default, field_def.choices)


class ScansTsvTests(unittest.TestCase):
    def test_sidecar_columns_reach_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _load(
                Path(tmp),
                "Manufacturer\tManufacturersModelName\tSampleEnvironment\tSamplePrimaryAntibody",
                "LifeCanvas\tSmartSPIM\tex vivo\tRRID:AB_1;RRID:AB_2",
            )
            metadata = manifest.datasets[0].assets[0].metadata
            self.assertEqual(metadata["Manufacturer"], "LifeCanvas")
            self.assertEqual(metadata["ManufacturersModelName"], "SmartSPIM")
            self.assertEqual(metadata["SampleEnvironment"], "ex vivo")
            self.assertEqual(metadata["SamplePrimaryAntibody"], ["RRID:AB_1", "RRID:AB_2"])
            validate_manifest(manifest)

    def test_no_defaults_injected_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _load(Path(tmp), "Species", "mouse")
            self.assertEqual(manifest.datasets[0].assets[0].metadata, {"Species": "mouse"})

    def test_invalid_sample_environment_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _load(Path(tmp), "SampleEnvironment", "exvivo")
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)


class MicroscopePresetTests(unittest.TestCase):
    def test_presets_round_trip(self) -> None:
        for model, manufacturer in MICROSCOPE_PRESETS.items():
            option = microscope_option(manufacturer, model)
            self.assertIn(option, MICROSCOPE_OPTIONS)
            self.assertNotIn(option, (MICROSCOPE_NOT_SET, MICROSCOPE_CUSTOM))
            self.assertEqual(
                microscope_fields(option),
                {"Manufacturer": manufacturer, "ManufacturersModelName": model},
            )

    def test_unknown_microscope_is_custom(self) -> None:
        self.assertEqual(microscope_option("Zeiss", "Lightsheet 7"), MICROSCOPE_CUSTOM)
        self.assertEqual(
            microscope_fields(MICROSCOPE_CUSTOM, " Zeiss ", "Lightsheet 7"),
            {"Manufacturer": "Zeiss", "ManufacturersModelName": "Lightsheet 7"},
        )

    def test_not_set(self) -> None:
        self.assertEqual(microscope_option("", ""), MICROSCOPE_NOT_SET)
        self.assertEqual(
            microscope_fields(MICROSCOPE_NOT_SET),
            {"Manufacturer": "", "ManufacturersModelName": ""},
        )


class GenerateTsvSidecarTests(unittest.TestCase):
    def test_sidecar_columns_ordered_before_other_extras(self) -> None:
        row = {**_ROW, "Species": "mouse", "SampleEnvironment": "ex vivo", "Manufacturer": "LifeCanvas"}
        header = generate_tsv([row]).splitlines()[0].split("\t")
        n = len(DEFAULT_TSV_COLUMNS)
        self.assertEqual(header[n:], ["Manufacturer", "SampleEnvironment", "Species"])
        self.assertTrue(set(header[n:-1]) <= set(SIDECAR_TSV_COLUMNS))

    def test_validate_form_checks_sample_environment(self) -> None:
        self.assertEqual(validate_form(_VALID_DD, [{**_ROW, "SampleEnvironment": "ex vivo"}]), [])
        errors = validate_form(_VALID_DD, [{**_ROW, "SampleEnvironment": "frozen"}])
        self.assertTrue(any("SampleEnvironment" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
