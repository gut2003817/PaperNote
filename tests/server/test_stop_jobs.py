import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.engines.engines import EngineError
from easyread.server.jobs import Jobs
from easyread.server import jobs_api
from easyread.library.library import Library
from easyread.library.store import Workspace, write_json_atomic


class StopModelWorkTest(unittest.TestCase):
    """一键停止：停模型的活，不停渲染原页。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = Library(Path(self.tmp.name))
        with patch("easyread.server.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)

    def paper(self, name, prepared=True, **job):
        root = self.lib.root / name
        root.mkdir()
        ws = Workspace(root)
        write_json_atomic(ws.paper_path, {"meta": {"pages": [{"n": 1}], "page_count": 1} if prepared else {}})
        if job:
            ws.update("job", lambda j: j.update(job))
        return ws

    def test_queued_unprepared_paper_keeps_rendering_without_model(self):
        ws = self.paper("paper1", prepared=False, state="queued", type="translate", translate=True, read=False)
        self.assertEqual(self.jobs.stop_model_work(), 1)
        job = ws.load("job")
        self.assertEqual((job["state"], job["type"], job["translate"]), ("queued", "prepare", False))

    def test_queued_prepared_paper_is_cancelled(self):
        ws = self.paper("paper1", state="queued", type="translate", translate=True)
        self.jobs.stop_model_work()
        self.assertEqual(ws.load("job")["state"], "cancelled")

    def test_running_job_gets_cancel_signal(self):
        self.paper("paper1", state="running", type="read", translate=True, read=True)
        ev = self.jobs.cancels["paper1"] = threading.Event()
        self.assertEqual(self.jobs.stop_model_work(), 1)
        self.assertTrue(ev.is_set())

    def test_waiting_for_page_confirmation_becomes_done(self):
        ws = self.paper("paper1", state="confirm", type="translate", translate=True)
        self.jobs.stop_model_work()
        self.assertEqual(ws.load("job")["state"], "done")

    def test_prepare_only_and_finished_jobs_are_left_alone(self):
        a = self.paper("paper1", prepared=False, state="queued", type="prepare", translate=False)
        b = self.paper("paper2", state="done", type="translate", translate=True)
        self.assertEqual(self.jobs.stop_model_work(), 0)
        self.assertEqual(a.load("job")["state"], "queued")
        self.assertEqual(b.load("job")["state"], "done")

    def test_only_listed_ids_are_stopped(self):
        a = self.paper("paper1", state="queued", type="translate", translate=True)
        b = self.paper("paper2", state="queued", type="translate", translate=True)
        self.assertEqual(self.jobs.stop_model_work(["paper2"]), 1)
        self.assertEqual(a.load("job")["state"], "queued")
        self.assertEqual(b.load("job")["state"], "cancelled")

    def test_error_after_stop_counts_as_cancelled(self):
        ws = self.paper("paper1", state="queued", type="translate", translate=True)

        def run(ws, job, cancel):
            self.jobs.stop_model_work()
            raise EngineError("connection refused")
        get = self.jobs.bulk.get
        self.jobs.bulk.put("paper1")
        with patch.object(self.jobs, "_run_bulk", side_effect=run), \
                patch.object(self.jobs.bulk, "get", side_effect=[get(), StopIteration]), self.assertRaises(StopIteration):
            self.jobs._bulk_loop()
        self.assertEqual(ws.load("job")["state"], "cancelled")
        self.assertNotIn("paper1", self.jobs.cancels)

    def test_api_rejects_bad_ids(self):
        app = type("App", (), {"jobs": self.jobs})()
        self.assertEqual(jobs_api.post(app, "/api/jobs/stop", {}), {"stopped": 0})
        with self.assertRaises(ValueError):
            jobs_api.post(app, "/api/jobs/stop", {"ids": "paper1"})


if __name__ == "__main__":
    unittest.main()
