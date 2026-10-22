"""Saved article content must remain available while PDF upgrades run."""
import http.client
import json
import tempfile
import threading
import unittest
import urllib.request
from contextlib import nullcontext
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.library import reader_files
from easyread.server import server
from easyread.library.store import Workspace, write_json_atomic


class Gate:
    def __init__(self):
        self.active = 0
        self.begins = 0
        self.finished = threading.Event()
        self.lock = threading.Lock()

    def begin(self):
        with self.lock:
            self.active += 1
            self.begins += 1
            self.finished.clear()

    def end(self):
        with self.lock:
            self.active -= 1
            if not self.active:
                self.finished.set()


class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root / "paper0001")
        self.ws.root.mkdir()
        write_json_atomic(self.ws.root / "paper.json", {"meta": {}, "blocks": []})
        self.gate = Gate()

    def tearDown(self):
        self.tmp.cleanup()

    def test_cancelled_read_does_not_send_a_second_error_response(self):
        handler = object.__new__(server.Handler)
        handler.app = SimpleNamespace(location=SimpleNamespace(request=lambda *args: nullcontext()))
        handler.command, handler.path = "GET", "/api/library"
        with patch.object(handler, "_get", side_effect=ConnectionAbortedError()), \
                patch.object(handler, "_json") as response, patch.object(server.log, "exception") as logged:
            handler.do_GET()
        response.assert_not_called()
        logged.assert_not_called()
        self.assertTrue(handler.close_connection)

    def test_open_is_nonblocking_deduplicated_and_crops_follow_layout(self):
        entered, release = threading.Event(), threading.Event()
        order = []

        def refresh(root):
            entered.set()
            self.assertTrue(release.wait(3))
            order.append("layout")

        with patch.object(reader_files.pdfwork, "refresh_layout", side_effect=refresh) as layout, \
                patch.object(reader_files.figures, "fill", side_effect=lambda ws: order.append("crop")) as crops, \
                patch.object(reader_files, "warm"):
            try:
                reader_files.prepare_later(self.ws, self.gate)
                self.assertTrue(entered.wait(1))
                reader_files.prepare_later(self.ws, self.gate)
                self.assertTrue(reader_files.busy())
                self.assertEqual(self.gate.begins, 1)
                crops.assert_not_called()
            finally:
                release.set()
                self.assertTrue(self.gate.finished.wait(3))
            self.assertEqual(order, ["layout", "crop"])
            self.assertEqual(layout.call_count, 1)
            self.assertEqual(self.gate.active, 0)
            self.assertFalse(reader_files.busy())

    def test_different_papers_do_not_prepare_pdfs_concurrently(self):
        other = Workspace(self.root / "paper0002")
        other.root.mkdir()
        first, second, release = threading.Event(), threading.Event(), threading.Event()
        other_gate = Gate()

        def refresh(root):
            if root == self.ws.root:
                first.set()
                self.assertTrue(release.wait(3))
            else:
                second.set()

        with patch.object(reader_files.pdfwork, "refresh_layout", side_effect=refresh), \
                patch.object(reader_files.figures, "fill"), patch.object(reader_files, "warm"):
            try:
                reader_files.prepare_later(self.ws, self.gate)
                self.assertTrue(first.wait(1))
                reader_files.prepare_later(other, other_gate)
                self.assertFalse(second.wait(.05))
            finally:
                release.set()
                self.assertTrue(self.gate.finished.wait(3))
                self.assertTrue(other_gate.finished.wait(3))
            self.assertTrue(second.is_set())

    def test_queued_translation_is_skipped(self):
        write_json_atomic(self.ws.root / "job.json", {"state": "queued"})
        with patch.object(reader_files.pdfwork, "refresh_layout") as refresh:
            reader_files.prepare_later(self.ws, self.gate)
        refresh.assert_not_called()
        self.assertEqual(self.gate.begins, 0)
        self.assertFalse(reader_files.busy())

    def test_translation_started_while_waiting_is_skipped(self):
        reader_files._PREPARE_SERIAL.acquire()
        with patch.object(reader_files.pdfwork, "refresh_layout") as refresh, \
                patch.object(reader_files.figures, "fill") as fill, patch.object(reader_files, "warm"):
            try:
                reader_files.prepare_later(self.ws, self.gate)
                write_json_atomic(self.ws.root / "job.json", {"state": "running"})
            finally:
                reader_files._PREPARE_SERIAL.release()
                self.assertTrue(self.gate.finished.wait(3))
            refresh.assert_not_called()
            fill.assert_not_called()
            self.assertEqual(self.gate.active, 0)

    def test_worker_exception_releases_gate_and_allows_retry(self):
        with patch.object(reader_files, "refresh_layout", side_effect=RuntimeError("broken PDF")), \
                patch.object(reader_files.log, "exception"), patch.object(reader_files.figures, "fill") as fill:
            reader_files.prepare_later(self.ws, self.gate)
            self.assertTrue(self.gate.finished.wait(3))
            fill.assert_not_called()
        self.assertFalse(reader_files.busy())
        with patch.object(reader_files, "refresh_layout"), \
                patch.object(reader_files.figures, "fill"), patch.object(reader_files, "warm"):
            reader_files.prepare_later(self.ws, self.gate)
            self.assertTrue(self.gate.finished.wait(3))
        self.assertEqual(self.gate.begins, 2)
        self.assertEqual(self.gate.active, 0)

    def test_failed_thread_start_releases_registration_and_gate(self):
        with patch.object(reader_files.threading, "Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("no thread")
            with self.assertRaises(RuntimeError):
                reader_files.prepare_later(self.ws, self.gate)
        self.assertEqual(self.gate.active, 0)
        self.assertFalse(reader_files.busy())

    def test_failed_warm_thread_start_also_releases_gate(self):
        with patch.object(reader_files.threading, "Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("no thread")
            with self.assertRaises(RuntimeError):
                reader_files.warm(self.ws.root, self.gate)
        self.assertEqual(self.gate.active, 0)
        self.assertFalse(reader_files.busy())

    def test_preparation_start_failure_keeps_persistent_http_response_valid(self):
        cfg = {"library_dir": str(self.root), "engine": "none"}
        with patch.object(server.config, "load", return_value=cfg), \
                patch.object(server, "_prepare_later", side_effect=RuntimeError("no worker thread")) as prepare, \
                patch.object(server.log, "exception") as logged:
            app = server.App(cfg)
            handler = type("TestHandler", (server.Handler,), {"app": app})
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            try:
                connection.request("GET", f"/api/p/{self.ws.id}/state")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                state = json.loads(response.read())
                self.assertEqual(state["id"], self.ws.id)
                original_socket = connection.sock

                # An appended error response would be read as this next result.
                connection.request("GET", "/api/version")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["api"], 1)
                self.assertIs(connection.sock, original_socket)
                prepare.assert_called_once()
                logged.assert_called_once()
                self.assertEqual(app.location.active, 0)
                self.assertFalse(reader_files.busy())
            finally:
                connection.close()
                httpd.shutdown()
                httpd.server_close()
                thread.join(2)
                app.location.marker.close()

    def test_api_sends_saved_state_before_pdf_upgrade_finishes(self):
        write_json_atomic(self.ws.root / "layout.json", {"p1": {"page": 1, "box": [0, 0, 1, 1]}})
        cfg = {"library_dir": str(self.root), "engine": "none"}
        entered, release = threading.Event(), threading.Event()
        finished = threading.Event()

        def refresh(root):
            entered.set()
            self.assertTrue(release.wait(3))
            write_json_atomic(root / "layout.json", {"p1": {"page": 1, "box": [.1, .1, .9, .9]}})

        def fill(ws):
            finished.set()

        with patch.object(server.config, "load", return_value=cfg), \
                patch.object(reader_files.pdfwork, "refresh_layout", side_effect=refresh), \
                patch.object(reader_files.figures, "fill", side_effect=fill), patch.object(reader_files, "warm"):
            app = server.App(cfg)
            handler = type("TestHandler", (server.Handler,), {"app": app})
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{httpd.server_port}/api/p/{self.ws.id}"
            try:
                with urllib.request.urlopen(url + "/state", timeout=1) as response:
                    state = json.load(response)
                self.assertEqual(state["layout"]["p1"]["box"], [0, 0, 1, 1])
                self.assertTrue(entered.wait(1))
                self.assertFalse(finished.is_set())
                self.assertGreater(app.location.active, 0)
                release.set()
                self.assertTrue(finished.wait(3))
                with urllib.request.urlopen(url + "/versions", timeout=1) as response:
                    versions = json.load(response)
                self.assertNotEqual(versions["layout"], state["versions"]["layout"])
                with urllib.request.urlopen(url + "/part/layout", timeout=1) as response:
                    part = json.load(response)
                self.assertEqual(part["data"]["p1"]["box"], [.1, .1, .9, .9])
            finally:
                release.set()
                httpd.shutdown()
                httpd.server_close()
                thread.join(2)
                app.location.marker.close()


if __name__ == "__main__":
    unittest.main()
