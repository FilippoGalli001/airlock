"""chamber/extract.py's active-content scan: real JavaScript is found, image bytes are not mistaken for it.

Run: python -m unittest discover -s tests -t .
"""
import glob
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("extract", os.path.join(ROOT, "chamber", "extract.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


class ActiveContent(unittest.TestCase):
    def test_javascript_pdf_is_flagged(self):
        found = extract.active_content(os.path.join(ROOT, "samples", "receipt-with-javascript.pdf"))
        self.assertIn("OpenAction", found)
        self.assertIn("JavaScript", found)

    def test_scanned_samples_are_clean(self):
        # their image streams contain random bytes such as "/AA"; only dictionaries may count
        for p in glob.glob(os.path.join(ROOT, "samples", "*.pdf")):
            if not p.endswith("receipt-with-javascript.pdf"):
                self.assertEqual(extract.active_content(p), [], p)


if __name__ == "__main__":
    unittest.main()
