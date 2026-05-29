# SPIMpack

SPIMpack is a standalone Python package for packaging/publishing SPIM datasets from existing microscopy source files.

## Scope

- Shared metadata/model layer for dataset manifests and validation
- Backend writer layer (pluggable)
- Initial backend: local Imaris symlink packaging
- CLI packaging workflow independent of SPIMprep internals and Snakemake

## Current backend

`local-imaris-symlink` writes:

- top-level `dataset_description.json`
- sidecars named `*_SPIM.json`
- symlinks named `*_SPIM.ims`

Sidecars preserve metadata that cannot be embedded in Imaris assets, including required SPIM fields:

- `orientation`
- `channel_labels`
- additional metadata fields from manifest input (and optional `RequiredMicroscopyFields`)

## Input format

Manifest input is YAML with optional TSV-driven asset rows:

```yaml
dataset_description:
  Name: Example
  BIDSVersion: 1.10.0
  RequiredMicroscopyFields: [Species]
datasets_tsv: datasets.tsv
```

Required TSV columns:

- `dataset_id`
- `bids_subdir`
- `source_ims`
- `output_prefix`
- `orientation`
- `channel_labels`

Output layout is BIDS-like and controlled by each row's `bids_subdir`.

Symlinks are absolute by default, with a `--relative-symlinks` option.

## CLI

```bash
spimpack package \
  --manifest /path/to/manifest.yml \
  --output-dir /path/to/output \
  --backend local-imaris-symlink
```

## Future backend model

The package separates shared models/validation from writer backends so future writers can be added without major restructuring, e.g.:

- object-store Zarr backend
- portal metadata ingest backend
