"""Anomaly & potential-forgery indicators (preliminary, always human-verified): hashing & perceptual hashing
for duplicate detection, PDF metadata consistency, date irregularities, error-level analysis for JPEG scans,
and an IsolationForest outlier score across the corpus."""
import hashlib
import io
import re
from datetime import date, datetime

import fitz
import numpy as np
from PIL import Image, ImageChops

EDITING_SOFTWARE = re.compile(r"photoshop|gimp|paint\.net|pixlr|canva|snapseed|photopea|illustrator|inkscape", re.I)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash(img: Image.Image, size=16) -> str:
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return "".join("1" if b else "0" for b in bits)


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b)) if a and b and len(a) == len(b) else 999


def first_page_image(path, mime, dpi=60):
    if mime == "application/pdf" or path.lower().endswith(".pdf"):
        d = fitz.open(path)
        pix = d[0].get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        d.close()
        return img
    return Image.open(path).convert("RGB")


def _pdf_date(s):
    if not s:
        return None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", s)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0))
    except ValueError:
        return None


def pdf_metadata(path):
    with open(path, "rb") as f:
        raw = f.read()
    d = fitz.open(path)
    meta = d.metadata or {}
    out = {
        "producer": meta.get("producer"), "creator": meta.get("creator"), "author": meta.get("author"), "title": meta.get("title"),
        "creation_date": _pdf_date(meta.get("creationDate")), "mod_date": _pdf_date(meta.get("modDate")),
        "incremental_updates": max(0, raw.count(b"%%EOF") - 1), "has_signature": (b"/ByteRange" in raw and b"/Sig" in raw), "has_javascript": b"/JS" in raw or b"/JavaScript" in raw,
        "encrypted": d.is_encrypted, "page_count": d.page_count, "pdf_version": raw[:8].decode("latin1", "ignore"),
    }
    out["has_text_layer"] = any(len(p.get_text("text").strip()) > 25 for p in d)
    d.close()
    return out


def image_metadata(path):
    img = Image.open(path)
    exif = {}
    try:
        for k, v in (img.getexif() or {}).items():
            exif[str(k)] = str(v)[:80]
    except Exception:
        pass
    return {"format": img.format, "size": list(img.size), "mode": img.mode, "exif": exif, "software": exif.get("305"), "page_count": 1, "has_text_layer": False}


