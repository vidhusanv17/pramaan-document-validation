"""Validation pipeline: per-document processing (hash, OCR, classify, extract, forensics) and
application-level checks (checklist completeness, expiry, cross-document consistency, institutional-record
cross-check, infrastructure norms, duplicates, issuing-authority verification, outlier scoring) -> evidence-
linked findings and a risk score. All outputs are decision support; nothing here takes a regulatory action."""
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image

from . import audit, classify, extract, forensics, ocr, verify
from .db import BASE_DIR
from .models import Alert, Application, Checklist, Document, Finding, Institution, Verification

CHECKLIST_FILE = BASE_DIR / "rules" / "checklists.json"
SEVERITY_WEIGHT = {"CRITICAL": 25, "HIGH": 12, "MEDIUM": 6, "LOW": 2, "INFO": 0}


def load_checklists(db):
    rows = db.query(Checklist).all()
    if rows:
        return {r.key: r.rules for r in rows}
    data = json.loads(Path(CHECKLIST_FILE).read_text(encoding="utf-8"))
    for key, rules in data["checklists"].items():
        db.add(Checklist(key=key, name=rules["name"], version="APH-2026-27.v1", rules=rules, updated_at=datetime.utcnow(), updated_by="system"))
    db.add(Checklist(key="_norms", name="Infrastructure norms & validity periods", version="APH-2026-27.v1",
                     rules={"infrastructure_norms": data["infrastructure_norms"], "document_validity": data["document_validity"], "_note": data["_note"]}, updated_at=datetime.utcnow(), updated_by="system"))
    db.commit()
    return {r.key: r.rules for r in db.query(Checklist).all()}


# ------------------------------------------------------------------ per document
def process_document(db, doc: Document, today=None):
    today = today or date.today()
    t0 = time.time()
    path, mime = doc.path, doc.mime or ""
    doc.sha256 = forensics.sha256_file(path)
    try:
        doc.phash = forensics.dhash(forensics.first_page_image(path, mime))
    except Exception:
        doc.phash = None
    is_pdf = mime == "application/pdf" or path.lower().endswith(".pdf")
    meta = forensics.pdf_metadata(path) if is_pdf else forensics.image_metadata(path)
    doc.metadata_ = json.loads(json.dumps(meta, default=str))
    res = ocr.extract(path, mime)
    doc.pages = res["page_count"]
    doc.text = res["text"]
    doc.ocr = {"engines": res["engines"], "confidence": round(sum(p["confidence"] for p in res["pages"]) / max(1, len(res["pages"])), 3),
               "pages": [{k: v for k, v in p.items() if k != "text"} for p in res["pages"]]}
    cls = classify.classify(doc.text)
    doc.classification = cls
    doc.doc_type = cls["label"] if cls["label"] != "UNREADABLE" else (doc.doc_type_declared or "UNREADABLE")
    doc.fields = extract.extract_fields(doc.text, res["pages"], doc.doc_type)
    f = {"flags": forensics.metadata_flags(meta, doc.fields, today)}
    if not is_pdf:
        f["ela"] = forensics.ela(path)
        if f["ela"] and f["ela"]["block_cv"] > 1.6 and f["ela"]["hot_fraction"] > 0.01:
            f["flags"].append({"rule": "IMG_ELA_INCONSISTENT", "severity": "MEDIUM", "title": "Uneven error levels in scanned image",
                               "explanation": f"Error-level analysis shows localised regions re-compressed differently from the rest of the scan (block CV {f['ela']['block_cv']}); possible pasted/edited region.",
                               "evidence": {"ela": f["ela"]}, "confidence": 0.55})
    f["qr"] = ocr.detect_qr(path, mime)
    vt = (doc.fields.get("valid_till") or {}).get("value")
    if vt:
        d = date.fromisoformat(vt)
        f["days_to_expiry"] = (d - today).days
        doc.validity_status = "EXPIRED" if d < today else ("EXPIRING" if (d - today).days <= 90 else "VALID")
    else:
        doc.validity_status = "UNKNOWN"
    doc.forensics = f
    doc.processed_at = datetime.utcnow()
    doc.forensics["processing_ms"] = int((time.time() - t0) * 1000)
    db.flush()
    return doc


