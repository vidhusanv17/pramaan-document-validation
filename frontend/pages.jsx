/* PRAMAAN pages: dashboard, risk-prioritised queue, upload & validate flow, checklists, alerts, audit, evaluation metrics. */

function Dashboard({ user, go, refreshKey }) {
  const { data, error } = useApi("/dashboard", [refreshKey]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const k = data.kpis;
  const cats = Object.entries(data.findings_by_category).sort((a, b) => b[1] - a[1]);
  const ver = Object.entries(data.verification_results);
  return (<div className="fade">
    <Section title={user.role === "INSTITUTION" ? "My applications - validation status" : "Validation overview"} right={<div className="text-[11px] text-slate-500">OCR engine: <b>{data.ocr.kind || "warming up"}</b> {data.ocr.ready ? "· ready" : ""} · as of {fmt.dt(data.as_of)}</div>} />
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 mb-4">
      <KPI label="Applications validated" value={k.validated + " / " + k.applications} tone="blue" onClick={() => go("queue")} />
      <KPI label="High-risk applications" value={k.high_risk} tone="red" sub={k.medium_risk + " medium · " + k.low_risk + " low"} onClick={() => go("queue/HIGH")} />
      <KPI label="Documents processed" value={k.documents} tone="slate" sub={k.pages + " pages · " + k.ocr_pages + " via OCR"} />
      <KPI label="Open findings" value={k.findings_open} tone="amber" sub={k.critical_open + " critical"} />
      <KPI label="Issuer-verified documents" value={k.verified_docs} tone="green" sub={k.mismatch_docs + " mismatch · " + k.manual_review_docs + " manual/pending"} />
      <KPI label="Avg processing per application" value={k.avg_processing_s + " s"} tone="purple" sub={k.decided + " decisions recorded"} />
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
      <Card title="Risk-prioritised queue (top)" className="xl:col-span-2" pad={false}>
        <Table dense rows={data.queue} onRow={r => go("report/" + r.id)} cols={[
          { h: "Application", r: r => <span className="font-mono text-[12px]">{r.app_no}</span> },
          { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.institution_pid} · {fmt.title(r.category)}</div></span> },
          { h: "Risk", r: r => <RiskBar score={r.risk_score} band={r.risk_band} /> },
          { h: "Findings", r: r => <SevDots s={r.by_severity} /> },
          { h: "Checklist", r: r => <span>{r.completeness_pct}%</span> },
          { h: "Status", r: r => <Chip value={r.status} /> }]} />
      </Card>
      <div className="space-y-3">
        <Card title="Findings by category"><Bars items={cats.map(([c, n]) => ({ label: CATEGORY_LABELS[c] || c, count: n, color: { FORGERY_INDICATOR: "#DC2626", DUPLICATE: "#B91C1C", VERIFICATION: "#7C3AED", EXPIRY: "#F59E0B", COMPLETENESS: "#D97706", CONSISTENCY: "#6D28D9", RECORD_MISMATCH: "#2563EB", INFRASTRUCTURE: "#0F766E", QUALITY: "#64748B" }[c] }))} /></Card>
        <Card title="Issuer verification outcomes"><div className="flex flex-wrap gap-1.5">{ver.map(([r, n]) => <Chip key={r} value={r} label={(RESULT_LABELS[r] || r) + " " + n} />)}</div>
          <div className="text-[11px] text-slate-500 mt-2">Methods: {Object.entries(data.verification_methods).map(([m, n]) => m + " " + n).join(" · ")}</div></Card>
      </div>
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
      <Card title="Risk distribution"><ChartBox type="doughnut" labels={["Low", "Medium", "High"]} data={[data.risk_distribution.LOW || 0, data.risk_distribution.MEDIUM || 0, data.risk_distribution.HIGH || 0]} colors={["#16A34A", "#F59E0B", "#DC2626"]} height={190} /></Card>
      <Card title="Findings by severity"><ChartBox labels={["Info", "Low", "Medium", "High", "Critical"]} data={["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"].map(s => data.findings_by_severity[s] || 0)} colors={["#94A3B8", "#60A5FA", "#F59E0B", "#F97316", "#DC2626"]} height={190} /></Card>
      <Card title="Document types detected"><Bars items={Object.entries(data.doc_types).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t, n]) => ({ label: t.replace(/_/g, " "), count: n }))} color="#3730A3" /></Card>
    </div>
    {data.alerts.length > 0 && <Card title="Critical alerts" className="mt-3"><ul className="divide-y divide-slate-100">{data.alerts.map(a => <li key={a.id} className="py-2 text-[12px]"><Chip value="CRITICAL" /> <Chip value={a.kind} label={CATEGORY_LABELS[a.kind] || a.kind} /> <span className="ml-1 font-medium">{a.title}</span><div className="text-[11px] text-slate-500 mt-0.5">{a.message}</div></li>)}</ul></Card>}
  </div>);
}
function RiskBar({ score, band }) {
  const col = { LOW: "#16A34A", MEDIUM: "#F59E0B", HIGH: "#DC2626" }[band] || "#94A3B8";
  return <div className="flex items-center gap-2"><div className="w-24 h-2 rounded bg-slate-100 overflow-hidden"><div className="h-full" style={{ width: Math.min(100, score || 0) + "%", background: col }}></div></div><b className="text-[12px]" style={{ color: col }}>{score}</b><Chip value={band} /></div>;
}
function SevDots({ s }) {
  const order = [["CRITICAL", "bg-red-600"], ["HIGH", "bg-orange-500"], ["MEDIUM", "bg-amber-400"], ["LOW", "bg-blue-400"], ["INFO", "bg-slate-300"]];
  return <div className="flex gap-1.5 text-[11px]">{order.filter(([k]) => (s || {})[k]).map(([k, c]) => <span key={k} className="flex items-center gap-0.5"><span className={"inline-block h-2.5 w-2.5 rounded-full " + c}></span>{s[k]}</span>)}{!Object.values(s || {}).some(Boolean) && <span className="text-slate-300">none</span>}</div>;
}

