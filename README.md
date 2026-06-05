# SPIMpack

SPIMpack is a standalone Python package for packaging/publishing SPIM datasets from existing microscopy source files into BIDS-structured output directories.

## Scope

- Shared metadata/model layer for dataset manifests and validation
- Backend writer layer (pluggable)
- Initial backend: local symlink packaging
- CLI packaging workflow independent of SPIMprep internals and Snakemake

## Current backend

`symlink` writes:

- top-level `dataset_description.json` with auto-injected SPIMpack `GeneratedBy` entry
- sidecars named `*_SPIM.json`
- symlinks named `*_SPIM.ims`

BIDS path structure is built from entities using pybids:

```
sub-{subject}/[ses-{session}/]micr/sub-{subject}[_ses-{session}][_sample-{sample}][_acq-{acquisition}]_SPIM.ims
```

Sidecars preserve metadata that cannot be embedded in Imaris assets, including required SPIM fields:

- `OrientationStringXYZ`
- `SampleStaining`
- additional metadata fields from manifest input (and optional `RequiredMicroscopyFields`)

## Input format

Manifest input is YAML with optional TSV-driven asset rows.

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
datasets_tsv: datasets.tsv
```

The writer automatically appends a `GeneratedBy` entry for SPIMpack if not already present.

### TSV columns

Required:

| Column                   | Description                              |
|--------------------------|------------------------------------------|
| `dataset_id`             | Logical dataset grouping key             |
| `subject`                | BIDS subject label (alphanumeric only)   |
| `sample`                 | BIDS sample label (alphanumeric only)    |
| `spim_path`              | Absolute path to the source microscopy asset (e.g. `.ims`, `.ome.zarr`) |
| `orientation_string_xyz` | Image orientation (e.g. `LPS`)           |
| `sample_staining`        | Semicolon-separated channel names        |

Optional (entity columns):

| Column | Description                                                |
|--------------------------|------------------------------------------|
| `session`                | BIDS session label (alphanumeric only)   |
| `acquisition`            | BIDS acquisition label, e.g. `4x`        |

Any additional columns are written into the sidecar JSON.

### Example TSV

```tsv
dataset_id	subject	session	sample	acquisition	spim_path	orientation_string_xyz	sample_staining	Species
cohort1	01	01	s01	4x1	/data/raw/sub01.ims	LPS	nuclei;membrane	mouse
```

## Validation

Before writing, SPIMpack validates:

- Required `dataset_description` fields: `Name`, `BIDSVersion`, `DatasetType`, `License`
- `DatasetType` must be `raw` or `derivative`
- `Authors` must be a list if provided
- BIDS entity values (`sub`, `ses`, `sample`, `acq`) must be **alphanumeric only** (letters and numbers, no hyphens or special characters)
- Required columns to map to BIDS sidecar metadata: `orientation_string_xyz`, `sample_staining`
- Source SPIM datasets (can be .ims, .ome.zarr, .ozx; any format ZarrNii supports) must exist

## CLI

```bash
spimpack package \
  --manifest /path/to/manifest.yml \
  --output-dir /path/to/output \
  --backend symlink \
  [--relative-symlinks]
```

Symlinks are absolute by default. Use `--relative-symlinks` to create relative symlinks.

## Interactive UI

SPIMpack ships with an optional Streamlit-based web UI that lets you define
manifests and datasets tables without editing YAML or TSV files by hand.

### Installation

Install SPIMpack with the `ui` extra to pull in Streamlit and Pandas:

```bash
pip install "spimpack[ui]"
```

Or, when working from a clone:

```bash
pip install -e ".[ui]"
```

### Running the UI

```bash
streamlit run ui/app.py
```

A browser window opens automatically.  You can also navigate to
`http://localhost:8501` manually.

### Workflow

1. **Dataset Description** – fill in the form fields (name, BIDS version,
   dataset type, license, authors).
2. **Datasets Table** – use the interactive table to add one row per imaging
   acquisition.  Required columns are marked with `*`; optional BIDS entity
   columns (`ses`, `acq`) can be left blank.  Extra PascalCase columns are
   written to the sidecar JSON.
3. **Validate & Download** – any validation errors are shown inline.  Once the
   form is valid, download `manifest.yml` and `datasets.tsv` with the provided
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
