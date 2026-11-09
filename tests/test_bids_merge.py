"""Tests for merging existing BIDS (MRI) datasets into SPIMpack output."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from spimpack.cli import main

_DD_YAML = (
    "dataset_description:\n  Name: Combined\n  BIDSVersion: 1.9.0\n"
    "  DatasetType: raw\n  License: CC0\n"
)
_SCAN_HEADER = "subject\tsession\tsample\tspim_path\torientation_string_xyz\tsample_staining\n"


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_mri(root: Path, subjects=("01", "02"), session: str | None = "invivo") -> Path:
    _touch(
        root / "dataset_description.json",
        json.dumps(
            {
                "Name": "MRI study",
                "BIDSVersion": "1.8.0",
                "Funding": ["grant"],
                "GeneratedBy": [{"Name": "dcm2bids"}],
            }
        ),
    )
    _touch(
        root / "participants.tsv",
        "participant_id\tage\n" + "".join(f"sub-{s}\t{i + 5}\n" for i, s in enumerate(subjects)),
    )
    _touch(root / "participants.json", json.dumps({"age": {"Units": "weeks"}}))
    _touch(root / ".bidsignore", "extra/\n")
    _touch(root / "README", "mri readme")
    _touch(root / "task-rest_bold.json", "{}")
    _touch(root / "derivatives/fmriprep/x.txt")
    _touch(root / "code/convert.py")
    for s in subjects:
        base = root / f"sub-{s}" / (f"ses-{session}" if session else "")
        prefix = f"sub-{s}_ses-{session}" if session else f"sub-{s}"
        _touch(base / "anat" / f"{prefix}_T1w.nii.gz")
        _touch(base / "anat" / f"{prefix}_T1w.json", "{}")
    return root


class BidsMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spim = _touch(self.root / "raw.ims", "ims")
        self.mri = _make_mri(self.root / "mri")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _manifest(self, rows: list[tuple[str, str]], extra: str = "", participants: str = "") -> Path:
        scans = _SCAN_HEADER + "".join(
            f"{sub}\t{ses}\ts01\t{self.spim}\tLPS\tc1\n" for sub, ses in rows
        )
        _touch(self.root / "scans.tsv", scans)
        if participants:
            _touch(self.root / "participants.tsv", participants)
        manifest = self.root / "manifest.yml"
        manifest.write_text(_DD_YAML + "scans_tsv: scans.tsv\n" + extra, encoding="utf-8")
        return manifest

    def _run(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(list(args))
            except SystemExit as exc:
                rc = int(exc.code or 0)
        return rc, out.getvalue(), err.getvalue()

    def test_merge_links_mri_and_merges_toplevel(self) -> None:
        manifest = self._manifest(
            [("01", "exvivo")],
            participants="participant_id\tgenotype\nsub-01\twt\n",
        )
        out = self.root / "out"
        rc, stdout, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(out),
            "--bids-source", str(self.mri),
        )
        self.assertEqual(rc, 0, stderr)

        t1 = out / "sub-01/ses-invivo/anat/sub-01_ses-invivo_T1w.nii.gz"
        self.assertTrue(t1.is_symlink())
        self.assertEqual(t1.readlink(), self.mri / "sub-01/ses-invivo/anat/sub-01_ses-invivo_T1w.nii.gz")
        self.assertTrue((out / "task-rest_bold.json").is_symlink())
        self.assertTrue((out / "README").is_symlink())
        self.assertTrue((out / "sub-01/ses-exvivo/micr/sub-01_ses-exvivo_sample-s01_SPIM.ims").is_symlink())
        # skipped directories
        self.assertFalse((out / "derivatives").exists())
        self.assertFalse((out / "code").exists())

        dd = json.loads((out / "dataset_description.json").read_text(encoding="utf-8"))
        self.assertEqual(dd["Name"], "Combined")
        self.assertEqual(dd["BIDSVersion"], "1.9.0")
        self.assertEqual(dd["Funding"], ["grant"])  # filled from MRI
        names = [e["Name"] for e in dd["GeneratedBy"]]
        self.assertEqual(names, ["dcm2bids", "SPIMpack"])
        self.assertIn("dataset_description.Name", stdout)  # override warning
        self.assertIn("'MRI study'", stdout)

        participants = (out / "participants.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(participants[0], "participant_id\tage\tgenotype")
        self.assertIn("sub-01\t5\twt", participants)
        self.assertIn("sub-02\t6\tn/a", participants)
        self.assertFalse((out / "participants.json").is_symlink())
        self.assertEqual(
            json.loads((out / "participants.json").read_text(encoding="utf-8")),
            {"age": {"Units": "weeks"}},
        )
        self.assertEqual((out / ".bidsignore").read_text(encoding="utf-8"), "extra/\n")

        self.assertIn("Matched (SPIM + BIDS) : 1", stdout)
        self.assertIn("BIDS only             : 1", stdout)

    def test_bids_sources_from_manifest_relative_path(self) -> None:
        manifest = self._manifest([("01", "exvivo")], extra="bids_sources:\n  - path: mri\n")
        out = self.root / "out"
        rc, _, stderr = self._run("package", "--manifest", str(manifest), "--output-dir", str(out))
        self.assertEqual(rc, 0, stderr)
        self.assertTrue((out / "sub-02/ses-invivo/anat/sub-02_ses-invivo_T1w.json").is_symlink())

    def test_spim_only_and_bids_only_subjects_are_reported_not_errors(self) -> None:
        # ctrl1 is a SPIM-only control brain; 002 looks like a typo of sub-02.
        manifest = self._manifest([("01", "exvivo"), ("ctrl1", "exvivo"), ("002", "exvivo")])
        out = self.root / "out"
        rc, stdout, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(out),
            "--bids-source", str(self.mri),
        )
        self.assertEqual(rc, 0, stderr)
        self.assertIn("4 subjects total", stdout)
        self.assertIn("Matched (SPIM + BIDS) : 1", stdout)
        self.assertIn("SPIM only             : 2", stdout)
        self.assertIn("BIDS only             : 1", stdout)
        ctrl_line = next(ln for ln in stdout.splitlines() if "sub-ctrl1" in ln)
        self.assertNotIn("similar to", ctrl_line)
        typo_line = next(ln for ln in stdout.splitlines() if "sub-002" in ln)
        self.assertIn("similar to BIDS sub-02", typo_line)

        self.assertTrue((out / "sub-ctrl1/ses-exvivo/micr/sub-ctrl1_ses-exvivo_sample-s01_SPIM.ims").is_symlink())
        participants = (out / "participants.tsv").read_text(encoding="utf-8")
        self.assertIn("sub-ctrl1\tn/a", participants)
        self.assertIn("sub-02\t6", participants)

    def test_spim_session_required(self) -> None:
        manifest = self._manifest([("01", "")])
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(self.root / "out"),
            "--bids-source", str(self.mri),
        )
        self.assertEqual(rc, 2)
        self.assertIn("session is required", stderr)

    def test_mri_without_sessions_errors(self) -> None:
        mri = _make_mri(self.root / "mri_nosess", session=None)
        manifest = self._manifest([("01", "exvivo")])
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(self.root / "out"),
            "--bids-source", str(mri),
        )
        self.assertEqual(rc, 2)
        self.assertIn("without a session level", stderr)

    def test_collision_with_existing_micr_errors(self) -> None:
        _touch(self.mri / "sub-01/ses-exvivo/micr/sub-01_ses-exvivo_sample-s01_SPIM.json", "{}")
        manifest = self._manifest([("01", "exvivo")])
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(self.root / "out"),
            "--bids-source", str(self.mri),
        )
        self.assertEqual(rc, 2)
        self.assertIn("file collision", stderr)

    def test_participants_conflict_errors(self) -> None:
        manifest = self._manifest(
            [("01", "exvivo")], participants="participant_id\tage\nsub-01\t99\n"
        )
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(self.root / "out"),
            "--bids-source", str(self.mri),
        )
        self.assertEqual(rc, 2)
        self.assertIn("participants.tsv conflict for sub-01 column 'age'", stderr)

    def test_nonempty_output_dir_errors(self) -> None:
        out = self.root / "out"
        _touch(out / "stale.txt")
        manifest = self._manifest([("01", "exvivo")])
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(out),
            "--bids-source", str(self.mri),
        )
        self.assertEqual(rc, 2)
        self.assertIn("not empty", stderr)

    def test_dry_run_writes_nothing(self) -> None:
        manifest = self._manifest([("01", "exvivo")])
        out = self.root / "out"
        rc, stdout, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(out),
            "--bids-source", str(self.mri), "--dry-run",
        )
        self.assertEqual(rc, 0, stderr)
        self.assertIn("Dry run", stdout)
        self.assertFalse(out.exists())

    def test_two_sources_merge_and_detect_collision(self) -> None:
        second = self.root / "mri2"
        _touch(second / "dataset_description.json", json.dumps({"Name": "Other", "BIDSVersion": "1.9.0"}))
        _touch(second / ".bidsignore", "extra/\nmore/\n")
        _touch(second / "README", "mri readme")  # identical -> fine
        _touch(second / "sub-03/ses-invivo/dwi/sub-03_ses-invivo_dwi.nii.gz")
        manifest = self._manifest([("03", "exvivo")])
        out = self.root / "out"
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(out),
            "--bids-source", str(self.mri), "--bids-source", str(second),
        )
        self.assertEqual(rc, 0, stderr)
        self.assertTrue((out / "sub-03/ses-invivo/dwi/sub-03_ses-invivo_dwi.nii.gz").is_symlink())
        self.assertTrue((out / "sub-01/ses-invivo/anat/sub-01_ses-invivo_T1w.nii.gz").is_symlink())
        self.assertEqual((out / ".bidsignore").read_text(encoding="utf-8"), "extra/\nmore/\n")

        _touch(second / "README", "different")
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(self.root / "out2"),
            "--bids-source", str(self.mri), "--bids-source", str(second),
        )
        self.assertEqual(rc, 2)
        self.assertIn("file collision: README", stderr)

    def test_relative_symlinks_for_mri_files(self) -> None:
        manifest = self._manifest([("01", "exvivo")])
        out = self.root / "out"
        rc, _, stderr = self._run(
            "package", "--manifest", str(manifest), "--output-dir", str(out),
            "--bids-source", str(self.mri), "--relative-symlinks",
        )
        self.assertEqual(rc, 0, stderr)
        t1 = out / "sub-01/ses-invivo/anat/sub-01_ses-invivo_T1w.nii.gz"
        self.assertFalse(t1.readlink().is_absolute())
        self.assertTrue(t1.resolve().is_file())

    def test_inspect_bids(self) -> None:
        rc, stdout, stderr = self._run("inspect-bids", str(self.mri))
        self.assertEqual(rc, 0, stderr)
        self.assertIn("Subjects  : 2", stdout)
        self.assertIn("Sessions  : invivo", stdout)
        self.assertIn("Datatypes : anat", stdout)


if __name__ == "__main__":
    unittest.main()
