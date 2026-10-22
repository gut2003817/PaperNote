import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import config
from easyread.engines.engines import Cancelled, EngineError
from easyread.library.library import Library
from easyread.library.store import Workspace, write_json_atomic
from easyread.server import paper_api
from easyread.server.jobs import Jobs


class StopQueue(BaseException):
    pass


class JobQueueRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = Library(Path(self.tmp.name))
        self.first = self.paper("paper0001")
        self.second = self.paper("paper0002")
        with patch("easyread.server.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)
        self.app = SimpleNamespace(lib=self.lib, jobs=self.jobs)

    def paper(self, pid):
        root = self.lib.root / pid
        root.mkdir()
        ws = Workspace(root)
        write_json_atomic(ws.paper_path, {"meta": {"pages": [{"n": 1}], "page_count": 1}})
        return ws

    def enqueue_pair(self, translate=False):
        self.jobs.enqueue(self.first, translate_after=translate)
        self.jobs.enqueue(self.second, translate_after=False)

    def delete_and_import(self):
        paper_api.post(self.app, self.first, ["", "api", "p", self.first.id, "delete"], {})
        self.third = self.paper("paper0003")
        self.jobs.enqueue(self.third, translate_after=False)

    def drain(self):
        get = self.jobs.bulk.get

        def next_job():
            if self.jobs.bulk.empty():
                raise StopQueue()
            return get()

        with patch.object(self.jobs.bulk, "get", side_effect=next_job), self.assertRaises(StopQueue):
            self.jobs._bulk_loop()
        self.assertEqual(self.second.load("job")["state"], "done")
        self.assertEqual(self.jobs.cancels, {})

    def assert_deleted_job_did_not_stop_queue(self):
        self.drain()
        self.assertEqual(self.third.load("job")["state"], "done")
        self.assertFalse(self.first.root.exists())

    def test_delete_during_preparation_keeps_existing_and_new_jobs_running(self):
        write_json_atomic(self.first.paper_path, {"meta": {}})
        self.enqueue_pair()
        with patch.object(config, "load", return_value={"engine": "none"}), \
                patch("easyread.server.jobs.translate.prepare", side_effect=lambda ws: self.delete_and_import()):
            self.assert_deleted_job_did_not_stop_queue()

    def delete_during_translation(self, with_usage):
        self.enqueue_pair(translate=True)

        def translate(ws, cfg, pages, cancel, report, meter, read):
            self.delete_and_import()
            self.assertTrue(cancel.is_set())
            if with_usage:
                meter.add(input=10, output=5)
                raise EngineError("model interrupted")
            raise Cancelled()

        with patch.object(config, "load", return_value={"engine": "claude"}), \
                patch("easyread.server.jobs.translate.translate_pages", side_effect=translate):
            self.assert_deleted_job_did_not_stop_queue()

    def test_delete_during_translation_keeps_queue_running(self):
        self.delete_during_translation(with_usage=False)

    def test_delete_during_translation_usage_flush_keeps_queue_running(self):
        self.delete_during_translation(with_usage=True)

    def test_delete_during_running_state_write_keeps_queue_running(self):
        self.enqueue_pair()

        def write(path, data):
            if path == self.first.root / "job.json" and data.get("state") == "running":
                self.jobs.cancels[self.first.id].set()
                self.lib.trash(self.first.id)
            return write_json_atomic(path, data)

        with patch.object(config, "load", return_value={"engine": "none"}), \
                patch("easyread.library.store.write_json_atomic", side_effect=write):
            self.drain()
        self.assertFalse(self.first.root.exists())

    def fail_status_write(self, state):
        self.enqueue_pair()
        run = self.jobs._run_bulk

        def work(ws, job, cancel):
            if ws.id == self.first.id:
                if state == "cancelled":
                    raise Cancelled()
                if state == "error":
                    raise ValueError("invalid model response")
            return run(ws, job, cancel)

        def write(path, data):
            if path == self.first.root / "job.json" and data.get("state") == state:
                raise PermissionError("job state is not writable")
            return write_json_atomic(path, data)

        with patch.object(config, "load", return_value={"engine": "none"}), \
                patch.object(self.jobs, "_run_bulk", side_effect=work), \
                patch("easyread.library.store.write_json_atomic", side_effect=write), \
                patch("easyread.server.jobs.log.exception") as logged:
            self.drain()
        self.assertTrue(logged.called)

    def test_running_state_write_failure_does_not_kill_worker(self):
        self.fail_status_write("running")

    def test_cancelled_state_write_failure_does_not_kill_worker(self):
        self.fail_status_write("cancelled")

    def test_error_state_write_failure_does_not_kill_worker(self):
        self.fail_status_write("error")

    def test_missing_file_error_in_existing_directory_is_not_silenced(self):
        with patch.object(self.first, "update", side_effect=FileNotFoundError("missing temporary file")):
            with self.assertRaises(FileNotFoundError):
                self.jobs._write(self.first, state="cancelled")

    def test_permission_error_is_not_silenced(self):
        with patch.object(self.first, "update", side_effect=PermissionError("read-only directory")):
            with self.assertRaises(PermissionError):
                self.jobs._write(self.first, state="cancelled")
