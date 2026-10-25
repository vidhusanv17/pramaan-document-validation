import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import audit, classify, mock_authority, ocr, pipeline, verify
from .auth import create_token, get_current_user, hash_pw, require_roles
from .db import DOCS_DIR, get_db
from .models import Alert, Application, AuditLog, Checklist, Document, Finding, Institution, User, Verification
from .util import row

router = APIRouter(prefix="/api")
OFFICERS = ("SCRUTINY_OFFICER", "VERIFICATION_OFFICER", "BUREAU_OFFICER", "ADMIN")


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db=Depends(get_db)):
    u = db.query(User).filter(User.username == body.username).first()
    if not u or u.password_hash != hash_pw(body.password):
        raise HTTPException(401, "Invalid credentials")
    audit.record(db, u.name, "LOGIN", "user", u.username, {}, u.role)
    db.commit()
    return {"token": create_token(u), "user": _user(u, db)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db=Depends(get_db)):
    return _user(user, db)


@router.get("/auth/demo-users")
def demo_users(db=Depends(get_db)):
    return [{"username": u.username, "name": u.name, "designation": u.designation, "role": u.role, "password": "demo123"} for u in db.query(User).order_by(User.id).all()]


def _user(u, db):
    d = row(u, exclude=("password_hash",))
    if u.institution_id:
        d["institution"] = row(db.get(Institution, u.institution_id))
    return d


def _scope(q, user):
    if user.role == "INSTITUTION":
        q = q.filter(Application.institution_id == user.institution_id)
    return q


# ------------------------------------------------------------------ dashboard & metrics
@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db=Depends(get_db)):
    apps = _scope(db.query(Application), user).all()
    ids = [a.id for a in apps]
    findings = db.query(Finding).filter(Finding.application_id.in_(ids)).all() if ids else []
    docs = db.query(Document).filter(Document.application_id.in_(ids)).all() if ids else []
    verifs = db.query(Verification).filter(Verification.application_id.in_(ids)).all() if ids else []
    open_f = [f for f in findings if f.state == "OPEN"]
    return {
        "as_of": datetime.utcnow().isoformat(), "ocr": ocr.status(),
        "kpis": {"applications": len(apps), "validated": sum(1 for a in apps if a.status == "VALIDATED"), "high_risk": sum(1 for a in apps if a.risk_band == "HIGH"), "medium_risk": sum(1 for a in apps if a.risk_band == "MEDIUM"),
                 "low_risk": sum(1 for a in apps if a.risk_band == "LOW"), "documents": len(docs), "pages": sum(d.pages or 0 for d in docs), "findings_open": len(open_f),
                 "critical_open": sum(1 for f in open_f if f.severity == "CRITICAL"), "verified_docs": sum(1 for d in docs if d.verification_status == "VERIFIED"),
                 "mismatch_docs": sum(1 for d in docs if d.verification_status == "MISMATCH"), "manual_review_docs": sum(1 for d in docs if d.verification_status in ("MANUAL_REVIEW", "SOURCE_UNAVAILABLE", "PENDING")),
                 "avg_processing_s": round(sum(a.processing_ms or 0 for a in apps) / max(1, len(apps)) / 1000, 1), "ocr_pages": sum(1 for d in docs for p in ((d.ocr or {}).get("pages") or []) if p.get("engine") not in ("pymupdf", None)),
                 "decided": sum(1 for a in apps if a.decision)},
        "findings_by_category": dict(Counter(f.category for f in findings)), "findings_by_severity": dict(Counter(f.severity for f in findings)),
        "verification_results": dict(Counter(v.result for v in verifs)), "verification_methods": dict(Counter(v.method for v in verifs)),
        "doc_types": dict(Counter(d.doc_type for d in docs)), "risk_distribution": dict(Counter(a.risk_band for a in apps)),
        "queue": [_app_brief(a, db) for a in sorted(apps, key=lambda a: -(a.risk_score or 0))[:6]],
        "alerts": [row(a) for a in db.query(Alert).filter(Alert.state == "OPEN").order_by(Alert.id.desc()).limit(8).all()] if user.role != "INSTITUTION" else [],
    }


