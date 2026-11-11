from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_DATASET_DESCRIPTION_FIELDS = ("Name", "BIDSVersion", "DatasetType", "License")

#: Names of ImageAsset attributes that are written directly to the JSON sidecar.
SIDECAR_ASSET_FIELDS = ("orientation_string_xyz", "sample_staining")

#: TSV columns that are required and map to ImageAsset / dataset fields (not entities, not sidecar).
REQUIRED_CORE_TSV_COLUMNS = ("spim_path", "orientation_string_xyz", "sample_staining")

@dataclass(frozen=True)
class SidecarFieldDef:
    """A recommended BIDS microscopy sidecar field that can be set per scan."""

    name: str  # sidecar key, also used as the scans.tsv column name
    group: str
    help: str
    default: str = ""  # pre-filled in the UI only; never injected by the CLI
    choices: tuple[str, ...] = ()  # allowed values; empty means free text
    multi: bool = False  # ';'-separated values become a JSON array (e.g. per channel)


#: Recommended sidecar fields for BIDS microscopy (``micr``) data, in UI order.
#: Each is an optional scans.tsv column of the same name.
SPIM_SIDECAR_FIELDS: tuple[SidecarFieldDef, ...] = (
    SidecarFieldDef("Manufacturer", "Microscope", "Manufacturer of the microscope."),
    SidecarFieldDef("ManufacturersModelName", "Microscope", "Manufacturer's model name of the microscope."),
    SidecarFieldDef("DeviceSerialNumber", "Microscope", "Serial number of the microscope (a unique pseudonym is fine)."),
    SidecarFieldDef("StationName", "Microscope", "Institution-defined name of the microscope."),
    SidecarFieldDef("SoftwareVersions", "Microscope", "Acquisition software version, e.g. ImSpector Pro 7.5."),
    SidecarFieldDef("InstitutionName", "Institution", "Institution in charge of the microscope.", default="Western University"),
    SidecarFieldDef("InstitutionalDepartmentName", "Institution", "Department in charge of the microscope."),
    SidecarFieldDef("InstitutionAddress", "Institution", "Address of the institution."),
    SidecarFieldDef("BodyPart", "Sample", "Body part imaged (DICOM Body Part Examined).", default="BRAIN"),
    SidecarFieldDef("BodyPartDetails", "Sample", "Additional details about the body part.", default="whole brain, optically cleared"),
    SidecarFieldDef(
        "SampleEnvironment", "Sample", "Environment in which the sample was imaged.",
        default="ex vivo", choices=("in vivo", "ex vivo", "in vitro"),
    ),
    SidecarFieldDef(
        "SamplePrimaryAntibody", "Sample",
        "Primary antibody (RRID, or name, supplier and catalog number). Separate per-channel values with ';'.",
        multi=True,
    ),
    SidecarFieldDef(
        "SampleSecondaryAntibody", "Sample",
        "Secondary antibody (RRID, or name, supplier and catalog number). Separate per-channel values with ';'.",
        multi=True,
    ),
)

SPIM_SIDECAR_FIELDS_BY_NAME: dict[str, SidecarFieldDef] = {f.name: f for f in SPIM_SIDECAR_FIELDS}

#: Microscopes offered as presets: model name -> manufacturer.
MICROSCOPE_PRESETS: dict[str, str] = {
    "UltraMicroscope Blaze II": "Miltenyi Biotec",
    "SmartSPIM": "LifeCanvas",
}


def parse_sidecar_value(name: str, raw: str) -> Any:
    """Convert a scans.tsv cell to its sidecar value (';'-lists become arrays for multi fields)."""
    field_def = SPIM_SIDECAR_FIELDS_BY_NAME.get(name)
    if field_def is None or not field_def.multi:
        return raw
    items = [v.strip() for v in raw.split(";") if v.strip()]
    return items if len(items) > 1 else (items[0] if items else "")


#: Path pattern used by pybids build_path for BIDS microscopy assets.
BIDS_MICR_PATTERN = (
    "sub-{subject}/[ses-{session}/]micr/"
    "sub-{subject}[_ses-{session}][_sample-{sample}][_acq-{acquisition}]_{suffix}{extension}"
)


def participant_id_with_prefix(participant_id: str) -> str:
    normalized = participant_id.strip()
    if normalized.startswith("sub-"):
        return normalized
    return f"sub-{normalized}"


def participant_label_from_id(participant_id: str) -> str:
    normalized = participant_id.strip()
    if normalized.startswith("sub-"):
        return normalized[4:]
    return normalized


@dataclass(frozen=True)
class EntityDef:
    """Definition of a BIDS entity used in filenames and TSV columns."""

    long_name: str   # used in BidsEntities and TSV headers
    short_name: str  # used in BIDS filename tokens (e.g. sub-, ses-, acq-)
    required: bool


#: Ordered BIDS entity definitions for SPIM microscopy data.
BIDS_ENTITY_DEFS: tuple[EntityDef, ...] = (
    EntityDef("subject", "sub", True),
    EntityDef("sample", "sample", True),
    EntityDef("session", "ses", False),
    EntityDef("acquisition", "acq", False),
)


@dataclass(frozen=True)
class BidsEntities:
    """BIDS entities that uniquely identify one image asset within a dataset."""

    subject: str
    sample: str
    session: str | None = None
    acquisition: str | None = None


@dataclass(frozen=True)
class ImageAsset:
    """A source microscopy image and its required sidecar metadata."""

    spim_path: Path
    entities: BidsEntities
    orientation_string_xyz: str
    sample_staining: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetSpec:
    """A logical dataset package with one or more image assets."""

    dataset_id: str
    assets: list[ImageAsset]


@dataclass(frozen=True)
class ParticipantSpec:
    """One participant row used to generate BIDS participants.tsv."""

    participant_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetManifest:
    """Top-level package manifest consumed by writer backends."""

    dataset_description: dict[str, Any]
    datasets: list[DatasetSpec]
    participants: list[ParticipantSpec] = field(default_factory=list)
    #: Existing BIDS datasets (e.g. MRI) whose files are linked into the output.
    bids_sources: list[Path] = field(default_factory=list)
