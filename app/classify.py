"""Document-type classifier: TF-IDF (1-2 grams) + logistic regression trained at startup on synthetic
templates of AICTE-relevant document types, with a keyword fallback. Returns label + calibrated-ish confidence."""
import random
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

DOC_TYPES = {
    "FIRE_NOC": "Fire safety NOC",
    "LEASE_DEED": "Registered lease deed",
    "AFFIDAVIT": "Affidavit (prescribed format)",
    "BUILDING_SAFETY": "Structural stability certificate",
    "NBA_ACCREDITATION": "NBA accreditation certificate",
    "LAND_DOCUMENT": "Land / sale deed",
    "OCCUPANCY_CERT": "Building occupancy certificate",
    "TER_RECEIPT": "TER charges payment receipt",
    "FACULTY_LIST": "Faculty list",
    "UNIVERSITY_AFFILIATION": "University affiliation letter",
    "BANK_FDR": "Bank FDR / security deposit",
    "BUILDING_PLAN": "Approved building plan",
}

_TEMPLATES = {
    "FIRE_NOC": ["{state} fire and rescue services no objection certificate fire safety noc no {ref} issued to {inst} the building complies with fire prevention and fire safety norms valid till {date} fire officer",
                 "office of the director of fire services noc for occupancy fire fighting installations hydrants extinguishers sprinklers inspected premises of {inst} certificate valid upto {date} divisional fire officer"],
    "LEASE_DEED": ["lease deed this deed of lease made on {date} between lessor and lessee {inst} period of lease {n} years rent payable registered at sub registrar office document no {ref} schedule of property land and building",
                   "registered lease agreement lessor hereby demises unto the lessee the premises for a term of {n} years stamp duty paid sub-registrar registration no {ref} witnesses"],
    "AFFIDAVIT": ["affidavit i the deponent chairman of the trust running {inst} do hereby solemnly affirm and declare that the information furnished in the application is true verification notary public stamp paper of rs 100 sworn before me on {date}",
                  "affidavit on non judicial stamp paper the deponent states that the institution shall abide by the regulations of aicte and the approval process handbook solemnly affirmed identified by advocate notary seal"],
    "BUILDING_SAFETY": ["structural stability certificate this is to certify that the building of {inst} has been inspected and is structurally safe and stable for its intended use chartered structural engineer registration no {ref} valid for {n} years dated {date}",
                        "certificate of structural soundness the rcc framed structure is structurally stable licensed structural engineer certificate no {ref} valid upto {date}"],
    "NBA_ACCREDITATION": ["national board of accreditation certificate of accreditation this is to certify that the programme offered by {inst} is accredited for {n} years tier ii valid up to {date} certificate no {ref} member secretary nba",
                          "nba accreditation status letter programme accredited academic years {date} accreditation valid till {date} nba new delhi reference {ref}"],
    "LAND_DOCUMENT": ["sale deed executed on {date} vendor and purchaser {inst} trust land measuring {n} acres survey no {ref} patta khata boundaries east west north south registered sub registrar consideration amount",
                      "land ownership document gift deed trust land survey number {ref} extent {n} acres encumbrance certificate nil village taluk district registered document"],
    "OCCUPANCY_CERT": ["municipal corporation occupancy certificate the building constructed as per sanctioned plan building permit no {ref} is fit for occupation completion certificate issued to {inst} dated {date}",
                       "town planning authority completion cum occupancy certificate building permission no {ref} floors ground plus {n} occupancy permitted {date}"],
    "TER_RECEIPT": ["all india council for technical education payment receipt ter charges technical education regulatory charges amount rs {amt} transaction id {ref} paid on {date} by {inst} payment successful",
                    "aicte online payment acknowledgement ter charges processing fee rs {amt} received from {inst} transaction reference {ref} status success"],
    "FACULTY_LIST": ["list of faculty members {inst} sl no name designation professor associate professor assistant professor qualification m tech ph d date of joining pan aadhaar department {date}",
                     "faculty details department wise name of faculty designation highest qualification experience years date of joining appointment order number salary bank account"],
    "UNIVERSITY_AFFILIATION": ["university provisional affiliation letter the syndicate has granted provisional affiliation to {inst} for the academic year {date} for the programmes listed intake registrar university ref {ref}",
                               "affiliation order continuation of affiliation to {inst} for the academic year {date} subject to compliance registrar affiliating university letter no {ref}"],
    "BANK_FDR": ["fixed deposit receipt fdr bank branch principal amount rs {amt} rate of interest maturity date {date} fdr no {ref} in the joint name of {inst} and aicte lien marked security deposit",
                 "term deposit advice deposit amount rs {amt} period {n} years maturity value fdr number {ref} lien in favour of aicte bank manager"],
    "BUILDING_PLAN": ["approved building plan sanctioned plan floor plan ground floor first floor built up area {amt} sq m carpet area classrooms laboratories library seminar hall plan approval no {ref} town planning {inst}",
                      "architectural drawings approved by competent authority total built-up area {amt} sqm plinth area floors permit no {ref} drawing scale 1:100 {date}"],
}
_FILL = {"state": ["tamil nadu", "karnataka", "kerala", "maharashtra", "telangana", "uttar pradesh", "west bengal"],
         "inst": ["abc college of engineering", "xyz institute of technology", "pqr college of pharmacy", "lmn institute of management", "stu polytechnic college"],
         "date": ["31-03-2027", "2026-27", "15 june 2025", "01/04/2026", "2027-03-31"], "n": ["3", "5", "10", "30", "2"], "amt": ["50,000", "3,00,000", "12,500", "8,000"],
         "ref": ["tnfrs/chn/2025/04471", "doc 1234/2016", "ssc/2024/118", "nba/acc/2023/771", "txn9f8a7b6c", "bp/2015/0912"]}

