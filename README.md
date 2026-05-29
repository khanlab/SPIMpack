# SPIMpack

SPIMpack is a standalone Python package for packaging/publishing SPIM datasets from existing microscopy source files into BIDS-structured output directories.

## Scope

- Shared metadata/model layer for dataset manifests and validation
- Backend writer layer (pluggable)
- Initial backend: local Imaris symlink packaging
- CLI packaging workflow independent of SPIMprep internals and Snakemake

## Current backend

`local-imaris-symlink` writes:

- top-level `dataset_description.json` with auto-injected SPIMpack `GeneratedBy` entry
- sidecars named `*_SPIM.json`
- symlinks named `*_SPIM.ims`

BIDS path structure is built from entities using pybids:

```
sub-{subject}/[ses-{session}/]micr/sub-{subject}[_ses-{session}][_sample-{sample}][_acq-{acquisition}]_SPIM.ims
```

Sidecars preserve metadata that cannot be embedded in Imaris assets, including required SPIM fields:

- `orientation`
- `channel_labels`
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

| Column          | Description                              |
|-----------------|------------------------------------------|
| `dataset_id`    | Logical dataset grouping key             |
| `sub`           | BIDS subject label (alphanumeric only)   |
| `sample`        | BIDS sample label (alphanumeric only)    |
| `source_ims`    | Absolute path to the source `.ims` file  |
| `orientation`   | Image orientation (e.g. `LPS`)          |
| `channel_labels`| Semicolon-separated channel names       |

Optional (entity columns):

| Column | Description                                          |
|--------|------------------------------------------------------|
| `ses`  | BIDS session label (alphanumeric only)               |
| `acq`  | BIDS acquisition label, e.g. objective `4x1`        |

Any additional columns are written into the sidecar JSON.

### Example TSV

```tsv
dataset_id	sub	ses	sample	acq	source_ims	orientation	channel_labels	Species
cohort1	01	01	s01	4x1	/data/raw/sub01.ims	LPS	nuclei;membrane	mouse
```

## Validation

Before writing, SPIMpack validates:

- Required `dataset_description` fields: `Name`, `BIDSVersion`, `DatasetType`, `License`
- `DatasetType` must be `raw` or `derivative`
- `Authors` must be a list if provided
- BIDS entity values (`sub`, `ses`, `sample`, `acq`) must be **alphanumeric only** (letters and numbers, no hyphens or special characters)
- Required sidecar fields: `orientation`, `channel_labels`
- Source `.ims` files must exist

## CLI

```bash
spimpack package \
  --manifest /path/to/manifest.yml \
  --output-dir /path/to/output \
  --backend local-imaris-symlink \
  [--relative-symlinks]
```

Symlinks are absolute by default. Use `--relative-symlinks` to create relative symlinks.

## Future backend model

The package separates shared models/validation from writer backends so future writers can be added without major restructuring, e.g.:

- object-store Zarr backend
- portal metadata ingest backend
