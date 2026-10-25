"""Synthetic demo corpus: 10 institutions, 10 applications, ~60 generated documents with planted problems so
every detection path can be shown (all names/numbers are fictitious). Also seeds the mock issuing-authority
registry and demo users. Ground truth is stored per document for the evaluation metrics endpoint."""
import random
from datetime import date, datetime, timedelta

from . import audit, docgen, mock_authority, pipeline
from .auth import hash_pw
from .db import DOCS_DIR
from .models import Application, Document, Institution, User

INSTITUTIONS = [
    ("1-4471", "Nalanda Institute of Technology, Guntur", "Engineering", "Andhra Pradesh", "Guntur", "SOUTH_CENTRAL"),
    ("1-4502", "Coastal Engineering College, Mangaluru", "Engineering", "Karnataka", "Dakshina Kannada", "SOUTH_WEST"),
    ("1-4388", "Chola Institute of Technology, Thanjavur", "Engineering", "Tamil Nadu", "Thanjavur", "SOUTHERN"),
    ("1-4419", "Malabar Institute of Pharmacy, Kozhikode", "Pharmacy", "Kerala", "Kozhikode", "SOUTH_WEST"),
    ("1-4530", "Deccan College of Pharmacy, Hyderabad", "Pharmacy", "Telangana", "Hyderabad", "SOUTH_CENTRAL"),
    ("1-4611", "Sahyadri Polytechnic, Kolhapur", "Polytechnic", "Maharashtra", "Kolhapur", "WESTERN"),
    ("1-4622", "Saraswati Institute of Management Studies, Pune", "Management", "Maharashtra", "Pune", "WESTERN"),
    ("1-4815", "Ganga Valley Engineering College, Kanpur", "Engineering", "Uttar Pradesh", "Kanpur Nagar", "NORTHERN"),
    ("1-4901", "Hooghly College of Engineering, Howrah", "Engineering", "West Bengal", "Howrah", "EASTERN"),
    ("1-4820", "Aravalli School of Architecture, Jaipur", "Architecture", "Rajasthan", "Jaipur", "NORTH_WEST"),
]
USERS = [
    ("admin", "System Administrator", "Admin, Approval Bureau", "ADMIN", None),
    ("scrutiny", "Smt. K. Lakshmi", "Scrutiny Officer, Approval Bureau", "SCRUTINY_OFFICER", None),
    ("verifier", "Sh. R. Pillai", "Verification Officer (documents & issuers)", "VERIFICATION_OFFICER", None),
    ("bureau", "Sh. A. K. Verma", "Director, Approval Bureau", "BUREAU_OFFICER", None),
    ("inst.nalanda", "Registrar, Nalanda Institute of Technology", "Institution user", "INSTITUTION", "1-4471"),
    ("inst.coastal", "Registrar, Coastal Engineering College", "Institution user", "INSTITUTION", "1-4502"),
]
FACULTY_NAMES = ["Dr. A. Kumar", "Dr. B. Rao", "Ms. C. Devi", "Mr. D. Singh", "Dr. E. Nair", "Ms. F. Iyer", "Mr. G. Das", "Dr. H. Patel", "Ms. I. Reddy", "Mr. J. Khan", "Dr. K. Menon", "Ms. L. Bose", "Mr. M. Gupta", "Dr. N. Pillai", "Ms. O. Shah", "Mr. P. Verma", "Dr. Q. Joshi", "Ms. R. Rani", "Mr. S. Yadav", "Dr. T. Sen", "Ms. U. Mishra", "Mr. V. Roy", "Dr. W. Jain", "Ms. X. Thomas"]


