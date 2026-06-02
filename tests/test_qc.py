from __future__ import annotations

import json
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from urllib.request import urlopen

from spimpack.cli import build_parser, main
from spimpack.qc import (
    DEFAULT_LEVEL,
    DEFAULT_ORIENTATIONS,
    DEFAULT_PORT,
    _encode_png,
    _make_handler,
    _slice_to_png,
    build_html,
    generate_previews,
    generate_slice_pngs,
)


class TestQcCliParsing(unittest.TestCase):
    """Verify that the CLI parser correctly handles the ``qc preview`` subcommand."""

    def _parse(self, argv: list[str]):
        return build_parser().parse_args(argv)

    def test_qc_preview_positional_required(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["qc", "preview"])

    def test_qc_preview_minimal(self) -> None:
        args = self._parse(["qc", "preview", "/data/sample.ims"])
        self.assertEqual(args.command, "qc")
        self.assertEqual(args.qc_command, "preview")
        self.assertEqual(args.source_ims, Path("/data/sample.ims"))
        self.assertIsNone(args.orientations)
        self.assertEqual(args.level, DEFAULT_LEVEL)
        self.assertIsNone(args.output_dir)
        self.assertEqual(args.port, DEFAULT_PORT)
        self.assertIsNone(args.channel_labels)
        self.assertFalse(args.no_browser)
        self.assertIsNone(args.vmin)
        self.assertIsNone(args.vmax)

    def test_qc_preview_all_options(self) -> None:
        args = self._parse(
            [
                "qc",
                "preview",
                "/data/sample.ims",
                "--orientations",
                "RAS",
                "LPS",
                "--level",
                "3",
                "--output-dir",
                "/tmp/qc",
                "--port",
                "8080",
                "--channel-labels",
                "DAPI",
                "GFP",
                "--no-browser",
                "--vmin",
                "100",
                "--vmax",
                "4000",
            ]
        )
        self.assertEqual(args.orientations, ["RAS", "LPS"])
        self.assertEqual(args.level, 3)
        self.assertEqual(args.output_dir, Path("/tmp/qc"))
        self.assertEqual(args.port, 8080)
        self.assertEqual(args.channel_labels, ["DAPI", "GFP"])
        self.assertTrue(args.no_browser)
        self.assertEqual(args.vmin, 100.0)
        self.assertEqual(args.vmax, 4000.0)

    def test_qc_subcommand_required(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["qc"])


class TestBuildHtml(unittest.TestCase):
    """Verify that build_html produces valid HTML with expected tokens."""

    def _previews(self, orientation: str) -> dict:
        return {
            orientation: {
                "ch0": {
                    "axial": Path(f"/tmp/preview_{orientation}_ch0_axial.png"),
                    "coronal": Path(f"/tmp/preview_{orientation}_ch0_coronal.png"),
                    "sagittal": Path(f"/tmp/preview_{orientation}_ch0_sagittal.png"),
                }
            }
        }

    def test_contains_viewer_elements(self) -> None:
        html = build_html(
            previews=self._previews("RAS"),
            orientations=["RAS"],
            channel_labels=["DAPI"],
        )
        self.assertIn("img-axial", html)
        self.assertIn("img-coronal", html)
        self.assertIn("img-sagittal", html)

    def test_preview_url_injected(self) -> None:
        html = build_html(
            previews=self._previews("LPS"),
            orientations=["LPS"],
            channel_labels=[],
        )
        self.assertIn("/preview_LPS_ch0_axial.png", html)
        self.assertIn("/preview_LPS_ch0_coronal.png", html)
        self.assertIn("/preview_LPS_ch0_sagittal.png", html)

    def test_channel_labels_injected(self) -> None:
        html = build_html(
            previews=self._previews("RAS"),
            orientations=["RAS"],
            channel_labels=["DAPI", "GFP"],
        )
        self.assertIn("DAPI", html)
        self.assertIn("GFP", html)

    def test_all_orientations_present(self) -> None:
        orientations = ["RAS", "LPS", "RPI"]
        html = build_html(
            previews=self._previews("RAS"),
            orientations=orientations,
            channel_labels=[],
        )
        for o in orientations:
            self.assertIn(o, html)

    def test_default_orientation_is_first_preview(self) -> None:
        html = build_html(
            previews=self._previews("RPI"),
            orientations=["RPI"],
            channel_labels=[],
        )
        self.assertIn('"RPI"', html)

    def test_empty_previews_default_is_empty_string(self) -> None:
        html = build_html(previews={}, orientations=["RAS"], channel_labels=[])
        self.assertIn('""', html)

    def test_no_placeholder_tokens_remain(self) -> None:
        html = build_html(
            previews=self._previews("RAS"),
            orientations=["RAS"],
            channel_labels=["ch1"],
        )
        self.assertNotIn("__PREVIEWS_PNG_JSON__", html)
        self.assertNotIn("__CHANNEL_LABELS_JSON__", html)
        self.assertNotIn("__ORIENTATIONS_JSON__", html)
        self.assertNotIn("__DEFAULT_ORIENTATION_JSON__", html)

    def test_multi_channel_previews(self) -> None:
        """Multi-channel (4D) previews appear correctly in generated HTML."""
        previews = {
            "RAS": {
                "ch0": {
                    "axial": Path("/tmp/preview_RAS_ch0_axial.png"),
                    "coronal": Path("/tmp/preview_RAS_ch0_coronal.png"),
                    "sagittal": Path("/tmp/preview_RAS_ch0_sagittal.png"),
                },
                "ch1": {
                    "axial": Path("/tmp/preview_RAS_ch1_axial.png"),
                    "coronal": Path("/tmp/preview_RAS_ch1_coronal.png"),
                    "sagittal": Path("/tmp/preview_RAS_ch1_sagittal.png"),
                },
            }
        }
        html = build_html(
            previews=previews,
            orientations=["RAS"],
            channel_labels=["DAPI", "GFP"],
        )
        self.assertIn("/preview_RAS_ch0_axial.png", html)
        self.assertIn("/preview_RAS_ch1_axial.png", html)
        self.assertIn("DAPI", html)
        self.assertIn("GFP", html)


