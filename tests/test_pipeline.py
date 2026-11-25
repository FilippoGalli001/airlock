"""Fail closed: a document never goes into a chamber that cannot be brought back to its clean baseline.

Run: python -m unittest discover -s tests -t .
"""
import os
import tempfile
import unittest

os.environ.setdefault("AIRLOCK_DATA", tempfile.mkdtemp(prefix="airlock-test-"))
os.environ.setdefault("AIRLOCK_ENV_FILE", os.devnull)

from ctrl import db, pipeline  # noqa: E402


class StuckChamber:
    """Reports dirty and cannot be reset."""
    baseline = "v1"

    def __init__(self):
        self.extracted = False

    def health(self):
        return {"ok": True, "dirty": True}

    def reset(self):
        raise RuntimeError("restore failed")

    def extract(self, data, ext):
        self.extracted = True
        raise AssertionError("must not extract into a dirty chamber")


class Unreachable(StuckChamber):
    def health(self):
        raise OSError("connection refused")


class FailClosed(unittest.TestCase):
    def tearDown(self):
        pipeline.HALT.update(halted=False, why="")

    def run_with(self, chamber):
        doc_id = pipeline.intake("bill.pdf", b"%PDF-1.4 fake")
        d = pipeline.process(doc_id, redteam=False, chamber=chamber, memory=object(), box=object())
        return doc_id, d

    def test_dirty_chamber_that_cannot_reset_halts_the_queue(self):
        ch = StuckChamber()
        doc_id, d = self.run_with(ch)
        self.assertFalse(ch.extracted)
        self.assertEqual(d["status"], "queued")          # retried later, not lost, not processed
        self.assertTrue(pipeline.HALT["halted"])
        self.assertIn("chamber_unavailable", [e["kind"] for e in db.events(doc_id)])

    def test_unreachable_chamber_halts_too(self):
        ch = Unreachable()
        _, d = self.run_with(ch)
        self.assertFalse(ch.extracted)
        self.assertEqual(d["status"], "queued")
        self.assertIn("unreachable", pipeline.HALT["why"])


if __name__ == "__main__":
    unittest.main()
