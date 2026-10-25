"""Synthetic document generator (reportlab) for the demo corpus: letterheads, bodies, signatures, optional
QR codes, 'scanned' PNG variants (skew + noise) and deliberate tampering (metadata / altered dates)."""
import io
import random
from datetime import date, timedelta

import fitz
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

W, H = A4


def _fmt(d: date):
    return d.strftime("%d-%m-%Y")


def body_for(doc_type, c):
    """Returns (letterhead, title, lines, signature) for a context dict c."""
    inst, state, ref = c["inst"], c["state"], c["ref"]
    issued, valid = c.get("issued"), c.get("valid")
    if doc_type == "FIRE_NOC":
        return (f"{state.upper()} FIRE AND RESCUE SERVICES", "NO OBJECTION CERTIFICATE (FIRE SAFETY)",
                [f"NOC No: {ref}", f"Date of issue: {_fmt(issued)}", "", f"Issued to: {inst}", f"Premises: Academic Block A, Block B and Hostel, {c.get('district', '')}, {state}",
                 "", "This is to certify that the above premises have been inspected and found to comply with the fire prevention",
                 "and fire safety norms. Fire-fighting installations (hydrants, extinguishers, sprinklers, alarm) are in working order.",
                 f"This No Objection Certificate is valid till: {_fmt(valid)}", "", "Conditions: The institution shall maintain all installations and conduct periodic drills."],
                "Divisional Fire Officer")
    if doc_type == "LEASE_DEED":
        return ("OFFICE OF THE SUB-REGISTRAR", "REGISTERED LEASE DEED",
                [f"Document No: {ref}", f"Executed on: {_fmt(issued)}", "", f"Lessor: {c.get('lessor', 'Sri Lakshmi Educational Trust')}", f"Lessee: {inst}",
                 f"Period of lease: {c.get('years', 30)} years from {_fmt(issued)}", f"Schedule of property: land measuring {c.get('acres', 3.2)} acres with buildings, Survey No {c.get('survey', '112/2A')}, {c.get('district', '')}, {state}",
                 "", "The lessor hereby demises unto the lessee the schedule property for educational purposes on the rent and terms stated herein.",
                 f"Valid till: {_fmt(valid)}", "Stamp duty paid. Registered at the office of the Sub-Registrar."],
                "Sub-Registrar")
    if doc_type == "AFFIDAVIT":
        return ("NON-JUDICIAL STAMP PAPER OF RS 100", "AFFIDAVIT",
                [f"Deponent: {c.get('deponent', 'Dr. S. Raghavan')}, Chairman of the Trust running {inst}", f"Dated: {_fmt(issued)}", "",
                 "I, the deponent, do hereby solemnly affirm and declare that the information furnished in the application to AICTE",
                 "for the academic year 2026-27 is true and correct; that the institution shall abide by the regulations of AICTE and the",
                 "Approval Process Handbook; and that no information has been concealed.", "", "Verification: Verified at the place and date above that the contents are true to my knowledge.",
                 f"Sworn before me on {_fmt(issued)}.", "Notary Public"],
                "Deponent")
    if doc_type == "BUILDING_SAFETY":
        return ("REGISTERED CHARTERED STRUCTURAL ENGINEER", "STRUCTURAL STABILITY CERTIFICATE",
                [f"Certificate No: {ref}", f"Date: {_fmt(issued)}", "", f"This is to certify that the building of {inst}, {c.get('district', '')}, {state}",
                 f"with total built-up area of {c.get('built_up', 9000):,} sq.m (RCC framed structure, G+{c.get('floors', 3)}) has been inspected by me and is",
                 "structurally safe and stable for its intended use as an educational institution.", f"This certificate is valid for 3 years, valid till {_fmt(valid)}.", "",
                 f"Engineer registration no: SE/{state[:2].upper()}/2011/0{c.get('n', 42)}"],
                "Chartered Structural Engineer")
    if doc_type == "NBA_ACCREDITATION":
        return ("NATIONAL BOARD OF ACCREDITATION", "CERTIFICATE OF ACCREDITATION",
                [f"Certificate No: {ref}", f"Date of issue: {_fmt(issued)}", "", f"This is to certify that the programme {c.get('programme', 'B.Tech - Computer Science & Engineering')}",
                 f"offered by {inst}, {state}", f"is accredited for {c.get('years', 3)} years (Tier II).", f"Accreditation valid up to: {_fmt(valid)}", "",
                 "Issued under the NBA accreditation framework."], "Member Secretary, NBA")
    if doc_type == "LAND_DOCUMENT":
        return ("OFFICE OF THE SUB-REGISTRAR", "SALE DEED",
                [f"Document No: {ref}", f"Executed on: {_fmt(issued)}", "", f"Vendor: {c.get('vendor', 'Sri K. Narayanan and others')}", f"Purchaser: {inst} (represented by its Trust)",
                 f"Land measuring {c.get('acres', 5.0)} acres, Survey No {c.get('survey', '88/1B')}, {c.get('district', '')}, {state}", "Boundaries: East - road, West - canal, North - Survey 88/1A, South - Survey 89.",
                 "Encumbrance certificate: nil. Consideration received in full. Registered at the office of the Sub-Registrar."], "Sub-Registrar")
    if doc_type == "OCCUPANCY_CERT":
        return (f"{c.get('district', 'MUNICIPAL')} MUNICIPAL CORPORATION", "OCCUPANCY CERTIFICATE",
                [f"Permit No: {ref}", f"Date: {_fmt(issued)}", "", f"The building constructed by {inst} at {c.get('district', '')}, {state} as per the sanctioned plan",
                 f"(built-up area {c.get('built_up', 9000):,} sq.m, G+{c.get('floors', 3)}) has been completed and is fit for occupation as an educational building.",
                 "Completion certificate issued accordingly."], "Commissioner")
    if doc_type == "TER_RECEIPT":
        return ("ALL INDIA COUNCIL FOR TECHNICAL EDUCATION - ONLINE PAYMENT", "PAYMENT RECEIPT - TER CHARGES",
                [f"Transaction ID: {ref}", f"Paid on: {_fmt(issued)}", f"Received from: {inst}", f"Amount: Rs {c.get('amount', 300000):,}", "Purpose: Technical Education Regulatory (TER) charges, AY 2026-27",
                 "Mode: Net banking", "Status: Successful"], "System generated receipt")
    if doc_type == "FACULTY_LIST":
        rows = [f"{i + 1}. {n}    {d}    {q}    Date of joining {dj}" for i, (n, d, q, dj) in enumerate(c.get("faculty", []))]
        return (inst.upper(), "LIST OF FACULTY MEMBERS (AY 2026-27)", [f"Date: {_fmt(issued)}", "Sl. Name    Designation    Qualification    Date of joining", ""] + rows, "Principal")
    if doc_type == "UNIVERSITY_AFFILIATION":
        return (c.get("university", f"{state} TECHNOLOGICAL UNIVERSITY").upper(), "PROVISIONAL AFFILIATION ORDER",
                [f"Letter No: {ref}", f"Date: {_fmt(issued)}", "", f"The Syndicate has granted provisional affiliation to {inst} for the academic year 2026-27",
                 f"for the programmes listed in the application with the intake approved by AICTE. Valid till: {_fmt(valid)}", "Subject to compliance with university regulations."], "Registrar")
    if doc_type == "BANK_FDR":
        return (c.get("bank", "STATE BANK OF INDIA"), "FIXED DEPOSIT RECEIPT",
                [f"FDR No: {ref}", f"Date: {_fmt(issued)}", f"Principal amount: Rs {c.get('amount', 5000000):,}", f"Maturity date: {_fmt(valid)}", f"In the joint name of {inst} and AICTE",
                 "Lien marked in favour of AICTE as security deposit."], "Branch Manager")
    if doc_type == "BUILDING_PLAN":
        return (f"{c.get('district', 'TOWN')} PLANNING AUTHORITY", "APPROVED BUILDING PLAN - SUMMARY SHEET",
                [f"Plan approval No: {ref}", f"Date: {_fmt(issued)}", f"Applicant: {inst}", f"Total built-up area: {c.get('built_up', 9000):,} sq.m", f"Floors: Ground + {c.get('floors', 3)}",
                 "Schedule: classrooms, laboratories, library, seminar hall, administrative block (drawings attached, scale 1:100)."], "Town Planning Officer")
    return ("DOCUMENT", doc_type, ["(generic document)"], "Signatory")


