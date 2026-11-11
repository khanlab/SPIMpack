"""Tests for samples.tsv / samples.json output (mirrors SPIMprep)."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from spimpack.cli import main
from spimpack.samples import SAMPLES_JSON

from test_bids_merge import _make_mri, _touch

_DD_YAML = (
    "dataset_description:\n  Name: Demo\n  BIDSVersion: 1.9.0\n"
    "  DatasetType: raw\n  License: CC0\n"
)
_HEADER = "subject\tsession\tsample\tacquisition\tspim_path\torientation_string_xyz\tsample_staining\n"


class SamplesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spim = _touch(self.root / "raw.ims", "ims")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, rows: list[tuple[str, str, str, str]], *extra: str) -> tuple[int, Path, str]:
        _touch(
            self.root / "scans.tsv",
            _HEADER + "".join(f"{s}\t{ses}\t{smp}\t{acq}\t{self.spim}\tLPS\tc1\n" for s, ses, smp, acq in rows),
        )
        manifest = _touch(self.root / "manifest.yml", _DD_YAML + "scans_tsv: scans.tsv\n")
        out = self.root / "out"
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                rc = main(["package", "--manifest", str(manifest), "--output-dir", str(out), *extra])
            except SystemExit as exc:
                rc = int(exc.code or 0)
        return rc, out, err.getvalue()

    def test_samples_tsv_one_row_per_sample(self) -> None:
        # two acquisitions of the same sample -> one samples.tsv row
        rc, out, err = self._run(
            [("01", "01", "brain", "4x"), ("01", "01", "brain", "15x"), ("02", "01", "brain", "4x")]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(
            (out / "samples.tsv").read_text(encoding="utf-8"),
            "participant_id\tsample_id\tsample_type\n"
            "sub-01\tsample-brain\ttissue\n"
            "sub-02\tsample-brain\ttissue\n",
        )
        self.assertEqual(json.loads((out / "samples.json").read_text(encoding="utf-8")), SAMPLES_JSON)

    def test_merge_with_source_samples(self) -> None:
        mri = _make_mri(self.root / "mri")
        _touch(
            mri / "samples.tsv",
            "participant_id\tsample_id\tsample_type\tpathology\n"
            "sub-01\tsample-brain\ttissue\thealthy\n"
            "sub-02\tsample-blood\ttissue\tn/a\n",
        )
        _touch(mri / "samples.json", json.dumps({"pathology": {"Description": "x"}}))
        rc, out, err = self._run([("01", "exvivo", "brain", "4x")], "--bids-source", str(mri))
        self.assertEqual(rc, 0, err)
        self.assertFalse((out / "samples.tsv").is_symlink())
        self.assertEqual(
            (out / "samples.tsv").read_text(encoding="utf-8"),
            "participant_id\tsample_id\tsample_type\tpathology\n"
            "sub-01\tsample-brain\ttissue\thealthy\n"
            "sub-02\tsample-blood\ttissue\tn/a\n",
        )
        sj = json.loads((out / "samples.json").read_text(encoding="utf-8"))
        self.assertEqual(sj["pathology"], {"Description": "x"})
        self.assertEqual(sj["sample_type"], SAMPLES_JSON["sample_type"])

    def test_merge_without_source_samples_still_writes_spim_samples(self) -> None:
        mri = _make_mri(self.root / "mri")
        rc, out, err = self._run([("01", "exvivo", "brain", "4x")], "--bids-source", str(mri))
        self.assertEqual(rc, 0, err)
        self.assertIn("sub-01\tsample-brain\ttissue", (out / "samples.tsv").read_text(encoding="utf-8"))

    def test_conflicting_sample_type_errors(self) -> None:
        mri = _make_mri(self.root / "mri")
        _touch(mri / "samples.tsv", "participant_id\tsample_id\tsample_type\nsub-01\tsample-brain\torganoid\n")
        rc, _, err = self._run([("01", "exvivo", "brain", "4x")], "--bids-source", str(mri))
        self.assertEqual(rc, 2)
        self.assertIn("samples.tsv conflict for sub-01 sample-brain column 'sample_type'", err)


if __name__ == "__main__":
    unittest.main()
