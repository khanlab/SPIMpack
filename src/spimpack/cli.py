from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path

from .backends import get_writer
from .backends.symlink import ensure_empty_output_dir
from .bids_source import format_source_summary, load_bids_source, plan_bids_merge
from .io import load_manifest
from .validation import ValidationError, validate_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spimpack",
        description="Assemble SPIM datasets with pluggable output backends.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    package = subparsers.add_parser("package", help="Package datasets from manifest input")
    package.add_argument("--manifest", required=True, type=Path, help="YAML manifest path")
    package.add_argument("--output-dir", required=True, type=Path, help="Output dataset root")
    package.add_argument(
        "--backend",
        default="symlink",
        help="Backend writer name (default: symlink)",
    )
    package.add_argument(
        "--relative-symlinks",
        action="store_true",
        help="Create relative symlinks instead of absolute symlinks",
    )
    package.add_argument(
        "--bids-source",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help=(
            "Existing BIDS dataset (e.g. MRI) to merge into the output via symlinks. "
            "Repeatable; added to any bids_sources listed in the manifest."
        ),
    )
    package.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the summary/subject report without writing anything",
    )

    inspect = subparsers.add_parser(
        "inspect-bids", help="Summarise existing BIDS dataset(s) before merging"
    )
    inspect.add_argument("paths", nargs="+", type=Path, help="BIDS dataset root(s)")
    return parser


def run_package(
    manifest_path: Path,
    output_dir: Path,
    backend: str,
    relative_symlinks: bool,
    bids_sources: list[Path] | None = None,
    dry_run: bool = False,
) -> int:
    manifest = load_manifest(manifest_path)
    if bids_sources:
        combined: list[Path] = []
        seen: set[str] = set()
        for source in [*manifest.bids_sources, *bids_sources]:
            key = os.path.abspath(source)
            if key not in seen:
                seen.add(key)
                combined.append(Path(key))
        manifest = dataclasses.replace(manifest, bids_sources=combined)
    validate_manifest(manifest)

    plan = None
    if manifest.bids_sources:
        sources = [load_bids_source(p) for p in manifest.bids_sources]
        plan = plan_bids_merge(manifest, sources)
        if not dry_run:
            ensure_empty_output_dir(output_dir)

    if not dry_run:
        writer = get_writer(backend, relative_symlinks=relative_symlinks)
        writer.write(manifest, output_dir, plan=plan)

    num_datasets = len(manifest.datasets)
    all_assets = [asset for dataset in manifest.datasets for asset in dataset.assets]
    num_scans = len(all_assets)
    num_subjects = len({asset.entities.subject for asset in all_assets})

    print("Dry run: nothing written." if dry_run else "Packaging complete.")
    print(f"  Output directory : {output_dir}")
    print(f"  Datasets         : {num_datasets}")
    print(f"  Subjects         : {num_subjects}")
    print(f"  Scans            : {num_scans}")
    if plan is not None:
        print(f"  BIDS sources     : {len(manifest.bids_sources)}")
        print(f"  Linked files     : {len(plan.links)}")
        print(f"  Participants     : {len(plan.participants)}")
        print()
        print(plan.report.format())
        if plan.warnings:
            print()
            print("Warnings:")
            for warning in plan.warnings:
                print(f"  - {warning}")

    return 0


def run_inspect(paths: list[Path]) -> int:
    for index, path in enumerate(paths):
        if index:
            print()
        print(format_source_summary(load_bids_source(path)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "package":
            return run_package(
                manifest_path=args.manifest,
                output_dir=args.output_dir,
                backend=args.backend,
                relative_symlinks=args.relative_symlinks,
                bids_sources=args.bids_source,
                dry_run=args.dry_run,
            )
        if args.command == "inspect-bids":
            return run_inspect(args.paths)
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        parser.exit(status=2, message=f"error: {exc}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
