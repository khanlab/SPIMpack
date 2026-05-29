from __future__ import annotations

import json
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

DEFAULT_ORIENTATIONS = ["RAS", "LAS", "RPS", "LPS", "RAI", "LAI", "RPI", "LPI"]
DEFAULT_LEVEL = 5
DEFAULT_PORT = 9753

_NIIVUE_VERSION = "0.39.1"

# HTML template uses __PLACEHOLDER__ tokens to avoid conflicts with CSS/JS braces.
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SPIMpack QC Preview</title>
  <script src="https://unpkg.com/@niivue/niivue@__NIIVUE_VERSION__/dist/niivue.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: sans-serif; display: flex; height: 100vh; overflow: hidden; }
    #sidebar {
      width: 280px; padding: 16px; background: #f4f4f4;
      overflow-y: auto; flex-shrink: 0; border-right: 1px solid #ddd;
    }
    #main { flex: 1; display: flex; flex-direction: column; }
    canvas { display: block; flex: 1; width: 100%; }
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
  </style>
</head>
<body>
  <div id="sidebar">
    <h2>SPIMpack QC Preview</h2>
    <h3>Candidate Orientations</h3>
    <div id="orientation-buttons"></div>
    <input type="hidden" id="selectedOrientation" value="">
    <hr>
    <h3>Channel Labels</h3>
    <div id="channelFields"></div>
    <button id="submitBtn" onclick="submitResult()">Save Selection</button>
    <div id="status"></div>
  </div>
  <div id="main">
    <canvas id="gl1"></canvas>
  </div>
  <script>
    const previews = __PREVIEWS_JSON__;
    const channelLabels = __CHANNEL_LABELS_JSON__;
    const orientations = __ORIENTATIONS_JSON__;
    const defaultOrientation = __DEFAULT_ORIENTATION_JSON__;
    let nv = null;

    async function initNiivue(url) {
      if (nv) {
        await nv.loadVolumes([{ url: url }]);
      } else {
        nv = new niivue.Niivue({ show3Dcrosshair: true, backColor: [0.1, 0.1, 0.1, 1] });
        await nv.attachToCanvas(document.getElementById('gl1'));
        await nv.loadVolumes([{ url: url }]);
      }
    }

    function selectOrientation(orientation) {
      document.getElementById('selectedOrientation').value = orientation;
      document.querySelectorAll('.orientation-btn').forEach(btn => btn.classList.remove('active'));
      const btn = document.getElementById('btn-' + orientation);
      if (btn) btn.classList.add('active');
      const url = previews[orientation];
      if (url) initNiivue(url);
    }

    // Build orientation buttons
    const availableSet = new Set(Object.keys(previews));
    const container = document.getElementById('orientation-buttons');
    orientations.forEach(function(o) {
      const btn = document.createElement('button');
      btn.id = 'btn-' + o;
      const available = availableSet.has(o);
      btn.className = 'orientation-btn' + (available ? '' : ' unavailable');
      btn.textContent = available ? o : o + ' (unavailable)';
      if (available) { btn.onclick = function() { selectOrientation(o); }; }
      container.appendChild(btn);
    });

    // Build channel label fields
    const channelContainer = document.getElementById('channelFields');
    if (channelLabels.length > 0) {
      channelLabels.forEach(function(label, i) {
        const lbl = document.createElement('label');
        lbl.textContent = 'Channel ' + (i + 1);
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.id = 'channel-' + i;
        inp.value = label;
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
      const firstAvailable = Object.keys(previews)[0];
      if (firstAvailable) selectOrientation(firstAvailable);
    }

    function submitResult() {
      const orientation = document.getElementById('selectedOrientation').value;
      if (!orientation) {
        alert('Please select an orientation first.');
        return;
      }
      const channels = [];
      channelLabels.forEach(function(_, i) {
        const el = document.getElementById('channel-' + i);
        channels.push(el ? el.value : '');
      });
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
        document.getElementById('status').textContent = 'Error: ' + err;
      });
    }
  </script>
</body>
</html>
"""


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


def build_html(
    previews: dict[str, Path],
    orientations: list[str],
    channel_labels: list[str],
) -> str:
    """Return the QC viewer HTML page populated with the given previews."""
    preview_urls = {o: f"/{p.name}" for o, p in previews.items()}
    default_orientation = list(previews.keys())[0] if previews else ""
    return (
        _HTML_TEMPLATE.replace("__NIIVUE_VERSION__", _NIIVUE_VERSION)
        .replace("__PREVIEWS_JSON__", json.dumps(preview_urls))
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
            pass  # Suppress default request logs

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                filename = self.path.lstrip("/")
                file_path = output_dir / filename
                if file_path.exists():
                    data = file_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404)
                    self.end_headers()

        def do_POST(self) -> None:
            if self.path == "/save":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data: dict[str, Any] = json.loads(body)
                result_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                resp = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
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
) -> dict[str, Any]:
    """Run the interactive QC orientation and channel-label preview workflow.

    1. Generates low-resolution NIfTI previews for each candidate *orientations*.
    2. Serves a Niivue-based viewer on ``http://localhost:<port>/``.
    3. Waits for the user to confirm an orientation and optionally edit channel labels.
    4. Saves the accepted metadata to ``<output_dir>/qc_result.json`` and returns it.
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
        previews = generate_previews(source_ims, orientations, level, output_dir)

        if not previews:
            raise RuntimeError(
                "No previews could be generated. "
                "Check that the source file is readable and try a higher --level value."
            )

        print(f"Generated {len(previews)} preview(s) in {output_dir}")
        html = build_html(previews, orientations, channel_labels)
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