function Queue({ user, go, risk, refreshKey }) {
  const [band, setBand] = useState(risk || ""); const [status, setStatus] = useState(""); const [q, setQ] = useState("");
  const { data, error } = useApi("/applications?" + (band ? "risk=" + band + "&" : "") + (status ? "status=" + status + "&" : "") + (q ? "q=" + encodeURIComponent(q) : ""), [refreshKey]);
  return (<div className="fade"><Section title={user.role === "INSTITUTION" ? "My applications" : "Verification queue - prioritised by risk"} right={<div className="flex gap-2 items-center">
    <input className={inputCls + " w-60"} placeholder="Search app no / institution / PID" value={q} onChange={e => setQ(e.target.value)} />
    <Sel value={band} onChange={setBand} all="All risk bands" options={[["HIGH", "High"], ["MEDIUM", "Medium"], ["LOW", "Low"]]} />
    <Sel value={status} onChange={setStatus} all="All statuses" options={[["VALIDATED", "Validated"], ["UNDER_REVIEW", "Under review"], ["DEFICIENCIES_COMMUNICATED", "Deficiencies communicated"], ["ROUTED_FOR_INSPECTION", "Routed for inspection"], ["CLEARED", "Cleared"], ["DRAFT,SUBMITTED", "Draft / submitted"]]} />
    {user.role === "INSTITUTION" && <Btn small tone="primary" onClick={() => go("upload")}>New application</Btn>}</div>} />
    <ErrorBox error={error} />
    <Card pad={false}><Table rows={data} onRow={r => go("report/" + r.id)} empty="No applications" cols={[
      { h: "Application", r: r => <span className="font-mono text-[12px]">{r.app_no}<div className="text-[10px] text-slate-400 font-sans">{fmt.date(r.submitted_at || r.created_at)}</div></span> },
      { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.institution_pid} · {r.institution_type} · {r.state}</div></span> },
      { h: "Category", r: r => <span>{r.checklist_name || fmt.title(r.category)}</span> },
      { h: "Risk score", r: r => <RiskBar score={r.risk_score} band={r.risk_band} /> },
      { h: "Findings", r: r => <SevDots s={r.by_severity} /> },
      { h: "Checklist", r: r => <div className="flex items-center gap-1.5"><div className="w-16 h-2 rounded bg-slate-100 overflow-hidden"><div className="h-full bg-ink-700" style={{ width: (r.completeness_pct || 0) + "%" }}></div></div><span className="text-[12px]">{r.completeness_pct}%</span></div> },
      { h: "Issuer verification", r: r => <div className="flex flex-wrap gap-1">{Object.entries(r.verification || {}).filter(([k]) => k !== "NOT_APPLICABLE").map(([k, n]) => <Chip key={k} value={k} label={(RESULT_LABELS[k] || k) + " " + n} />)}</div> },
      { h: "Docs", k: "documents" }, { h: "Status", r: r => <Chip value={r.status} /> }]} /></Card></div>);
}

