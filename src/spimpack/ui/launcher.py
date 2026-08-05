"""Launcher for the SPIMpack Streamlit interface."""

from __future__ import annotations

import subprocess
import sys
from importlib.resources import as_file, files


def main() -> int:
    """Launch the packaged Streamlit application."""
    app_resource = files("spimpack.ui").joinpath("app.py")

    # as_file also handles package resources that are not represented directly
    # as ordinary filesystem paths.
    with as_file(app_resource) as app_path:
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            *sys.argv[1:],
        ]
        return subprocess.call(command)
