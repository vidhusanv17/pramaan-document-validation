"""Intelligent field extraction: regex/heuristic extractors per document type. Every value carries its
page, the text snippet it came from and (where available) the OCR/text-layer box, so findings stay
evidence-linked."""
import re
from datetime import date, datetime

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE = r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:" + MONTHS + r")[a-z]*\.?,?\s+\d{4}|(?:" + MONTHS + r")[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
AREA = r"([\d,]+(?:\.\d+)?)\s*(sq\.?\s*(?:m|mt|mtr|mtrs|meters?|metres?)\b|sqm\b|square\s*met(?:er|re)s?|acres?\b|hectares?\b|sq\.?\s*ft\b|sqft\b)"

INST_NAME = re.compile(r"((?:[A-Z][A-Za-z&.'\-]*\s+){1,5}(?:College|Institute|Institution|School|Polytechnic|Academy)(?:\s+(?:of|for)\s+[A-Z][A-Za-z&.'\-]*(?:\s+(?:&|and)\s+[A-Z][A-Za-z]*)?(?:\s+[A-Z][A-Za-z]*)?)?(?:,\s*[A-Z][a-z]+)?)")

COMMON = {
    "pid": r"\b(1-\d{4,10})\b",
    "ref_no": r"(?:NOC|Ref(?:erence)?|Certificate|Deed|Receipt|Document|Registration|FDR|Letter|Transaction|Permit|Order|Plan approval|Approval|Sanction)\s*(?:No|Number|ID|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-\.]{4,40})",
    "issued_on": r"(?:date of issue|issued on|dated|date|executed on|made on|paid on|sworn before me on)\s*[:\-]?\s*" + DATE,
    "valid_till": r"(?:valid (?:till|upto|up to|until)|validity(?: up to| till)?|expiry|expires on|valid for the period .*? to)\s*[:\-]?\s*" + DATE,
    "signature": r"(digitally signed|signature|sd/-|signed by)",
    "issuer": r"^(.*?(?:department|services|university|corporation|board|council|bank|notary|engineer|sub-?registrar|authority|office of)[^\n]*)$",
}
BY_TYPE = {
    "LEASE_DEED": {"lease_years": r"(?:period|term) of (?:the )?lease[^\d]{0,40}(\d{1,2})\s*years", "area": AREA, "lessee": r"lessee\s*[:\-]?\s*([A-Z][A-Za-z&.,'\- ]{6,80})", "lessor": r"lessor\s*[:\-]?\s*([A-Z][A-Za-z&.,'\- ]{4,80})"},
    "LAND_DOCUMENT": {"land_area": AREA, "survey_no": r"survey\s*no\.?\s*[:\-]?\s*([0-9/\-A-Z]+)"},
    "BUILDING_SAFETY": {"built_up_area": AREA, "valid_years": r"valid for (\d{1,2})\s*years"},
    "BUILDING_PLAN": {"built_up_area": AREA, "floors": r"(?:ground\s*\+\s*(\d)|G\s*\+\s*(\d))"},
    "OCCUPANCY_CERT": {"built_up_area": AREA, "floors": r"(?:ground\s*\+\s*(\d)|G\s*\+\s*(\d))"},
    "TER_RECEIPT": {"amount": r"(?:Rs\.?|INR|\u20b9)\s*([\d,]+(?:\.\d+)?)", "transaction_id": r"transaction\s*(?:id|ref(?:erence)?|no)\.?\s*[:\-]?\s*([A-Z0-9\-]{6,})", "status": r"status\s*[:\-]?\s*(success(?:ful)?|failed|pending)"},
    "BANK_FDR": {"amount": r"(?:Rs\.?|INR|\u20b9)\s*([\d,]+(?:\.\d+)?)", "maturity_date": r"maturity\s*(?:date)?\s*[:\-]?\s*" + DATE, "bank": r"^([A-Z][A-Za-z ]+Bank[A-Za-z ]*)$", "lien": r"(lien marked|lien in favour of aicte)"},
    "FACULTY_LIST": {"faculty_rows": r"^\s*\d{1,3}[.)]?\s+[A-Z][A-Za-z. ]+\s+(?:Professor|Associate Professor|Assistant Professor|Lecturer)"},
    "NBA_ACCREDITATION": {"programme": r"programme[s]?\s*[:\-]?\s*([A-Z][A-Za-z.&/ \-]{4,80})", "tier": r"tier\s*[-]?\s*(i{1,3}|1|2)"},
    "UNIVERSITY_AFFILIATION": {"academic_year": r"academic year\s*[:\-]?\s*(\d{4}\s*-\s*\d{2,4})", "university": r"^([A-Z][A-Za-z. ]+University[A-Za-z ]*)$"},
    "FIRE_NOC": {"building": r"(?:building|premises|block)[s]?\s*[:\-]?\s*([A-Za-z0-9,&\- ]{4,80})"},
    "AFFIDAVIT": {"deponent": r"deponent\s*[:\-]?\s*([A-Z][A-Za-z. ]{4,60})", "stamp_value": r"stamp paper of (?:Rs\.?|INR)\s*([\d,]+)"},
}


def parse_date(s):
    if not s:
        return None
    s = s.strip().replace(",", "")
    s = re.sub(r"(\d)(st|nd|rd|th)", r"\1", s)
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%y", "%d/%m/%y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y", "%d %b. %Y", "%d %Sept %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})\s+(" + MONTHS + r")[a-z]*\.?\s+(\d{4})", s, re.I)
    if m:
        mon = m.group(2)[:3].lower()
        idx = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(mon) + 1
        try:
            return date(int(m.group(3)), idx, int(m.group(1)))
        except ValueError:
            return None
    return None