def make_pdf(path, doc_type, ctx, qr_url=None, metadata=None):
    head, title, lines, signer = body_for(doc_type, ctx)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    c.setAuthor(head.title())
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W / 2, H - 22 * mm, head)
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, H - 27 * mm, "(synthetic document generated for the PRAMAAN prototype - not a real certificate)")
    c.setLineWidth(0.6)
    c.line(20 * mm, H - 30 * mm, W - 20 * mm, H - 30 * mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, H - 40 * mm, title)
    c.setFont("Helvetica", 10)
    y = H - 52 * mm
    for ln in lines:
        if y < 30 * mm:  # paginate long documents (e.g. faculty lists)
            c.setFont("Helvetica", 8)
            c.drawCentredString(W / 2, 15 * mm, f"{title} - continued")
            c.showPage()
            c.setFont("Helvetica", 10)
            y = H - 25 * mm
        c.drawString(22 * mm, y, ln[:118])
        y -= 6 * mm
    if y < 40 * mm:
        c.showPage()
        c.setFont("Helvetica", 10)
        y = H - 25 * mm
    y -= 10 * mm
    c.drawString(22 * mm, y, "Sd/-")
    c.drawString(22 * mm, y - 6 * mm, signer)
    if qr_url:
        import qrcode
        img = qrcode.make(qr_url).convert("RGB")
        ib = io.BytesIO()
        img.save(ib, format="PNG")
        ib.seek(0)
        from reportlab.lib.utils import ImageReader
        c.drawImage(ImageReader(ib), W - 55 * mm, 22 * mm, 32 * mm, 32 * mm)
        c.setFont("Helvetica", 7)
        c.drawString(W - 55 * mm, 19 * mm, "Scan to verify with issuer")
    c.showPage()
    c.save()
    data = buf.getvalue()
    if metadata:
        d = fitz.open(stream=data, filetype="pdf")
        md = d.metadata or {}
        md.update(metadata)
        d.set_metadata(md)
        data = d.tobytes(incremental=False)
        d.close()
    with open(path, "wb") as f:
        f.write(data)
    return path


def tamper_incremental(path, metadata):
    """Simulate editing after creation: write metadata via an incremental update (adds a second %%EOF)."""
    d = fitz.open(path)
    md = d.metadata or {}
    md.update(metadata)
    d.set_metadata(md)
    d.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    d.close()


def pdf_to_scan_png(pdf_path, png_path, angle=1.4, dpi=150, noise=6, seed=1):
    """Render a PDF page and degrade it like a phone/flatbed scan: rotation, grey cast, noise, JPEG-ish blur."""
    d = fitz.open(pdf_path)
    pix = d[0].get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    d.close()
    img = img.rotate(angle, expand=True, fillcolor=(236, 233, 225), resample=Image.BICUBIC)
    a = np.asarray(img).astype(np.int16)
    rnd = np.random.default_rng(seed)
    a = a - 10 + rnd.normal(0, noise, a.shape)
    a = np.clip(a, 0, 255).astype(np.uint8)
    out = Image.fromarray(a)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=78)
    buf.seek(0)
    Image.open(buf).convert("RGB").save(png_path, "PNG")
    return png_path
