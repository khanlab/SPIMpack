"""Tests for the UI generation helpers in ui/generate.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add ui/ to path so generate can be imported without installing as a package.
sys.path.insert(0, str(Path(__file__).parent.parent / "ui"))

from generate import (
    DEFAULT_TSV_COLUMNS,
    REQUIRED_TSV_COLUMNS,
    generate_manifest_yaml,
    generate_tsv,
    validate_form,
)

_VALID_DD = {
    "Name": "Demo",
    "BIDSVersion": "1.9.0",
    "DatasetType": "raw",
    "License": "CC0",
}

_VALID_ROW = {
    "dataset_id": "cohort1",
    "sub": "01",
    "sample": "s01",
    "ses": "",
    "acq": "",
    "spim_path": "/data/raw/sub01.ims",
    "orientation_string_xyz": "LPS",
    "sample_staining": "nuclei;membrane",
}


class TestValidateForm(unittest.TestCase):
    def test_valid_returns_no_errors(self):
        errors = validate_form(_VALID_DD, [_VALID_ROW])
        self.assertEqual(errors, [])

    def test_missing_name_returns_error(self):
        dd = {**_VALID_DD, "Name": ""}
        errors = validate_form(dd, [_VALID_ROW])
        self.assertTrue(any("Name" in e for e in errors))

    def test_missing_bids_version_returns_error(self):
        dd = {**_VALID_DD, "BIDSVersion": ""}
        errors = validate_form(dd, [_VALID_ROW])
        self.assertTrue(any("BIDSVersion" in e for e in errors))

    def test_invalid_dataset_type_returns_error(self):
        dd = {**_VALID_DD, "DatasetType": "unknown"}
        errors = validate_form(dd, [_VALID_ROW])
        self.assertTrue(any("DatasetType" in e for e in errors))

    def test_authors_not_list_returns_error(self):
        dd = {**_VALID_DD, "Authors": "Not A List"}
        errors = validate_form(dd, [_VALID_ROW])
        self.assertTrue(any("Authors" in e for e in errors))

    def test_authors_as_list_is_valid(self):
        dd = {**_VALID_DD, "Authors": ["Author One", "Author Two"]}
        errors = validate_form(dd, [_VALID_ROW])
        self.assertEqual(errors, [])

    def test_empty_rows_returns_error(self):
        errors = validate_form(_VALID_DD, [])
        self.assertTrue(any("row" in e.lower() for e in errors))

    def test_missing_required_tsv_column_returns_error(self):
        row = {**_VALID_ROW, "sub": ""}
        errors = validate_form(_VALID_DD, [row])
        self.assertTrue(any("sub" in e for e in errors))

    def test_invalid_bids_label_returns_error(self):
        row = {**_VALID_ROW, "sub": "sub-01"}  # hyphen is not allowed
        errors = validate_form(_VALID_DD, [row])
        self.assertTrue(any("sub" in e for e in errors))

    def test_valid_bids_label_alphanumeric(self):
        row = {**_VALID_ROW, "sub": "01", "sample": "s01A"}
        errors = validate_form(_VALID_DD, [row])
        self.assertEqual(errors, [])

    def test_optional_bids_entity_blank_is_valid(self):
        row = {**_VALID_ROW, "ses": "", "acq": ""}
        errors = validate_form(_VALID_DD, [row])
        self.assertEqual(errors, [])

    def test_optional_bids_entity_set_and_valid(self):
        row = {**_VALID_ROW, "ses": "01", "acq": "4x"}
        errors = validate_form(_VALID_DD, [row])
        self.assertEqual(errors, [])

    def test_optional_bids_entity_invalid_label(self):
        row = {**_VALID_ROW, "ses": "01-a"}  # hyphen not allowed
        errors = validate_form(_VALID_DD, [row])
        self.assertTrue(any("ses" in e for e in errors))


class TestGenerateManifestYaml(unittest.TestCase):
    def test_basic_output_contains_required_keys(self):
        yaml_text = generate_manifest_yaml(_VALID_DD, "datasets.tsv")
        self.assertIn("dataset_description:", yaml_text)
        self.assertIn("datasets_tsv:", yaml_text)
        self.assertIn("datasets.tsv", yaml_text)

    def test_name_present_in_output(self):
        yaml_text = generate_manifest_yaml(_VALID_DD)
        self.assertIn("Demo", yaml_text)

    def test_custom_tsv_filename(self):
        yaml_text = generate_manifest_yaml(_VALID_DD, "my_data.tsv")
        self.assertIn("my_data.tsv", yaml_text)

    def test_empty_values_omitted(self):
        dd = {**_VALID_DD, "License": ""}
        yaml_text = generate_manifest_yaml(dd)
        # Empty License should be omitted from the output
        self.assertNotIn("License:", yaml_text)

    def test_authors_list_present(self):
        dd = {**_VALID_DD, "Authors": ["Alice", "Bob"]}
        yaml_text = generate_manifest_yaml(dd)
        self.assertIn("Alice", yaml_text)
        self.assertIn("Bob", yaml_text)


class TestGenerateTsv(unittest.TestCase):
    def test_header_row_present(self):
        tsv = generate_tsv([_VALID_ROW])
        first_line = tsv.splitlines()[0]
        self.assertIn("dataset_id", first_line)
        self.assertIn("sub", first_line)
        self.assertIn("spim_path", first_line)

    def test_default_columns_in_header(self):
        tsv = generate_tsv([_VALID_ROW])
        header = tsv.splitlines()[0].split("\t")
        for col in DEFAULT_TSV_COLUMNS:
            self.assertIn(col, header)

    def test_data_row_written(self):
        tsv = generate_tsv([_VALID_ROW])
        lines = tsv.splitlines()
        self.assertEqual(len(lines), 2)  # header + 1 data row
        self.assertIn("cohort1", lines[1])
        self.assertIn("/data/raw/sub01.ims", lines[1])

    def test_extra_pascalcase_column_included(self):
        row = {**_VALID_ROW, "Species": "mouse"}
        tsv = generate_tsv([row])
        header = tsv.splitlines()[0]
        self.assertIn("Species", header)
        self.assertIn("mouse", tsv.splitlines()[1])

    def test_extra_column_parameter(self):
        tsv = generate_tsv([_VALID_ROW], extra_columns=["MyMeta"])
        header = tsv.splitlines()[0]
        self.assertIn("MyMeta", header)

    def test_empty_rows_produces_header_only(self):
        tsv = generate_tsv([])
        lines = [l for l in tsv.splitlines() if l]
        self.assertEqual(len(lines), 1)

    def test_multiple_rows(self):
        row2 = {**_VALID_ROW, "dataset_id": "cohort2", "sub": "02"}
        tsv = generate_tsv([_VALID_ROW, row2])
        lines = tsv.splitlines()
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
