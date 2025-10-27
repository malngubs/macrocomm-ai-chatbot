#!/usr/bin/env python
"""
tools/pdf_ocr_to_txt.py
-----------------------
OCR-only pass for PDFs (useful if you want to force OCR and skip structured parsing).

USAGE:
  python tools/pdf_ocr_to_txt.py --src corp_docs --out corp_docs/txt
  python tools/pdf_ocr_to_txt.py --src corp_docs --out corp_docs/txt --only "VEHICLE EMERGENCY GUIDE.pdf"
"""

from __future__ import annotations
import os, io, argparse, platform
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image
import pytesseract

def _wire_tesseract():
    if platform.system().lower() != "windows":
        return
    try:
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

def ocr_pdf(pdf: Path, dpi: int = 300, langs: str = "eng") -> str:
    doc = fitz.open(pdf)
    parts = []
    for p in doc:
        pix = p.get_pixmap(matrix=fitz.Matrix(dpi/72.0, dpi/72.0), alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        img = img.point(lambda x: 255 if x > 200 else (0 if x < 80 else x))
        parts.append(pytesseract.image_to_string(img, lang=langs, config="--oem 1 --psm 3").strip())
    return "\n\n".join([t for t in parts if t])

def should_process(file_name: str, only: Optional[str]) -> bool:
    return True if not only else (only.lower() in file_name.lower())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--langs", default="eng")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    src = Path(args.src).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    processed = 0
    for pdf in sorted(src.glob("*.pdf")):
        if not should_process(pdf.name, args.only):
            continue
        try:
            txt = ocr_pdf(pdf, dpi=args.dpi, langs=args.langs)
            (out / (pdf.stem + ".txt")).write_text(txt, encoding="utf-8", errors="ignore")
            print(f"[OK] OCR -> TXT: {pdf.name}")
            processed += 1
            if args.only:
                break
        except Exception as e:
            print(f"[WARN] OCR failed on {pdf.name} :: {e}")

    if processed == 0:
        print("[INFO] No PDFs matched your filter.")

if __name__ == "__main__":
    main()

