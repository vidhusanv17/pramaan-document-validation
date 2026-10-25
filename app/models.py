from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    name = Column(String(128))
    designation = Column(String(128))
    role = Column(String(32), nullable=False)  # INSTITUTION | SCRUTINY_OFFICER | VERIFICATION_OFFICER | BUREAU_OFFICER | ADMIN
    region = Column(String(32), nullable=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=True)


class Institution(Base):
    """Institutional records already available in authorised AICTE systems (synthetic)."""
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    pid = Column(String(16), unique=True, index=True)
    name = Column(String(200), nullable=False)
    type = Column(String(32))
    state = Column(String(64))
    district = Column(String(64))
    region = Column(String(32))
    records = Column(JSON, default=dict)  # previous_eoa, approved_intake, programmes, accreditation, ter_paid, deficiencies, faculty_on_record, land_acres_on_record ...


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    app_no = Column(String(32), unique=True, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False)
    category = Column(String(32), nullable=False)  # EOA | NEW_INSTITUTION | INCREASE_INTAKE | NEW_COURSE | CLOSURE
    declared = Column(JSON, default=dict)
    status = Column(String(32), default="DRAFT")  # DRAFT | SUBMITTED | VALIDATED | UNDER_REVIEW | DEFICIENCIES_COMMUNICATED | CLEARED | ROUTED_FOR_INSPECTION
    risk_score = Column(Float, default=0.0)
    risk_band = Column(String(8), default="LOW")  # LOW | MEDIUM | HIGH
    anomaly_score = Column(Float, nullable=True)
    checklist_key = Column(String(32))
    summary = Column(JSON, default=dict)
    created_at = Column(DateTime)
    submitted_at = Column(DateTime, nullable=True)
    validated_at = Column(DateTime, nullable=True)
    processing_ms = Column(Integer, nullable=True)
    decision = Column(JSON, nullable=True)
    institution = relationship("Institution")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    filename = Column(String(200))
    path = Column(String(300))
    mime = Column(String(64))
    size = Column(Integer)
    doc_type_declared = Column(String(32), nullable=True)
    doc_type = Column(String(32), nullable=True)  # detected
    classification = Column(JSON, nullable=True)  # {label, confidence, top3}
    sha256 = Column(String(64), index=True)
    phash = Column(String(32), index=True)
    pages = Column(Integer, default=0)
    text = Column(Text)
    ocr = Column(JSON, nullable=True)  # per page: engine, confidence, chars
    fields = Column(JSON, default=dict)  # {field: {value, page, snippet, bbox, confidence}}
    metadata_ = Column("metadata", JSON, default=dict)
    forensics = Column(JSON, default=dict)
    verification_status = Column(String(24), default="NOT_APPLICABLE")  # VERIFIED | MISMATCH | EXPIRED | PENDING | SOURCE_UNAVAILABLE | MANUAL_REVIEW | NOT_APPLICABLE
    validity_status = Column(String(16), nullable=True)  # VALID | EXPIRED | EXPIRING | UNKNOWN
    uploaded_at = Column(DateTime)
    processed_at = Column(DateTime, nullable=True)
    ground_truth = Column(JSON, nullable=True)  # synthetic seed only: planted truth for evaluation metrics


class Finding(Base):
    __tablename__ = "findings"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    rule_id = Column(String(32))
    category = Column(String(32))  # COMPLETENESS | EXPIRY | CONSISTENCY | RECORD_MISMATCH | FORGERY_INDICATOR | DUPLICATE | VERIFICATION | INFRASTRUCTURE | QUALITY
    severity = Column(String(16))  # INFO | LOW | MEDIUM | HIGH | CRITICAL
    title = Column(String(200))
    explanation = Column(Text)
    evidence = Column(JSON, default=dict)  # {document, page, field, snippet, bbox, expected, observed, source}
    confidence = Column(Float, default=0.8)
    state = Column(String(16), default="OPEN")  # OPEN | ACCEPTED | DISMISSED | RESOLVED
    reviewed_by = Column(String(128), nullable=True)
    review_note = Column(Text, nullable=True)
    created_at = Column(DateTime)


class Verification(Base):
    __tablename__ = "verifications"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    source = Column(String(128))
    method = Column(String(32))  # API | QR | DIGITAL_SIGNATURE | PORTAL_LOOKUP | MANUAL
    request = Column(JSON, default=dict)
    response = Column(JSON, nullable=True)
    result = Column(String(24))
    detail = Column(Text)
    requested_at = Column(DateTime)
    responded_at = Column(DateTime, nullable=True)


class Checklist(Base):
    __tablename__ = "checklists"
    id = Column(Integer, primary_key=True)
    key = Column(String(32), unique=True)
    name = Column(String(128))
    version = Column(String(32))
    rules = Column(JSON, default=dict)
    updated_at = Column(DateTime)
    updated_by = Column(String(64))


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    kind = Column(String(48))
    severity = Column(String(16))
    application_id = Column(Integer, nullable=True)
    document_id = Column(Integer, nullable=True)
    title = Column(String(200))
    message = Column(Text)
    state = Column(String(16), default="OPEN")
    created_at = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime)
    actor = Column(String(128))
    actor_role = Column(String(32))
    action = Column(String(64), index=True)
    entity_type = Column(String(32))
    entity_id = Column(String(32))
    details = Column(JSON, default=dict)
    prev_hash = Column(String(64))
    hash = Column(String(64))
