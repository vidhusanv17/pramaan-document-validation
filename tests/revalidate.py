"""Push current rules/checklists.json norms into the running server (admin) and re-validate every application."""
import json, pathlib, sys, httpx
B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8061"
c = httpx.Client(base_url=B, timeout=300)
H = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "admin", "password": "demo123"}).json()["token"]}
data = json.loads(pathlib.Path(__file__).resolve().parent.parent.joinpath("rules", "checklists.json").read_text(encoding="utf-8"))
cl = c.get("/api/checklists", headers=H).json()
norms = next(x for x in cl["items"] if x["key"] == "_norms")
rules = dict(norms["rules"]); rules["infrastructure_norms"] = data["infrastructure_norms"]
print("PUT norms", c.put("/api/checklists/_norms", json={"rules": rules}, headers=H).json()["version"])
for a in c.get("/api/applications", headers=H).json():
    r = c.post(f"/api/applications/{a['id']}/validate", headers=H).json()
    print(a["app_no"], r["risk_score"], r["risk_band"], len(r["findings"]))
m = c.get("/api/metrics", headers=H).json()
print(json.dumps({"planted": m["planted_anomalies"], "fp": m["high_severity_forgery_flags_on_clean_docs"], "cls": m["classification_accuracy"], "fields": {k: v["accuracy"] for k, v in m["field_extraction"].items()}}))