EXPECT = {"EXPIRED": ["CHK-EXPIRED"], "TOO_OLD": ["CHK-TOO-OLD"], "NAME_MISMATCH": ["CON-NAME"], "AREA_SHORTFALL": ["INF-AREA"], "FACULTY_COUNT_DIFFERS": ["CON-FACULTY"],
          "SOURCE_UNAVAILABLE": ["VER-UNAVAILABLE"], "DUPLICATE_FILE": ["DUP-SHA256"], "VERIFICATION_MISMATCH": ["VER-MISMATCH"], "TAMPERED_METADATA": ["META_MOD_BEFORE_CREATION", "META_IMAGE_EDITOR"],
          "REF_NOT_FOUND": ["VER-MANUAL"], "DATE_ORDER": ["DATE_ORDER"], "WRONG_HEAD": ["QLT-WRONG-HEAD"], "EXPIRING": ["CHK-EXPIRING"]}


@router.get("/metrics")
def metrics(user: User = Depends(require_roles(*OFFICERS)), db=Depends(get_db)):
    """Evaluation against the synthetic corpus' planted ground truth (seed only)."""
    docs = db.query(Document).filter(Document.ground_truth != None).all()  # noqa: E711
    cls_ok = sum(1 for d in docs if d.doc_type == (d.ground_truth or {}).get("doc_type"))
    fields = {"ref_no": [0, 0], "issued_on": [0, 0], "valid_till": [0, 0]}
    for d in docs:
        gt = d.ground_truth or {}
        for k in fields:
            if gt.get(k):
                fields[k][1] += 1
                got = ((d.fields or {}).get(k) or {}).get("value")
                if k == "ref_no":
                    ok = got and gt[k].upper().replace(" ", "") in str(got).upper().replace(" ", "")
                else:
                    ok = got == gt[k]
                fields[k][0] += 1 if ok else 0
    planted_total = planted_hit = 0
    misses = []
    for d in docs:
        rules = {f.rule_id for f in db.query(Finding).filter(Finding.document_id == d.id).all()}
        for tag in (d.ground_truth or {}).get("planted", []):
            if tag == "SCANNED_OCR":
                planted_total += 1
                hit = any(p.get("engine") not in ("pymupdf", None) for p in ((d.ocr or {}).get("pages") or []))
            elif tag == "QR_VERIFIED":
                planted_total += 1
                hit = db.query(Verification).filter(Verification.document_id == d.id, Verification.method == "QR", Verification.result == "VERIFIED").count() > 0
            else:
                planted_total += 1
                hit = bool(rules & set(EXPECT.get(tag, [])))
            planted_hit += 1 if hit else 0
            if not hit:
                misses.append({"document": d.filename, "planted": tag})
    clean_docs = [d for d in docs if not (d.ground_truth or {}).get("planted")]
    fp = sum(1 for d in clean_docs for f in db.query(Finding).filter(Finding.document_id == d.id, Finding.category.in_(["FORGERY_INDICATOR", "DUPLICATE"]), Finding.severity.in_(["HIGH", "CRITICAL"])).all())
    apps = db.query(Application).all()
    return {"documents_evaluated": len(docs), "classification_accuracy": round(cls_ok / max(1, len(docs)), 3),
            "field_extraction": {k: {"correct": v[0], "total": v[1], "accuracy": round(v[0] / max(1, v[1]), 3)} for k, v in fields.items()},
            "planted_anomalies": {"total": planted_total, "detected": planted_hit, "recall": round(planted_hit / max(1, planted_total), 3), "misses": misses},
            "high_severity_forgery_flags_on_clean_docs": fp, "clean_documents": len(clean_docs),
            "avg_processing_s_per_application": round(sum(a.processing_ms or 0 for a in apps) / max(1, len(apps)) / 1000, 1), "ocr": ocr.status(),
            "note": "Synthetic corpus; figures demonstrate the evaluation harness, not field accuracy on real AICTE documents."}


# ------------------------------------------------------------------ applications
def _app_brief(a, db):
    inst = db.get(Institution, a.institution_id)
    d = row(a, exclude=("declared",))
    s = a.summary or {}
    d.update({"institution_name": inst.name, "institution_pid": inst.pid, "institution_type": inst.type, "state": inst.state, "documents": s.get("documents", 0), "findings": s.get("findings", 0),
              "by_severity": s.get("by_severity", {}), "completeness_pct": s.get("completeness_pct"), "verification": s.get("verification", {}), "checklist_name": (pipeline.load_checklists(db).get(a.category) or {}).get("name")})
    return d


