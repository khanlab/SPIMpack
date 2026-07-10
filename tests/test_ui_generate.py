"""Tests for the UI generation helpers in ui/generate.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add ui/ to path so generate can be imported without installing as a package.
sys.path.insert(0, str(Path(__file__).parent.parent / "ui"))

from generate import (
    DEFAULT_PARTICIPANTS_COLUMNS,
    DEFAULT_TSV_COLUMNS,
    REQUIRED_TSV_COLUMNS,
    generate_manifest_yaml,
    generate_participants_tsv,
    generate_tsv,
    parse_participants_file,
    validate_form,
)

_VALID_DD = {
    "Name": "Demo",
    "BIDSVersion": "1.9.0",
    "DatasetType": "raw",
    "License": "CC0",
}

_VALID_ROW = {
    "subject": "01",
    "sample": "s01",
    "session": "",
    "acquisition": "",
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
        row = {**_VALID_ROW, "subject": ""}
        errors = validate_form(_VALID_DD, [row])
        self.assertTrue(any("subject" in e for e in errors))

    def test_invalid_bids_label_returns_error(self):
        row = {**_VALID_ROW, "subject": "sub-01"}  # hyphen is not allowed
        errors = validate_form(_VALID_DD, [row])
        self.assertTrue(any("subject" in e for e in errors))

    def test_valid_bids_label_alphanumeric(self):
        row = {**_VALID_ROW, "subject": "01", "sample": "s01A"}
        errors = validate_form(_VALID_DD, [row])
        self.assertEqual(errors, [])

    def test_optional_bids_entity_blank_is_valid(self):
        row = {**_VALID_ROW, "session": "", "acquisition": ""}
        errors = validate_form(_VALID_DD, [row])
        self.assertEqual(errors, [])

    def test_optional_bids_entity_set_and_valid(self):
        row = {**_VALID_ROW, "session": "01", "acquisition": "4x"}
        errors = validate_form(_VALID_DD, [row])
        self.assertEqual(errors, [])

    def test_optional_bids_entity_invalid_label(self):
        row = {**_VALID_ROW, "session": "01-a"}  # hyphen not allowed
        errors = validate_form(_VALID_DD, [row])
        self.assertTrue(any("session" in e for e in errors))


class TestGenerateManifestYaml(unittest.TestCase):
    def test_basic_output_contains_required_keys(self):
        yaml_text = generate_manifest_yaml(_VALID_DD, "scans.tsv")
        self.assertIn("dataset_description:", yaml_text)
        self.assertIn("scans_tsv:", yaml_text)
        self.assertIn("scans.tsv", yaml_text)

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
        self.assertIn("subject", first_line)
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
        self.assertIn("01", lines[1])
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
        lines = [line for line in tsv.splitlines() if line]
        self.assertEqual(len(lines), 1)

    def test_multiple_rows(self):
        row2 = {**_VALID_ROW, "subject": "02"}
        tsv = generate_tsv([_VALID_ROW, row2])
        lines = tsv.splitlines()
        self.assertEqual(len(lines), 3)


class TestGenerateParticipantsTsv(unittest.TestCase):
    _ROW = {
        "participant_id": "sub-01",
        "age": "30",
        "sex": "M",
        "genotype": "WT",
        "treatment": "vehicle",
    }

    def test_header_contains_default_columns(self):
        tsv = generate_participants_tsv([self._ROW])
        header = tsv.splitlines()[0].split("\t")
        for col in DEFAULT_PARTICIPANTS_COLUMNS:
            self.assertIn(col, header)

    def test_participant_id_is_first_column(self):
        tsv = generate_participants_tsv([self._ROW])
        first_col = tsv.splitlines()[0].split("\t")[0]
        self.assertEqual(first_col, "participant_id")

    def test_data_row_written(self):
        tsv = generate_participants_tsv([self._ROW])
        lines = tsv.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("sub-01", lines[1])
        self.assertIn("30", lines[1])

    def test_empty_rows_produces_header_only(self):
        tsv = generate_participants_tsv([])
        lines = [l for l in tsv.splitlines() if l]
        self.assertEqual(len(lines), 1)

    def test_extra_column_included(self):
        row = {**self._ROW, "species": "mouse"}
        tsv = generate_participants_tsv([row])
        header = tsv.splitlines()[0]
        self.assertIn("species", header)
        self.assertIn("mouse", tsv.splitlines()[1])

    def test_extra_column_parameter(self):
        tsv = generate_participants_tsv([self._ROW], extra_columns=["notes"])
        header = tsv.splitlines()[0]
        self.assertIn("notes", header)

    def test_multiple_rows(self):
        row2 = {**self._ROW, "participant_id": "sub-02"}
        tsv = generate_participants_tsv([self._ROW, row2])
        lines = tsv.splitlines()
        self.assertEqual(len(lines), 3)


class TestParseParticipantsFile(unittest.TestCase):
    def _make_tsv_bytes(self, header: list[str], rows: list[list[str]]) -> bytes:
        lines = ["\t".join(header)]
        for row in rows:
            lines.append("\t".join(row))
        return "\n".join(lines).encode("utf-8")

    def _make_csv_bytes(self, header: list[str], rows: list[list[str]]) -> bytes:
        lines = [",".join(header)]
        for row in rows:
            lines.append(",".join(row))
        return "\n".join(lines).encode("utf-8")

    def test_parse_tsv(self):
        content = self._make_tsv_bytes(
            ["participant_id", "age"], [["sub-01", "25"]]
        )
        cols, rows = parse_participants_file(content, "participants.tsv")
        self.assertEqual(cols, ["participant_id", "age"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["participant_id"], "sub-01")
        self.assertEqual(rows[0]["age"], "25")

    def test_parse_csv(self):
        content = self._make_csv_bytes(
            ["ID", "Age", "Sex"], [["sub-01", "30", "F"]]
        )
        cols, rows = parse_participants_file(content, "data.csv")
        self.assertEqual(cols, ["ID", "Age", "Sex"])
        self.assertEqual(rows[0]["Sex"], "F")

    def test_parse_empty_tsv(self):
        content = self._make_tsv_bytes(["participant_id", "age"], [])
        cols, rows = parse_participants_file(content, "p.tsv")
        self.assertEqual(cols, ["participant_id", "age"])
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
