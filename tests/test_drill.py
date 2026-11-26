"""The public red-team drill: never reaches the model, one at a time, only the latest one kept, never retried.

Run: python -m unittest discover -s tests -t .
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("AIRLOCK_DATA", tempfile.mkdtemp(prefix="airlock-test-"))
os.environ.setdefault("AIRLOCK_ENV_FILE", os.devnull)

from ctrl import db, pipeline  # noqa: E402


class FooledJail:
    """A clean chamber where the drill's hostile code did NOT trip the canary (the worst case for cost)."""
    baseline = "v1"

    def health(self):
        return {"ok": True, "dirty": False}

    def reset(self):
        return 0.1

    def extract(self, data, ext):
        return {"extract": {"pages": ["PACIFIC GRID ELECTRIC  Amount due $78.40"]}, "ms": 1}

    def run_python(self, code, stdin=""):
        return {"stdout": "", "stderr": "", "returncode": 0, "ms": 1}

    def check(self):
        return {"canary_read": False}


class Unreachable(FooledJail):
    def health(self):
        raise OSError("connection refused")


class NoTouch:
    """Box or Pinecone: a drill must not call either."""
    def __getattr__(self, name):
        raise AssertionError(f"a drill called {name}")


def finish_all_drills():
    while (d := db.active_drill()):
        db.update(d, status="quarantined")


class Drill(unittest.TestCase):
    def setUp(self):
        finish_all_drills()

    def tearDown(self):
        pipeline.HALT.update(halted=False, why="")
        finish_all_drills()

    def test_drill_never_calls_the_model_even_if_the_canary_stays_quiet(self):
        doc_id, started = pipeline.start_drill()
        self.assertTrue(started)
        with mock.patch.object(pipeline.agent, "run", return_value=None) as model:
            d = pipeline.process(doc_id, chamber=FooledJail(), memory=NoTouch(), box=NoTouch())
        model.assert_not_called()
        self.assertEqual(d["status"], "quarantined")

    def test_one_drill_at_a_time(self):
        first, started = pipeline.start_drill()
        again, started_again = pipeline.start_drill()
        self.assertTrue(started)
        self.assertFalse(started_again)
        self.assertEqual(first, again)

    def test_only_the_latest_finished_drill_is_kept(self):
        ids = []
        for _ in range(3):
            doc_id, _ = pipeline.start_drill()
            db.update(doc_id, status="quarantined")
            ids.append(doc_id)
        drills = [d["id"] for d in db.documents(500) if d["source"] == "redteam"]
        self.assertEqual(drills, [ids[-1]])
        self.assertEqual(db.events(ids[0]), [])

    def test_drill_is_not_retried_when_the_chamber_is_down(self):
        doc_id, _ = pipeline.start_drill()
        d = pipeline.process(doc_id, chamber=Unreachable(), memory=NoTouch(), box=NoTouch())
        self.assertEqual(d["status"], "quarantined")
        self.assertIsNone(db.active_drill())
        self.assertTrue(pipeline.HALT["halted"])   # real documents still wait for a clean chamber

    def test_real_documents_are_never_pruned(self):
        real = pipeline.intake("bill.pdf", b"%PDF-1.4 fake")
        db.update(real, status="filed")
        doc_id, _ = pipeline.start_drill()
        db.update(doc_id, status="quarantined")
        pipeline.start_drill()
        self.assertIsNotNone(db.get(real))


if __name__ == "__main__":
    unittest.main()