KEYWORDS = {
    "FIRE_NOC": ["fire", "noc", "no objection"], "LEASE_DEED": ["lease", "lessor", "lessee"], "AFFIDAVIT": ["affidavit", "deponent", "solemnly"],
    "BUILDING_SAFETY": ["structural", "stability", "structurally"], "NBA_ACCREDITATION": ["accreditation", "nba", "accredited"], "LAND_DOCUMENT": ["sale deed", "survey", "acres"],
    "OCCUPANCY_CERT": ["occupancy", "completion certificate"], "TER_RECEIPT": ["ter charges", "payment receipt", "transaction"], "FACULTY_LIST": ["faculty", "designation", "qualification"],
    "UNIVERSITY_AFFILIATION": ["affiliation", "university", "syndicate"], "BANK_FDR": ["fixed deposit", "fdr", "maturity"], "BUILDING_PLAN": ["building plan", "built up area", "built-up area", "floor plan"],
}

_model = None


def _corpus(n_per_type=60, seed=26261):
    rnd = random.Random(seed)
    X, y = [], []
    for label, temps in _TEMPLATES.items():
        for i in range(n_per_type):
            t = rnd.choice(temps)
            txt = re.sub(r"\{(\w+)\}", lambda m: rnd.choice(_FILL[m.group(1)]), t)
            words = txt.split()
            # random dropout to make it robust to OCR noise
            keep = [w for w in words if rnd.random() > 0.12]
            X.append(" ".join(keep))
            y.append(label)
    return X, y


def train():
    global _model
    X, y = _corpus()
    _model = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)), ("clf", LogisticRegression(max_iter=3000, C=8.0))])
    _model.fit(X, y)
    return _model


def classify(text: str) -> dict:
    global _model
    if _model is None:
        train()
    t = re.sub(r"\s+", " ", (text or "").lower())
    if len(t) < 40:
        return {"label": "UNREADABLE", "confidence": 0.0, "top3": [], "method": "none"}
    probs = _model.predict_proba([t])[0]
    classes = list(_model.classes_)
    ranked = sorted(zip(classes, probs), key=lambda x: -x[1])
    label, conf = ranked[0]
    # keyword agreement boosts confidence; disagreement tempers it
    hits = {k: sum(1 for kw in kws if kw in t) for k, kws in KEYWORDS.items()}
    best_kw = max(hits, key=hits.get)
    method = "tfidf+lr"
    if hits[best_kw] >= 2 and best_kw != label and hits[label] == 0:
        label, conf, method = best_kw, max(0.55, float(conf) * 0.8), "keyword-override"
    elif hits.get(label, 0) >= 1:
        conf = min(0.99, float(conf) + 0.1)
    return {"label": label, "confidence": round(float(conf), 3), "top3": [{"label": c, "p": round(float(p), 3)} for c, p in ranked[:3]], "method": method}
