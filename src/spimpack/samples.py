"""BIDS ``samples.tsv`` / ``samples.json`` (required for microscopy).

Mirrors SPIMprep (``workflow/scripts/create_samples_tsv.py`` and
``resources/bids_template_files/samples.json``): one row per SPIM sample with
``participant_id``, ``sample_id`` and ``sample_type`` fixed to ``tissue``.
"""
from __future__ import annotations

from .models import DatasetManifest

SAMPLES_COLUMNS = ["participant_id", "sample_id", "sample_type"]
SAMPLE_TYPE = "tissue"

SAMPLES_JSON = {
    "sample_id": {
        "Description": (
            "A sample identifier of the form sample-<label>, matching a sample entity "
            "found in the dataset. The combination of sample_id and participant_id "
            "MUST be unique."
        )
    },
    "participant_id": {
        "Description": (
            "A participant identifier of the form sub-<label>, matching a participant "
            "entity found in the dataset. The combination of sample_id and "
            "participant_id MUST be unique."
        )
    },
    "sample_type": {
        "Description": (
            "type of sample from ENCODE Biosample Type "
            "(https://www.encodeproject.org/profiles/biosample_type)"
        )
    },
}


def spim_sample_rows(manifest: DatasetManifest) -> list[dict[str, str]]:
    """One row per unique (subject, sample) in the SPIM scans, in scan order."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for dataset in manifest.datasets:
        for asset in dataset.assets:
            key = (f"sub-{asset.entities.subject}", f"sample-{asset.entities.sample}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {"participant_id": key[0], "sample_id": key[1], "sample_type": SAMPLE_TYPE}
            )
    return rows
