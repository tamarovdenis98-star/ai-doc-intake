"""Text out of a document: the PDF text layer when there is one, OCR (tesseract rus+eng) otherwise."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

MIN_CHARS_PER_PAGE = 60   # less than this on average = no usable text layer (a scan inside a PDF)
OCR_DPI = 200
OCR_MAX_PAGES = 6


@dataclass
class TextResult:
    method: str             # 'pdf_text' | 'ocr'
    pages: int
    text: str
    ocr_confidence: float | None = None


def extract(data: bytes, mime: str) -> TextResult:
    if mime == "application/pdf":
        res = _pdf_text_layer(data)
        if res.pages and len(res.text.strip()) >= MIN_CHARS_PER_PAGE * res.pages:
            return res
        return _ocr_images(_pdf_pages_as_images(data), res.pages)
    img = Image.open(io.BytesIO(data))
    img.load()
    return _ocr_images([img], 1)


def _pdf_text_layer(data: bytes) -> TextResult:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        # layout=True keeps table columns apart, which matters for line items
        pages = [p.extract_text(layout=True) or "" for p in pdf.pages]
    return TextResult("pdf_text", len(pages), _clean("\n\f\n".join(pages)))


def _pdf_pages_as_images(data: bytes) -> list[Image.Image]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    try:
        return [pdf[i].render(scale=OCR_DPI / 72).to_pil() for i in range(min(len(pdf), OCR_MAX_PAGES))]
    finally:
        pdf.close()


def _ocr_images(images: list[Image.Image], pages: int) -> TextResult:
    import pytesseract
    texts, confs = [], []
    for img in images[:OCR_MAX_PAGES]:
        img = remove_rules(ImageOps.autocontrast(ImageOps.exif_transpose(img).convert("L")))
        d = pytesseract.image_to_data(img, lang="rus+eng", config="--psm 6", output_type=pytesseract.Output.DICT)
        lines: dict[tuple, list[str]] = {}
        for i, word in enumerate(d["text"]):
            if not word.strip():
                continue
            lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(word)
            c = float(d["conf"][i])
            if c >= 0:
                confs.append(c)
        texts.append("\n".join(" ".join(ws) for ws in lines.values()))
    conf = round(sum(confs) / len(confs), 2) if confs else 0.0
    return TextResult("ocr", max(pages, len(images)), _clean("\n\f\n".join(texts)), conf)


def remove_rules(img: Image.Image) -> Image.Image:
    """Erases table borders (long dark horizontal / vertical runs) before OCR.

    Measured on a scanned invoice: with the borders tesseract recovered 0 of 8 table values (names, prices,
    amounts), without them 8 of 8. Text strokes are short, so only lines longer than ~4 % of the page width
    (horizontal) or ~1.7 % of its height (vertical) are removed.
    """
    w, h = img.size
    h_run, v_run = max(60, w // 25), max(30, h // 60)
    src = img.point(lambda p: 0 if p < 160 else 255).load()
    out = img.copy()
    dst = out.load()
    for y in range(h):
        run = 0
        for x in range(w + 1):
            if x < w and src[x, y] == 0:
                run += 1
                continue
            if run > h_run:
                for xx in range(x - run, x):
                    dst[xx, y] = 255
            run = 0
    for x in range(w):
        run = 0
        for y in range(h + 1):
            if y < h and src[x, y] == 0:
                run += 1
                continue
            if run > v_run:
                for yy in range(y - run, y):
                    dst[x, yy] = 255
            run = 0
    return out


def _clean(text: str) -> str:
    out = []
    for line in text.replace("\r", "").split("\n"):
        line = line.rstrip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