def ela(path, quality=90):
    """Error Level Analysis on JPEG/PNG scans: regions edited after the last save re-compress differently."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    re_img = Image.open(buf)
    diff = ImageChops.difference(img, re_img).convert("L")
    a = np.asarray(diff, dtype=np.float32)
    if a.size == 0:
        return None
    mean = float(a.mean())
    # block-wise: how uneven is the error level?
    h, w = a.shape
    bs = 64
    blocks = [a[y:y + bs, x:x + bs].mean() for y in range(0, h - bs + 1, bs) for x in range(0, w - bs + 1, bs)]
    blocks = np.array(blocks) if blocks else np.array([mean])
    nonflat = blocks[blocks > 0.5]
    cv = float(nonflat.std() / (nonflat.mean() + 1e-6)) if len(nonflat) > 3 else 0.0
    hot = float((blocks > (blocks.mean() + 3 * blocks.std() + 1e-6)).mean()) if len(blocks) > 3 else 0.0
    return {"mean": round(mean, 2), "max": round(float(a.max()), 1), "block_cv": round(cv, 3), "hot_fraction": round(hot, 4), "quality": quality}


def metadata_flags(meta, fields, today=None):
    """Rule-based indicators derived from metadata + extracted dates. Each flag has an explanation and evidence."""
    today = today or date.today()
    flags = []
    cre, mod = meta.get("creation_date"), meta.get("mod_date")
    if cre and mod and mod < cre:
        flags.append({"rule": "META_MOD_BEFORE_CREATION", "severity": "HIGH", "title": "Modification date precedes creation date",
                      "explanation": f"PDF ModDate {mod:%d %b %Y %H:%M} is earlier than CreationDate {cre:%d %b %Y %H:%M}; timestamps were edited or the file was re-assembled.",
                      "evidence": {"creation_date": cre.isoformat(), "mod_date": mod.isoformat()}, "confidence": 0.85})
    sw = " ".join(str(meta.get(k) or "") for k in ("producer", "creator", "software"))
    if EDITING_SOFTWARE.search(sw):
        flags.append({"rule": "META_IMAGE_EDITOR", "severity": "HIGH", "title": "Produced with an image-editing application",
                      "explanation": f"Producer/Creator field reads '{sw.strip()}'. Government certificates are normally generated by office/registry software or scanners; an image editor is a known alteration indicator.",
                      "evidence": {"producer": meta.get("producer"), "creator": meta.get("creator")}, "confidence": 0.8})
    if meta.get("incremental_updates", 0) >= 1 and meta.get("has_signature"):
        flags.append({"rule": "META_MODIFIED_AFTER_SIGNING", "severity": "CRITICAL", "title": "File modified after digital signature",
                      "explanation": f"{meta['incremental_updates']} incremental update(s) saved after the signature object; content may differ from what was signed.",
                      "evidence": {"incremental_updates": meta["incremental_updates"]}, "confidence": 0.9})
    elif meta.get("incremental_updates", 0) >= 2:
        flags.append({"rule": "META_INCREMENTAL_UPDATES", "severity": "LOW", "title": "Multiple incremental edits saved into the PDF",
                      "explanation": f"The file carries {meta['incremental_updates']} incremental updates (edit sessions after the original save).",
                      "evidence": {"incremental_updates": meta["incremental_updates"]}, "confidence": 0.6})
    if meta.get("has_javascript"):
        flags.append({"rule": "META_JAVASCRIPT", "severity": "MEDIUM", "title": "Embedded JavaScript in document", "explanation": "Certificates should not contain scripts.", "evidence": {}, "confidence": 0.9})
    issued = fields.get("issued_on", {}).get("value")
    valid = fields.get("valid_till", {}).get("value")
    try:
        d_issued = date.fromisoformat(issued) if issued else None
        d_valid = date.fromisoformat(valid) if valid else None
    except ValueError:
        d_issued = d_valid = None
    if d_issued and d_issued > today:
        flags.append({"rule": "DATE_FUTURE_ISSUE", "severity": "HIGH", "title": "Issue date is in the future", "explanation": f"Document states it was issued on {d_issued}, after today ({today}).",
                      "evidence": {"field": "issued_on", "page": fields["issued_on"].get("page"), "bbox": fields["issued_on"].get("bbox"), "snippet": fields["issued_on"].get("snippet")}, "confidence": 0.95})
    if d_issued and d_valid and d_valid < d_issued:
        flags.append({"rule": "DATE_ORDER", "severity": "HIGH", "title": "Validity ends before the issue date", "explanation": f"Valid till {d_valid} but issued on {d_issued}: an impossible date sequence, typical of an altered validity field.",
                      "evidence": {"field": "valid_till", "page": fields["valid_till"].get("page"), "bbox": fields["valid_till"].get("bbox"), "snippet": fields["valid_till"].get("snippet"), "issued_on": issued, "valid_till": valid}, "confidence": 0.9})
    if cre and d_issued and (cre.date() - d_issued).days > 400 and not meta.get("has_text_layer", True) is False:
        pass
    return flags


def features(doc):
    """Numeric feature vector for the outlier model."""
    f = doc.forensics or {}
    m = doc.metadata_ or {}
    o = doc.ocr or {}
    pages = max(1, doc.pages or 1)
    text_len = len(doc.text or "")
    return [
        pages, text_len / pages, float(o.get("confidence", 1.0) or 0), int(bool(m.get("has_text_layer", True))), int(m.get("incremental_updates", 0) or 0),
        int(bool(f.get("flags"))), len(f.get("flags", [])), float((f.get("ela") or {}).get("block_cv", 0) or 0), float((doc.classification or {}).get("confidence", 0) or 0),
        float(f.get("days_to_expiry", 0) or 0) / 365.0,
    ]


def outlier_scores(docs):
    """IsolationForest over the whole processed corpus -> {doc_id: score in [0,1], higher = more anomalous}."""
    if len(docs) < 8:
        return {}
    try:
        from sklearn.ensemble import IsolationForest
    except Exception:
        return {}
    X = np.array([features(d) for d in docs], dtype=float)
    model = IsolationForest(n_estimators=200, contamination=0.1, random_state=26261).fit(X)
    raw = -model.score_samples(X)  # higher = more abnormal
    lo, hi = float(raw.min()), float(raw.max())
    return {d.id: round(float((r - lo) / (hi - lo + 1e-9)), 3) for d, r in zip(docs, raw)}
