# SPIMpack

SPIMpack is a standalone Python package for packaging/publishing SPIM datasets from existing microscopy source files into BIDS-structured output directories.

## Installation

Install pixi first, then either clone the repo and install, or use the following to install the latest release:

```
pixi global install spimpack -c https://prefix.dev/akhanf/khanlab -c conda-forge
```

## Scope

- Shared metadata/model layer for dataset manifests and validation
- Backend writer layer (pluggable)
- Initial backend: local symlink packaging
- CLI packaging workflow independent of SPIMprep internals and Snakemake

## Backends

- `symlink` (default): links the dataset into the output directory.
- `mind`: writes `ingest_manifest.json`, describing the same dataset for upload to MIND. See
  [MIND ingest manifest](#mind-ingest-manifest).

`symlink` writes:

- top-level `dataset_description.json` with auto-injected SPIMpack `GeneratedBy` entry
- `samples.tsv` (`participant_id`, `sample_id`, `sample_type`), one row per
  subject/sample with `sample_type` set to `tissue`, plus `samples.json`
  (same as SPIMprep; required for BIDS microscopy)
- sidecars named `*_SPIM.json`
- symlinks named `*_SPIM.<extension>`, where the extension is derived from the
  source asset: `.ome.zarr`/`.zarr` stores keep their full extension, while
  compound file extensions collapse to the plain format extension
  (e.g. `x.ome.ims` -> `.ims`)

BIDS path structure is built from entities using pybids:

```
sub-{subject}/[ses-{session}/]micr/sub-{subject}[_ses-{session}][_sample-{sample}][_acq-{acquisition}]_SPIM{extension}
```

Sidecars preserve metadata that cannot be embedded in Imaris assets, including required SPIM fields:

- `OrientationStringXYZ`
- `SampleStaining`
- `PixelSize` / `PixelSizeUnits` for `.ims` and OME-Zarr (`.ome.zarr`, `.zarr`, `.ozx`) sources: the
  full-resolution voxel size, read lazily from the image's metadata with zarrnii and written as
  `[PixelSizeX, PixelSizeY, PixelSizeZ]` in `mm`. If the file can't be read, a
  warning is printed and the fields are left out.
- additional metadata fields from manifest input (and optional `RequiredMicroscopyFields`);
  these take precedence over values read from the image

## Input format

Manifest input is YAML with optional TSV-driven scan rows.

### YAML manifest example

```yaml
dataset_description:
  Name: My SPIM Dataset
  BIDSVersion: 1.9.0
  DatasetType: raw
  License: CC-BY-4.0
  Authors:
    - Author Name 1
    - Author Name 2
scans_tsv: scans.tsv
participants_tsv: participants.tsv  # optional
```

The writer automatically appends a `GeneratedBy` entry for SPIMpack if not already present.

### scans.tsv columns

Required:

| Column                   | Description                              |
|--------------------------|------------------------------------------|
| `subject`                | BIDS subject label (alphanumeric only)   |
| `sample`                 | BIDS sample label (alphanumeric only)    |
| `spim_path`              | Absolute path to the source microscopy asset (e.g. `.ims`, `.ome.zarr`) |
| `orientation_string_xyz` | Image orientation (e.g. `LPS`)           |
| `sample_staining`        | Semicolon-separated channel names        |

Optional:

| Column                   | Description                              |
|--------------------------|------------------------------------------|
| `session`                | BIDS session label (alphanumeric only)   |
| `acquisition`            | BIDS acquisition label, e.g. `4x`        |

Recommended BIDS sidecar fields (optional columns; each column name is the sidecar key):

| Column                        | Notes                                            |
|-------------------------------|--------------------------------------------------|
| `Manufacturer`                | e.g. `Miltenyi Biotec`, `LifeCanvas`             |
| `ManufacturersModelName`      | e.g. `UltraMicroscope Blaze II`, `SmartSPIM`     |
| `DeviceSerialNumber`          | a unique pseudonym is fine                       |
| `StationName`                 |                                                  |
| `SoftwareVersions`            | acquisition software version                     |
| `InstitutionName`             | e.g. `Western University`                        |
| `InstitutionalDepartmentName` |                                                  |
| `InstitutionAddress`          |                                                  |
| `BodyPart`                    | e.g. `BRAIN`                                     |
| `BodyPartDetails`             | e.g. `whole brain, optically cleared`            |
| `SampleEnvironment`           | must be `in vivo`, `ex vivo` or `in vitro`       |
| `SamplePrimaryAntibody`       | `;`-separated per channel -> JSON array          |
| `SampleSecondaryAntibody`     | `;`-separated per channel -> JSON array          |

Without these, the bids-validator reports `SIDECAR_KEY_RECOMMENDED` warnings.
The CLI writes only the values in the TSV; the UI pre-fills the defaults shown
in the examples above and offers the two microscopes as presets.

Any additional columns are written into the sidecar JSON.

### Example TSV

```tsv
subject	session	sample	acquisition	spim_path	orientation_string_xyz	sample_staining	Species
01	01	s01	4x1	/data/raw/sub01.ims	RPI	Abeta;YoPro;CD31	mouse
```

### participants.tsv (optional)

Use participant-level metadata once per participant and SPIMpack will write BIDS `participants.tsv`:

```tsv
participant_id	sex	age	genotype
sub-01	F	10	wt
```

When `participants.tsv` is present, each `scans.tsv` row must reference a known participant via `subject`.

## Validation

Before writing, SPIMpack validates:

- Required `dataset_description` fields: `Name`, `BIDSVersion`, `DatasetType`, `License`
- `DatasetType` must be `raw` or `derivative`
- `Authors` must be a list if provided
- BIDS entity values (`subject`, `session`, `sample`, `acquisition`) must be **alphanumeric only** (letters and numbers, no hyphens or special characters)
- Required columns to map to BIDS sidecar metadata: `orientation_string_xyz`, `sample_staining`
- Source SPIM datasets (can be .ims, .ome.zarr, .ozx; any format ZarrNii supports) must exist

### Running the bids-validator on `.ims` datasets

`.ims` is not a BIDS microscopy extension, so the bids-validator reports
`EXTENSION_MISMATCH` for each `*_SPIM.ims` file. It still validates the sidecar
for those files (e.g. missing `PixelSize` is still reported as
`SIDECAR_KEY_REQUIRED`), so you can ignore just that one issue with a config file
instead of adding `*.ims` to `.bidsignore` (which would also stop the sidecars
from being checked):

```json
{
  "ignore": [
    {"code": "EXTENSION_MISMATCH", "location": "**/*.ims"}
  ]
}
```

```
bids-validator /path/to/dataset -c bids-validator-config.json
```

## CLI

```bash
spimpack package \
  --manifest /path/to/manifest.yml \
  --output-dir /path/to/output \
  --backend symlink \
  [--relative-symlinks]
```

Symlinks are absolute by default. Use `--relative-symlinks` to create relative symlinks.
Use `--dry-run` to validate and print the summary without writing anything.

## Merging with an existing BIDS dataset (e.g. MRI)

SPIMpack can combine the SPIM data with one or more existing BIDS datasets, producing
a single dataset with e.g. `anat/`, `dwi/` and `micr/` side by side. Source datasets
are indexed with pybids; every file is symlinked at the same relative path
(`derivatives/`, `sourcedata/`, `code/` and dotfiles are skipped). Source files are
linked by path, not resolved.

List the sources in the manifest (relative paths resolve against the manifest
directory), and/or pass `--bids-source PATH` (repeatable):

```yaml
bids_sources:
  - path: /data/bids/mri_study
```

```bash
spimpack inspect-bids /data/bids/mri_study          # subjects, sessions, datatypes
spimpack package --manifest manifest.yml --output-dir /data/combined --dry-run
spimpack package --manifest manifest.yml --output-dir /data/combined
```

Rules:

- **Sessions are required** in both the SPIM scans and the source dataset(s).
- Subjects only in SPIM (e.g. control brains) or only in the source dataset are
  allowed. A subject-matching summary lists matched, SPIM-only and BIDS-only
  subjects with counts; SPIM-only labels that closely resemble a BIDS subject
  (e.g. `002` vs `02`) are flagged as possible naming errors. Fix labels in
  `scans.tsv` or in the source dataset.
- `dataset_description.json`: manifest values win; fields the manifest omits are
  filled from the source(s); every dropped value is reported as a warning.
  `GeneratedBy` entries are combined.
- `participants.tsv`: rows/columns are combined on `participant_id`; conflicting
  values are an error. Missing values are written as `n/a`.
- `participants.json` is merged (conflicting keys are an error), `.bidsignore` lines
  are combined.
- `samples.tsv`/`samples.json`: any rows/columns from the source(s) are combined with
  the SPIM samples on (`participant_id`, `sample_id`); conflicting values are an error.
- Any path provided by two sources (unless the files are identical) or by a source
  and SPIMpack is an error.
- The output directory must be new or empty. To pick up changes in the source
  dataset, re-run into a fresh directory.

In the UI, enter the dataset root(s) under **0. Existing BIDS dataset**; scan entries
then show whether each subject matches (or is SPIM-only), and the subject-matching
summary is shown before download.

## MIND ingest manifest

```bash
spimpack package --manifest manifest.yml --output-dir /path/to/out --backend mind [--convert-to-ome-zarr]
```

Instead of a dataset on disk, the `mind` backend writes `/path/to/out/ingest_manifest.json`: the input the MIND
server validates before any data is uploaded. It describes exactly the dataset the `symlink` backend would write,
merged BIDS sources included:

- JSON, TSV and root text files (`dataset_description.json`, `participants.tsv`, `samples.tsv`, sidecars,
  `README`, ...) are inside the manifest, with their contents.
- Every other file (images, NIfTI, `.bval`/`.bvec`) is listed with its BIDS path, its source path and its size.
  An OME-Zarr store is one entry, with its total size and file count.
- With `--convert-to-ome-zarr`, images that are not OME-Zarr (`.ims`, `.ozx`) are listed under an `.ome.zarr`
  path and marked `"convert": true`: the uploader converts them while writing to storage, so the uploaded
  dataset is plain BIDS microscopy. Without it they are listed as files in their source format.

The manifest format belongs to the `mind-ingest` package (in the MIND server repository). When it is installed
(`pip install "spimpack[mind]"`), the manifest is validated against BIDS and MIND's `spim` profile before it is
written, and an invalid dataset is refused with the list of problems; otherwise a warning says it was not
validated.

## Interactive UI

SPIMpack ships with an optional Streamlit-based web UI that lets you define
manifests and scans tables without editing YAML or TSV files by hand.

### Running the UI

```bash
pixi run spimpack-ui
```

A browser window opens automatically.  You can also navigate to
`http://localhost:8501` manually.

### Workflow

To edit an existing manifest, open **Load existing manifest.yml to edit** at the
top, enter (or browse to) the manifest path and click **Load**. Its scans.tsv,
participants.tsv and BIDS sources are loaded into the form. Extra scans.tsv columns
(e.g. `Species`) and extra `dataset_description` fields (e.g. `Funding`) are kept
and editable, and the save path is set to the loaded manifest.

1. **Dataset Description** – fill in the form fields (name, BIDS version,
   dataset type, license, authors).
2. **Scans Table** – use the interactive table to add one row per imaging
   acquisition.  Required columns are marked with `*`; optional BIDS entity
   columns (`session`, `acquisition`) can be left blank.  Extra PascalCase columns are
   written to the sidecar JSON.  Each scan has a **Microscope & sample metadata**
   panel for the recommended sidecar fields: pick the microscope
   (UltraMicroscope Blaze II / SmartSPIM, or custom), and check the pre-filled
   institution and sample defaults. **Apply these to all scans** copies the panel
   to every scan.
3. **Validate & Download** – any validation errors are shown inline.  Once the
   form is valid, download `manifest.yml` and `scans.tsv` with the provided
   buttons.
4. Run the CLI as usual:

```bash
spimpack package \
  --manifest manifest.yml \
  --output-dir /path/to/output \
  --backend symlink
```

## Future backend model

The package separates shared models/validation from writer backends so future writers can be added without major restructuring, e.g.:

- object-store Zarr backend
- portal metadata ingest backend