def _faculty(n, rnd):
    des = ["Professor", "Associate Professor", "Assistant Professor"]
    return [(FACULTY_NAMES[i % len(FACULTY_NAMES)], des[min(2, i // 4)], rnd.choice(["Ph.D", "M.Tech", "M.E", "M.Pharm", "MBA"]), f"{rnd.randint(1, 28):02d}-0{rnd.randint(1, 9)}-20{rnd.randint(10, 24)}") for i in range(n)]


def seed(db):
    if db.query(Institution).count():
        return False
    rnd = random.Random(26261)
    today = date.today()
    insts = {}
    for pid, name, typ, state, district, region in INSTITUTIONS:
        inst = Institution(pid=pid, name=name, type=typ, state=state, district=district, region=region, records={
            "approved_intake": {"Engineering": 300, "Pharmacy": 160, "Polytechnic": 180, "Management": 120, "Architecture": 40}[typ],
            "programmes": {"Engineering": ["B.Tech CSE", "B.Tech ECE", "B.Tech ME"], "Pharmacy": ["B.Pharm", "D.Pharm"], "Polytechnic": ["Diploma CE", "Diploma ME", "Diploma CSE"], "Management": ["MBA"], "Architecture": ["B.Arch"]}[typ],
            "previous_eoa": {"year": "2025-26", "status": "GRANTED"}, "ter_paid": True, "faculty_on_record": {"Engineering": 62, "Pharmacy": 28, "Polytechnic": 34, "Management": 18, "Architecture": 12}[typ],
            "accreditation": {"status": "NONE"}, "land_acres_on_record": {"Engineering": 10.5, "Pharmacy": 2.4, "Polytechnic": 6.0, "Management": 2.0, "Architecture": 1.5}[typ]})
        db.add(inst)
        insts[pid] = inst
    db.flush()
    # record-level tweaks for scenarios
    insts["1-4388"].records = {**insts["1-4388"].records, "ter_paid": False, "previous_eoa": {"year": "2025-26", "status": "GRANTED_WITH_DEFICIENCIES", "note": "Faculty shortfall of 8 in ECE; undertaking given to recruit by Dec 2025"}}
    insts["1-4471"].records = {**insts["1-4471"].records, "accreditation": {"status": "ACCREDITED", "programmes": ["B.Tech CSE"], "valid_till": "2028-06-30"}}
    for uname, name, desig, role, pid in USERS:
        db.add(User(username=uname, password_hash=hash_pw("demo123"), name=name, designation=desig, role=role, institution_id=insts[pid].id if pid else None))
    db.flush()

    reg = {"records": {}, "unavailable_sources": ["fire:Kerala"]}
    mock_authority.save(reg)

    def new_app(inst, category, declared, days_ago):
        a = Application(app_no=f"1-2026-{4600 + db.query(Application).count() + 1:05d}", institution_id=inst.id, category=category, declared=declared, status="SUBMITTED",
                        created_at=datetime.utcnow() - timedelta(days=days_ago), submitted_at=datetime.utcnow() - timedelta(days=days_ago))
        db.add(a)
        db.flush()
        return a

    def add_doc(app, inst, doc_type, ctx, *, qr_url=None, metadata=None, tamper=None, scan=False, declared_type=None, truth=None, filename=None, copy_of=None):
        fn = filename or f"{inst.pid.replace('-', '')}_{doc_type.lower()}.pdf"
        folder = DOCS_DIR / app.app_no
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / fn
        if copy_of:
            path.write_bytes(open(copy_of, "rb").read())
        else:
            docgen.make_pdf(str(path), doc_type, {"inst": inst.name, "state": inst.state, "district": inst.district, **ctx}, qr_url=qr_url, metadata=metadata)
            if tamper:
                docgen.tamper_incremental(str(path), tamper)
        mime = "application/pdf"
        if scan:
            png = folder / fn.replace(".pdf", "_scan.png")
            docgen.pdf_to_scan_png(str(path), str(png), angle=scan if isinstance(scan, (int, float)) else 1.4)
            path.unlink()
            path, mime, fn = png, "image/png", png.name
        prints_ref = doc_type not in ("AFFIDAVIT", "FACULTY_LIST")
        prints_valid = doc_type in ("FIRE_NOC", "LEASE_DEED", "BUILDING_SAFETY", "NBA_ACCREDITATION", "UNIVERSITY_AFFILIATION")
        gt = {"doc_type": doc_type, "ref_no": ctx.get("ref") if prints_ref else None, "issued_on": ctx.get("issued").isoformat() if ctx.get("issued") else None,
              "valid_till": ctx.get("valid").isoformat() if (ctx.get("valid") and prints_valid) else None, "planted": truth or []}
        d = Document(application_id=app.id, filename=fn, path=str(path), mime=mime, size=path.stat().st_size, doc_type_declared=declared_type or doc_type, uploaded_at=app.submitted_at, ground_truth=gt)
        db.add(d)
        db.flush()
        return d

    def registry(source_key, ref, record):
        mock_authority.put(source_key, ref, record)

    def std_ctx(inst, kind, i, **kw):
        base = {"ref": f"{kind}/{inst.state[:2].upper()}/{2024 + (i % 3)}/{1000 + i * 37 % 900:04d}", "issued": today - timedelta(days=kw.pop("age", 120)), "n": 40 + i}
        base["valid"] = base["issued"] + timedelta(days=kw.pop("life", 365))
        base.update(kw)
        return base

    # ------------------------------------------------------------ A: clean application (Nalanda, EOA, accredited)
    A = insts["1-4471"]
    appA = new_app(A, "EOA", {"intake": 300, "faculty_count": 62, "built_up_area_sqm": 9800, "land_acres": 10.5, "library_volumes": 12000, "accreditation_claimed": True, "programmes": ["B.Tech CSE", "B.Tech ECE", "B.Tech ME"]}, 3)
    c = std_ctx(A, "TNFRS", 1, age=60, life=365); registry("fire", c["ref"], {"institution": A.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appA, A, "FIRE_NOC", c)
    c = std_ctx(A, "LD", 2, age=3000, life=365 * 30, acres=10.5, years=30); registry("registrar", c["ref"], {"institution": A.name, "valid_till": c["valid"].isoformat(), "acres": 10.5})
    add_doc(appA, A, "LEASE_DEED", c)
    add_doc(appA, A, "AFFIDAVIT", std_ctx(A, "AFF", 3, age=20, life=365))
    add_doc(appA, A, "BUILDING_SAFETY", std_ctx(A, "SSC", 4, age=200, life=1095, built_up=9800, floors=4))
    c = std_ctx(A, "TXN", 5, age=10, amount=300000); registry("aicte_payments", c["ref"], {"institution": A.name, "amount": 300000, "status": "SUCCESS"})
    add_doc(appA, A, "TER_RECEIPT", c)
    add_doc(appA, A, "FACULTY_LIST", std_ctx(A, "FAC", 6, age=15, faculty=_faculty(62, rnd)))
    c = std_ctx(A, "AFFL", 7, age=90, life=365); registry("university", c["ref"], {"institution": A.name, "valid_till": c["valid"].isoformat(), "academic_year": "2026-27"})
    add_doc(appA, A, "UNIVERSITY_AFFILIATION", c)
    c = std_ctx(A, "NBA", 8, age=500, life=1095, programme="B.Tech - Computer Science & Engineering", years=3); registry("nba", c["ref"], {"institution": A.name, "valid_till": c["valid"].isoformat(), "programme": "B.Tech CSE"})
    nba_A = add_doc(appA, A, "NBA_ACCREDITATION", c)

    # ------------------------------------------------------------ B: expired Fire NOC + old affidavit (Coastal)
    B = insts["1-4502"]
    appB = new_app(B, "EOA", {"intake": 300, "faculty_count": 60, "built_up_area_sqm": 9200, "land_acres": 10.5, "library_volumes": 9000, "programmes": ["B.Tech CSE", "B.Tech ECE", "B.Tech ME"]}, 5)
    c = std_ctx(B, "KSFES", 11, age=400, life=365); registry("fire", c["ref"], {"institution": B.name, "valid_till": c["valid"].isoformat(), "status": "EXPIRED"})
    add_doc(appB, B, "FIRE_NOC", c, truth=["EXPIRED"])
    c = std_ctx(B, "LD", 12, age=2000, life=365 * 30, acres=10.5); registry("registrar", c["ref"], {"institution": B.name, "valid_till": c["valid"].isoformat()})
    add_doc(appB, B, "LEASE_DEED", c)
    add_doc(appB, B, "AFFIDAVIT", std_ctx(B, "AFF", 13, age=420, life=365), truth=["TOO_OLD"])
    add_doc(appB, B, "BUILDING_SAFETY", std_ctx(B, "SSC", 14, age=100, life=1095, built_up=9200))
    c = std_ctx(B, "TXN", 15, age=8, amount=300000); registry("aicte_payments", c["ref"], {"institution": B.name, "amount": 300000, "status": "SUCCESS"})
    add_doc(appB, B, "TER_RECEIPT", c)
    add_doc(appB, B, "FACULTY_LIST", std_ctx(B, "FAC", 16, age=12, faculty=_faculty(60, rnd)))
    c = std_ctx(B, "AFFL", 17, age=80, life=365); registry("university", c["ref"], {"institution": B.name, "valid_till": c["valid"].isoformat()})
    add_doc(appB, B, "UNIVERSITY_AFFILIATION", c)

    # ------------------------------------------------------------ C: wrong institution on lease deed, intake exceeds record, area shortfall, TER unpaid (Chola)
    C = insts["1-4388"]
    appC = new_app(C, "EOA", {"intake": 360, "faculty_count": 48, "built_up_area_sqm": 6400, "land_acres": 10.5, "library_volumes": 3000, "programmes": ["B.Tech CSE", "B.Tech ECE", "B.Tech ME"]}, 4)
    c = std_ctx(C, "TNFRS", 21, age=100, life=365); registry("fire", c["ref"], {"institution": C.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appC, C, "FIRE_NOC", c)
    c = std_ctx(C, "LD", 22, age=1500, life=365 * 30, acres=10.5); registry("registrar", c["ref"], {"institution": "Kaveri College of Engineering, Mysuru", "valid_till": c["valid"].isoformat()})
    add_doc(appC, C, "LEASE_DEED", {**c, "inst_override": True}, truth=["NAME_MISMATCH"], filename="14388_lease_deed.pdf")
    # overwrite lessee name in that deed: regenerate with another institution name
    d_lease = db.query(Document).filter(Document.application_id == appC.id, Document.doc_type_declared == "LEASE_DEED").first()
    docgen.make_pdf(d_lease.path, "LEASE_DEED", {"inst": "Kaveri College of Engineering, Mysuru", "state": "Karnataka", "district": "Mysuru", **c})
    add_doc(appC, C, "AFFIDAVIT", std_ctx(C, "AFF", 23, age=30, life=365))
    add_doc(appC, C, "BUILDING_SAFETY", std_ctx(C, "SSC", 24, age=300, life=1095, built_up=6400), truth=["AREA_SHORTFALL"])
    add_doc(appC, C, "FACULTY_LIST", std_ctx(C, "FAC", 26, age=10, faculty=_faculty(41, rnd)), truth=["FACULTY_COUNT_DIFFERS"])
    c = std_ctx(C, "AFFL", 27, age=70, life=365); registry("university", c["ref"], {"institution": C.name, "valid_till": c["valid"].isoformat()})
    add_doc(appC, C, "UNIVERSITY_AFFILIATION", c)
    # TER receipt missing (and record says unpaid)

    # ------------------------------------------------------------ D: duplicate of A's NBA certificate (Malabar; Kerala fire API unavailable)
    D = insts["1-4419"]
    appD = new_app(D, "EOA", {"intake": 160, "faculty_count": 28, "built_up_area_sqm": 2400, "land_acres": 2.4, "library_volumes": 6000, "accreditation_claimed": True, "programmes": ["B.Pharm", "D.Pharm"]}, 6)
    c = std_ctx(D, "KFRS", 31, age=90, life=365); registry("fire", c["ref"], {"institution": D.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appD, D, "FIRE_NOC", c, truth=["SOURCE_UNAVAILABLE"])
    c = std_ctx(D, "LD", 32, age=1800, life=365 * 30, acres=2.4); registry("registrar", c["ref"], {"institution": D.name, "valid_till": c["valid"].isoformat()})
    add_doc(appD, D, "LEASE_DEED", c)
    add_doc(appD, D, "AFFIDAVIT", std_ctx(D, "AFF", 33, age=25, life=365))
    add_doc(appD, D, "BUILDING_SAFETY", std_ctx(D, "SSC", 34, age=150, life=1095, built_up=2400))
    c = std_ctx(D, "TXN", 35, age=6, amount=200000); registry("aicte_payments", c["ref"], {"institution": D.name, "amount": 200000, "status": "SUCCESS"})
    add_doc(appD, D, "TER_RECEIPT", c)
    add_doc(appD, D, "FACULTY_LIST", std_ctx(D, "FAC", 36, age=9, faculty=_faculty(28, rnd)))
    c = std_ctx(D, "AFFL", 37, age=60, life=365); registry("university", c["ref"], {"institution": D.name, "valid_till": c["valid"].isoformat()})
    add_doc(appD, D, "UNIVERSITY_AFFILIATION", c)
    add_doc(appD, D, "NBA_ACCREDITATION", {}, copy_of=nba_A.path, truth=["DUPLICATE_FILE", "VERIFICATION_MISMATCH"], filename="14419_nba_accreditation.pdf")

    # ------------------------------------------------------------ E: tampered Fire NOC (metadata + altered validity), Deccan
    E = insts["1-4530"]
    appE = new_app(E, "INCREASE_INTAKE", {"intake": 160, "proposed_intake": 220, "faculty_count": 30, "built_up_area_sqm": 2600, "land_acres": 2.4, "library_volumes": 7000, "programmes": ["B.Pharm", "D.Pharm"]}, 2)
    c = std_ctx(E, "TSDRFS", 41, age=200, life=365)
    true_valid = c["valid"]
    registry("fire", c["ref"], {"institution": E.name, "valid_till": true_valid.isoformat(), "status": "VALID"})
    c_alt = {**c, "valid": true_valid + timedelta(days=365)}  # document shows one extra year
    add_doc(appE, E, "FIRE_NOC", c_alt, metadata={"producer": "Adobe Photoshop 24.1 (Windows)", "creator": "Adobe Photoshop", "creationDate": "D:20260915101500", "modDate": "D:20260410093000"}, truth=["TAMPERED_METADATA", "VERIFICATION_MISMATCH"])
    c = std_ctx(E, "LD", 42, age=2200, life=365 * 30, acres=2.4); registry("registrar", c["ref"], {"institution": E.name, "valid_till": c["valid"].isoformat()})
    add_doc(appE, E, "LEASE_DEED", c)
    add_doc(appE, E, "AFFIDAVIT", std_ctx(E, "AFF", 43, age=15, life=365))
    add_doc(appE, E, "BUILDING_SAFETY", std_ctx(E, "SSC", 44, age=120, life=1095, built_up=2600))
    add_doc(appE, E, "BUILDING_PLAN", std_ctx(E, "BP", 45, age=400, built_up=2600, floors=3), truth=["AREA_SHORTFALL"])
    c = std_ctx(E, "TXN", 46, age=4, amount=400000); registry("aicte_payments", c["ref"], {"institution": E.name, "amount": 400000, "status": "SUCCESS"})
    add_doc(appE, E, "TER_RECEIPT", c)
    add_doc(appE, E, "FACULTY_LIST", std_ctx(E, "FAC", 47, age=7, faculty=_faculty(30, rnd)))
    c = std_ctx(E, "AFFL", 48, age=50, life=365); registry("university", c["ref"], {"institution": E.name, "valid_till": c["valid"].isoformat()})
    add_doc(appE, E, "UNIVERSITY_AFFILIATION", c)

    # ------------------------------------------------------------ F: scanned (skewed) Fire NOC with QR -> OCR + QR verification (Sahyadri)
    F_ = insts["1-4611"]
    appF = new_app(F_, "EOA", {"intake": 180, "faculty_count": 34, "built_up_area_sqm": 5600, "land_acres": 6.0, "library_volumes": 5000, "programmes": ["Diploma CE", "Diploma ME", "Diploma CSE"]}, 7)
    c = std_ctx(F_, "MFS", 51, age=80, life=365); registry("fire", c["ref"], {"institution": F_.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appF, F_, "FIRE_NOC", c, qr_url=f"https://pramaan.aicte.gov.in/mock-authority/fire/{c['ref']}", scan=1.6, truth=["SCANNED_OCR", "QR_VERIFIED"])
    c = std_ctx(F_, "LD", 52, age=2600, life=365 * 30, acres=6.0); registry("registrar", c["ref"], {"institution": F_.name, "valid_till": c["valid"].isoformat()})
    add_doc(appF, F_, "LEASE_DEED", c)
    add_doc(appF, F_, "AFFIDAVIT", std_ctx(F_, "AFF", 53, age=40, life=365), scan=-1.1, truth=["SCANNED_OCR"])
    add_doc(appF, F_, "BUILDING_SAFETY", std_ctx(F_, "SSC", 54, age=80, life=1095, built_up=5600))
    c = std_ctx(F_, "TXN", 55, age=5, amount=250000); registry("aicte_payments", c["ref"], {"institution": F_.name, "amount": 250000, "status": "SUCCESS"})
    add_doc(appF, F_, "TER_RECEIPT", c)
    add_doc(appF, F_, "FACULTY_LIST", std_ctx(F_, "FAC", 56, age=11, faculty=_faculty(34, rnd)))
    c = std_ctx(F_, "AFFL", 57, age=45, life=365); registry("university", c["ref"], {"institution": F_.name, "valid_till": c["valid"].isoformat()})
    add_doc(appF, F_, "UNIVERSITY_AFFILIATION", c)

    # ------------------------------------------------------------ G: missing documents + affiliation ref not found at source (Saraswati)
    G = insts["1-4622"]
    appG = new_app(G, "EOA", {"intake": 120, "faculty_count": 18, "built_up_area_sqm": 1400, "land_acres": 2.0, "library_volumes": 4500, "programmes": ["MBA"]}, 9)
    c = std_ctx(G, "MFS", 61, age=70, life=365); registry("fire", c["ref"], {"institution": G.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appG, G, "FIRE_NOC", c)
    c = std_ctx(G, "LD", 62, age=1200, life=365 * 30, acres=2.0); registry("registrar", c["ref"], {"institution": G.name, "valid_till": c["valid"].isoformat()})
    add_doc(appG, G, "LEASE_DEED", c)
    add_doc(appG, G, "AFFIDAVIT", std_ctx(G, "AFF", 63, age=22, life=365))
    add_doc(appG, G, "BUILDING_SAFETY", std_ctx(G, "SSC", 64, age=90, life=1095, built_up=1400), truth=["AREA_SHORTFALL"])
    add_doc(appG, G, "UNIVERSITY_AFFILIATION", std_ctx(G, "AFFL", 67, age=40, life=365), truth=["REF_NOT_FOUND"])
    # TER receipt and faculty list missing -> completeness

    # ------------------------------------------------------------ H: impossible dates in structural certificate; receipt uploaded under wrong head (Ganga Valley)
    Hh = insts["1-4815"]
    appH = new_app(Hh, "EOA", {"intake": 300, "faculty_count": 64, "built_up_area_sqm": 10200, "land_acres": 10.5, "library_volumes": 15000, "programmes": ["B.Tech CSE", "B.Tech ECE", "B.Tech ME"]}, 1)
    c = std_ctx(Hh, "UPFS", 71, age=110, life=365); registry("fire", c["ref"], {"institution": Hh.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appH, Hh, "FIRE_NOC", c)
    c = std_ctx(Hh, "LD", 72, age=2900, life=365 * 30, acres=10.5); registry("registrar", c["ref"], {"institution": Hh.name, "valid_till": c["valid"].isoformat()})
    add_doc(appH, Hh, "LEASE_DEED", c)
    add_doc(appH, Hh, "AFFIDAVIT", std_ctx(Hh, "AFF", 73, age=18, life=365))
    c = std_ctx(Hh, "SSC", 74, age=60, life=1095, built_up=10200)
    add_doc(appH, Hh, "BUILDING_SAFETY", {**c, "valid": c["issued"] - timedelta(days=700)}, truth=["DATE_ORDER"])
    c = std_ctx(Hh, "TXN", 75, age=3, amount=300000); registry("aicte_payments", c["ref"], {"institution": Hh.name, "amount": 300000, "status": "SUCCESS"})
    add_doc(appH, Hh, "TER_RECEIPT", c, declared_type="FACULTY_LIST", truth=["WRONG_HEAD"])
    add_doc(appH, Hh, "FACULTY_LIST", std_ctx(Hh, "FAC", 76, age=6, faculty=_faculty(64, rnd)))
    c = std_ctx(Hh, "AFFL", 77, age=30, life=365); registry("university", c["ref"], {"institution": Hh.name, "valid_till": c["valid"].isoformat()})
    add_doc(appH, Hh, "UNIVERSITY_AFFILIATION", c)

    # ------------------------------------------------------------ I: new institution, clean except FDR amount mismatch at bank (Hooghly)
    I = insts["1-4901"]
    appI = new_app(I, "NEW_INSTITUTION", {"intake": 180, "faculty_count": 36, "built_up_area_sqm": 6000, "land_acres": 10.8, "library_volumes": 4200, "programmes": ["B.Tech CSE", "B.Tech ECE"]}, 12)
    add_doc(appI, I, "AFFIDAVIT", std_ctx(I, "AFF", 81, age=12, life=365))
    c = std_ctx(I, "SD", 82, age=400, acres=10.8); registry("registrar", c["ref"], {"institution": I.name, "acres": 10.8})
    add_doc(appI, I, "LAND_DOCUMENT", c)
    add_doc(appI, I, "BUILDING_PLAN", std_ctx(I, "BP", 83, age=380, built_up=6000, floors=3))
    add_doc(appI, I, "OCCUPANCY_CERT", std_ctx(I, "OC", 84, age=90, built_up=6000, floors=3))
    add_doc(appI, I, "BUILDING_SAFETY", std_ctx(I, "SSC", 85, age=85, life=1095, built_up=6000))
    c = std_ctx(I, "WBFES", 86, age=60, life=365); registry("fire", c["ref"], {"institution": I.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appI, I, "FIRE_NOC", c)
    c = std_ctx(I, "FDR", 87, age=30, life=365 * 5, amount=5000000); registry("bank", c["ref"], {"institution": I.name, "amount": 3500000, "maturity": c["valid"].isoformat()})
    add_doc(appI, I, "BANK_FDR", c, truth=["VERIFICATION_MISMATCH"])
    c = std_ctx(I, "TXN", 88, age=2, amount=500000); registry("aicte_payments", c["ref"], {"institution": I.name, "amount": 500000, "status": "SUCCESS"})
    add_doc(appI, I, "TER_RECEIPT", c)

    # ------------------------------------------------------------ J: expiring soon + near-duplicate scan reuse of F's affidavit (Aravalli)
    J = insts["1-4820"]
    appJ = new_app(J, "EOA", {"intake": 40, "faculty_count": 12, "built_up_area_sqm": 900, "land_acres": 1.5, "library_volumes": 4100, "programmes": ["B.Arch"]}, 8)
    c = std_ctx(J, "RFS", 91, age=320, life=365); registry("fire", c["ref"], {"institution": J.name, "valid_till": c["valid"].isoformat(), "status": "VALID"})
    add_doc(appJ, J, "FIRE_NOC", c, truth=["EXPIRING"])
    c = std_ctx(J, "LD", 92, age=900, life=365 * 30, acres=1.5); registry("registrar", c["ref"], {"institution": J.name, "valid_till": c["valid"].isoformat()})
    add_doc(appJ, J, "LEASE_DEED", c)
    add_doc(appJ, J, "AFFIDAVIT", std_ctx(J, "AFF", 93, age=28, life=365))
    add_doc(appJ, J, "BUILDING_SAFETY", std_ctx(J, "SSC", 94, age=70, life=1095, built_up=900), truth=["AREA_SHORTFALL"])
    c = std_ctx(J, "TXN", 95, age=4, amount=150000); registry("aicte_payments", c["ref"], {"institution": J.name, "amount": 150000, "status": "SUCCESS"})
    add_doc(appJ, J, "TER_RECEIPT", c)
    add_doc(appJ, J, "FACULTY_LIST", std_ctx(J, "FAC", 96, age=9, faculty=_faculty(12, rnd)))
    c = std_ctx(J, "AFFL", 97, age=35, life=365); registry("university", c["ref"], {"institution": J.name, "valid_till": c["valid"].isoformat()})
    add_doc(appJ, J, "UNIVERSITY_AFFILIATION", c)

    mock_authority.save(mock_authority._registry)
    db.commit()
    audit.record(db, "system", "SEED", "system", None, {"institutions": len(insts), "applications": db.query(Application).count(), "documents": db.query(Document).count(), "note": "synthetic corpus with planted anomalies"})
    db.commit()
    for app in db.query(Application).order_by(Application.id).all():
        pipeline.validate_application(db, app, actor="system")
    return True
