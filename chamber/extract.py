"""Text extraction. Runs INSIDE the jail (no network, unprivileged), on an untrusted file.

Reads /work/input.<ext>, writes one JSON object to stdout:
  {"method": "pdftotext"|"ocr"|"text", "pages": [str, ...], "chars": int}
"""
import glob
import json
import os
import subprocess
import sys

MIN_CHARS_PER_PAGE = 40  # below this, a PDF page is treated as a scan
MAX_PAGES = 10


def run(argv, timeout=60):
    return subprocess.run(argv, capture_output=True, timeout=timeout, check=False)


def pdf_pages_text(path):
    out = run(["pdftotext", "-layout", "-l", str(MAX_PAGES), path, "-"]).stdout.decode("utf-8", "replace")
    return [p.strip() for p in out.split("\f") if p.strip()]


def ocr_image(path):
    out = run(["tesseract", path, "-", "-l", "ita+eng"], timeout=90).stdout
    return out.decode("utf-8", "replace").strip()


def ocr_pdf(path):
    run(["pdftoppm", "-r", "200", "-l", str(MAX_PAGES), "-png", path, "/tmp/page"], timeout=90)
    return [ocr_image(p) for p in sorted(glob.glob("/tmp/page-*.png"))]


def main():
    files = glob.glob("/work/input.*")
    if not files:
        print(json.dumps({"error": "no input"}))
        return 1
    path = files[0]
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        pages = pdf_pages_text(path)
        method = "pdftotext"
        if sum(len(p) for p in pages) < MIN_CHARS_PER_PAGE * max(1, len(pages)):
            pages = ocr_pdf(path)
            method = "ocr"
    elif ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
        pages = [ocr_image(path)]
        method = "ocr"
    else:
        with open(path, "rb") as f:
            pages = [f.read(200_000).decode("utf-8", "replace")]
        method = "text"
    print(json.dumps({"method": method, "pages": pages, "chars": sum(len(p) for p in pages)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
