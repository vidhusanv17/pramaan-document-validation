"""Simulated issuing-authority registries (fire services, NBA, universities, sub-registrar, AICTE payments,
banks). In production each adapter calls the authority's authorised API / DigiLocker / portal; here the
registry is seeded JSON so the verification workflow (verified / mismatch / expired / pending / source
unavailable / manual review) can be demonstrated end to end. Exposed over HTTP too, under /mock-authority."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .db import DATA_DIR

REG_FILE = DATA_DIR / "mock_authority.json"
_registry = {"records": {}, "unavailable_sources": []}

SOURCES = {
    "FIRE_NOC": {"name": "State Fire & Rescue Services", "method": "API", "key": "fire"},
    "NBA_ACCREDITATION": {"name": "National Board of Accreditation (NBA)", "method": "API", "key": "nba"},
    "UNIVERSITY_AFFILIATION": {"name": "Affiliating University", "method": "API", "key": "university"},
    "LEASE_DEED": {"name": "Sub-Registrar (State Registration Dept.)", "method": "PORTAL_LOOKUP", "key": "registrar"},
    "LAND_DOCUMENT": {"name": "Sub-Registrar (State Registration Dept.)", "method": "PORTAL_LOOKUP", "key": "registrar"},
    "TER_RECEIPT": {"name": "AICTE payment gateway", "method": "API", "key": "aicte_payments"},
    "BANK_FDR": {"name": "Issuing bank (FDR confirmation)", "method": "API", "key": "bank"},
}


def load():
    global _registry
    if REG_FILE.exists():
        _registry = json.loads(REG_FILE.read_text(encoding="utf-8"))
    return _registry


def save(reg):
    global _registry
    _registry = reg
    REG_FILE.write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")


def put(source_key, ref, record):
    reg = _registry
    reg["records"].setdefault(source_key, {})[ref.upper()] = record


def lookup(source_key, ref, state=None):
    """Returns (status, record). status: OK | NOT_FOUND | UNAVAILABLE."""
    reg = _registry or load()
    if source_key in reg.get("unavailable_sources", []) or (state and f"{source_key}:{state}" in reg.get("unavailable_sources", [])):
        return "UNAVAILABLE", None
    rec = reg.get("records", {}).get(source_key, {}).get((ref or "").upper())
    return ("OK", rec) if rec else ("NOT_FOUND", None)


router = APIRouter(prefix="/mock-authority", tags=["mock issuing authorities"])


@router.get("/{source_key}/{ref:path}")
def http_lookup(source_key: str, ref: str, state: str = None):
    status, rec = lookup(source_key, ref, state)
    if status == "UNAVAILABLE":
        raise HTTPException(503, f"{source_key} verification service unavailable")
    if status == "NOT_FOUND":
        raise HTTPException(404, "No record for this reference")
    return {"source": source_key, "reference": ref.upper(), "record": rec}


@router.get("")
def registry_summary():
    reg = _registry or load()
    return {"sources": {k: len(v) for k, v in reg.get("records", {}).items()}, "unavailable_sources": reg.get("unavailable_sources", [])}
