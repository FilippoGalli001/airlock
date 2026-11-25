"""The review must be claimed once: double clicks and approve-then-reject cannot both run.

Run: python -m unittest discover -s tests -t .
"""
import os
import tempfile
import threading
import time
import unittest

os.environ["AIRLOCK_DATA"] = tempfile.mkdtemp(prefix="airlock-test-")
os.environ["AIRLOCK_ENV_FILE"] = os.devnull

from ctrl import db, pipeline  # noqa: E402

PROPOSAL = {"doc_type": "payslip", "issuer": "Acme Software", "date": "2026-11-30", "total": 4420.1,
            "currency": "USD", "confidence": 0.95, "suspicious": False, "reason": "paystub"}


class SlowBox:
    """Stands in for Box: slow uploads, counted."""
    def __init__(self):
        self.uploads = []

    def layout(self):
        return {"types": {"payslip": "f-pay", "other": "f-other"}}

    def upload(self, folder, name, data):
        time.sleep(0.2)
        self.uploads.append(name)
        return f"file-{len(self.uploads)}"


class FakeMemory:
    def __init__(self):
        self.records = []

    def remember(self, record_id, text, **meta):
        self.records.append(text)


def awaiting_doc():
    doc_id = pipeline.intake("paystub-nov.pdf", b"%PDF-1.4 fake")
    db.update(doc_id, status="awaiting_approval", proposal=PROPOSAL,
              decision={"action": "APPROVAL", "reasons": ["payslip"]})
    return doc_id


class Review(unittest.TestCase):
    def test_parallel_clicks_file_once(self):
        doc_id, box, mem = awaiting_doc(), SlowBox(), FakeMemory()
        results = []

        def click(action, note):
            try:
                pipeline.review(doc_id, action, {}, note, box=box, memory=mem)
                results.append(action)
            except ValueError as e:
                results.append(f"refused: {e}")

        threads = [threading.Thread(target=click, args=a) for a in
                   (("approve", ""), ("approve", ""), ("approve", "x"), ("reject", "no"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for r in results if not r.startswith("refused")), 1, results)
        self.assertLessEqual(len(box.uploads), 2)   # original + .airlock.json, at most once
        self.assertEqual(len(mem.records), 1)
        self.assertIn(db.get(doc_id)["status"], ("filed", "rejected"))

    def test_background_answers_before_filing(self):
        doc_id, box, mem = awaiting_doc(), SlowBox(), FakeMemory()
        t0 = time.time()
        d = pipeline.review(doc_id, "approve", {}, "", box=box, memory=mem, background=True)
        self.assertLess(time.time() - t0, 0.15)
        self.assertEqual(d["status"], "filing")
        with self.assertRaises(ValueError):
            pipeline.review(doc_id, "reject", {}, "too late", box=box, memory=mem)
        for _ in range(50):
            if db.get(doc_id)["status"] == "filed":
                break
            time.sleep(0.05)
        self.assertEqual(db.get(doc_id)["status"], "filed")
        self.assertEqual(len(box.uploads), 2)

    def test_invalid_review_does_not_claim(self):
        doc_id = awaiting_doc()
        with self.assertRaises(ValueError):
            pipeline.review(doc_id, "reject", {}, "", box=SlowBox(), memory=FakeMemory())
        self.assertEqual(db.get(doc_id)["status"], "awaiting_approval")


if __name__ == "__main__":
    unittest.main()
