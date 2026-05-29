from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backends import get_writer
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
        default="local-imaris-symlink",
        help="Backend writer name (default: local-imaris-symlink)",
    )
    package.add_argument(
        "--relative-symlinks",
        action="store_true",
        help="Create relative symlinks instead of absolute symlinks",
    )
    return parser


def run_package(manifest_path: Path, output_dir: Path, backend: str, relative_symlinks: bool) -> int:
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest)
    writer = get_writer(backend, relative_symlinks=relative_symlinks)
    writer.write(manifest, output_dir)
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
            )
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        parser.exit(status=2, message=f"error: {exc}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