function Upload({ user, go }) {
  const [category, setCategory] = useState("EOA"); const [declared, setDeclared] = useState({ intake: 300, faculty_count: 60, built_up_area_sqm: 9000, land_acres: 10.5, library_volumes: 8000, accreditation_claimed: false });
  const [app, setApp] = useState(null); const [docs, setDocs] = useState([]); const [busy, setBusy] = useState(false); const [err, setErr] = useState(null); const [docType, setDocType] = useState("");
  const [drag, setDrag] = useState(false);
  const insts = useApi(user.role === "INSTITUTION" ? "/auth/me" : "/institutions");
  const [instId, setInstId] = useState("");
  const cl = useApi("/checklists");
  const set = (k, v) => setDeclared(d => ({ ...d, [k]: v }));
  const create = async () => { setBusy(true); setErr(null); try { const a = await api.post("/applications", { category, declared, institution_id: instId ? parseInt(instId, 10) : undefined }); setApp(a); } catch (e) { setErr(e.message); } finally { setBusy(false); } };
  const send = async (files) => {
    if (!files.length) return; setBusy(true); setErr(null);
    try { const fd = new FormData(); for (const f of files) fd.append("files", f); if (docType) fd.append("doc_type", docType);
      const r = await fetch("/api/applications/" + app.id + "/documents", { method: "POST", headers: { Authorization: "Bearer " + api.token() }, body: fd });
      const data = await r.json(); if (!r.ok) throw new Error(data.detail || "upload failed"); setDocs(d => d.concat(data)); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const validate = async () => { setBusy(true); setErr(null); try { await api.post("/applications/" + app.id + "/validate"); go("report/" + app.id); } catch (e) { setErr(e.message); } finally { setBusy(false); } };
  const req = cl.data && cl.data.items.find(c => c.key === category);
  return (<div className="fade"><Section title="Submit application & documents" />
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <Card title="1 · Application details">
        {user.role !== "INSTITUTION" && insts.data && <Field label="Institution"><select className={inputCls} value={instId} onChange={e => setInstId(e.target.value)}><option value="">select</option>{insts.data.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>}
        <Field label="Category"><Sel value={category} onChange={setCategory} options={[["EOA", "Extension of Approval"], ["INCREASE_INTAKE", "EoA - increase in intake"], ["NEW_COURSE", "EoA - new course"], ["NEW_INSTITUTION", "New institution"], ["CLOSURE", "Closure"]]} /></Field>
        <div className="grid grid-cols-2 gap-2">{[["intake", "Intake (seats)"], ["faculty_count", "Faculty count"], ["built_up_area_sqm", "Built-up area (sq m)"], ["land_acres", "Land (acres)"], ["library_volumes", "Library volumes"]].map(([k, l]) => <Field key={k} label={l}><input type="number" className={inputCls} value={declared[k]} onChange={e => set(k, parseFloat(e.target.value))} disabled={!!app} /></Field>)}
          {category === "INCREASE_INTAKE" && <Field label="Proposed intake"><input type="number" className={inputCls} value={declared.proposed_intake || ""} onChange={e => set("proposed_intake", parseInt(e.target.value, 10))} disabled={!!app} /></Field>}</div>
        <label className="text-[12px] flex items-center gap-2 mb-3"><input type="checkbox" checked={!!declared.accreditation_claimed} onChange={e => set("accreditation_claimed", e.target.checked)} disabled={!!app} /> NBA accreditation claimed</label>
        {!app ? <Btn tone="primary" disabled={busy || (user.role !== "INSTITUTION" && !instId)} onClick={create}>Create application</Btn> : <div className="text-[12px] text-green-700 font-semibold">Application {app.app_no} created</div>}
        {req && <div className="mt-4 text-[11px] text-slate-500"><b>Checklist - {req.name}:</b> {req.rules.required_documents.filter(r => r.required).map(r => (cl.data.doc_types[r.doc_type] || r.doc_type)).join(", ")}</div>}
      </Card>
      <Card title="2 · Upload documents (PDF or scans)" className="lg:col-span-2">
        <ErrorBox error={err} />
        <div className="flex gap-2 items-center mb-2"><span className="text-[12px] text-slate-600">Declared type (optional - the classifier detects it anyway):</span><Sel value={docType} onChange={setDocType} all="Auto-detect" options={cl.data ? Object.entries(cl.data.doc_types) : []} /></div>
        <div onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); if (app) send(Array.from(e.dataTransfer.files)); }}
          className={"rounded-xl border-2 border-dashed p-8 text-center text-[13px] transition " + (drag ? "border-ink-700 bg-indigo-50" : "border-slate-300 bg-slate-50") + (!app ? " opacity-50" : "")}>
          <div className="text-slate-700 font-medium">Drop PDFs / JPG / PNG scans here</div><div className="text-[11px] text-slate-500 mt-1">Each file is hashed, OCR'd (RapidOCR / text layer), classified, field-extracted and checked for forgery indicators on upload.</div>
          <label className="inline-block mt-3"><input type="file" multiple className="hidden" disabled={!app || busy} onChange={e => send(Array.from(e.target.files))} /><span className={"rounded-md px-3 py-1.5 text-[12px] cursor-pointer " + (app ? "bg-ink-700 text-white" : "bg-slate-300 text-white")}>{busy ? "Processing..." : "Choose files"}</span></label></div>
        {docs.length > 0 && <div className="mt-3"><Table dense rows={docs} cols={[{ h: "File", k: "filename" }, { h: "Detected type", r: r => <span>{r.label} <span className="text-[11px] text-slate-400">{Math.round((r.classification || {}).confidence * 100)}%</span></span> }, { h: "Pages / OCR", r: r => r.pages + " · " + ((r.ocr || {}).engines || []).join("+") + " · conf " + (r.ocr || {}).confidence }, { h: "Validity", r: r => <Chip value={r.validity_status} /> }, { h: "Fields", r: r => Object.keys(r.fields || {}).length }, { h: "Flags", r: r => ((r.forensics || {}).flags || []).length ? <Chip tone="red" label={((r.forensics || {}).flags || []).length + " indicator(s)"} /> : <span className="text-slate-300">none</span> }, { h: "SHA-256", r: r => <span className="font-mono text-[10px] text-slate-400">{(r.sha256 || "").slice(0, 12)}</span> }]} />
          <div className="mt-3 flex items-center gap-3"><Btn tone="primary" disabled={busy} onClick={validate}>3 · Run validation →</Btn><span className="text-[11px] text-slate-500">Checklist completeness, expiry, consistency, institutional records, infrastructure norms, duplicates and issuer verification.</span></div></div>}
      </Card></div></div>);
}