def _locate(pages, needle):
    """Find the page and line box containing the needle text."""
    n = re.sub(r"\s+", " ", needle).strip().lower()
    for p in pages:
        for b in p.get("boxes", []):
            if n and n[: min(len(n), 24)] in re.sub(r"\s+", " ", b[4]).lower():
                return p["page"], b[:4]
    for p in pages:
        if n and n[: min(len(n), 24)] in re.sub(r"\s+", " ", p.get("text", "")).lower():
            return p["page"], None
    return (pages[0]["page"] if pages else 1), None


def _snippet(text, start, end, width=70):
    s = max(0, start - width)
    e = min(len(text), end + width)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def extract_fields(text, pages, doc_type):
    fields = {}
    patterns = dict(COMMON)
    patterns.update(BY_TYPE.get(doc_type, {}))
    flat = text or ""
    for name, pat in patterns.items():
        flags = re.I | re.M
        if name == "faculty_rows":
            rows = re.findall(pat, flat, flags)
            if rows:
                fields["faculty_count"] = {"value": len(rows), "page": 1, "snippet": f"{len(rows)} faculty rows detected", "confidence": 0.85}
            continue
        m = re.search(pat, flat, flags)
        if not m:
            continue
        val = next((g for g in m.groups() if g), m.group(0)).strip()
        if name in ("issued_on", "valid_till", "maturity_date"):
            d = parse_date(val)
            if not d:
                continue
            val_out = d.isoformat()
        elif name in ("area", "land_area", "built_up_area"):
            num = float(val.replace(",", ""))
            unit = m.group(2).lower() if m.lastindex and m.lastindex >= 2 and m.group(2) else ""
            if "acre" in unit:
                val_out = {"value": num, "unit": "acres"}
            elif "hect" in unit:
                val_out = {"value": round(num * 2.471, 2), "unit": "acres"}
            elif "ft" in unit:
                val_out = {"value": round(num * 0.0929, 1), "unit": "sqm"}
            else:
                val_out = {"value": num, "unit": "sqm"}
        elif name == "amount":
            val_out = float(val.replace(",", ""))
        elif name == "signature":
            val_out = True
        elif name == "institution_name":
            val_out = re.sub(r"\s+", " ", val).strip(" ,.")
        else:
            val_out = re.sub(r"\s+", " ", val).strip(" ,.")
        page, bbox = _locate(pages, m.group(0))
        fields[name] = {"value": val_out, "page": page, "bbox": bbox, "snippet": _snippet(flat, m.start(), m.end()), "confidence": 0.9 if bbox else 0.75}
    # institution name: proper-noun phrase ending in College/Institute/School/Polytechnic/Academy (case-sensitive),
    # preferring the one that follows an addressee keyword
    cands = [(m.start(), m.group(1)) for m in INST_NAME.finditer(flat)]
    if cands:
        pref = re.search(r"(?:Issued to|In favour of|Lessee|Purchaser|Received from|Applicant|Issued to|granted provisional affiliation to|offered by|certify that the building of|running|In the joint name of|name of)\s*[:\-]?\s*", flat)
        pick = None
        if pref:
            after = [c for c in cands if c[0] >= pref.end() - 1 and c[0] - pref.end() < 8]
            pick = after[0] if after else None
        pick = pick or cands[0]
        name = re.sub(r"\s+", " ", pick[1]).strip(" ,.")
        page, bbox = _locate(pages, name)
        fields["institution_name"] = {"value": name, "page": page, "bbox": bbox, "snippet": _snippet(flat, pick[0], pick[0] + len(pick[1])), "confidence": 0.85 if pref else 0.7}
    return fields
