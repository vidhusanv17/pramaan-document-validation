"""OCR engine chain: PyMuPDF text layer -> RapidOCR (ONNX, offline) -> Tesseract (if installed) -> none.
Scanned pages are pre-processed with OpenCV (grey, deskew, denoise) before OCR. Boxes are kept in pixel
coordinates at RENDER_DPI so the UI can highlight evidence on the rendered page image."""
import io
import threading
import time

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

RENDER_DPI = 150
_engine = {"kind": None, "obj": None, "ready": False, "error": None, "init_seconds": None}
_lock = threading.Lock()


def warmup():
    with _lock:
        if _engine["ready"] or _engine["error"]:
            return _engine
        t0 = time.time()
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine["obj"] = RapidOCR()
            _engine["kind"] = "rapidocr"
            _engine["ready"] = True
        except Exception as e:  # pragma: no cover
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                _engine["obj"] = pytesseract
                _engine["kind"] = "tesseract"
                _engine["ready"] = True
            except Exception as e2:
                _engine["error"] = f"no OCR engine available ({e}; {e2})"
        _engine["init_seconds"] = round(time.time() - t0, 1)
        return _engine


def status():
    return {k: v for k, v in _engine.items() if k != "obj"}


def preprocess(rgb: np.ndarray):
    """Grey -> denoise -> deskew. Returns (processed_rgb, angle_degrees)."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21) if gray.size < 4_000_000 else gray
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    angle = 0.0
    if len(coords) > 500:
        rect = cv2.minAreaRect(coords.astype(np.float32))
        a = rect[-1]
        if a < -45:
            a += 90
        if a > 45:
            a -= 90
        angle = float(a)
    out = rgb
    if 0.3 < abs(angle) < 15:
        h, w = gray.shape
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        out = cv2.warpAffine(rgb, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return out, round(angle, 2)


def ocr_image(rgb: np.ndarray):
    eng = warmup()
    if not eng["ready"]:
        return {"text": "", "boxes": [], "confidence": 0.0, "engine": "none", "error": eng["error"]}
    if eng["kind"] == "rapidocr":
        res, _ = eng["obj"](rgb)
        lines = []
        for box, text, conf in (res or []):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append([float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), text, float(conf)])
        lines.sort(key=lambda b: (round(b[1] / 18), b[0]))
        text = "\n".join(b[4] for b in lines)
        conf = float(np.mean([b[5] for b in lines])) if lines else 0.0
        return {"text": text, "boxes": lines, "confidence": round(conf, 3), "engine": "rapidocr"}
    # tesseract
    pt = eng["obj"]
    data = pt.image_to_data(Image.fromarray(rgb), output_type=pt.Output.DICT)
    lines, confs = {}, []
    for i, w in enumerate(data["text"]):
        if not w.strip():
            continue
        key = (data["block_num"][i], data["line_num"][i])
        x, y, ww, hh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        b = lines.setdefault(key, [x, y, x + ww, y + hh, [], []])
        b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x + ww), max(b[3], y + hh)
        b[4].append(w)
        c = float(data["conf"][i])
        if c >= 0:
            b[5].append(c / 100)
            confs.append(c / 100)
    boxes = [[b[0], b[1], b[2], b[3], " ".join(b[4]), float(np.mean(b[5])) if b[5] else 0.0] for b in lines.values()]
    return {"text": "\n".join(b[4] for b in boxes), "boxes": boxes, "confidence": round(float(np.mean(confs)) if confs else 0.0, 3), "engine": "tesseract"}


def render_page(path: str, page_no: int, dpi: int = RENDER_DPI) -> np.ndarray:
    doc = fitz.open(path)
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    doc.close()
    return img.copy()


def extract(path: str, mime: str) -> dict:
    """Returns {pages:[{page,text,engine,confidence,boxes,width,height,deskew}], text, page_count, engines}."""
    pages = []
    if mime == "application/pdf" or path.lower().endswith(".pdf"):
        doc = fitz.open(path)
        scale = RENDER_DPI / 72.0
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            w, h = page.rect.width * scale, page.rect.height * scale
            if len(text.strip()) >= 25:
                words = page.get_text("words")
                lines = {}
                for x0, y0, x1, y1, wd, blk, ln, _ in words:
                    b = lines.setdefault((blk, ln), [x0, y0, x1, y1, []])
                    b[0], b[1], b[2], b[3] = min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)
                    b[4].append(wd)
                boxes = [[b[0] * scale, b[1] * scale, b[2] * scale, b[3] * scale, " ".join(b[4]), 1.0] for b in lines.values()]
                pages.append({"page": i, "text": text, "engine": "pymupdf", "confidence": 1.0, "boxes": boxes, "width": w, "height": h, "deskew": 0.0})
            else:
                pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
                rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
                pre, angle = preprocess(rgb)
                r = ocr_image(pre)
                pages.append({"page": i, "text": r["text"], "engine": r["engine"], "confidence": r["confidence"], "boxes": r["boxes"], "width": pix.width, "height": pix.height, "deskew": angle})
        doc.close()
    else:
        img = Image.open(path).convert("RGB")
        rgb = np.array(img)
        pre, angle = preprocess(rgb)
        r = ocr_image(pre)
        pages.append({"page": 1, "text": r["text"], "engine": r["engine"], "confidence": r["confidence"], "boxes": r["boxes"], "width": rgb.shape[1], "height": rgb.shape[0], "deskew": angle})
    return {"pages": pages, "text": "\n\n".join(p["text"] for p in pages), "page_count": len(pages), "engines": sorted({p["engine"] for p in pages})}


def page_png(path: str, mime: str, page_no: int, highlight=None, dpi: int = RENDER_DPI) -> bytes:
    """Rendered page as PNG with an optional [x0,y0,x1,y1] evidence highlight (coordinates at RENDER_DPI)."""
    if mime == "application/pdf" or path.lower().endswith(".pdf"):
        rgb = render_page(path, page_no, dpi)
    else:
        rgb = np.array(Image.open(path).convert("RGB"))
    img = Image.fromarray(rgb).convert("RGBA")
    if highlight:
        from PIL import ImageDraw
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        x0, y0, x1, y1 = [float(v) for v in highlight]
        pad = 6
        d.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], fill=(250, 204, 21, 90), outline=(220, 38, 38, 255), width=4)
        img = Image.alpha_composite(img, ov)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def detect_qr(path: str, mime: str):
    """Decode a QR code on the first page, if any (OpenCV)."""
    try:
        if mime == "application/pdf" or path.lower().endswith(".pdf"):
            rgb = render_page(path, 1, 200)
        else:
            rgb = np.array(Image.open(path).convert("RGB"))
        det = cv2.QRCodeDetector()
        data, pts, _ = det.detectAndDecode(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if data:
            return {"payload": data, "points": pts.reshape(-1, 2).tolist() if pts is not None else None}
    except Exception:
        pass
    return None