class TestGeneratePreviews(unittest.TestCase):
    """Verify generate_previews with zarrnii mocked out."""

    def _make_fake_zarrnii(self, tmp_dir: Path):
        """Return a mock ZarrNii class that writes a tiny NIfTI file."""

        class _FakeImg:
            def __init__(self, nii_path: Path):
                self._nii_path = nii_path

            def to_nifti(self):
                return self  # mimic nibabel NIfTI

            def to_filename(self, path: str) -> None:
                Path(path).write_bytes(b"NIFTI")

        class _FakeZarrNii:
            @staticmethod
            def from_file(path: str, level: int = 5, orientation: str = "RAS"):
                return _FakeImg(tmp_dir / f"preview_{orientation}.nii.gz")

        return _FakeZarrNii

    def test_generates_nifti_for_each_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "sample.ims"
            source.write_bytes(b"ims")
            out_dir = tmp_path / "previews"
            fake_cls = self._make_fake_zarrnii(out_dir)

            with unittest.mock.patch("spimpack.qc._require_zarrnii", return_value=fake_cls):
                result = generate_previews(source, ["RAS", "LPS"], level=5, output_dir=out_dir)

            self.assertEqual(set(result.keys()), {"RAS", "LPS"})
            for path in result.values():
                self.assertTrue(path.exists(), f"{path} should exist")

    def test_skips_failed_orientation_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "sample.ims"
            source.write_bytes(b"ims")
            out_dir = tmp_path / "previews"

            class _FailingZarrNii:
                @staticmethod
                def from_file(path, level=5, orientation="RAS"):
                    if orientation == "LPS":
                        raise RuntimeError("unsupported")
                    # Return a fake image for the other orientation
                    class _FakeImg:
                        def to_nifti(self):
                            return self
                        def to_filename(self, p):
                            Path(p).write_bytes(b"NIFTI")
                    return _FakeImg()

            with unittest.mock.patch(
                "spimpack.qc._require_zarrnii", return_value=_FailingZarrNii
            ):
                result = generate_previews(source, ["RAS", "LPS"], level=5, output_dir=out_dir)

            self.assertIn("RAS", result)
            self.assertNotIn("LPS", result)

    def test_missing_zarrnii_raises_import_error(self) -> None:
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "zarrnii":
                raise ModuleNotFoundError("No module named 'zarrnii'")
            return real_import(name, *args, **kwargs)

        with unittest.mock.patch("builtins.__import__", side_effect=mock_import):
            from spimpack import qc as qc_mod
            with self.assertRaises(ImportError) as ctx:
                qc_mod._require_zarrnii()
        self.assertIn("zarrnii", str(ctx.exception))


