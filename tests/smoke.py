"""API smoke test against a running PRAMAAN server: python tests/smoke.py [base_url]"""
import io
import json
import sys
from collections import Counter

import httpx

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8061"
c = httpx.Client(base_url=B, timeout=180)


def login(u):
    r = c.post("/api/auth/login", json={"username": u, "password": "demo123"})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


out = {"health": c.get("/api/health").json()}
H = login("scrutiny")
d = c.get("/api/dashboard", headers=H).json()
out["kpis"] = d["kpis"]
out["findings_by_category"] = d["findings_by_category"]
out["verification_results"] = d["verification_results"]
apps = c.get("/api/applications", headers=H).json()
out["queue"] = [{k: a[k] for k in ("app_no", "institution_name", "risk_score", "risk_band", "findings", "completeness_pct")} for a in apps]
if apps:
    rep = c.get(f"/api/applications/{apps[0]['id']}", headers=H).json()
    out["top_report"] = {"app": rep["app_no"], "findings": [(f["severity"], f["rule_id"], f["title"][:70]) for f in rep["findings"]][:14],
                         "verifications": [(v["method"], v["result"]) for v in rep["verifications"]], "checklist": [(r["label"], r["status"]) for r in rep["summary"]["checklist"]]}
    # evidence page png with highlight
    f_ev = next((f for f in rep["findings"] if f.get("evidence", {}).get("bbox")), None)
    if f_ev:
        bb = ",".join(str(round(v)) for v in f_ev["evidence"]["bbox"])
        r = c.get(f"/api/documents/{f_ev['document_id']}/page/{f_ev['evidence']['page']}.png?highlight={bb}")
        out["evidence_png"] = {"status": r.status_code, "bytes": len(r.content), "finding": f_ev["title"][:60]}
    # review a finding (dismiss requires note)
    f0 = rep["findings"][0]
    r = c.post(f"/api/findings/{f0['id']}/review", json={"state": "DISMISSED"}, headers=H)
    out["dismiss_without_note"] = r.status_code
    r = c.post(f"/api/findings/{f0['id']}/review", json={"state": "ACCEPTED", "note": "Confirmed on inspection of the document"}, headers=H)
    out["accept"] = {"status": r.status_code, "risk": r.json().get("risk_score")}
    # decision guard: clear with open critical
    r = c.post(f"/api/applications/{apps[0]['id']}/decision", json={"action": "CLEAR", "note": "Clearing for test purposes only"}, headers=H)
    out["clear_with_open_critical"] = {"status": r.status_code, "detail": r.json().get("detail", "")[:90]}
    r = c.post(f"/api/applications/{apps[0]['id']}/decision", json={"action": "COMMUNICATE_DEFICIENCIES", "note": "Deficiency letter to issue for expired/mismatched documents"}, headers=H)
    out["decision"] = {"status": r.status_code, "app_status": r.json().get("status")}
out["metrics"] = c.get("/api/metrics", headers=H).json()
out["registry"] = c.get("/api/registry", headers=H).json()
out["audit_chain"] = c.get("/api/audit?limit=1", headers=H).json()["chain"]

# institution upload + validate flow with a freshly generated PDF
inst = login("inst.coastal")
a = c.post("/api/applications", json={"category": "EOA", "declared": {"intake": 300, "faculty_count": 60, "built_up_area_sqm": 9200, "land_acres": 10.5, "library_volumes": 9000}}, headers=inst).json()
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
buf = io.BytesIO()
cv = canvas.Canvas(buf, pagesize=A4)
cv.setFont("Helvetica", 11)
y = 800
for ln in ["KARNATAKA FIRE AND EMERGENCY SERVICES", "NO OBJECTION CERTIFICATE (FIRE SAFETY)", "NOC No: KSFES/MNG/2026/0777", "Date of issue: 01-09-2026", "Issued to: Coastal Engineering College, Mangaluru",
           "The premises comply with fire safety norms. Fire fighting installations are in working order.", "This No Objection Certificate is valid till: 31-08-2027", "Divisional Fire Officer"]:
    cv.drawString(60, y, ln)
    y -= 22
cv.showPage()
cv.save()
files = [("files", ("new_fire_noc.pdf", buf.getvalue(), "application/pdf"))]
r = c.post(f"/api/applications/{a['id']}/documents", files=files, headers=inst)
out["upload"] = {"status": r.status_code, "detected": [(x["doc_type"], x["classification"]["confidence"], x.get("validity_status"), list((x.get("fields") or {}).keys())) for x in r.json()] if r.status_code == 200 else r.text[:200]}
r = c.post(f"/api/applications/{a['id']}/validate", headers=inst)
rep = r.json()
out["validate_new"] = {"status": r.status_code, "risk": rep.get("risk_score"), "band": rep.get("risk_band"), "findings": [(f["severity"], f["rule_id"]) for f in rep.get("findings", [])][:12], "institution_sees_verifications": len(rep.get("verifications", []))}
print(json.dumps(out, indent=1, default=str))
