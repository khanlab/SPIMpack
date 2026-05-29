from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backends import get_writer
from .io import load_manifest
from .qc import DEFAULT_LEVEL, DEFAULT_ORIENTATIONS, DEFAULT_PORT
from .validation import ValidationError, validate_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spimpack",
        description="Assemble SPIM datasets with pluggable output backends.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------ package
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

    # ---------------------------------------------------------------------- qc
    qc = subparsers.add_parser("qc", help="Quality-control commands for dataset inspection")
    qc_sub = qc.add_subparsers(dest="qc_command", required=True)

    qc_preview = qc_sub.add_parser(
        "preview",
        help="Launch an interactive browser-based viewer to validate orientation and channel labels",
    )
    qc_preview.add_argument("source_ims", type=Path, help="Source .ims file to preview")
    qc_preview.add_argument(
        "--orientations",
        nargs="+",
        metavar="ORIENTATION",
        default=None,
        help=(
            "Candidate orientation strings to compare "
            f"(default: {' '.join(DEFAULT_ORIENTATIONS)})"
        ),
    )
    qc_preview.add_argument(
        "--level",
        type=int,
        default=DEFAULT_LEVEL,
        help=f"Zarr resolution level to load for previews (default: {DEFAULT_LEVEL})",
    )
    qc_preview.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save NIfTI previews and qc_result.json (default: temp directory)",
    )
    qc_preview.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local port for the QC viewer web server (default: {DEFAULT_PORT})",
    )
    qc_preview.add_argument(
        "--channel-labels",
        nargs="+",
        metavar="LABEL",
        default=None,
        help="Initial channel label(s) to pre-populate in the viewer (e.g. DAPI GFP)",
    )
    qc_preview.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server but do not open a browser window automatically",
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

        if args.command == "qc":
            from .qc import run_qc_preview

            if args.qc_command == "preview":
                run_qc_preview(
                    source_ims=args.source_ims,
                    orientations=args.orientations,
                    level=args.level,
                    output_dir=args.output_dir,
                    port=args.port,
                    channel_labels=args.channel_labels,
                    open_browser=not args.no_browser,
                )
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        parser.exit(status=2, message=f"error: {exc}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