class TestEncodePng(unittest.TestCase):
    """Verify the stdlib PNG encoder produces valid PNG bytes."""

    def test_encode_png_produces_png_signature(self) -> None:
        import numpy as np
        data = np.zeros((4, 4), dtype=np.uint8)
        png_bytes = _encode_png(data)
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_encode_png_roundtrip(self) -> None:
        """The PNG should be decodable by a standard image library."""
        import io
        import struct
        import zlib
        import numpy as np

        arr = np.arange(256, dtype=np.uint8).reshape(16, 16)
        png_bytes = _encode_png(arr)

        # Minimal hand-verification: parse IHDR to check dimensions.
        # PNG layout: 8-byte sig, then chunks (4 len + 4 type + data + 4 crc)
        pos = 8
        length = struct.unpack(">I", png_bytes[pos:pos+4])[0]
        chunk_type = png_bytes[pos+4:pos+8]
        ihdr_data = png_bytes[pos+8:pos+8+length]
        self.assertEqual(chunk_type, b"IHDR")
        w, h = struct.unpack(">II", ihdr_data[:8])
        self.assertEqual(w, 16)
        self.assertEqual(h, 16)

    def test_slice_to_png_returns_bytes(self) -> None:
        import numpy as np
        data = np.random.randint(0, 256, size=(10, 10, 10), dtype=np.uint8)
        result = _slice_to_png(data, axis=2, index=5)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_slice_to_png_with_vmin_vmax(self) -> None:
        import numpy as np
        data = np.full((5, 5, 5), fill_value=128, dtype=np.uint8)
        # With vmin=0, vmax=255, a constant-128 slice should not be all-black
        result = _slice_to_png(data, axis=2, index=2, vmin=0, vmax=255)
        self.assertTrue(result.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_slice_to_png_empty_on_2d_input(self) -> None:
        import numpy as np
        data = np.zeros((10, 10), dtype=np.uint8)
        result = _slice_to_png(data, axis=0, index=0)
        self.assertEqual(result, b"")


class TestGenerateSlicePngs(unittest.TestCase):
    """Verify generate_slice_pngs with nibabel mocked out."""

    def _make_fake_nibabel_img(self, shape=(20, 20, 20)):
        import numpy as np

        class _FakeImg:
            dataobj = np.random.randint(0, 256, size=shape, dtype=np.uint8)

        class _FakeNib:
            @staticmethod
            def load(path):
                return _FakeImg()

        return _FakeNib

    def test_generates_single_channel_pngs(self) -> None:
        """3-D NIfTI produces a single channel (ch0) with three views."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nii_path = tmp_path / "preview_RAS.nii.gz"
            nii_path.write_bytes(b"fake")
            fake_nib = self._make_fake_nibabel_img(shape=(20, 20, 20))

            with unittest.mock.patch.dict("sys.modules", {"nibabel": fake_nib}):
                result = generate_slice_pngs(nii_path, tmp_path, "RAS")

            self.assertEqual(set(result.keys()), {"ch0"})
            self.assertEqual(set(result["ch0"].keys()), {"axial", "coronal", "sagittal"})
            for path in result["ch0"].values():
                self.assertTrue(path.exists())
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

    def test_generates_multi_channel_pngs(self) -> None:
        """4-D NIfTI (X, Y, Z, C) produces one channel dict per channel."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nii_path = tmp_path / "preview_RAS.nii.gz"
            nii_path.write_bytes(b"fake")
            # Shape (20, 20, 20, 2) – 2 channels
            fake_nib = self._make_fake_nibabel_img(shape=(20, 20, 20, 2))

            with unittest.mock.patch.dict("sys.modules", {"nibabel": fake_nib}):
                result = generate_slice_pngs(nii_path, tmp_path, "RAS")

            self.assertEqual(set(result.keys()), {"ch0", "ch1"})
            for ch_views in result.values():
                self.assertEqual(set(ch_views.keys()), {"axial", "coronal", "sagittal"})
                for path in ch_views.values():
                    self.assertTrue(path.exists())
                    self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

    def test_output_files_named_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nii_path = tmp_path / "preview_LPS.nii.gz"
            nii_path.write_bytes(b"fake")
            fake_nib = self._make_fake_nibabel_img()

            with unittest.mock.patch.dict("sys.modules", {"nibabel": fake_nib}):
                result = generate_slice_pngs(nii_path, tmp_path, "LPS")

            for ch_key, ch_views in result.items():
                for view, path in ch_views.items():
                    self.assertEqual(path.name, f"preview_LPS_{ch_key}_{view}.png")


class TestHttpServer(unittest.TestCase):
    """Smoke-test the QC HTTP server handler."""

    def _start_server(self, tmp: Path, html: str, result_path: Path, port: int):
        stop_event = threading.Event()
        handler_class = _make_handler(tmp, result_path, html, stop_event)
        from http.server import HTTPServer

        server = HTTPServer(("localhost", port), handler_class)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, stop_event

    def _find_free_port(self) -> int:
        import socket

        with socket.socket() as s:
            s.bind(("localhost", 0))
            return s.getsockname()[1]

    def test_get_root_returns_html(self) -> None:
        import http.client

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result_path = tmp_path / "qc_result.json"
            stop_event = threading.Event()
            port = self._find_free_port()
            html = "<html><body>test</body></html>"
            handler_class = _make_handler(tmp_path, result_path, html, stop_event)
            from http.server import HTTPServer

            server = HTTPServer(("localhost", port), handler_class)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("localhost", port)
                conn.request("GET", "/")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
                self.assertIn("test", body)
            finally:
                server.shutdown()

    def test_post_save_writes_json_and_sets_event(self) -> None:
        import http.client

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result_path = tmp_path / "qc_result.json"
            stop_event = threading.Event()
            port = self._find_free_port()
            html = "<html></html>"
            handler_class = _make_handler(tmp_path, result_path, html, stop_event)
            from http.server import HTTPServer

            server = HTTPServer(("localhost", port), handler_class)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                payload = json.dumps(
                    {"orientation": "RAS", "channel_labels": ["DAPI", "GFP"]}
                ).encode("utf-8")
                conn = http.client.HTTPConnection("localhost", port)
                conn.request(
                    "POST",
                    "/save",
                    body=payload,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                )
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                # Wait up to 2 s for the handler to set the event
                self.assertTrue(stop_event.wait(timeout=2))
                saved = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["orientation"], "RAS")
                self.assertEqual(saved["channel_labels"], ["DAPI", "GFP"])
            finally:
                server.shutdown()

    def test_get_nifti_file(self) -> None:
        import http.client

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nii_file = tmp_path / "preview_RAS.nii.gz"
            nii_file.write_bytes(b"\x00\x01\x02")
            result_path = tmp_path / "qc_result.json"
            stop_event = threading.Event()
            port = self._find_free_port()
            html = "<html></html>"
            handler_class = _make_handler(tmp_path, result_path, html, stop_event)
            from http.server import HTTPServer

            server = HTTPServer(("localhost", port), handler_class)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("localhost", port)
                conn.request("GET", "/preview_RAS.nii.gz")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.read(), b"\x00\x01\x02")
            finally:
                server.shutdown()

    def test_get_png_file_content_type(self) -> None:
        import http.client

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            png_file = tmp_path / "preview_RAS_axial.png"
            png_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            result_path = tmp_path / "qc_result.json"
            stop_event = threading.Event()
            port = self._find_free_port()
            html = "<html></html>"
            handler_class = _make_handler(tmp_path, result_path, html, stop_event)
            from http.server import HTTPServer

            server = HTTPServer(("localhost", port), handler_class)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("localhost", port)
                conn.request("GET", "/preview_RAS_axial.png")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.getheader("Content-Type"), "image/png")
            finally:
                server.shutdown()

    def test_get_missing_file_returns_404(self) -> None:
        import http.client

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result_path = tmp_path / "qc_result.json"
            stop_event = threading.Event()
            port = self._find_free_port()
            html = "<html></html>"
            handler_class = _make_handler(tmp_path, result_path, html, stop_event)
            from http.server import HTTPServer

            server = HTTPServer(("localhost", port), handler_class)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("localhost", port)
                conn.request("GET", "/nonexistent.nii.gz")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 404)
            finally:
                server.shutdown()

    def test_get_debug_returns_file_listing(self) -> None:
        import http.client

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create a preview file in the output dir
            (tmp_path / "preview_RAS.nii.gz").write_bytes(b"\x00" * 42)
            result_path = tmp_path / "qc_result.json"
            stop_event = threading.Event()
            port = self._find_free_port()
            html = "<html></html>"
            handler_class = _make_handler(tmp_path, result_path, html, stop_event)
            from http.server import HTTPServer

            server = HTTPServer(("localhost", port), handler_class)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("localhost", port)
                conn.request("GET", "/debug")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("files", data)
                names = [f["name"] for f in data["files"]]
                self.assertIn("preview_RAS.nii.gz", names)
                size = next(f["size_bytes"] for f in data["files"] if f["name"] == "preview_RAS.nii.gz")
                self.assertEqual(size, 42)
            finally:
                server.shutdown()


class TestDefaultConstants(unittest.TestCase):
    def test_default_orientations_nonempty(self) -> None:
        self.assertTrue(len(DEFAULT_ORIENTATIONS) > 0)

    def test_default_level_positive(self) -> None:
        self.assertGreater(DEFAULT_LEVEL, 0)

    def test_default_port_in_range(self) -> None:
        self.assertGreater(DEFAULT_PORT, 1024)
        self.assertLess(DEFAULT_PORT, 65536)
