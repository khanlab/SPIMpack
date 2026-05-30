from __future__ import annotations

import json
import os
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
  <script
    id="niivue-script"
    src="https://unpkg.com/@niivue/niivue@__NIIVUE_VERSION__/dist/niivue.umd.min.js"
    onerror="showError('Failed to load Niivue from CDN (unpkg.com). ' +
      'Check your internet connection or try a different network. ' +
      'Open the browser console (F12) for details.')">
  </script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: sans-serif; display: flex; height: 100vh; overflow: hidden; }
    #sidebar {
      width: 300px; padding: 16px; background: #f4f4f4;
      overflow-y: auto; flex-shrink: 0; border-right: 1px solid #ddd;
    }
    #main { flex: 1; display: flex; flex-direction: column; min-width: 0; position: relative; }
    canvas { display: block; flex: 1; width: 100%; min-height: 0; }
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
    #debug-link { font-size: 11px; color: #888; text-decoration: none; display: block; margin-top: 12px; }
    #debug-link:hover { color: #2196f3; }
    #error-panel {
      display: none; position: absolute; top: 16px; left: 16px; right: 16px;
      background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px;
      padding: 14px 16px; font-size: 13px; color: #856404; z-index: 100;
    }
    #error-panel strong { display: block; margin-bottom: 6px; font-size: 14px; }
    #error-panel ul { margin: 6px 0 0 18px; }
    #error-panel li { margin-bottom: 4px; }
    #loading-overlay {
      display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(17,17,17,0.65); color: #fff; font-size: 14px;
      align-items: center; justify-content: center; z-index: 50;
    }
    #loading-overlay.visible { display: flex; }
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
    <a id="debug-link" href="/debug" target="_blank">Debug info (available previews)</a>
  </div>
  <div id="main">
    <canvas id="gl1"></canvas>
    <div id="loading-overlay">Loading preview\u2026</div>
    <div id="error-panel"></div>
  </div>
  <script>
    function showError(msg, bullets) {
      var panel = document.getElementById('error-panel');
      var html = '<strong>\u26a0\ufe0f ' + msg + '</strong>';
      if (bullets && bullets.length) {
        html += '<ul>';
        bullets.forEach(function(b) { html += '<li>' + b + '</li>'; });
        html += '</ul>';
      }
      panel.innerHTML = html;
      panel.style.display = 'block';
    }

    function hideLoading() {
      document.getElementById('loading-overlay').classList.remove('visible');
    }
    function showLoading() {
      document.getElementById('loading-overlay').classList.add('visible');
    }

    // Check WebGL2 availability before doing anything else.
    (function checkWebGL2() {
      var testCanvas = document.createElement('canvas');
      var ctx = testCanvas.getContext('webgl2');
      if (!ctx) {
        showError('WebGL2 is not available in this browser.', [
          'Try a different browser: Chrome or Firefox (desktop) work best.',
          'If using Chrome, navigate to <code>chrome://flags</code> and ensure "WebGL" is enabled.',
          'If running inside a VM or remote desktop, hardware GPU acceleration may be disabled \u2014 try <code>chrome --use-gl=swiftshader</code> as a software fallback.',
          'Some browser privacy extensions (e.g. Canvas Blocker) can block WebGL \u2014 disable them for localhost.',
          'Verify WebGL2 support at <a href="https://get.webgl.org/webgl2/" target="_blank">get.webgl.org/webgl2</a>.'
        ]);
      }
    })();

    const previews = __PREVIEWS_JSON__;
    const channelLabels = __CHANNEL_LABELS_JSON__;
    const orientations = __ORIENTATIONS_JSON__;
    const defaultOrientation = __DEFAULT_ORIENTATION_JSON__;
    let nv = null;

    async function initNiivue(url) {
      if (typeof niivue === 'undefined') {
        showError('Niivue library did not load.', [
          'The Niivue script could not be fetched from <code>unpkg.com</code>.',
          'Check your internet connection \u2014 unpkg.com must be reachable from your browser.',
          'Open the browser console (F12 \u2192 Console) and look for network errors.',
          'As a workaround, run <code>spimpack qc preview --no-browser</code>, then open the URL manually in a browser that can reach unpkg.com.'
        ]);
        return;
      }
      showLoading();
      try {
        if (nv) {
          await nv.loadVolumes([{ url: url }]);
        } else {
          nv = new niivue.Niivue({ show3Dcrosshair: true, backColor: [0.1, 0.1, 0.1, 1] });
          await nv.attachToCanvas(document.getElementById('gl1'));
          await nv.loadVolumes([{ url: url }]);
        }
        document.getElementById('error-panel').style.display = 'none';
      } catch (err) {
        showError('Failed to load preview image.', [
          'Error: ' + err.message,
          'Open the browser console (F12 \u2192 Network tab) and check that <code>' + url + '</code> returned HTTP 200.',
          'If the file is missing, re-run with <code>--level</code> set to a lower value (e.g. <code>--level 4</code>) to check whether the zarr level exists.',
          'Verify the NIfTI files exist by visiting <a href="/debug" target="_blank">/debug</a>.'
        ]);
      } finally {
        hideLoading();
      }
    }

    function selectOrientation(orientation) {
      document.getElementById('selectedOrientation').value = orientation;
      document.querySelectorAll('.orientation-btn').forEach(function(btn) {
        btn.classList.remove('active');
      });
      var btn = document.getElementById('btn-' + orientation);
      if (btn) btn.classList.add('active');
      var url = previews[orientation];
      if (url) initNiivue(url);
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

    // Build channel label fields
    const channelContainer = document.getElementById('channelFields');
    if (channelLabels.length > 0) {
      channelLabels.forEach(function(label, i) {
        var lbl = document.createElement('label');
        lbl.textContent = 'Channel ' + (i + 1);
        var inp = document.createElement('input');
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
      channelLabels.forEach(function(_, i) {
        var el = document.getElementById('channel-' + i);
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
        document.getElementById('status').textContent = 'Error saving: ' + err;
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

            # Serve NIfTI preview files — normalise and strip to basename to prevent
            # path traversal (e.g. /../../../etc/passwd).
            filename = os.path.basename(os.path.normpath(path.lstrip("/")))
            if not filename:
                self.send_response(400)
                self.end_headers()
                return
            file_path = output_dir / filename
            if file_path.exists() and file_path.is_file():
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
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