function Checklists({ user }) {
  const { data, error, reload } = useApi("/checklists");
  const [sel, setSel] = useState(null); const [text, setText] = useState(""); const [msg, setMsg] = useState(null);
  useEffect(() => { if (data && !sel) { setSel(data.items[0].key); setText(JSON.stringify(data.items[0].rules, null, 2)); } }, [data]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const cur = data.items.find(c => c.key === sel);
  const pick = (k) => { const c = data.items.find(x => x.key === k); setSel(k); setText(JSON.stringify(c.rules, null, 2)); setMsg(null); };
  const save = async () => { try { const r = await api.put("/checklists/" + sel, { rules: JSON.parse(text) }); setMsg("Saved as " + r.version + " (audited)"); reload(); } catch (e) { setMsg("Error: " + e.message); } };
  return (<div className="fade"><Section title="Configurable checklists & norms" />
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <Card title="Checklists">{data.items.map(c => <button key={c.key} onClick={() => pick(c.key)} className={"block w-full text-left rounded-md px-3 py-2 text-[12px] mb-1 " + (sel === c.key ? "bg-ink-800 text-white" : "bg-slate-50 hover:bg-slate-100")}>{c.name}<div className={"text-[10px] " + (sel === c.key ? "text-indigo-200" : "text-slate-400")}>{c.key} · {c.version}</div></button>)}
        {cur && cur.rules.required_documents && <div className="mt-3 text-[12px]"><b>Required documents</b><ul className="mt-1 space-y-0.5">{cur.rules.required_documents.map((r, i) => <li key={i} className="flex gap-1 flex-wrap">{data.doc_types[r.doc_type] || r.doc_type}{r.required && <Chip tone="red" label="required" />}{r.must_be_valid && <Chip tone="amber" label="valid" />}{r.verify && <Chip tone="purple" label="verify with issuer" />}</li>)}</ul></div>}</Card>
      <Card title={"Rules JSON - " + (cur ? cur.name : "")} className="lg:col-span-2"><textarea className={inputCls + " font-mono text-[11px]"} rows="26" value={text} onChange={e => setText(e.target.value)} disabled={user.role !== "ADMIN"} />
        <div className="mt-2 flex items-center gap-3"><Btn tone="primary" disabled={user.role !== "ADMIN"} onClick={save}>Save new version</Btn>{msg && <span className="text-[12px]">{msg}</span>}{user.role !== "ADMIN" && <span className="text-[11px] text-slate-400">Only administrators can edit.</span>}</div>
        <div className="text-[11px] text-slate-400 mt-2">Numbers are illustrative placeholders to be aligned with the applicable Approval Process Handbook.</div></Card></div></div>);
}

function Audit({ refreshKey }) {
  const [action, setAction] = useState("");
  const { data, error } = useApi("/audit?limit=200" + (action ? "&action=" + action : ""), [refreshKey]);
  return (<div className="fade"><Section title="Audit trail (hash-chained)" right={data && <div className={"text-[12px] font-semibold px-3 py-1 rounded-md " + (data.chain.intact ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800")}>{data.chain.intact ? "Chain intact" : "Chain BROKEN"} · {data.chain.entries} entries · head {data.chain.head_hash.slice(0, 12)}...</div>} />
    <ErrorBox error={error} /><div className="mb-2"><input className={inputCls + " w-72"} placeholder="Filter by action, e.g. FINDING_DISMISSED" value={action} onChange={e => setAction(e.target.value.toUpperCase())} /></div>
    <Card pad={false}><Table dense rows={data && data.items} cols={[{ h: "#", k: "id" }, { h: "Time", r: r => fmt.dt(r.ts) }, { h: "Actor", r: r => <span>{r.actor}<div className="text-[11px] text-slate-400">{fmt.title(r.actor_role)}</div></span> }, { h: "Action", r: r => <Chip tone="slate" label={fmt.title(r.action)} /> }, { h: "Entity", r: r => (r.entity_type || "") + " " + (r.entity_id || "") }, { h: "Details", r: r => <span className="font-mono text-[11px] text-slate-600 break-all">{JSON.stringify(r.details)}</span> }, { h: "Hash", r: r => <span className="font-mono text-[10px] text-slate-400">{(r.hash || "").slice(0, 10)}<br />{"\u2191 " + (r.prev_hash || "").slice(0, 10)}</span> }]} /></Card></div>);
}

function Metrics() {
  const { data, error } = useApi("/metrics");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const fe = data.field_extraction;
  return (<div className="fade"><Section title="Prototype evaluation on the synthetic corpus" />
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
      <KPI label="Document classification accuracy" value={Math.round(data.classification_accuracy * 100) + "%"} tone="blue" sub={data.documents_evaluated + " documents"} />
      <KPI label="Planted anomalies detected (recall)" value={Math.round(data.planted_anomalies.recall * 100) + "%"} tone="green" sub={data.planted_anomalies.detected + " of " + data.planted_anomalies.total} />
      <KPI label="High-severity forgery flags on clean documents" value={data.high_severity_forgery_flags_on_clean_docs} tone={data.high_severity_forgery_flags_on_clean_docs ? "amber" : "green"} sub={data.clean_documents + " clean documents"} />
      <KPI label="Avg processing per application" value={data.avg_processing_s_per_application + " s"} tone="purple" sub={"OCR: " + (data.ocr.kind || "none") + (data.ocr.init_seconds ? " (init " + data.ocr.init_seconds + " s)" : "")} />
    </div>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Card title="Field extraction accuracy (exact match vs planted truth)"><Table dense rows={Object.entries(fe).map(([k, v]) => ({ id: k, field: k, ...v }))} cols={[{ h: "Field", r: r => fmt.title(r.field) }, { h: "Correct", k: "correct" }, { h: "Total", k: "total" }, { h: "Accuracy", r: r => <div className="flex items-center gap-2"><div className="w-24 h-2 rounded bg-slate-100 overflow-hidden"><div className="h-full bg-ink-700" style={{ width: (r.accuracy * 100) + "%" }}></div></div>{Math.round(r.accuracy * 100)}%</div> }]} /></Card>
      <Card title="Missed planted anomalies">{data.planted_anomalies.misses.length === 0 ? <div className="text-[13px] text-green-700 py-4">All planted anomalies were detected.</div> : <Table dense rows={data.planted_anomalies.misses.map((m, i) => ({ id: i, ...m }))} cols={[{ h: "Document", k: "document" }, { h: "Planted", k: "planted" }]} />}</Card>
    </div>
    <div className="text-[11px] text-slate-500 mt-3">{data.note}</div></div>);
}

function Alerts({ refreshKey }) {
  const { data, error } = useApi("/alerts", [refreshKey]);
  return (<div className="fade"><Section title="Critical alerts" /><ErrorBox error={error} />
    {!data ? <Spinner /> : data.length === 0 ? <Card><Empty text="No alerts" /></Card> : <div className="space-y-2">{data.map(a => <div key={a.id} className="rounded-lg bg-white border border-slate-200 px-4 py-3 text-[12px]"><div className="flex gap-1.5 items-center"><Chip value={a.severity} /><Chip value={a.kind} label={CATEGORY_LABELS[a.kind] || a.kind} /><span className="text-slate-400">{fmt.dt(a.created_at)}</span></div><div className="font-semibold text-slate-800 mt-1"><a className="hover:underline" href={"#/report/" + a.application_id}>{a.title}</a></div><div className="text-slate-600">{a.message}</div></div>)}</div>}</div>);
}
