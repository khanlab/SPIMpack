"""Streamlit-based UI for building SPIMpack manifest and datasets TSV files.

Run with:
    streamlit run ui/app.py
"""
from __future__ import annotations

import contextlib
import io
import sys
import uuid
from pathlib import Path
from typing import Any

import streamlit as st

# Allow running directly from the repo root without installing the package.
# When streamlit executes `streamlit run ui/app.py`, the working directory is
# typically the repo root and the package may not be on PYTHONPATH yet.
_ui_dir = Path(__file__).parent
_repo_root = _ui_dir.parent
if str(_repo_root / "src") not in sys.path:
    sys.path.insert(0, str(_repo_root / "src"))
if str(_ui_dir) not in sys.path:
    sys.path.insert(0, str(_ui_dir))

from generate import (  # noqa: E402
    generate_manifest_yaml,
    generate_tsv,
    validate_form,
)
from spimpack.cli import run_package  # noqa: E402
from spimpack.validation import ValidationError  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
#: Predefined stain options available in each channel selectbox.
_STAIN_OPTIONS: list[str] = [
    "— none —",
    "Abeta",
    "YoPro",
    "VACht",
    "ChAT",
    "Iba1",
    "NeuN",
    "CD31",
    "— custom —",
]
_MAX_STAINING_CHANNELS: int = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _browse_for_file() -> str | None:
    """Open a native OS file-picker dialog and return the chosen path.

    Uses Tkinter (standard library) so no extra dependencies are required.
    Falls back gracefully to None in headless / server environments where
    Tkinter or a display server is unavailable.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askopenfilename(
            title="Select SPIM file",
            filetypes=[
                ("SPIM files", "*.ims *.zarr *.ome.zarr *.ozx"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path or None
    except (ImportError, OSError, RuntimeError):
        # ImportError  – Tkinter not installed (some minimal Linux environments)
        # OSError      – no display server available (headless/server)
        # RuntimeError – Tcl/Tk initialisation failure
        return None

def _render_scan_entry(scan_id: str, scan_index: int) -> dict[str, Any]:
    """Render all widgets for one scan entry and return its current field values."""

    spim_key = f"spim_{scan_id}"
    browse_trigger_key = f"browse_trigger_{scan_id}"

    # ---- Handle Browse-triggered selection BEFORE creating text_input ----
    if browse_trigger_key in st.session_state:
        st.session_state[spim_key] = st.session_state.pop(browse_trigger_key)
        st.rerun()

    with st.container(border=True):
        hdr_col, rm_col = st.columns([10, 1])
        with hdr_col:
            st.markdown(f"##### Scan {scan_index + 1}")
        with rm_col:
            remove_clicked: bool = st.button(
                "✕", key=f"rm_{scan_id}", help="Remove this scan"
            )

        # ---- SPIM file path --------------------------------------------------
        path_col, browse_col = st.columns([5, 1])
        with path_col:
            spim_path: str = st.text_input(
                "SPIM file path *",
                key=spim_key,
                placeholder="/data/raw/sub01.ims",
                help="Absolute path to the source microscopy file (.ims, .ome.zarr, .ozx, …)",
            )
        with browse_col:
            st.write("\u00a0")
            if st.button("📂 Browse", key=f"browse_{scan_id}"):
                selected = _browse_for_file()
                if selected:
                    # Set a temporary trigger instead of overwriting the widget key
                    st.session_state[browse_trigger_key] = selected
                    st.rerun()
                else:
                    st.toast(
                        "File dialog unavailable — please type the path manually.",
                        icon="ℹ️",
                    )

        # ---- Validate file existence ----------------------------------------
        if spim_path:
            try:
                p = Path(spim_path)
                if not p.is_absolute():
                    st.caption("⚠️ Please enter an absolute path")
                elif p.exists():
                    st.caption("✅ File found on filesystem")
                else:
                    st.caption("⚠️ File not found at this path")
            except (OSError, ValueError):
                st.caption("⚠️ Invalid path")

        # ---- Dataset ID & orientation ----------------------------------------
        c1, c2 = st.columns(2)
        with c1:
            dataset_id: str = st.text_input(
                "Dataset ID *",
                key=f"dataset_id_{scan_id}",
                help="Logical dataset grouping key (e.g. cohort1)",
            )
        with c2:
            orientation: str = st.text_input(
                "Orientation XYZ *",
                key=f"orient_{scan_id}",
                placeholder="LPS",
                help="Image orientation string, e.g. LPS",
            )

        # ---- BIDS entities ---------------------------------------------------
        e1, e2, e3, e4 = st.columns(4)
        with e1:
            sub: str = st.text_input(
                "Subject (sub) *",
                key=f"sub_{scan_id}",
                help="BIDS subject label — alphanumeric only, e.g. 01",
            )
        with e2:
            sample: str = st.text_input(
                "Sample (sample) *",
                key=f"sample_{scan_id}",
                help="BIDS sample label — alphanumeric only, e.g. s01",
            )
        with e3:
            ses: str = st.text_input(
                "Session (ses)",
                key=f"ses_{scan_id}",
                help="BIDS session label (optional) — alphanumeric only",
            )
        with e4:
            acq: str = st.text_input(
                "Acquisition (acq)",
                key=f"acq_{scan_id}",
                help="BIDS acquisition label (optional), e.g. 4x",
            )

        # ---- Sample staining -------------------------------------------------
        st.markdown("**Sample staining** (select up to 3 channels)")
        stain_cols = st.columns(_MAX_STAINING_CHANNELS)
        staining_channels: list[str] = []
        for ch_idx, s_col in enumerate(stain_cols):
            with s_col:
                selected_stain: str = st.selectbox(
                    f"Channel {ch_idx + 1}",
                    options=_STAIN_OPTIONS,
                    key=f"stain_{scan_id}_{ch_idx}",
                )
                if selected_stain == "— custom —":
                    custom_val: str = st.text_input(
                        "Custom stain name",
                        key=f"stain_custom_{scan_id}_{ch_idx}",
                        placeholder="Enter stain name",
                        label_visibility="collapsed",
                    )
                    if custom_val.strip():
                        staining_channels.append(custom_val.strip())
                elif selected_stain and selected_stain != "— none —":
                    staining_channels.append(selected_stain)

    return {
        "_scan_id": scan_id,
        "_remove": remove_clicked,
        "dataset_id": dataset_id,
        "sub": sub,
        "sample": sample,
        "ses": ses,
        "acq": acq,
        "spim_path": spim_path,
        "orientation_string_xyz": orientation,
        "sample_staining": ";".join(staining_channels),
    }


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SPIMpack Manifest Builder",
    page_icon="🔬",
    layout="wide",
)
st.title("🔬 SPIMpack Manifest Builder")
st.caption(
    "Build your `manifest.yml` and `datasets.tsv` files interactively, "
    "then download them for use with `spimpack package`."
)

# ---------------------------------------------------------------------------
# Section 1 – Dataset Description
# ---------------------------------------------------------------------------
st.header("1. Dataset Description")

col1, col2 = st.columns(2)
with col1:
    name = st.text_input(
        "Dataset Name *",
        placeholder="My SPIM Dataset",
    )
    bids_version = st.text_input(
        "BIDS Version *",
        value="1.9.0",
    )
with col2:
    dataset_type = st.selectbox(
        "Dataset Type *",
        options=["raw", "derivative"],
        help="Indicates whether this is raw or derived data.",
    )
    license_val = st.text_input(
        "License *",
        placeholder="CC-BY-4.0",
        help="E.g. CC0, CC-BY-4.0, MIT",
    )

authors_text = st.text_area(
    "Authors (one per line)",
    placeholder="Author Name 1\nAuthor Name 2",
    help="Enter one author name per line.  Leave blank to omit from manifest.",
)
authors = [a.strip() for a in authors_text.splitlines() if a.strip()]

dataset_description: dict[str, Any] = {
    "Name": name,
    "BIDSVersion": bids_version,
    "DatasetType": dataset_type,
    "License": license_val,
}
if authors:
    dataset_description["Authors"] = authors

# ---------------------------------------------------------------------------
# Section 2 – Scan Entries
# ---------------------------------------------------------------------------
st.header("2. Scan Entries")
st.caption(
    "Each scan corresponds to one row in `datasets.tsv`.  "
    "Click **Browse** to pick the SPIM file with a file dialog; "
    "or type the path directly.  Required fields are marked with `*`."
)

# Initialise the list of scan IDs in session state on first load.
if "scan_ids" not in st.session_state:
    st.session_state["scan_ids"] = [str(uuid.uuid4())]

# Render all scan entries and collect row data.
scan_results: list[dict[str, Any]] = []
to_remove: str | None = None
for idx, sid in enumerate(st.session_state["scan_ids"]):
    entry = _render_scan_entry(sid, idx)
    remove = entry.pop("_remove")
    entry_scan_id = entry.pop("_scan_id")
    if remove:
        to_remove = entry_scan_id
    else:
        scan_results.append(entry)

# Handle removal after the full render pass to avoid mid-loop mutation.
if to_remove is not None:
    st.session_state["scan_ids"].remove(to_remove)
    st.rerun()

if st.button("➕ Add Scan", key="add_scan", type="secondary"):
    st.session_state["scan_ids"].append(str(uuid.uuid4()))
    st.rerun()

# Build non-empty rows for validation / generation.
non_empty_rows = [
    r for r in scan_results if any(str(v).strip() for v in r.values())
]

# ---------------------------------------------------------------------------
# TSV filename
# ---------------------------------------------------------------------------
tsv_filename = st.text_input(
    "TSV filename",
    value="datasets.tsv",
    help="Relative filename stored in manifest.yml as `datasets_tsv`.",
)

# ---------------------------------------------------------------------------
# Section 3 – Validate & Download
# ---------------------------------------------------------------------------
st.header("3. Validate & Download")

errors = validate_form(dataset_description, non_empty_rows)

if errors:
    st.error("**Please fix the following issues before downloading:**")
    for err in errors:
        st.markdown(f"- {err}")
else:
    st.success("✅ No validation errors — files are ready to download.")

manifest_yaml = generate_manifest_yaml(dataset_description, tsv_filename)
tsv_content = generate_tsv(non_empty_rows)

dl_col1, dl_col2 = st.columns(2)
with dl_col1:
    st.download_button(
        label="⬇️ Download manifest.yml",
        data=manifest_yaml,
        file_name="manifest.yml",
        mime="text/yaml",
        disabled=bool(errors),
    )
with dl_col2:
    st.download_button(
        label="⬇️ Download datasets.tsv",
        data=tsv_content,
        file_name=tsv_filename,
        mime="text/tab-separated-values",
        disabled=bool(errors),
    )

# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------
with st.expander("Preview manifest.yml", expanded=False):
    st.code(manifest_yaml, language="yaml")

with st.expander("Preview datasets.tsv", expanded=False):
    st.code(tsv_content)

# ---------------------------------------------------------------------------
# Section 4 – Run spimpack package
# ---------------------------------------------------------------------------
st.header("4. Run spimpack package")
st.caption(
    "Save the generated files to disk and invoke `spimpack package` directly. "
    "The manifest and TSV are written to the paths you specify below before the "
    "command is executed."
)

run_col1, run_col2 = st.columns(2)
with run_col1:
    manifest_save_path = st.text_input(
        "Manifest save path *",
        placeholder="/data/project/manifest.yml",
        help="Absolute path where manifest.yml will be written before running spimpack.",
    )
with run_col2:
    output_dir_path = st.text_input(
        "Output directory *",
        placeholder="/data/bids_output",
        help="Directory where spimpack will write the packaged BIDS dataset.",
    )

opt_col1, opt_col2 = st.columns(2)
with opt_col1:
    run_backend = st.selectbox(
        "Backend",
        options=["symlink"],
        help="Backend writer to use for packaging.",
    )
with opt_col2:
    run_relative_symlinks = st.checkbox(
        "Relative symlinks",
        value=False,
        help="Create relative symlinks instead of absolute symlinks (symlink backend only).",
    )

# Show a preview of the command that will be executed.
if manifest_save_path and output_dir_path:
    cmd_parts = [
        "spimpack", "package",
        "--manifest", manifest_save_path,
        "--output-dir", output_dir_path,
        "--backend", run_backend,
    ]
    if run_relative_symlinks:
        cmd_parts.append("--relative-symlinks")
    st.code(" ".join(cmd_parts), language="bash")

run_disabled = bool(errors) or not manifest_save_path or not output_dir_path

if run_disabled and not errors and (not manifest_save_path or not output_dir_path):
    st.caption("⚠️ Provide a manifest save path and output directory to enable this button.")

if st.button(
    "💾 Save Files & ▶️ Run spimpack package",
    key="run_spimpack",
    disabled=run_disabled,
    type="primary",
):
    manifest_path_obj = Path(manifest_save_path)
    tsv_path_obj = manifest_path_obj.parent / tsv_filename
    # Save files to disk.
    try:
        manifest_path_obj.parent.mkdir(parents=True, exist_ok=True)
        manifest_path_obj.write_text(manifest_yaml, encoding="utf-8")
        tsv_path_obj.write_text(tsv_content, encoding="utf-8")
        st.info(f"Saved `{manifest_path_obj}` and `{tsv_path_obj}`")
    except OSError as exc:
        st.error(f"❌ Failed to save files: {exc}")
    else:
        # Invoke spimpack package, capturing printed output.
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                run_package(
                    manifest_path=manifest_path_obj,
                    output_dir=Path(output_dir_path),
                    backend=run_backend,
                    relative_symlinks=run_relative_symlinks,
                )
        except (ValidationError, ValueError, FileNotFoundError) as exc:
            st.error(f"❌ spimpack package failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Unexpected error: {exc}")
        else:
            st.success("✅ spimpack package completed successfully.")
        captured = buf.getvalue()
        if captured:
            st.code(captured)

