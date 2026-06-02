from __future__ import annotations

import json
import os
import struct
import tempfile
import threading
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

DEFAULT_ORIENTATIONS = ["RAS", "LAS", "RPS", "LPS", "RAI", "LAI", "RPI", "LPI"]
DEFAULT_LEVEL = 5
DEFAULT_PORT = 9753

# HTML template uses __PLACEHOLDER__ tokens to avoid conflicts with CSS/JS braces.
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SPIMpack QC Preview</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: sans-serif; display: flex; height: 100vh; overflow: hidden; }
    #sidebar {
      width: 300px; padding: 16px; background: #f4f4f4;
      overflow-y: auto; flex-shrink: 0; border-right: 1px solid #ddd;
    }
    #main { flex: 1; display: flex; flex-direction: column; min-width: 0; position: relative; }
    #viewer {
      flex: 1; display: flex; gap: 4px; padding: 8px;
      background: #111; min-height: 0; overflow: hidden;
    }
    .slice-panel {
      flex: 1; display: flex; flex-direction: column; align-items: center;
      min-width: 0; overflow: hidden;
    }
    .slice-label {
      color: #aaa; font-size: 11px; text-transform: uppercase;
      letter-spacing: 1px; padding: 4px 0; flex-shrink: 0;
    }
    .slice-img {
      flex: 1; min-height: 0; max-width: 100%; object-fit: contain;
      display: block; background: #000;
    }
    h2 { font-size: 16px; margin-bottom: 12px; }
    h3 { font-size: 13px; text-transform: uppercase; color: #888; margin: 16px 0 8px; }
    .orientation-btn {
      display: block; width: 100%; padding: 8px 10px; margin-bottom: 5px;
      background: #e8e8e8; border: 1px solid #ccc; cursor: pointer;
      text-align: left; border-radius: 4px; font-size: 13px;
    }
    .orientation-btn:hover:not(.unavailable) { background: #d0eaff; border-color: #90c0ff; }
    .orientation-btn.active { background: #4caf50; color: white; border-color: #388e3c; }
    .orientation-btn.unavailable { color: #aaa; cursor: not-allowed; font-style: italic; }
    .channel-btn {
      display: block; width: 100%; padding: 8px 10px; margin-bottom: 5px;
      background: #e8e8e8; border: 1px solid #ccc; cursor: pointer;
      text-align: left; border-radius: 4px; font-size: 13px;
    }
    .channel-btn:hover { background: #d0eaff; border-color: #90c0ff; }
    .channel-btn.active { background: #2196f3; color: white; border-color: #1976d2; }
    label { display: block; font-size: 12px; color: #555; margin-bottom: 3px; }
    input[type=text] {
      width: 100%; padding: 5px 7px; margin-bottom: 10px;
      border: 1px solid #ccc; border-radius: 3px; font-size: 13px;
    }
    input[type=text]:focus { outline: none; border-color: #2196f3; }
    #submitBtn {
      width: 100%; padding: 10px; background: #2196f3; color: white;
      border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin-top: 8px;
    }
    #submitBtn:hover { background: #1976d2; }
    #status { margin-top: 10px; font-size: 12px; color: #388e3c; word-break: break-all; }
    hr { border: none; border-top: 1px solid #ddd; margin: 12px 0; }
    #debug-link { font-size: 11px; color: #888; text-decoration: none; display: block; margin-top: 12px; }
    #debug-link:hover { color: #2196f3; }
    #error-panel {
      display: none; position: absolute; top: 16px; left: 16px; right: 16px;
      background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px;
      padding: 14px 16px; font-size: 13px; color: #856404; z-index: 100;
    }
    #error-panel strong { display: block; margin-bottom: 6px; font-size: 14px; }
  </style>
</head>
<body>
  <div id="sidebar">
    <h2>SPIMpack QC Preview</h2>
    <h3>Candidate Orientations</h3>
    <div id="orientation-buttons"></div>
    <input type="hidden" id="selectedOrientation" value="">
    <div id="channel-section">
      <hr>
      <h3>Channels</h3>
      <div id="channel-buttons"></div>
    </div>
    <hr>
    <h3>Channel Labels</h3>
    <div id="channelFields"></div>
    <button id="submitBtn" onclick="submitResult()">Save Selection</button>
    <div id="status"></div>
    <a id="debug-link" href="/debug" target="_blank">Debug info (available previews)</a>
  </div>
  <div id="main">
    <div id="viewer">
      <div class="slice-panel">
        <div class="slice-label">Axial</div>
        <img id="img-axial" class="slice-img" src="" alt="Axial slice">
      </div>
      <div class="slice-panel">
        <div class="slice-label">Coronal</div>
        <img id="img-coronal" class="slice-img" src="" alt="Coronal slice">
      </div>
      <div class="slice-panel">
        <div class="slice-label">Sagittal</div>
        <img id="img-sagittal" class="slice-img" src="" alt="Sagittal slice">
      </div>
    </div>
    <div id="error-panel"></div>
  </div>
  <script>
    const previews = __PREVIEWS_PNG_JSON__;
    const channelLabels = __CHANNEL_LABELS_JSON__;
    const orientations = __ORIENTATIONS_JSON__;
    const defaultOrientation = __DEFAULT_ORIENTATION_JSON__;

    var currentOrientation = '';
    var currentChannel = '';

    function channelDisplayName(chKey, idx) {
      return channelLabels.length > idx ? channelLabels[idx] : 'Channel ' + (idx + 1);
    }

    function updateImages() {
      var chViews = ((previews[currentOrientation] || {})[currentChannel]) || {};
      ['axial', 'coronal', 'sagittal'].forEach(function(view) {
        var img = document.getElementById('img-' + view);
        if (img) img.src = chViews[view] || '';
      });
    }

    function selectChannel(chKey) {
      currentChannel = chKey;
      document.querySelectorAll('#channel-buttons .channel-btn').forEach(function(b) {
        b.classList.remove('active');
      });
      var btn = document.getElementById('chbtn-' + chKey);
      if (btn) btn.classList.add('active');
      updateImages();
    }

    function buildChannelButtons(chKeys) {
      var container = document.getElementById('channel-buttons');
      container.innerHTML = '';
      chKeys.forEach(function(chKey, i) {
        var btn = document.createElement('button');
        btn.id = 'chbtn-' + chKey;
        btn.className = 'channel-btn';
        btn.textContent = channelDisplayName(chKey, i);
        btn.onclick = function() { selectChannel(chKey); };
        container.appendChild(btn);
      });
      // Hide channel section when there is only one channel
      document.getElementById('channel-section').style.display =
        chKeys.length > 1 ? '' : 'none';
    }

    function selectOrientation(orientation) {
      currentOrientation = orientation;
      document.getElementById('selectedOrientation').value = orientation;
      document.querySelectorAll('#orientation-buttons .orientation-btn').forEach(function(btn) {
        btn.classList.remove('active');
      });
      var btn = document.getElementById('btn-' + orientation);
      if (btn) btn.classList.add('active');

      var chKeys = Object.keys(previews[orientation] || {});
      buildChannelButtons(chKeys);
      if (chKeys.length > 0 && chKeys.indexOf(currentChannel) === -1) {
        currentChannel = chKeys[0];
      }
      document.querySelectorAll('#channel-buttons .channel-btn').forEach(function(b) {
        b.classList.remove('active');
      });
      var chBtn = document.getElementById('chbtn-' + currentChannel);
      if (chBtn) chBtn.classList.add('active');
      updateImages();
      document.getElementById('error-panel').style.display = 'none';
    }

    // Build orientation buttons
    const availableSet = new Set(Object.keys(previews));
    const container = document.getElementById('orientation-buttons');
    orientations.forEach(function(o) {
      var btn = document.createElement('button');
      btn.id = 'btn-' + o;
      var available = availableSet.has(o);
      btn.className = 'orientation-btn' + (available ? '' : ' unavailable');
      btn.textContent = available ? o : o + ' (unavailable)';
      if (available) { btn.onclick = function() { selectOrientation(o); }; }
      container.appendChild(btn);
    });

    // Determine channel count from the first available orientation's previews
    var firstOriKey = Object.keys(previews)[0];
    var firstOriChannels = firstOriKey ? Object.keys(previews[firstOriKey]) : [];
    var nChannels = firstOriChannels.length;

    // Build channel label fields
    const channelContainer = document.getElementById('channelFields');
    if (nChannels > 0) {
      firstOriChannels.forEach(function(chKey, i) {
        var lbl = document.createElement('label');
        lbl.textContent = 'Channel ' + (i + 1);
        var inp = document.createElement('input');
        inp.type = 'text';
        inp.id = 'channel-' + i;
        inp.value = channelLabels.length > i ? channelLabels[i] : '';
        channelContainer.appendChild(lbl);
        channelContainer.appendChild(inp);
      });
    } else {
      channelContainer.innerHTML = '<p style="color:#aaa;font-size:12px;padding:4px 0">No channel labels provided.<br>Use --channel-labels to supply them.</p>';
    }

    // Auto-select default orientation
    if (defaultOrientation && availableSet.has(defaultOrientation)) {
      selectOrientation(defaultOrientation);
    } else {
      var firstAvailable = Object.keys(previews)[0];
      if (firstAvailable) selectOrientation(firstAvailable);
    }

    function submitResult() {
      var orientation = document.getElementById('selectedOrientation').value;
      if (!orientation) {
        alert('Please select an orientation first.');
        return;
      }
      var channels = [];
      for (var i = 0; i < nChannels; i++) {
        var el = document.getElementById('channel-' + i);
        channels.push(el ? el.value : '');
      }
      fetch('/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ orientation: orientation, channel_labels: channels })
      }).then(function(r) { return r.json(); }).then(function(data) {
        document.getElementById('status').textContent =
          'Saved! orientation=' + data.orientation +
          (data.channel_labels && data.channel_labels.length
            ? ', channels=[' + data.channel_labels.join(', ') + ']' : '');
      }).catch(function(err) {
        document.getElementById('status').textContent = 'Error saving: ' + err;
      });
    }
  </script>
</body>
</html>
"""


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    """Return a single PNG chunk (length + type + data + CRC)."""
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)


def _encode_png(data_2d: Any) -> bytes:
    """Encode a 2-D uint8 array-like as a grayscale PNG using only stdlib.

    ``data_2d`` must expose ``.shape`` (rows, cols) and ``.tobytes()``-like
    access via row iteration — a NumPy ndarray satisfies this.
    """
    h, w = data_2d.shape
    raw = b"".join(b"\x00" + bytes(data_2d[y]) for y in range(h))
    compressed = zlib.compress(raw, level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _slice_to_png(
    data: Any,
    axis: int,
    index: int,
    vmin: float | None = None,
    vmax: float | None = None,
) -> bytes:
    """Extract a 2-D slice from a 3-D array, normalise to uint8, and encode as PNG.

    *vmin* and *vmax* optionally pin the display range (data units).  Values
    below *vmin* are clipped to black; values above *vmax* are clipped to white.
    When not provided the per-slice min/max is used (auto-contrast).

    Returns an empty bytes object if the slice cannot be extracted.
    """
    import numpy as np

    slc = np.take(data, index, axis=axis)
    if slc.ndim != 2:
        return b""
    slc = slc.astype(float)
    lo = float(vmin) if vmin is not None else float(slc.min())
    hi = float(vmax) if vmax is not None else float(slc.max())
    if hi > lo:
        slc = np.clip((slc - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    else:
        slc = np.zeros_like(slc, dtype=np.uint8)
    slc = np.flipud(slc)
    return _encode_png(slc)


def _require_zarrnii() -> Any:
    """Import and return the ZarrNii class, raising a clear error if unavailable."""
    try:
        from zarrnii import ZarrNii  # type: ignore[import]

        return ZarrNii
    except ImportError as exc:
        raise ImportError(
            "zarrnii is required for QC preview. "
            "Install it with: pip install zarrnii"
        ) from exc


def generate_previews(
    source_ims: Path,
    orientations: list[str],
    level: int,
    output_dir: Path,
) -> dict[str, Path]:
    """Load a low-resolution version of *source_ims* for each candidate orientation
    and export it as a NIfTI file.

    Returns a mapping of orientation string -> NIfTI path for successful previews.
    Orientations that could not be generated are omitted with a warning.
    """
    ZarrNii = _require_zarrnii()
    output_dir.mkdir(parents=True, exist_ok=True)

    previews: dict[str, Path] = {}
    for orientation in orientations:
        nii_path = output_dir / f"preview_{orientation}.nii.gz"
        try:
            img = ZarrNii.from_file(str(source_ims), level=level, orientation=orientation)
            nii = img.to_nifti()
            nii.to_filename(str(nii_path))
            previews[orientation] = nii_path
        except (ValueError, RuntimeError, KeyError, OSError, TypeError) as exc:
            print(f"Warning: could not generate preview for orientation {orientation!r}: {exc}")
    return previews


def generate_slice_pngs(
    nii_path: Path,
    output_dir: Path,
    orientation: str,
    vmin: float | None = None,
    vmax: float | None = None,
) -> dict[str, dict[str, Path]]:
    """Generate axial, coronal, and sagittal mid-slice PNG images from a NIfTI file.

    Supports both 3-D (single-channel) and 4-D (multi-channel) volumes.  For a
    4-D array the last dimension is treated as the channel axis and a separate
    set of PNGs is produced for every channel (``"ch0"``, ``"ch1"``, …).

    *vmin* / *vmax* optionally fix the display range (data units) for all
    slices.  When not provided, per-slice auto-contrast is applied.

    Uses nibabel and numpy (both part of the ``qc`` extras) to load the volume.
    PNGs are written to *output_dir* without any third-party image library.

    Returns a mapping of ``{channel_key: {view_name: PNG path}}``.  For 3-D
    data the only channel key is ``"ch0"``.  Views or channels that could not
    be generated are omitted silently.
    """
    try:
        import nibabel as nib  # type: ignore[import]
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "nibabel and numpy are required for slice PNG generation. "
            "Install them with: pip install nibabel numpy"
        ) from exc

    img = nib.load(str(nii_path))
    data = np.asarray(img.dataobj).squeeze()

    if data.ndim < 3:
        return {}

    # Split 4-D data (X, Y, Z, C) into per-channel 3-D arrays.
    if data.ndim == 4:
        channel_arrays = [data[..., c] for c in range(data.shape[3])]
    else:
        channel_arrays = [data]

    view_axes = {"axial": 2, "coronal": 1, "sagittal": 0}
    result: dict[str, dict[str, Path]] = {}

    for ch_idx, ch_data in enumerate(channel_arrays):
        ch_key = f"ch{ch_idx}"
        ch_slices: dict[str, Path] = {}
        for view, axis in view_axes.items():
            if ch_data.shape[axis] == 0:
                continue
            mid_idx = ch_data.shape[axis] // 2
            png_bytes = _slice_to_png(ch_data, axis, mid_idx, vmin=vmin, vmax=vmax)
            if png_bytes:
                png_path = output_dir / f"preview_{orientation}_{ch_key}_{view}.png"
                png_path.write_bytes(png_bytes)
                ch_slices[view] = png_path
        if ch_slices:
            result[ch_key] = ch_slices

    return result


def build_html(
    previews: dict[str, dict[str, dict[str, Path]]],
    orientations: list[str],
    channel_labels: list[str],
) -> str:
    """Return the QC viewer HTML page populated with the given PNG slice previews.

    *previews* maps each orientation string to a dict of channel keys to view
    dicts, e.g.::

        {
            "RAS": {
                "ch0": {"axial": Path(...), "coronal": Path(...), "sagittal": Path(...)},
                "ch1": {"axial": Path(...), ...},
            }
        }
    """
    preview_urls: dict[str, dict[str, dict[str, str]]] = {
        o: {
            ch: {view: f"/{p.name}" for view, p in views.items()}
            for ch, views in channels.items()
        }
        for o, channels in previews.items()
    }
    default_orientation = list(previews.keys())[0] if previews else ""
    return (
        _HTML_TEMPLATE
        .replace("__PREVIEWS_PNG_JSON__", json.dumps(preview_urls))
        .replace("__CHANNEL_LABELS_JSON__", json.dumps(channel_labels))
        .replace("__ORIENTATIONS_JSON__", json.dumps(orientations))
        .replace("__DEFAULT_ORIENTATION_JSON__", json.dumps(default_orientation))
    )


def _make_handler(
    output_dir: Path,
    result_path: Path,
    html: str,
    stop_event: threading.Event,
) -> type:
    """Create an HTTPRequestHandler class bound to the given QC context."""

    class _QCHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # Suppress default per-request log noise

        def _send_json(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]  # strip query string

            if path in ("/", "/index.html"):
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/debug":
                files = sorted(output_dir.iterdir()) if output_dir.exists() else []
                self._send_json({
                    "output_dir": str(output_dir),
                    "files": [
                        {"name": f.name, "size_bytes": f.stat().st_size}
                        for f in files
                        if f.is_file()
                    ],
                })
                return

            # Serve preview files — normalise and strip to basename to prevent
            # path traversal (e.g. /../../../etc/passwd).
            filename = os.path.basename(os.path.normpath(path.lstrip("/")))
            if not filename:
                self.send_response(400)
                self.end_headers()
                return
            file_path = output_dir / filename
            if file_path.exists() and file_path.is_file():
                data = file_path.read_bytes()
                suffix = Path(filename).suffix.lower()
                content_type = "image/png" if suffix == ".png" else "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                print(f"[spimpack qc] 404: {path!r} not found in output directory")
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path == "/save":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data: dict[str, Any] = json.loads(body)
                result_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                self._send_json(data)
                stop_event.set()
            else:
                self.send_response(404)
                self.end_headers()

    return _QCHandler


def launch_viewer(
    output_dir: Path,
    html: str,
    result_path: Path,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Start the local QC web server and wait until the user saves a selection.

    Returns the saved QC result dict ``{"orientation": ..., "channel_labels": [...]}``.
    """
    stop_event = threading.Event()
    handler_class = _make_handler(output_dir, result_path, html, stop_event)
    server = HTTPServer(("localhost", port), handler_class)

    url = f"http://localhost:{port}/"
    print(f"QC viewer running at {url}")
    print("Select an orientation, confirm channel labels, then click 'Save Selection'.")
    print("Press Ctrl+C to abort without saving.")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    if open_browser:
        webbrowser.open(url)

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        print("\nAborted.")
        server.shutdown()
        raise

    server.shutdown()
    return json.loads(result_path.read_text(encoding="utf-8"))


def run_qc_preview(
    source_ims: Path,
    orientations: list[str] | None = None,
    level: int = DEFAULT_LEVEL,
    output_dir: Path | None = None,
    port: int = DEFAULT_PORT,
    channel_labels: list[str] | None = None,
    open_browser: bool = True,
    vmin: float | None = None,
    vmax: float | None = None,
) -> dict[str, Any]:
    """Run the interactive QC orientation and channel-label preview workflow.

    1. Generates low-resolution NIfTI previews for each candidate *orientations*.
    2. Extracts axial/coronal/sagittal PNG slices for every channel in each NIfTI.
    3. Serves a PNG-based viewer on ``http://localhost:<port>/``.
    4. Waits for the user to confirm an orientation and optionally edit channel labels.
    5. Saves the accepted metadata to ``<output_dir>/qc_result.json`` and returns it.

    *vmin* and *vmax* optionally pin the display brightness range (data units).
    """
    if orientations is None:
        orientations = DEFAULT_ORIENTATIONS
    if channel_labels is None:
        channel_labels = []

    _tmp_dir: tempfile.TemporaryDirectory | None = None
    if output_dir is None:
        _tmp_dir = tempfile.TemporaryDirectory(prefix="spimpack_qc_")
        output_dir = Path(_tmp_dir.name)

    try:
        print(
            f"Generating level-{level} previews for {len(orientations)} orientation(s): "
            + ", ".join(orientations)
        )
        nii_previews = generate_previews(source_ims, orientations, level, output_dir)

        if not nii_previews:
            raise RuntimeError(
                "No previews could be generated. "
                "Check that the source file is readable and try a higher --level value."
            )

        print(f"Generated {len(nii_previews)} NIfTI preview(s); extracting PNG slices…")
        png_previews: dict[str, dict[str, dict[str, Path]]] = {}
        for orientation, nii_path in nii_previews.items():
            slices = generate_slice_pngs(nii_path, output_dir, orientation, vmin=vmin, vmax=vmax)
            if slices:
                png_previews[orientation] = slices
            else:
                print(f"Warning: could not extract slices for orientation {orientation!r}")

        if not png_previews:
            raise RuntimeError(
                "No PNG slices could be generated from the NIfTI previews. "
                "Ensure nibabel and numpy are installed (pip install nibabel numpy)."
            )

        print(f"Launching viewer for {len(png_previews)} orientation(s) in {output_dir}")
        html = build_html(png_previews, orientations, channel_labels)
        result_path = output_dir / "qc_result.json"

        result = launch_viewer(
            output_dir=output_dir,
            html=html,
            result_path=result_path,
            port=port,
            open_browser=open_browser,
        )
    finally:
        if _tmp_dir is not None:
            _tmp_dir.cleanup()

    print(f"Accepted orientation : {result.get('orientation')}")
    if result.get("channel_labels"):
        print(f"Confirmed channels   : {result['channel_labels']}")
    return result
