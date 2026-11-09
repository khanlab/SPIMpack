"""Ingest existing BIDS datasets (e.g. MRI) and plan merging them with SPIM output.

Files from each source dataset are exposed as relative-path -> source-path pairs so
that any backend (symlink, copy, object store) can materialise them. Top-level files
that both datasets may define (``dataset_description.json``, ``participants.tsv``,
``participants.json``, ``.bidsignore``) are merged instead of linked.
"""
from __future__ import annotations

import csv
import difflib
import filecmp
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bids import BIDSLayout, BIDSLayoutIndexer

from .layout import asset_relpaths
from .models import DatasetManifest, ParticipantSpec, participant_id_with_prefix
from .samples import SAMPLES_COLUMNS, SAMPLES_JSON, spim_sample_rows
from .validation import ValidationError

#: Top-level files that are merged rather than linked.
MERGED_TOPLEVEL_FILES = frozenset(
    {
        "dataset_description.json",
        "participants.tsv",
        "participants.json",
        "samples.tsv",
        "samples.json",
        ".bidsignore",
    }
)

_MISSING_VALUES = frozenset({"", "n/a"})


@dataclass(frozen=True)
class BidsSource:
    """An indexed existing BIDS dataset."""

    root: Path
    dataset_description: dict[str, Any]
    participants_columns: list[str]
    participants: dict[str, dict[str, str]]  # participant_id -> row without participant_id
    participants_json: dict[str, Any]
    bidsignore: list[str]
    files: dict[str, Path]  # posix relpath -> absolute source path (merged files excluded)
    sessions: dict[str, set[str]]  # subject label -> session labels
    samples_columns: list[str] = field(default_factory=list)
    samples: list[dict[str, str]] = field(default_factory=list)
    samples_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubjectReport:
    """Subject/session matching between SPIM scans and BIDS sources."""

    spim_sessions: dict[str, set[str]]
    source_sessions: dict[str, set[str]]

    @property
    def matched(self) -> list[str]:
        return sorted(self.spim_sessions.keys() & self.source_sessions.keys())

    @property
    def spim_only(self) -> list[str]:
        return sorted(self.spim_sessions.keys() - self.source_sessions.keys())

    @property
    def source_only(self) -> list[str]:
        return sorted(self.source_sessions.keys() - self.spim_sessions.keys())

    def suggestion(self, subject: str) -> str | None:
        """Likely intended BIDS-source subject(s) for an unmatched SPIM label, e.g. 'sub-02'."""
        candidates = list(self.source_sessions)
        normalized = _normalize_label(subject)
        exact = [c for c in candidates if _normalize_label(c) == normalized]
        # Strict cutoff: SPIM-only subjects (e.g. control brains) are expected, so
        # only flag labels that look like a typo of an existing subject.
        close = exact or difflib.get_close_matches(subject, candidates, n=3, cutoff=0.75)
        return " or ".join(f"sub-{c}" for c in close) or None

    def format(self) -> str:
        def ses(sessions: set[str]) -> str:
            return ", ".join(sorted(s for s in sessions if s)) or "-"

        total = len(self.spim_sessions.keys() | self.source_sessions.keys())
        lines = [
            f"Subject matching (SPIM scans vs existing BIDS): {total} subjects total",
            f"  Matched (SPIM + BIDS) : {len(self.matched)}",
        ]
        for subject in self.matched:
            lines.append(
                f"    sub-{subject:<12} BIDS ses: {ses(self.source_sessions[subject]):<20} "
                f"SPIM ses: {ses(self.spim_sessions[subject])}"
            )
        lines.append(f"  SPIM only             : {len(self.spim_only)}")
        for subject in self.spim_only:
            hint = self.suggestion(subject)
            suffix = f"  <- similar to BIDS {hint}; check for a naming error" if hint else ""
            lines.append(f"    sub-{subject:<12} SPIM ses: {ses(self.spim_sessions[subject])}{suffix}")
        lines.append(f"  BIDS only             : {len(self.source_only)}")
        if self.source_only:
            lines.append("    " + ", ".join(f"sub-{s}" for s in self.source_only))
        return "\n".join(lines)


