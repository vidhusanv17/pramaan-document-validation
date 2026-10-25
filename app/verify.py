"""Verification through original issuing authorities: QR payloads, digital-signature presence and
registry adapters. Records source, timestamp, request and response; distinguishes
VERIFIED / MISMATCH / EXPIRED / PENDING / SOURCE_UNAVAILABLE / MANUAL_REVIEW."""
import difflib
import re
from datetime import date, datetime

from . import mock_authority
from .models import Verification


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def name_similarity(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def text_similarity(a, b):
    a, b = re.sub(r"\s+", " ", (a or "").lower())[:4000], re.sub(r"\s+", " ", (b or "").lower())[:4000]
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).quick_ratio() if abs(len(a) - len(b)) > 400 else difflib.SequenceMatcher(None, a, b).ratio()


def verify_document(db, doc, app, inst, today=None):
    today = today or date.today()
    fields = doc.fields or {}
    out = []
    src = mock_authority.SOURCES.get(doc.doc_type)
    ref = (fields.get("ref_no") or {}).get("value") or (fields.get("transaction_id") or {}).get("value")
    qr = (doc.forensics or {}).get("qr")

    # 1) QR code pointing at an authority verification URL
    if qr and qr.get("payload"):
        m = re.search(r"/mock-authority/(\w+)/([^?\s]+)", qr["payload"])
        v = Verification(document_id=doc.id, application_id=app.id, source=(src or {}).get("name", "QR issuer"), method="QR", request={"payload": qr["payload"]}, requested_at=datetime.utcnow())
        if m:
            status, rec = mock_authority.lookup(m.group(1), m.group(2), inst.state)
            v.response = {"status": status, "record": rec}
            v.result, v.detail = _compare(status, rec, fields, inst, today, doc)
        else:
            v.result, v.detail = "MANUAL_REVIEW", "QR payload is not an authority verification URL"
        v.responded_at = datetime.utcnow()
        db.add(v)
        out.append(v)

    # 2) Digital signature presence (certificate chain validation needs the issuer CA - production)
    if (doc.metadata_ or {}).get("has_signature"):
        v = Verification(document_id=doc.id, application_id=app.id, source="Embedded PKCS#7 signature", method="DIGITAL_SIGNATURE", request={},
                         response={"present": True}, result="PENDING", detail="Signature object present; certificate-chain validation against the issuer CA is performed in production (eSign / CCA trust list).",
                         requested_at=datetime.utcnow(), responded_at=datetime.utcnow())
        db.add(v)
        out.append(v)

    # 3) Registry / API adapter for the document type
    if src:
        v = Verification(document_id=doc.id, application_id=app.id, source=src["name"], method=src["method"], request={"reference": ref, "state": inst.state, "institution": inst.name}, requested_at=datetime.utcnow())
        if not ref:
            v.result, v.detail, v.response = "MANUAL_REVIEW", "No reference number could be extracted from the document; verify manually with the issuer.", None
        else:
            status, rec = mock_authority.lookup(src["key"], ref, inst.state)
            v.response = {"status": status, "record": rec, "endpoint": f"/mock-authority/{src['key']}/{ref}"}
            v.result, v.detail = _compare(status, rec, fields, inst, today, doc)
        v.responded_at = datetime.utcnow()
        db.add(v)
        out.append(v)
    elif not out:
        v = Verification(document_id=doc.id, application_id=app.id, source="No authorised digital source for this document type", method="MANUAL", request={}, response=None,
                         result="MANUAL_REVIEW", detail="Issuer offers no API/QR/digital-signature channel; route to manual confirmation.", requested_at=datetime.utcnow(), responded_at=datetime.utcnow())
        db.add(v)
        out.append(v)

    # roll-up status for the document
    order = ["MISMATCH", "EXPIRED", "SOURCE_UNAVAILABLE", "MANUAL_REVIEW", "PENDING", "VERIFIED"]
    results = [v.result for v in out]
    if "VERIFIED" in results and not any(r in results for r in ("MISMATCH", "EXPIRED")):
        doc.verification_status = "VERIFIED"
    else:
        doc.verification_status = next((r for r in order if r in results), "NOT_APPLICABLE")
    db.flush()
    return out


def _compare(status, rec, fields, inst, today, doc):
    if status == "UNAVAILABLE":
        return "SOURCE_UNAVAILABLE", "Issuing authority service did not respond; retry scheduled and case routed for manual confirmation."
    if status == "NOT_FOUND":
        return "MANUAL_REVIEW", "Reference number not found in the issuer's records - confirm with the issuing authority."
    problems = []
    rec_name = rec.get("institution")
    if rec_name and name_similarity(rec_name, inst.name) < 0.8:
        problems.append(f"issued to '{rec_name}', not '{inst.name}'")
    doc_valid = (fields.get("valid_till") or {}).get("value")
    rec_valid = rec.get("valid_till")
    if rec_valid and doc_valid and rec_valid != doc_valid:
        problems.append(f"validity at source {rec_valid} differs from document {doc_valid}")
    if rec.get("amount") and (fields.get("amount") or {}).get("value") and abs(float(rec["amount"]) - float(fields["amount"]["value"])) > 1:
        problems.append(f"amount at source Rs {rec['amount']:,} differs from document Rs {fields['amount']['value']:,}")
    if rec.get("status") and rec["status"].upper() in ("REVOKED", "CANCELLED", "FAILED"):
        problems.append(f"source status is {rec['status']}")
    if problems:
        return "MISMATCH", "Mismatch with issuing-authority record: " + "; ".join(problems) + "."
    if rec_valid:
        try:
            if date.fromisoformat(rec_valid) < today:
                return "EXPIRED", f"Issuer confirms the document but its validity ended on {rec_valid}."
        except ValueError:
            pass
    return "VERIFIED", "Details match the issuing authority's record" + (f" (valid till {rec_valid})" if rec_valid else "") + "."
