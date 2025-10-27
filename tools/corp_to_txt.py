#!/usr/bin/env python
"""
tools/corp_to_txt.py
--------------------
Convert PDFs in --src to plain text files in --out.

• Parses "born-digital" PDFs with PyMuPDF (fast & accurate).
• If extracted text is too short, automatically falls back to OCR.
• You can force OCR for all files with --force-ocr.
• Windows-friendly Tesseract detection (no PATH tweaks required).

USAGE:
  python tools/corp_to_txt.py --src corp_docs --out corp_docs/txt
  # only one file (case-insensitive substring match)
  python tools/corp_to_txt.py --src corp_docs --out corp_docs/txt --only "VEHICLE EMERGENCY GUIDE.pdf"
"""

from __future__ import annotations
import os, io, argparse, platform
from pathlib import Path
from typing import Optional

import fitz                         # PyMuPDF
from PIL import Image
import pytesseract

# --- Windows-friendly: locate tesseract.exe if PATH isn't updated ----------
def _wire_tesseract():
    if platform.system().lower() != "windows":
        return
    try:  # already visible?
        if pytesseract.get_tesseract_version():
            return
    except Exception:
        pass
    for exe in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]:
        if os.path.exists(exe):
            pytesseract.pytesseract.tesseract_cmd = exe
            break
_wire_tesseract()
# ---------------------------------------------------------------------------

def extract_text_pdf(pdf_path: Path, min_len: int = 250) -> str:
    """
    Try structured extraction first; if result is too short, return "" so caller can OCR.
    min_len guards against "parsed but basically empty" PDFs.
    """
    doc = fitz.open(pdf_path)
    parts = []
    for p in doc:
        parts.append(p.get_text("text") or "")
    text = "\n".join(parts).strip()
    return text if len(text) >= min_len else ""

def ocr_pdf(pdf_path: Path, dpi: int = 300, langs: str = "eng") -> str:
    """
    OCR every page at high DPI with a little pre-processing for cleaner text.
    """
    doc = fitz.open(pdf_path)
    chunks = []
    for p in doc:
        # Render page to bitmap
        mat = fitz.Matrix(dpi/72.0, dpi/72.0)
        pix = p.get_pixmap(matrix=mat, alpha=False)
        # Pillow image
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")  # grayscale
        # Light threshold (helps faint scans)
        img = img.point(lambda x: 255 if x > 200 else (0 if x < 80 else x))
        # OCR
        txt = pytesseract.image_to_string(img, lang=langs, config="--oem 1 --psm 3") or ""
        chunks.append(txt.strip())
    return "\n\n".join([c for c in chunks if c])

def save_txt(out_dir: Path, stem: str, content: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.txt").write_text(content, encoding="utf-8", errors="ignore")

def should_process(file_name: str, only: Optional[str]) -> bool:
    return True if not only else (only.lower() in file_name.lower())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="Folder containing PDFs")
    ap.add_argument("--out", required=True, help="Output folder for .txt")
    ap.add_argument("--langs", default="eng", help="Tesseract languages, e.g. 'eng+afr'")
    ap.add_argument("--dpi", type=int, default=300, help="Render DPI for OCR")
    ap.add_argument("--only", default=None, help="Only process the first file whose name contains this substring")
    ap.add_argument("--force-ocr", action="store_true", help="OCR every file (skip structured extraction)")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    out = Path(args.out).resolve()

    if not src.exists():
        raise FileNotFoundError(f"--src not found: {src}")

    processed = 0
    for pdf in sorted(src.glob("*.pdf")):
        if not should_process(pdf.name, args.only):
            continue

        try:
            stem = pdf.stem
            content = ""
            if not args.force_ocr:
                content = extract_text_pdf(pdf)
            if not content:
                # fallback (or forced) OCR
                content = ocr_pdf(pdf, dpi=args.dpi, langs=args.langs)

            if content.strip():
                save_txt(out, stem, content)
                print(f"[OK]  .PDF -> TXT: {pdf.name}")
                print(f"[preview] {(out / (stem + '.txt')).name}")
            else:
                print(f"[WARN] Empty text after OCR: {pdf.name}")

            processed += 1
            if args.only:  # when --only is used, stop after first match
                break

        except Exception as e:
            print(f"[WARN] Failed on {pdf.name} :: {e}")

    if processed == 0:
        print("[INFO] No PDFs matched your filter.")

if __name__ == "__main__":
    main()