# ------------------------------------------------------------------ application
def _f(app, rule_id, category, severity, title, explanation, evidence=None, document=None, confidence=0.8):
    return Finding(application_id=app.id, document_id=document.id if document else None, rule_id=rule_id, category=category, severity=severity,
                   title=title, explanation=explanation, evidence=evidence or {}, confidence=confidence, state="OPEN", created_at=datetime.utcnow())


def _ev(doc, field=None, extra=None):
    e = {"document_id": doc.id, "filename": doc.filename, "doc_type": doc.doc_type}
    if field and doc.fields and field in doc.fields:
        fv = doc.fields[field]
        e.update({"field": field, "page": fv.get("page"), "bbox": fv.get("bbox"), "snippet": fv.get("snippet"), "value": fv.get("value")})
    if extra:
        e.update(extra)
    return e


def validate_application(db, app: Application, actor="system", actor_role=None, today=None):
    today = today or date.today()
    t0 = time.time()
    inst = db.get(Institution, app.institution_id)
    rec = inst.records or {}
    declared = app.declared or {}
    lists = load_checklists(db)
    checklist = lists.get(app.category) or lists.get("EOA")
    norms = lists.get("_norms", {}).get("infrastructure_norms", {})
    validity_days = lists.get("_norms", {}).get("document_validity", {})
    app.checklist_key = app.category

    docs = db.query(Document).filter(Document.application_id == app.id).order_by(Document.id).all()
    for d in docs:
        if not d.processed_at:
            process_document(db, d, today)

    # preserve reviewer decisions on re-validation
    prev = {(x.rule_id, x.document_id, x.title): (x.state, x.reviewed_by, x.review_note) for x in db.query(Finding).filter(Finding.application_id == app.id).all() if x.state != "OPEN"}
    db.query(Finding).filter(Finding.application_id == app.id).delete()
    db.query(Verification).filter(Verification.application_id == app.id).delete()
    F = []
    by_type = {}
    for d in docs:
        by_type.setdefault(d.doc_type, []).append(d)

    # ---- 1. checklist completeness, validity, age
    checklist_rows = []
    for req in checklist.get("required_documents", []):
        dt = req["doc_type"]
        present = by_type.get(dt, []) or (by_type.get(req.get("alternative"), []) if req.get("alternative") else [])
        label = classify.DOC_TYPES.get(dt, dt)
        if not present:
            if req.get("required") and not (dt == "NBA_ACCREDITATION" and not declared.get("accreditation_claimed")):
                F.append(_f(app, "CHK-MISSING", "COMPLETENESS", "HIGH", f"Missing: {label}", f"The {checklist['name']} checklist requires a {label}; none of the uploaded documents was classified as this type.", {"doc_type": dt, "checklist": app.category}))
                checklist_rows.append({"doc_type": dt, "label": label, "status": "MISSING", "required": True})
            else:
                checklist_rows.append({"doc_type": dt, "label": label, "status": "NOT_REQUIRED" if not req.get("required") else "OPTIONAL", "required": bool(req.get("required"))})
            continue
        d = present[0]
        st = "PRESENT"
        if req.get("must_be_valid"):
            if d.validity_status == "EXPIRED":
                F.append(_f(app, "CHK-EXPIRED", "EXPIRY", "CRITICAL", f"Expired: {label}", f"{label} expired on {d.fields['valid_till']['value']}; a currently valid document is required.", _ev(d, "valid_till"), d, 0.95))
                st = "EXPIRED"
            elif d.validity_status == "EXPIRING":
                F.append(_f(app, "CHK-EXPIRING", "EXPIRY", "LOW", f"Expiring soon: {label}", f"{label} is valid only till {d.fields['valid_till']['value']} ({d.forensics.get('days_to_expiry')} days); renewal will be due during the approval year.", _ev(d, "valid_till"), d, 0.9))
                st = "EXPIRING"
            elif d.validity_status == "UNKNOWN":
                F.append(_f(app, "CHK-NO-VALIDITY", "COMPLETENESS", "MEDIUM", f"Validity date not found: {label}", f"No 'valid till' date could be read from the {label}; confirm validity manually.", _ev(d), d, 0.7))
                st = "VALIDITY_UNKNOWN"
        if req.get("max_age_days") and (d.fields.get("issued_on") or {}).get("value"):
            age = (today - date.fromisoformat(d.fields["issued_on"]["value"])).days
            if age > req["max_age_days"]:
                F.append(_f(app, "CHK-TOO-OLD", "EXPIRY", "MEDIUM", f"{label} older than {req['max_age_days']} days", f"Issued {age} days ago ({d.fields['issued_on']['value']}); the checklist accepts documents up to {req['max_age_days']} days old.", _ev(d, "issued_on"), d, 0.9))
                st = "TOO_OLD" if st == "PRESENT" else st
        if d.doc_type_declared and d.doc_type_declared != d.doc_type and (d.classification or {}).get("confidence", 0) >= 0.6:
            F.append(_f(app, "QLT-WRONG-HEAD", "QUALITY", "MEDIUM", f"Uploaded under wrong head: {d.filename}", f"Declared as {classify.DOC_TYPES.get(d.doc_type_declared, d.doc_type_declared)} but the content reads as {label} (confidence {d.classification['confidence']}).", _ev(d, extra={"declared": d.doc_type_declared, "detected": d.doc_type}), d, d.classification["confidence"]))
        checklist_rows.append({"doc_type": dt, "label": label, "status": st, "required": bool(req.get("required")), "document_id": d.id, "verify": bool(req.get("verify"))})

    # ---- 2. readability / quality
    for d in docs:
        conf = (d.ocr or {}).get("confidence", 1.0)
        if d.doc_type == "UNREADABLE" or len(d.text or "") < 50:
            F.append(_f(app, "QLT-UNREADABLE", "QUALITY", "MEDIUM", f"Unreadable upload: {d.filename}", "OCR could not recover usable text (blank, too dark or too small). Request a clearer scan.", _ev(d), d, 0.9))
        elif conf < 0.6:
            F.append(_f(app, "QLT-LOW-OCR", "QUALITY", "LOW", f"Low OCR confidence: {d.filename}", f"Average OCR confidence {conf}; extracted values from this document should be confirmed manually.", _ev(d), d, 0.8))

    # ---- 3. cross-document consistency (names, PIDs, identifiers, dates)
    for d in docs:
        nm = (d.fields.get("institution_name") or {}).get("value")
        if nm and verify.name_similarity(nm, inst.name) < 0.72 and d.doc_type != "FACULTY_LIST":
            F.append(_f(app, "CON-NAME", "CONSISTENCY", "HIGH", f"Institution name differs in {classify.DOC_TYPES.get(d.doc_type, d.doc_type)}", f"Document names '{nm}' while the application is from '{inst.name}' (similarity {round(verify.name_similarity(nm, inst.name), 2)}). Could be a document of another institution.", _ev(d, "institution_name", {"expected": inst.name}), d, 0.8))
        pid = (d.fields.get("pid") or {}).get("value")
        if pid and pid != inst.pid:
            F.append(_f(app, "CON-PID", "CONSISTENCY", "CRITICAL", f"Permanent ID mismatch in {d.filename}", f"Document carries PID {pid}; the applicant's PID is {inst.pid}.", _ev(d, "pid", {"expected": inst.pid}), d, 0.95))
    refs = {}
    for d in docs:
        r = (d.fields.get("ref_no") or {}).get("value")
        if r:
            refs.setdefault(r, []).append(d)
    for r, ds in refs.items():
        if len(ds) > 1 and len({x.doc_type for x in ds}) > 1:
            F.append(_f(app, "CON-REF-REUSED", "CONSISTENCY", "MEDIUM", f"Same reference number on different document types", f"Reference {r} appears on {', '.join(classify.DOC_TYPES.get(x.doc_type, x.doc_type) for x in ds)}.", {"ref_no": r, "documents": [x.id for x in ds]}, ds[0], 0.7))

    # ---- 4. institutional records cross-check (records already in authorised AICTE systems)
    record_rows = []
    def rr(item, record, declared_v, status, note=None):
        record_rows.append({"item": item, "on_record": record, "declared": declared_v, "status": status, "note": note})
    if rec.get("approved_intake") is not None and declared.get("intake") is not None:
        ok = declared["intake"] <= rec["approved_intake"] or app.category in ("INCREASE_INTAKE", "NEW_COURSE")
        rr("Total intake", rec["approved_intake"], declared["intake"], "MATCH" if declared["intake"] == rec["approved_intake"] else ("PROPOSED_INCREASE" if ok else "EXCEEDS"))
        if not ok:
            F.append(_f(app, "REC-INTAKE", "RECORD_MISMATCH", "HIGH", "Declared intake exceeds approved intake", f"Application declares {declared['intake']} seats but the approved intake on record is {rec['approved_intake']} and no increase has been applied for.", {"declared": declared["intake"], "on_record": rec["approved_intake"]}, None, 0.95))
    if rec.get("ter_paid") is not None:
        rr("TER charges", "Paid" if rec["ter_paid"] else "Not paid", "-", "MATCH" if rec["ter_paid"] else "PENDING")
        if not rec["ter_paid"]:
            F.append(_f(app, "REC-TER", "RECORD_MISMATCH", "HIGH", "TER payment not reflected in AICTE records", "Payment status on record is 'not paid'; the uploaded receipt (if any) must be verified with the payment gateway before processing.", {"on_record": "NOT_PAID"}, None, 0.85))
    if rec.get("previous_eoa"):
        rr("Previous EoA", rec["previous_eoa"].get("status"), "-", "MATCH" if rec["previous_eoa"].get("status") == "GRANTED" else "ATTENTION", rec["previous_eoa"].get("note"))
        if rec["previous_eoa"].get("status") == "GRANTED_WITH_DEFICIENCIES":
            F.append(_f(app, "REC-DEFICIENCY", "RECORD_MISMATCH", "MEDIUM", "Unresolved deficiencies from previous approval cycle", rec["previous_eoa"].get("note") or "Previous EoA was granted with deficiencies; compliance evidence should be checked.", {"on_record": rec["previous_eoa"]}, None, 0.8))
    if declared.get("accreditation_claimed"):
        acc = rec.get("accreditation") or {}
        rr("NBA accreditation", acc.get("status", "none on record"), "Claimed", "MATCH" if acc.get("status") == "ACCREDITED" else "UNSUPPORTED")
        if acc.get("status") != "ACCREDITED" and not by_type.get("NBA_ACCREDITATION"):
            F.append(_f(app, "REC-ACCREDITATION", "RECORD_MISMATCH", "MEDIUM", "Accreditation claimed but not on record", "No NBA accreditation is recorded for this institution and no certificate was uploaded.", {"declared": True}, None, 0.8))
    fl = by_type.get("FACULTY_LIST", [])
    if fl and (fl[0].fields.get("faculty_count") or {}).get("value") is not None and declared.get("faculty_count") is not None:
        cnt = fl[0].fields["faculty_count"]["value"]
        rr("Faculty count", rec.get("faculty_on_record"), declared.get("faculty_count"), "MATCH" if abs(cnt - declared["faculty_count"]) <= 1 else "DIFFERS", f"{cnt} rows in uploaded list")
        if abs(cnt - declared["faculty_count"]) > 1:
            F.append(_f(app, "CON-FACULTY", "CONSISTENCY", "MEDIUM", "Faculty count differs from uploaded list", f"Application declares {declared['faculty_count']} faculty; the uploaded list contains {cnt} entries.", _ev(fl[0], "faculty_count", {"declared": declared["faculty_count"]}), fl[0], 0.8))

    # ---- 5. infrastructure compliance assistance (configurable norms)
    infra_rows = []
    intake = declared.get("proposed_intake") or declared.get("intake") or rec.get("approved_intake") or 0
    per_student = (norms.get("built_up_area_sqm_per_student") or {}).get(inst.type)
    area_doc = next((d for t in ("BUILDING_PLAN", "BUILDING_SAFETY", "OCCUPANCY_CERT") for d in by_type.get(t, []) if (d.fields.get("built_up_area") or {}).get("value")), None)
    area_val = (area_doc.fields["built_up_area"]["value"]["value"] if area_doc else declared.get("built_up_area_sqm"))
    if per_student and intake:
        req_area = round(per_student * intake)
        ok = area_val is not None and area_val >= req_area
        infra_rows.append({"item": "Built-up area (sq m)", "norm": f">= {req_area} ({per_student} x {intake} students)", "declared": declared.get("built_up_area_sqm"), "evidence": area_val, "source": area_doc.filename if area_doc else "declared only", "status": "OK" if ok else ("SHORTFALL" if area_val is not None else "NO_EVIDENCE")})
        if area_val is not None and not ok:
            F.append(_f(app, "INF-AREA", "INFRASTRUCTURE", "HIGH", "Built-up area below norm for the intake", f"Evidence shows {area_val} sq m against a requirement of about {req_area} sq m for {intake} students ({per_student} sq m/student). Flag for additional evidence or physical inspection.", _ev(area_doc, "built_up_area", {"required": req_area}) if area_doc else {"declared": area_val, "required": req_area}, area_doc, 0.8))
        elif area_val is None:
            F.append(_f(app, "INF-AREA-EVIDENCE", "INFRASTRUCTURE", "MEDIUM", "No built-up area evidence", "Neither the building plan nor the structural certificate states the built-up area; request evidence.", {}, None, 0.7))
    min_land = (norms.get("min_land_acres") or {}).get(inst.type)
    land_doc = next((d for t in ("LAND_DOCUMENT", "LEASE_DEED") for d in by_type.get(t, []) if (d.fields.get("land_area") or d.fields.get("area") or {}).get("value")), None)
    land_val = None
    if land_doc:
        lv = (land_doc.fields.get("land_area") or land_doc.fields.get("area"))["value"]
        land_val = lv["value"] if lv.get("unit") == "acres" else round(lv["value"] / 4046.86, 2)
    if min_land:
        ok = land_val is not None and land_val >= min_land
        infra_rows.append({"item": "Land (acres)", "norm": f">= {min_land}", "declared": declared.get("land_acres"), "evidence": land_val, "source": land_doc.filename if land_doc else "-", "status": "OK" if ok else ("SHORTFALL" if land_val is not None else "NO_EVIDENCE")})
        if land_val is not None and not ok:
            F.append(_f(app, "INF-LAND", "INFRASTRUCTURE", "HIGH", "Land area below norm", f"Land document shows {land_val} acres; the norm for a {inst.type} institution is {min_land} acres.", _ev(land_doc, "land_area" if "land_area" in land_doc.fields else "area", {"required": min_land}), land_doc, 0.8))
    ratio = norms.get("faculty_student_ratio")
    fac = declared.get("faculty_count") or rec.get("faculty_on_record")
    if ratio and fac and intake:
        need = -(-intake * 4 // ratio)  # 4-year programmes approximated; configurable
        infra_rows.append({"item": "Faculty (1:" + str(ratio) + ")", "norm": f">= {need}", "declared": declared.get("faculty_count"), "evidence": (fl[0].fields.get("faculty_count") or {}).get("value") if fl else None, "source": fl[0].filename if fl else "-", "status": "OK" if fac >= need else "SHORTFALL"})
        if fac < need:
            F.append(_f(app, "INF-FACULTY", "INFRASTRUCTURE", "MEDIUM", "Faculty strength below prescribed ratio", f"{fac} faculty for an intake of {intake} (approx. {need} required at 1:{ratio}).", {"declared": fac, "required": need}, None, 0.75))
    if norms.get("library_volumes_min") and declared.get("library_volumes") is not None:
        ok = declared["library_volumes"] >= norms["library_volumes_min"]
        infra_rows.append({"item": "Library volumes", "norm": f">= {norms['library_volumes_min']}", "declared": declared["library_volumes"], "evidence": None, "source": "declared", "status": "OK" if ok else "SHORTFALL"})
        if not ok:
            F.append(_f(app, "INF-LIBRARY", "INFRASTRUCTURE", "LOW", "Library volumes below norm", f"Declared {declared['library_volumes']} volumes against {norms['library_volumes_min']}.", {"declared": declared["library_volumes"]}, None, 0.7))

    # ---- 7. verification through issuing authorities
    verifs = []
    to_verify = {row["doc_type"] for row in checklist.get("required_documents", []) if row.get("verify")}
    for d in docs:
        if d.doc_type in to_verify or (d.forensics or {}).get("qr") or (d.metadata_ or {}).get("has_signature"):
            vs = verify.verify_document(db, d, app, inst, today)
            verifs.extend(vs)
            for v in vs:
                label = classify.DOC_TYPES.get(d.doc_type, d.doc_type)
                if v.result == "MISMATCH":
                    F.append(_f(app, "VER-MISMATCH", "VERIFICATION", "CRITICAL", f"Issuer record does not match - {label}", v.detail + " Treat as a preliminary indicator; obtain confirmation from the issuing authority before any adverse action.", _ev(d, "valid_till" if "validity" in v.detail else ("amount" if "amount" in v.detail else "institution_name"), {"source": v.source, "method": v.method, "response": v.response}), d, 0.9))
                elif v.result == "EXPIRED":
                    F.append(_f(app, "VER-EXPIRED", "VERIFICATION", "HIGH", f"Issuer confirms expiry - {label}", v.detail, _ev(d, "valid_till", {"source": v.source}), d, 0.95))
                elif v.result == "SOURCE_UNAVAILABLE":
                    F.append(_f(app, "VER-UNAVAILABLE", "VERIFICATION", "INFO", f"Source unavailable - {label}", v.detail, _ev(d, extra={"source": v.source}), d, 0.9))
                elif v.result == "MANUAL_REVIEW" and v.method != "MANUAL":
                    F.append(_f(app, "VER-MANUAL", "VERIFICATION", "LOW", f"Manual confirmation needed - {label}", v.detail, _ev(d, "ref_no", {"source": v.source}), d, 0.8))
        else:
            d.verification_status = "NOT_APPLICABLE"

    # ---- 6. anomaly / forgery indicators + duplicates across the corpus
    for d in docs:
        for fl_ in (d.forensics or {}).get("flags", []):
            F.append(_f(app, fl_["rule"], "FORGERY_INDICATOR", fl_["severity"], f"{fl_['title']} - {classify.DOC_TYPES.get(d.doc_type, d.doc_type)}", fl_["explanation"] + " Preliminary indicator requiring human verification; not proof of forgery.", _ev(d, fl_.get("evidence", {}).get("field"), fl_.get("evidence")), d, fl_.get("confidence", 0.7)))
        if d.sha256:
            twins = db.query(Document).join(Application, Document.application_id == Application.id).filter(Document.sha256 == d.sha256, Document.id != d.id, Application.institution_id != inst.id).all()
            for t in twins:
                ta = db.get(Application, t.application_id)
                ti = db.get(Institution, ta.institution_id)
                mine = d.verification_status == "VERIFIED"
                F.append(_f(app, "DUP-SHA256", "DUPLICATE", "MEDIUM" if mine else "CRITICAL", f"Identical file submitted by another institution - {classify.DOC_TYPES.get(d.doc_type, d.doc_type)}",
                            f"SHA-256 {d.sha256[:16]}... matches '{t.filename}' in application {ta.app_no} of {ti.name}. The same certificate cannot belong to two institutions." + (" The issuing authority confirms THIS copy belongs to the applicant, so the other application is the suspect one." if mine else ""),
                            _ev(d, extra={"other_application": ta.app_no, "other_institution": ti.name, "other_document_id": t.id, "this_copy_verified": mine}), d, 0.98))
        if d.phash and d.doc_type not in ("AFFIDAVIT", "TER_RECEIPT", "FACULTY_LIST"):  # standard templates are legitimately alike
            near = [x for x in db.query(Document).join(Application, Document.application_id == Application.id).filter(Document.id != d.id, Application.institution_id != inst.id, Document.phash != None).all()  # noqa: E711
                    if forensics.hamming(x.phash, d.phash) <= 6 and x.sha256 != d.sha256 and verify.text_similarity(x.text, d.text) >= 0.95]
            for t in near[:2]:
                ta = db.get(Application, t.application_id)
                F.append(_f(app, "DUP-PHASH", "DUPLICATE", "MEDIUM", f"Visually near-identical document in another application", f"Perceptual hash within 4 bits of '{t.filename}' in {ta.app_no}; likely the same scan with minor edits.", _ev(d, extra={"other_application": ta.app_no, "other_document_id": t.id, "hamming": forensics.hamming(t.phash, d.phash)}), d, 0.7))
        r = (d.fields.get("ref_no") or {}).get("value")
        if r and not (d.sha256 and twins):
            for t in db.query(Document).join(Application, Document.application_id == Application.id).filter(Document.id != d.id, Application.institution_id != inst.id, Document.doc_type == d.doc_type).all():
                if ((t.fields or {}).get("ref_no") or {}).get("value") == r:
                    ta = db.get(Application, t.application_id)
                    F.append(_f(app, "DUP-REF", "DUPLICATE", "HIGH", f"Reference number already used by another institution", f"{classify.DOC_TYPES.get(d.doc_type, d.doc_type)} reference {r} also appears in application {ta.app_no}.", _ev(d, "ref_no", {"other_application": ta.app_no}), d, 0.85))
                    break

    # ---- 8. ML outlier score over the processed corpus
    all_docs = db.query(Document).filter(Document.processed_at != None).all()  # noqa: E711
    scores = forensics.outlier_scores(all_docs)
    for d in docs:
        if d.id in scores:
            fz = dict(d.forensics or {})
            fz["anomaly_score"] = scores[d.id]
            d.forensics = fz
            if scores[d.id] >= 0.85 and not any(x.document_id == d.id and x.category in ("FORGERY_INDICATOR", "DUPLICATE") for x in F):
                F.append(_f(app, "ML-OUTLIER", "FORGERY_INDICATOR", "LOW", f"Statistical outlier - {classify.DOC_TYPES.get(d.doc_type, d.doc_type)}", f"IsolationForest outlier score {scores[d.id]} (page density, OCR confidence, metadata and validity features differ from the corpus). Advisory only.", _ev(d, extra={"anomaly_score": scores[d.id]}), d, 0.5))
    app.anomaly_score = round(max([scores.get(d.id, 0) for d in docs] or [0]), 3)

    # ---- persist findings (restore reviewer states), risk score, summary
    for x in F:
        key = (x.rule_id, x.document_id, x.title)
        if key in prev:
            x.state, x.reviewed_by, x.review_note = prev[key]
        db.add(x)
    db.flush()
    open_f = [x for x in F if x.state in ("OPEN", "ACCEPTED")]
    score = sum(SEVERITY_WEIGHT.get(x.severity, 0) for x in open_f) + 15 * (app.anomaly_score or 0)
    app.risk_score = round(min(100.0, score), 1)
    app.risk_band = "HIGH" if app.risk_score >= 40 else ("MEDIUM" if app.risk_score >= 15 else "LOW")
    sev = {s: sum(1 for x in F if x.severity == s) for s in SEVERITY_WEIGHT}
    cat = {}
    for x in F:
        cat[x.category] = cat.get(x.category, 0) + 1
    vstat = {}
    for d in docs:
        vstat[d.verification_status] = vstat.get(d.verification_status, 0) + 1
    app.summary = {"documents": len(docs), "findings": len(F), "by_severity": sev, "by_category": cat, "checklist": checklist_rows, "records": record_rows, "infrastructure": infra_rows,
                   "verification": vstat, "completeness_pct": round(100 * sum(1 for r in checklist_rows if r["required"] and r["status"] not in ("MISSING",)) / max(1, sum(1 for r in checklist_rows if r["required"]))),
                   "ocr_engines": sorted({e for d in docs for e in ((d.ocr or {}).get("engines") or [])})}
    app.status = "VALIDATED" if app.status in ("DRAFT", "SUBMITTED", "VALIDATED") else app.status
    app.validated_at = datetime.utcnow()
    app.processing_ms = int((time.time() - t0) * 1000) + sum(int((d.forensics or {}).get("processing_ms", 0)) for d in docs)
    for x in F:
        if x.severity == "CRITICAL" and x.state == "OPEN":
            db.add(Alert(kind=x.category, severity="CRITICAL", application_id=app.id, document_id=x.document_id, title=f"{app.app_no}: {x.title}", message=x.explanation, created_at=datetime.utcnow()))
    audit.record(db, actor, "APPLICATION_VALIDATED", "application", app.app_no, {"findings": len(F), "risk_score": app.risk_score, "risk_band": app.risk_band, "by_severity": sev, "checklist": app.category, "documents": len(docs)}, actor_role)
    db.commit()
    return app
