"""Streamlit-based UI for building SPIMpack manifest and datasets TSV files.

Run with:
    streamlit run ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow running directly from the repo root without installing the package.
_ui_dir = Path(__file__).parent
_repo_root = _ui_dir.parent
if str(_repo_root / "src") not in sys.path:
    sys.path.insert(0, str(_repo_root / "src"))
if str(_ui_dir) not in sys.path:
    sys.path.insert(0, str(_ui_dir))

from generate import (  # noqa: E402
    DEFAULT_TSV_COLUMNS,
    _OPTIONAL_ENTITY_COLUMNS,
    generate_manifest_yaml,
    generate_tsv,
    validate_form,
)

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

dataset_description: dict = {
    "Name": name,
    "BIDSVersion": bids_version,
    "DatasetType": dataset_type,
    "License": license_val,
}
if authors:
    dataset_description["Authors"] = authors

# ---------------------------------------------------------------------------
# Section 2 – Datasets Table
# ---------------------------------------------------------------------------
st.header("2. Datasets Table")

_optional_col_note = ", ".join(f"`{c}`" for c in _OPTIONAL_ENTITY_COLUMNS)
st.caption(
    "Fill in one row per imaging acquisition.  "
    f"Optional BIDS entity columns ({_optional_col_note}) may be left blank.  "
    "Any extra **PascalCase** columns you add are written to the sidecar JSON."
)

_default_columns = list(DEFAULT_TSV_COLUMNS)
_empty_row: dict[str, str] = {col: "" for col in _default_columns}

if "df" not in st.session_state:
    st.session_state["df"] = pd.DataFrame([_empty_row])

_column_config = {
    "dataset_id": st.column_config.TextColumn(
        "dataset_id *",
        help="Logical dataset grouping key",
    ),
    "sub": st.column_config.TextColumn(
        "sub *",
        help="BIDS subject label (alphanumeric only)",
    ),
    "sample": st.column_config.TextColumn(
        "sample *",
        help="BIDS sample label (alphanumeric only)",
    ),
    "ses": st.column_config.TextColumn(
        "ses",
        help="BIDS session label (optional, alphanumeric only)",
    ),
    "acq": st.column_config.TextColumn(
        "acq",
        help="BIDS acquisition label (optional, e.g. 4x)",
    ),
    "spim_path": st.column_config.TextColumn(
        "spim_path *",
        help="Absolute path to the source microscopy file (.ims, .ome.zarr, …)",
    ),
    "orientation_string_xyz": st.column_config.TextColumn(
        "orientation_string_xyz *",
        help="Image orientation string, e.g. LPS",
    ),
    "sample_staining": st.column_config.TextColumn(
        "sample_staining *",
        help="Semicolon-separated channel names, e.g. nuclei;membrane",
    ),
}

edited_df: pd.DataFrame = st.data_editor(
    st.session_state["df"],
    num_rows="dynamic",
    use_container_width=True,
    column_config=_column_config,
    key="data_editor",
)
st.session_state["df"] = edited_df

# Filter out completely blank rows before validation/generation
all_rows = edited_df.to_dict(orient="records")
non_empty_rows = [
    r for r in all_rows if any(str(v).strip() for v in r.values())
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