@dataclass(frozen=True)
class MergePlan:
    """Everything a backend needs to write the merged dataset."""

    dataset_description: dict[str, Any]
    participants_columns: list[str]
    participants: list[ParticipantSpec]
    participants_json: dict[str, Any]
    bidsignore: list[str]
    links: dict[str, Path]  # posix relpath -> source path
    report: SubjectReport
    samples_columns: list[str]
    samples: list[dict[str, str]]
    samples_json: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def load_bids_source(root: Path) -> BidsSource:
    """Index an existing BIDS dataset with pybids.

    pybids already skips ``derivatives/``, ``sourcedata/``, ``code/`` and dotfiles.
    Every subject must use a session level (``sub-X/ses-Y/...``).
    """
    root = Path(os.path.abspath(Path(root).expanduser()))
    if not root.is_dir():
        raise ValidationError(f"BIDS source is not a directory: {root}")
    dd_path = root / "dataset_description.json"
    if not dd_path.is_file():
        raise ValidationError(f"BIDS source has no dataset_description.json: {root}")
    try:
        dataset_description = json.loads(dd_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in {dd_path}: {exc}") from exc

    layout = BIDSLayout(
        root,
        validate=False,
        indexer=BIDSLayoutIndexer(validate=False, index_metadata=False),
    )
    layout_root = Path(layout.root)

    files: dict[str, Path] = {}
    sessions: dict[str, set[str]] = {}
    no_session: set[str] = set()
    for filename in layout.get(return_type="filename"):
        rel = Path(filename).relative_to(layout_root).as_posix()
        if rel in MERGED_TOPLEVEL_FILES:
            continue
        files[rel] = root / rel
        parts = rel.split("/")
        if not parts[0].startswith("sub-") or len(parts) < 2:
            continue
        subject = parts[0][4:]
        if parts[1].startswith("ses-"):
            sessions.setdefault(subject, set()).add(parts[1][4:])
        elif len(parts) > 2:
            # file inside a datatype dir directly under sub-X (no session level)
            no_session.add(subject)
        else:
            sessions.setdefault(subject, set())

    no_session |= {s for s, ses in sessions.items() if not ses}
    if no_session:
        listed = ", ".join(f"sub-{s}" for s in sorted(no_session))
        raise ValidationError(
            f"BIDS source {root} has subjects without a session level: {listed}. "
            "Merging requires sub-<label>/ses-<label>/ directories in both datasets."
        )

    columns, participants = _read_participants(root / "participants.tsv")
    participants_json: dict[str, Any] = {}
    pj_path = root / "participants.json"
    if pj_path.is_file():
        try:
            participants_json = json.loads(pj_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid JSON in {pj_path}: {exc}") from exc

    bidsignore_path = root / ".bidsignore"
    bidsignore = (
        [ln.strip() for ln in bidsignore_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if bidsignore_path.is_file()
        else []
    )

    samples_columns, samples = _read_samples(root / "samples.tsv")
    samples_json: dict[str, Any] = {}
    sj_path = root / "samples.json"
    if sj_path.is_file():
        try:
            samples_json = json.loads(sj_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid JSON in {sj_path}: {exc}") from exc

    return BidsSource(
        root=root,
        dataset_description=dataset_description,
        participants_columns=columns,
        participants=participants,
        participants_json=participants_json,
        bidsignore=bidsignore,
        files=files,
        sessions=sessions,
        samples_columns=samples_columns,
        samples=samples,
        samples_json=samples_json,
    )


def format_source_summary(source: BidsSource) -> str:
    """Human-readable summary of an indexed BIDS source."""
    all_sessions = sorted({ses for s in source.sessions.values() for ses in s})
    datatypes = sorted(
        {
            rel.split("/")[2]
            for rel in source.files
            if rel.startswith("sub-") and rel.count("/") >= 3
        }
    )
    lines = [
        f"BIDS source : {source.root}",
        f"  Name      : {source.dataset_description.get('Name', '(none)')}",
        f"  Subjects  : {len(source.sessions)}",
        f"  Sessions  : {', '.join(all_sessions) or '(none)'}",
        f"  Datatypes : {', '.join(datatypes) or '(none)'}",
        f"  Files     : {len(source.files)} (+ merged top-level files)",
    ]
    return "\n".join(lines)


def plan_bids_merge(manifest: DatasetManifest, sources: list[BidsSource]) -> MergePlan:
    """Check SPIM scans against the BIDS sources and build a merge plan.

    Raises ValidationError listing every problem found (with the subject report
    appended) so naming errors can be fixed in one pass.
    """
    errors: list[str] = []
    warnings: list[str] = []

    assets = [asset for dataset in manifest.datasets for asset in dataset.assets]
    spim_sessions: dict[str, set[str]] = {}
    for asset in assets:
        spim_sessions.setdefault(asset.entities.subject, set()).add(asset.entities.session or "")
    source_sessions: dict[str, set[str]] = {}
    for source in sources:
        for subject, ses in source.sessions.items():
            source_sessions.setdefault(subject, set()).update(ses)
    report = SubjectReport(spim_sessions=spim_sessions, source_sessions=source_sessions)

    # SPIM-only and BIDS-only subjects are allowed (e.g. control brains in a SPIM
    # batch); they are listed in the report rather than treated as errors.

    # ---- linked files: source/source and source/SPIM collisions --------------
    links: dict[str, Path] = {}
    origin: dict[str, Path] = {}
    for source in sources:
        for rel, path in source.files.items():
            if rel in links:
                if _same_file(links[rel], path):
                    continue
                errors.append(
                    f"file collision: {rel} exists in both {origin[rel]} and {source.root}"
                )
                continue
            links[rel] = path
            origin[rel] = source.root
    for asset in assets:
        for rel in asset_relpaths(asset):
            if rel in links:
                errors.append(f"file collision: SPIM output {rel} already exists in {origin[rel]}")

    dataset_description = _merge_dataset_description(manifest, sources, warnings)
    columns, participants = _merge_participants(manifest, sources, report, errors)
    participants_json = _merge_participants_json(sources, errors)
    samples_columns, samples = _merge_samples(manifest, sources, errors)
    samples_json = _merge_json(
        "samples.json", [(str(s.root), s.samples_json) for s in sources], errors
    )
    for key, value in SAMPLES_JSON.items():
        samples_json.setdefault(key, value)

    bidsignore: list[str] = []
    for source in sources:
        for line in source.bidsignore:
            if line not in bidsignore:
                bidsignore.append(line)

    if errors:
        raise ValidationError(
            "cannot merge with existing BIDS dataset(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\n\n"
            + report.format()
        )

    return MergePlan(
        dataset_description=dataset_description,
        participants_columns=columns,
        participants=participants,
        participants_json=participants_json,
        bidsignore=bidsignore,
        links=links,
        report=report,
        samples_columns=samples_columns,
        samples=samples,
        samples_json=samples_json,
        warnings=warnings,
    )


def _normalize_label(label: str) -> str:
    """Case-insensitive label with zero-padding removed from numbers ('Mouse007' -> 'mouse7')."""
    return re.sub(r"\d+", lambda m: str(int(m.group())), label.lower())


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.realpath(a) == os.path.realpath(b) or filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _read_participants(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    if not path.is_file():
        return [], {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        if "participant_id" not in fieldnames:
            raise ValidationError(f"{path} missing required column: participant_id")
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            pid = (row.get("participant_id") or "").strip()
            if not pid:
                continue
            rows[participant_id_with_prefix(pid)] = {
                k: (v or "").strip() for k, v in row.items() if k != "participant_id" and k
            }
    return [c for c in fieldnames if c != "participant_id"], rows


def _merge_dataset_description(
    manifest: DatasetManifest, sources: list[BidsSource], warnings: list[str]
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    owner: dict[str, str] = {}
    generated_by: list[Any] = []

    for source in sources:
        for key, value in source.dataset_description.items():
            if key == "GeneratedBy":
                generated_by.extend(e for e in value if e not in generated_by)
                continue
            if key not in merged:
                merged[key] = value
                owner[key] = str(source.root)
            elif merged[key] != value:
                warnings.append(
                    f"dataset_description.{key}: dropped {value!r} from {source.root} "
                    f"(kept {merged[key]!r} from {owner[key]})"
                )

    for key, value in manifest.dataset_description.items():
        if key == "GeneratedBy":
            generated_by.extend(e for e in value if e not in generated_by)
            continue
        if key in merged and merged[key] != value:
            warnings.append(
                f"dataset_description.{key}: manifest value {value!r} overrides "
                f"{merged[key]!r} from {owner[key]}"
            )
        merged[key] = value

    if generated_by:
        merged["GeneratedBy"] = generated_by
    return merged


def _merge_participants(
    manifest: DatasetManifest,
    sources: list[BidsSource],
    report: SubjectReport,
    errors: list[str],
) -> tuple[list[str], list[ParticipantSpec]]:
    columns: list[str] = []
    rows: dict[str, dict[str, str]] = {}
    row_origin: dict[tuple[str, str], str] = {}

    def add(pid: str, values: dict[str, Any], origin: str) -> None:
        row = rows.setdefault(pid, {})
        for key, raw in values.items():
            value = "" if raw is None else str(raw).strip()
            if key not in columns:
                columns.append(key)
            if value in _MISSING_VALUES:
                continue
            existing = row.get(key, "")
            if existing in _MISSING_VALUES:
                row[key] = value
                row_origin[(pid, key)] = origin
            elif existing != value:
                errors.append(
                    f"participants.tsv conflict for {pid} column '{key}': "
                    f"{existing!r} ({row_origin[(pid, key)]}) vs {value!r} ({origin})"
                )

    for source in sources:
        for col in source.participants_columns:
            if col not in columns:
                columns.append(col)
        for pid, values in source.participants.items():
            add(pid, values, str(source.root))
    for participant in manifest.participants:
        add(participant_id_with_prefix(participant.participant_id), participant.metadata, "manifest")

    # Every subject present in the merged dataset gets a row.
    for subject in sorted(report.source_sessions.keys() | report.spim_sessions.keys()):
        rows.setdefault(f"sub-{subject}", {})

    participants = [
        ParticipantSpec(participant_id=pid, metadata=rows[pid]) for pid in sorted(rows)
    ]
    return columns, participants


def _merge_participants_json(sources: list[BidsSource], errors: list[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    owner: dict[str, Path] = {}
    for source in sources:
        for key, value in source.participants_json.items():
            if key in merged and merged[key] != value:
                errors.append(
                    f"participants.json conflict for '{key}' between {owner[key]} and {source.root}"
                )
                continue
            merged.setdefault(key, value)
            owner.setdefault(key, source.root)
    return merged


def _merge_json(
    name: str, items: list[tuple[str, dict[str, Any]]], errors: list[str]
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    owner: dict[str, str] = {}
    for origin, data in items:
        for key, value in data.items():
            if key in merged and merged[key] != value:
                errors.append(f"{name} conflict for '{key}' between {owner[key]} and {origin}")
                continue
            merged.setdefault(key, value)
            owner.setdefault(key, origin)
    return merged


def _read_samples(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        missing = [c for c in ("participant_id", "sample_id") if c not in fieldnames]
        if missing:
            raise ValidationError(f"{path} missing required column(s): {', '.join(missing)}")
        rows = [
            {k: (v or "").strip() for k, v in row.items() if k}
            for row in reader
            if (row.get("participant_id") or "").strip() and (row.get("sample_id") or "").strip()
        ]
    return fieldnames, rows


def _merge_samples(
    manifest: DatasetManifest, sources: list[BidsSource], errors: list[str]
) -> tuple[list[str], list[dict[str, str]]]:
    """Combine source samples.tsv rows with the SPIM samples, keyed on (participant_id, sample_id)."""
    columns = list(SAMPLES_COLUMNS)
    rows: dict[tuple[str, str], dict[str, str]] = {}
    row_origin: dict[tuple[tuple[str, str], str], str] = {}

    tables = [(str(s.root), s.samples_columns, s.samples) for s in sources]
    tables.append(("SPIM scans", SAMPLES_COLUMNS, spim_sample_rows(manifest)))
    for origin, table_columns, table_rows in tables:
        columns.extend(c for c in table_columns if c not in columns)
        for raw in table_rows:
            key = (
                participant_id_with_prefix(raw["participant_id"]),
                raw["sample_id"] if raw["sample_id"].startswith("sample-") else f"sample-{raw['sample_id']}",
            )
            row = rows.setdefault(key, {"participant_id": key[0], "sample_id": key[1]})
            for column, value in raw.items():
                if column in ("participant_id", "sample_id") or value in _MISSING_VALUES:
                    continue
                existing = row.get(column, "")
                if existing in _MISSING_VALUES:
                    row[column] = value
                    row_origin[(key, column)] = origin
                elif existing != value:
                    errors.append(
                        f"samples.tsv conflict for {key[0]} {key[1]} column '{column}': "
                        f"{existing!r} ({row_origin[(key, column)]}) vs {value!r} ({origin})"
                    )
    return columns, [rows[k] for k in sorted(rows)]
