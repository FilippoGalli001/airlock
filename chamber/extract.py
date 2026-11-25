"""Text extraction. Runs INSIDE the jail (no network, unprivileged), on an untrusted file.

Reads /work/input.<ext>, writes one JSON object to stdout:
  {"method": "pdftotext"|"ocr"|"text", "pages": [str, ...], "chars": int,
   "total_pages": int|null, "pages_truncated": bool, "text_truncated": bool, "active_content": [str, ...]}
Never prints more than MAX_TEXT characters of document text, so the JSON always fits the worker's cap.
"""
import glob
import json
import os
import re
import subprocess
import sys

MIN_CHARS_PER_PAGE = 40  # below this, a PDF page is treated as a scan
MAX_PAGES = 10
MAX_TEXT = 120_000
# PDF features that run or launch something when the file is opened; plain documents never need them
ACTIVE_RE = re.compile(rb"/(JavaScript|JS|OpenAction|AA|Launch|EmbeddedFile|RichMedia|XFA|SubmitForm|ImportData)\b")


def run(argv, timeout=60):
    return subprocess.run(argv, capture_output=True, timeout=timeout, check=False)


STREAM_RE = re.compile(rb"stream\r?\n.*?endstream", re.DOTALL)


def active_content(path):
    """Look for active-content keys in the PDF's object dictionaries. Stream bodies (images, compressed text)
    are skipped: their random bytes can contain '/AA' or '/JS' by chance."""
    with open(path, "rb") as f:
        data = f.read(20 * 1024 * 1024)
    return sorted({m.group(1).decode() for m in ACTIVE_RE.finditer(STREAM_RE.sub(b"stream endstream", data))})


def total_pages(path):
    out = run(["pdfinfo", path]).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    return int(m.group(1)) if m else None


def pdf_pages_text(path):
    out = run(["pdftotext", "-layout", "-l", str(MAX_PAGES), path, "-"]).stdout.decode("utf-8", "replace")
    return [p.strip() for p in out.split("\f") if p.strip()]


def ocr_image(path):
    out = run(["tesseract", path, "-", "-l", "eng+ita"], timeout=90).stdout
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
    info = {"total_pages": None, "pages_truncated": False, "active_content": []}
    if ext == ".pdf":
        info["active_content"] = active_content(path)
        info["total_pages"] = total_pages(path)
        info["pages_truncated"] = bool(info["total_pages"] and info["total_pages"] > MAX_PAGES)
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
            pages = [f.read(MAX_TEXT + 1).decode("utf-8", "replace")]
        method = "text"
    chars = sum(len(p) for p in pages)
    kept, used = [], 0
    for p in pages:  # cap the text so the JSON stays well under the worker's output limit
        room = MAX_TEXT - used
        if room <= 0:
            break
        kept.append(p[:room])
        used += len(kept[-1])
    print(json.dumps({"method": method, "pages": kept, "chars": chars, "text_truncated": chars > MAX_TEXT,
                      **info}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