@router.get("/applications")
def applications(status: Optional[str] = None, risk: Optional[str] = None, q: Optional[str] = None, user: User = Depends(get_current_user), db=Depends(get_db)):
    qry = _scope(db.query(Application), user)
    if status:
        qry = qry.filter(Application.status.in_(status.split(",")))
    if risk:
        qry = qry.filter(Application.risk_band.in_(risk.split(",")))
    out = [_app_brief(a, db) for a in qry.all()]
    if q:
        ql = q.lower()
        out = [x for x in out if ql in x["app_no"].lower() or ql in x["institution_name"].lower() or ql in x["institution_pid"].lower()]
    return sorted(out, key=lambda x: -(x["risk_score"] or 0))


class NewApp(BaseModel):
    institution_id: Optional[int] = None
    category: str
    declared: dict = {}


@router.post("/applications")
def create_application(body: NewApp, user: User = Depends(get_current_user), db=Depends(get_db)):
    inst_id = user.institution_id if user.role == "INSTITUTION" else body.institution_id
    inst = db.get(Institution, inst_id) if inst_id else None
    if not inst:
        raise HTTPException(422, "institution_id required")
    a = Application(app_no=f"1-2026-{4600 + db.query(Application).count() + 1:05d}", institution_id=inst.id, category=body.category, declared=body.declared, status="DRAFT", created_at=datetime.utcnow())
    db.add(a)
    db.flush()
    audit.record(db, user.name, "APPLICATION_CREATED", "application", a.app_no, {"category": body.category, "institution": inst.name}, user.role)
    db.commit()
    return _app_brief(a, db)


