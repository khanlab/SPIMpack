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
    _make_handler,
    build_html,
    generate_previews,
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
            ]
        )
        self.assertEqual(args.orientations, ["RAS", "LPS"])
        self.assertEqual(args.level, 3)
        self.assertEqual(args.output_dir, Path("/tmp/qc"))
        self.assertEqual(args.port, 8080)
        self.assertEqual(args.channel_labels, ["DAPI", "GFP"])
        self.assertTrue(args.no_browser)

    def test_qc_subcommand_required(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["qc"])


class TestBuildHtml(unittest.TestCase):
    """Verify that build_html produces valid HTML with expected tokens."""

    def test_contains_niivue_script(self) -> None:
        html = build_html(
            previews={"RAS": Path("/tmp/preview_RAS.nii.gz")},
            orientations=["RAS"],
            channel_labels=["DAPI"],
        )
        self.assertIn("niivue", html)

    def test_preview_url_injected(self) -> None:
        html = build_html(
            previews={"LPS": Path("/tmp/preview_LPS.nii.gz")},
            orientations=["LPS"],
            channel_labels=[],
        )
        self.assertIn("/preview_LPS.nii.gz", html)

    def test_channel_labels_injected(self) -> None:
        html = build_html(
            previews={"RAS": Path("/tmp/preview_RAS.nii.gz")},
            orientations=["RAS"],
            channel_labels=["DAPI", "GFP"],
        )
        self.assertIn("DAPI", html)
        self.assertIn("GFP", html)

    def test_all_orientations_present(self) -> None:
        orientations = ["RAS", "LPS", "RPI"]
        html = build_html(
            previews={"RAS": Path("/tmp/preview_RAS.nii.gz")},
            orientations=orientations,
            channel_labels=[],
        )
        for o in orientations:
            self.assertIn(o, html)

    def test_default_orientation_is_first_preview(self) -> None:
        html = build_html(
            previews={"RPI": Path("/tmp/preview_RPI.nii.gz")},
            orientations=["RPI"],
            channel_labels=[],
        )
        self.assertIn('"RPI"', html)

    def test_empty_previews_default_is_empty_string(self) -> None:
        html = build_html(previews={}, orientations=["RAS"], channel_labels=[])
        self.assertIn('""', html)

    def test_no_placeholder_tokens_remain(self) -> None:
        html = build_html(
            previews={"RAS": Path("/tmp/preview_RAS.nii.gz")},
            orientations=["RAS"],
            channel_labels=["ch1"],
        )
        self.assertNotIn("__PREVIEWS_JSON__", html)
        self.assertNotIn("__CHANNEL_LABELS_JSON__", html)
        self.assertNotIn("__ORIENTATIONS_JSON__", html)
        self.assertNotIn("__DEFAULT_ORIENTATION_JSON__", html)
        self.assertNotIn("__NIIVUE_VERSION__", html)


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


class TestDefaultConstants(unittest.TestCase):
    def test_default_orientations_nonempty(self) -> None:
        self.assertTrue(len(DEFAULT_ORIENTATIONS) > 0)

    def test_default_level_positive(self) -> None:
        self.assertGreater(DEFAULT_LEVEL, 0)

    def test_default_port_in_range(self) -> None:
        self.assertGreater(DEFAULT_PORT, 1024)
        self.assertLess(DEFAULT_PORT, 65536)