@router.post("/applications/{app_id}/documents")
async def upload(app_id: int, files: List[UploadFile] = File(...), doc_type: Optional[str] = Form(None), user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    folder = DOCS_DIR / a.app_no
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        ext = Path(f.filename or "upload").suffix.lower()
        if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"):
            raise HTTPException(422, f"Unsupported file type {ext}; upload PDF or image scans")
        safe = "".join(ch for ch in (f.filename or "upload") if ch.isalnum() or ch in "._- ")[:120]
        path = folder / f"{int(datetime.utcnow().timestamp())}_{safe}"
        with path.open("wb") as fh:
            shutil.copyfileobj(f.file, fh)
        mime = "application/pdf" if ext == ".pdf" else ("image/png" if ext == ".png" else "image/jpeg")
        d = Document(application_id=a.id, filename=safe, path=str(path), mime=mime, size=path.stat().st_size, doc_type_declared=doc_type or None, uploaded_at=datetime.utcnow())
        db.add(d)
        db.flush()
        pipeline.process_document(db, d)
        audit.record(db, user.name, "DOCUMENT_UPLOADED", "document", d.id, {"filename": safe, "sha256": d.sha256, "detected": d.doc_type, "app_no": a.app_no}, user.role)
        out.append(_doc_brief(d))
    if a.status == "DRAFT":
        a.status = "DRAFT"
    db.commit()
    return out


@router.post("/applications/{app_id}/validate")
def validate(app_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    if not db.query(Document).filter(Document.application_id == a.id).count():
        raise HTTPException(422, "Upload at least one document before validation")
    if a.status == "DRAFT":
        a.status = "SUBMITTED"
        a.submitted_at = datetime.utcnow()
    pipeline.validate_application(db, a, actor=user.name, actor_role=user.role)
    return report(app_id, user, db)


def _doc_brief(d):
    x = row(d, exclude=("text", "ground_truth", "path"))
    x["label"] = classify.DOC_TYPES.get(d.doc_type, d.doc_type)
    x["text_preview"] = (d.text or "")[:600]
    return x


@router.get("/applications/{app_id}")
def report(app_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    d = _app_brief(a, db)
    d["declared"] = a.declared
    d["institution"] = row(db.get(Institution, a.institution_id))
    d["documents"] = [_doc_brief(x) for x in db.query(Document).filter(Document.application_id == a.id).order_by(Document.id).all()]
    fq = db.query(Finding).filter(Finding.application_id == a.id)
    if user.role == "INSTITUTION":  # institutions see rectifiable issues, not forensic indicators
        fq = fq.filter(Finding.category.in_(["COMPLETENESS", "EXPIRY", "QUALITY", "CONSISTENCY", "INFRASTRUCTURE"]))
    d["findings"] = [row(x) for x in fq.order_by(Finding.severity.desc(), Finding.id).all()]
    d["verifications"] = [row(x) for x in db.query(Verification).filter(Verification.application_id == a.id).order_by(Verification.id).all()] if user.role != "INSTITUTION" else []
    d["summary"] = a.summary
    d["audit"] = [row(x) for x in db.query(AuditLog).filter(AuditLog.entity_id == a.app_no).order_by(AuditLog.id.desc()).limit(20).all()]
    d["checklist_rules"] = pipeline.load_checklists(db).get(a.category)
    d["ground_truth"] = {x.id: x.ground_truth for x in db.query(Document).filter(Document.application_id == a.id).all() if x.ground_truth} if user.role == "ADMIN" else None
    return d


class DecisionIn(BaseModel):
    action: str  # CLEAR | COMMUNICATE_DEFICIENCIES | ROUTE_INSPECTION | HOLD
    note: Optional[str] = None


@router.post("/applications/{app_id}/decision")
def decision(app_id: int, body: DecisionIn, user: User = Depends(require_roles("SCRUTINY_OFFICER", "BUREAU_OFFICER")), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    if body.action not in ("CLEAR", "COMMUNICATE_DEFICIENCIES", "ROUTE_INSPECTION", "HOLD"):
        raise HTTPException(422, "Unknown action")
    if not body.note or len(body.note.strip()) < 10:
        raise HTTPException(422, "A recorded note (>= 10 characters) is mandatory for every decision")
    open_crit = db.query(Finding).filter(Finding.application_id == a.id, Finding.severity == "CRITICAL", Finding.state == "OPEN").count()
    if body.action == "CLEAR" and open_crit:
        raise HTTPException(409, f"{open_crit} CRITICAL finding(s) are still unreviewed; accept or dismiss each with a note before clearing")
    a.decision = {"action": body.action, "note": body.note, "by": user.name, "role": user.role, "at": datetime.utcnow().isoformat()}
    a.status = {"CLEAR": "CLEARED", "COMMUNICATE_DEFICIENCIES": "DEFICIENCIES_COMMUNICATED", "ROUTE_INSPECTION": "ROUTED_FOR_INSPECTION", "HOLD": "UNDER_REVIEW"}[body.action]
    audit.record(db, user.name, "DECISION_" + body.action, "application", a.app_no, {"note": body.note, "risk_score": a.risk_score}, user.role)
    db.commit()
    return report(app_id, user, db)


def _404():
    raise HTTPException(404, "Not found")


# ------------------------------------------------------------------ documents / evidence
@router.get("/documents/{doc_id}/file")
def doc_file(doc_id: int, db=Depends(get_db)):
    d = db.get(Document, doc_id) or _404()
    return FileResponse(d.path, media_type=d.mime, filename=d.filename)


@router.get("/documents/{doc_id}/page/{page_no}.png")
def doc_page(doc_id: int, page_no: int, highlight: Optional[str] = Query(None, description="x0,y0,x1,y1 at 150 dpi"), db=Depends(get_db)):
    d = db.get(Document, doc_id) or _404()
    hl = [float(v) for v in highlight.split(",")] if highlight else None
    png = ocr.page_png(d.path, d.mime, max(1, page_no), hl)
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


@router.get("/documents/{doc_id}")
def doc_detail(doc_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    d = db.get(Document, doc_id) or _404()
    a = db.get(Application, d.application_id)
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    x = _doc_brief(d)
    x["text"] = d.text
    x["findings"] = [row(f) for f in db.query(Finding).filter(Finding.document_id == d.id).all()]
    x["verifications"] = [row(v) for v in db.query(Verification).filter(Verification.document_id == d.id).all()]
    return x


@router.post("/documents/{doc_id}/verify")
def reverify(doc_id: int, user: User = Depends(require_roles("VERIFICATION_OFFICER", "SCRUTINY_OFFICER", "BUREAU_OFFICER")), db=Depends(get_db)):
    d = db.get(Document, doc_id) or _404()
    a = db.get(Application, d.application_id)
    inst = db.get(Institution, a.institution_id)
    db.query(Verification).filter(Verification.document_id == d.id).delete()
    vs = verify.verify_document(db, d, a, inst)
    audit.record(db, user.name, "DOCUMENT_REVERIFIED", "document", d.id, {"results": [v.result for v in vs], "app_no": a.app_no}, user.role)
    db.commit()
    return {"verification_status": d.verification_status, "verifications": [row(v) for v in vs]}


class ReviewIn(BaseModel):
    state: str  # ACCEPTED | DISMISSED | RESOLVED
    note: Optional[str] = None


@router.post("/findings/{fid}/review")
def review(fid: int, body: ReviewIn, user: User = Depends(require_roles(*OFFICERS)), db=Depends(get_db)):
    f = db.get(Finding, fid) or _404()
    if body.state not in ("ACCEPTED", "DISMISSED", "RESOLVED", "OPEN"):
        raise HTTPException(422)
    if body.state == "DISMISSED" and (not body.note or len(body.note.strip()) < 5):
        raise HTTPException(422, "Dismissing a system finding requires a recorded reason")
    f.state = body.state
    f.reviewed_by = user.name
    f.review_note = body.note
    a = db.get(Application, f.application_id)
    audit.record(db, user.name, "FINDING_" + body.state, "finding", f.id, {"rule": f.rule_id, "title": f.title, "note": body.note, "app_no": a.app_no}, user.role)
    # recompute risk from open+accepted findings
    fs = db.query(Finding).filter(Finding.application_id == a.id).all()
    a.risk_score = round(min(100.0, sum(pipeline.SEVERITY_WEIGHT.get(x.severity, 0) for x in fs if x.state in ("OPEN", "ACCEPTED")) + 15 * (a.anomaly_score or 0)), 1)
    a.risk_band = "HIGH" if a.risk_score >= 40 else ("MEDIUM" if a.risk_score >= 15 else "LOW")
    db.commit()
    return {"finding": row(f), "risk_score": a.risk_score, "risk_band": a.risk_band}


# ------------------------------------------------------------------ institutions, checklists, alerts, audit
@router.get("/institutions")
def institutions(user: User = Depends(get_current_user), db=Depends(get_db)):
    q = db.query(Institution)
    if user.role == "INSTITUTION":
        q = q.filter(Institution.id == user.institution_id)
    return [row(i) for i in q.order_by(Institution.name).all()]


@router.get("/checklists")
def checklists(user: User = Depends(get_current_user), db=Depends(get_db)):
    return {"items": [row(c) for c in db.query(Checklist).order_by(Checklist.id).all()], "doc_types": classify.DOC_TYPES}


class ChecklistIn(BaseModel):
    rules: dict


@router.put("/checklists/{key}")
def put_checklist(key: str, body: ChecklistIn, user: User = Depends(require_roles("ADMIN")), db=Depends(get_db)):
    c = db.query(Checklist).filter(Checklist.key == key).first() or _404()
    c.rules = body.rules
    n = int((c.version or "v1").rsplit("v", 1)[-1] or 1) + 1
    c.version = f"APH-2026-27.v{n}"
    c.updated_at = datetime.utcnow()
    c.updated_by = user.name
    audit.record(db, user.name, "CHECKLIST_UPDATED", "checklist", key, {"version": c.version}, user.role)
    db.commit()
    return row(c)


@router.get("/alerts")
def alerts(user: User = Depends(require_roles(*OFFICERS)), db=Depends(get_db)):
    return [row(a) for a in db.query(Alert).order_by(Alert.id.desc()).limit(200).all()]


@router.get("/audit")
def audit_log(limit: int = Query(150, le=1000), action: Optional[str] = None, user: User = Depends(get_current_user), db=Depends(get_db)):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    return {"items": [row(e) for e in q.order_by(AuditLog.id.desc()).limit(limit).all()], "chain": audit.verify_chain(db)}


@router.get("/ocr/status")
def ocr_status():
    return ocr.status()


@router.get("/registry")
def registry(user: User = Depends(require_roles(*OFFICERS))):
    return mock_authority.registry_summary()
