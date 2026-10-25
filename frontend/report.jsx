/* Application validation report: evidence-linked findings, checklist, documents, issuer verification,
   institutional records & infrastructure norms, decision panel, audit. */

const SEV_ORDER = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };

function Report({ id, user, go, refreshKey, initialTab, evidenceId }) {
  const { data, error, reload } = useApi("/applications/" + id, [refreshKey]);
  const [tab, setTab] = useState(initialTab || "findings");
  const [evidence, setEvidence] = useState(null);
  useEffect(() => {  // deep link: #/report/<id>/findings/<findingId|first> opens the evidence viewer
    if (!data || !evidenceId) return;
    const f = evidenceId === "first" ? data.findings.find(x => x.evidence && x.evidence.bbox) : data.findings.find(x => String(x.id) === String(evidenceId));
    const d = f && data.documents.find(x => x.id === f.document_id);
    if (f && d) setEvidence({ document: d, page: f.evidence.page || 1, bbox: f.evidence.bbox, title: f.title, snippet: f.evidence.snippet });
  }, [data, evidenceId]);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const a = data;
  const isOfficer = ["SCRUTINY_OFFICER", "VERIFICATION_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(user.role);
  const rerun = async () => { setBusy(true); try { await api.post("/applications/" + id + "/validate"); reload(); toast.show("Validation re-run; findings refreshed"); } catch (e) { toast.show(e.message, "err"); } finally { setBusy(false); } };
  const tabs = [["findings", "Findings (" + a.findings.length + ")"], ["checklist", "Checklist"], ["documents", "Documents (" + a.documents.length + ")"]].concat(isOfficer ? [["verification", "Issuer verification (" + a.verifications.length + ")"], ["records", "Records & norms"], ["audit", "Audit"]] : [["records", "Norms"]]);
  const s = a.summary || {};
  return (<div className="fade">{toast.el}
    <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
      <div><a href="#/queue" className="text-[11px] text-indigo-700">&larr; queue</a>
        <h1 className="text-[17px] font-semibold text-slate-900">{a.institution_name} <span className="font-mono text-[13px] text-slate-500">{a.app_no}</span></h1>
        <div className="text-[12px] text-slate-500">{a.institution_pid} · {a.institution_type} · {a.institution.district}, {a.state} · {a.checklist_name || fmt.title(a.category)} · submitted {fmt.date(a.submitted_at)} · processed in {((a.processing_ms || 0) / 1000).toFixed(1)} s{s.ocr_engines ? " · OCR: " + s.ocr_engines.join(", ") : ""}</div></div>
      <div className="flex items-center gap-2"><Chip value={a.status} /><RiskBar score={a.risk_score} band={a.risk_band} />{isOfficer && <Btn small disabled={busy} onClick={rerun}>Re-run validation</Btn>}</div>
    </div>
    <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">
      <MiniStat label="Checklist completeness" value={(s.completeness_pct ?? "-") + "%"} tone={s.completeness_pct === 100 ? "green" : "amber"} />
      <MiniStat label="Critical / high findings" value={((s.by_severity || {}).CRITICAL || 0) + " / " + ((s.by_severity || {}).HIGH || 0)} tone={((s.by_severity || {}).CRITICAL || 0) ? "red" : "slate"} />
      <MiniStat label="Issuer verified" value={(s.verification || {}).VERIFIED || 0} tone="green" />
      <MiniStat label="Issuer mismatch / expired" value={((s.verification || {}).MISMATCH || 0) + " / " + ((s.verification || {}).EXPIRED || 0)} tone={((s.verification || {}).MISMATCH || 0) ? "red" : "slate"} />
      <MiniStat label="Manual / source unavailable" value={((s.verification || {}).MANUAL_REVIEW || 0) + ((s.verification || {}).SOURCE_UNAVAILABLE || 0) + ((s.verification || {}).PENDING || 0)} tone="amber" />
    </div>
    <div className="flex gap-1 mb-3 flex-wrap">{tabs.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={"px-3 py-1.5 rounded-md text-[12px] " + (tab === k ? "bg-ink-800 text-white" : "bg-white border border-slate-300 text-slate-700")}>{l}</button>)}</div>
    <div className="grid grid-cols-1 xl:grid-cols-4 gap-3">
      <div className="xl:col-span-3">
        {tab === "findings" && <Findings a={a} user={user} isOfficer={isOfficer} onEvidence={setEvidence} onChanged={reload} toast={toast} />}
        {tab === "checklist" && <ChecklistTab a={a} onEvidence={setEvidence} />}
        {tab === "documents" && <DocumentsTab a={a} isOfficer={isOfficer} onEvidence={setEvidence} />}
        {tab === "verification" && <VerificationTab a={a} user={user} onChanged={reload} toast={toast} />}
        {tab === "records" && <RecordsTab a={a} />}
        {tab === "audit" && <Card pad={false}><Table dense rows={a.audit} cols={[{ h: "Time", r: r => fmt.dt(r.ts) }, { h: "Actor", r: r => r.actor + " (" + fmt.title(r.actor_role) + ")" }, { h: "Action", r: r => <Chip tone="slate" label={fmt.title(r.action)} /> }, { h: "Details", r: r => <span className="font-mono text-[11px] break-all">{JSON.stringify(r.details)}</span> }, { h: "Hash", r: r => <span className="font-mono text-[10px] text-slate-400">{(r.hash || "").slice(0, 10)}</span> }]} /></Card>}
      </div>
      <div className="space-y-3">
        {isOfficer && <DecisionPanel a={a} user={user} onChanged={reload} toast={toast} />}
        <Card title="Declared in application"><table className="w-full text-[12px]"><tbody>{Object.entries(a.declared || {}).map(([k, v]) => <tr key={k} className="border-b border-slate-100"><td className="py-1 text-slate-500">{fmt.title(k)}</td><td className="py-1 text-right font-medium">{Array.isArray(v) ? v.join(", ") : String(v)}</td></tr>)}</tbody></table></Card>
        <Card title="How to read this report"><ul className="text-[11px] text-slate-600 space-y-1 list-disc pl-4"><li>Every finding links to the document, page and text it came from.</li><li>Forgery indicators are preliminary signals, not proof; accept or dismiss each with a note.</li><li>Issuer verification compares extracted values with the issuing authority's record.</li><li>Clearing requires all critical findings to be reviewed.</li></ul></Card>
      </div>
    </div>
    {evidence && <EvidenceViewer e={evidence} docs={a.documents} onClose={() => setEvidence(null)} />}
  </div>);
}
function MiniStat({ label, value, tone }) { return <div className={"rounded-lg bg-white border border-slate-200 px-3 py-2 border-l-4 " + ({ green: "border-l-green-600", red: "border-l-red-600", amber: "border-l-amber-500", slate: "border-l-slate-300" }[tone || "slate"])}><div className="text-[16px] font-bold">{value}</div><div className="text-[11px] text-slate-500">{label}</div></div>; }

function Findings({ a, user, isOfficer, onEvidence, onChanged, toast }) {
  const [filter, setFilter] = useState(""); const [review, setReview] = useState(null);
  const list = a.findings.filter(f => !filter || f.category === filter).sort((x, y) => (SEV_ORDER[x.severity] - SEV_ORDER[y.severity]) || x.id - y.id);
  const cats = [...new Set(a.findings.map(f => f.category))];
  const doc = (id) => a.documents.find(d => d.id === id);
  return (<div>
    <div className="flex gap-1 flex-wrap mb-2"><button onClick={() => setFilter("")} className={"px-2.5 py-1 rounded-md text-[11px] " + (!filter ? "bg-ink-800 text-white" : "bg-white border border-slate-300")}>All</button>{cats.map(c => <button key={c} onClick={() => setFilter(c)} className={"px-2.5 py-1 rounded-md text-[11px] " + (filter === c ? "bg-ink-800 text-white" : "bg-white border border-slate-300")}>{CATEGORY_LABELS[c] || c} ({a.findings.filter(f => f.category === c).length})</button>)}</div>
    {list.length === 0 && <Card><Empty text="No findings - all checks passed" /></Card>}
    <div className="space-y-2">{list.map(f => { const d = doc(f.document_id); const hasEv = f.evidence && (f.evidence.page || f.evidence.snippet || f.evidence.bbox); return (
      <div key={f.id} className={"rounded-lg bg-white border px-4 py-3 " + (f.state === "DISMISSED" ? "border-slate-200 opacity-60" : f.severity === "CRITICAL" ? "border-red-300" : "border-slate-200")}>
        <div className="flex items-start justify-between gap-3">
          <div className="text-[12px]">
            <div className="flex items-center gap-1.5 flex-wrap"><Chip value={f.severity} /><Chip value={f.category} label={CATEGORY_LABELS[f.category] || f.category} /><span className="text-[10px] font-mono text-slate-400">{f.rule_id}</span>{f.state !== "OPEN" && <Chip value={f.state} />}<span className="text-[10px] text-slate-400">confidence {Math.round((f.confidence || 0) * 100)}%</span></div>
            <div className="font-semibold text-slate-800 mt-1">{f.title}</div>
            <div className="text-slate-600 mt-0.5">{f.explanation}</div>
            {f.evidence && f.evidence.snippet && <div className="mt-1.5 rounded bg-amber-50 border border-amber-100 px-2 py-1 text-[11px] text-slate-700 font-mono">"...{f.evidence.snippet}..."</div>}
            <div className="text-[11px] text-slate-400 mt-1">{d ? d.filename + " · " + d.label + (f.evidence.page ? " · page " + f.evidence.page : "") : "application level"}{f.evidence && f.evidence.expected !== undefined ? " · expected " + JSON.stringify(f.evidence.expected) : ""}{f.evidence && f.evidence.source ? " · source: " + f.evidence.source : ""}{f.review_note ? " · reviewer: " + f.review_note : ""}</div>
          </div>
          <div className="flex flex-col gap-1 shrink-0">
            {d && hasEv && <Btn small onClick={() => onEvidence({ document: d, page: f.evidence.page || 1, bbox: f.evidence.bbox, title: f.title, snippet: f.evidence.snippet })}>View evidence</Btn>}
            {isOfficer && f.state === "OPEN" && <Btn small tone="ok" onClick={() => setReview({ f, state: "ACCEPTED" })}>Accept</Btn>}
            {isOfficer && f.state === "OPEN" && <Btn small tone="ghost" onClick={() => setReview({ f, state: "DISMISSED" })}>Dismiss</Btn>}
            {isOfficer && f.state !== "OPEN" && <Btn small onClick={() => api.post("/findings/" + f.id + "/review", { state: "OPEN" }).then(onChanged)}>Reopen</Btn>}
          </div></div></div>); })}</div>
    {review && <ReviewModal r={review} onClose={() => setReview(null)} onDone={() => { setReview(null); onChanged(); toast.show("Review recorded; risk score recomputed"); }} onErr={m => toast.show(m, "err")} />}
  </div>);
}
function ReviewModal({ r, onClose, onDone, onErr }) {
  const [note, setNote] = useState("");
  return (<Modal title={(r.state === "ACCEPTED" ? "Accept finding" : "Dismiss finding") + " - " + r.f.title} onClose={onClose}>
    <div className="text-[12px] text-slate-600 mb-3">{r.state === "ACCEPTED" ? "Accepting confirms the issue is real and keeps it in the risk score; it will be included in the deficiency communication." : "Dismissing marks the system finding as not applicable (false positive). A reason is mandatory and audited."}</div>
    <Field label="Reviewer note"><textarea rows="3" className={inputCls} value={note} onChange={e => setNote(e.target.value)} /></Field>
    <Btn tone={r.state === "ACCEPTED" ? "ok" : "primary"} onClick={async () => { try { await api.post("/findings/" + r.f.id + "/review", { state: r.state, note }); onDone(); } catch (e) { onErr(e.message); } }}>Confirm</Btn></Modal>);
}

function ChecklistTab({ a, onEvidence }) {
  const rows = (a.summary || {}).checklist || [];
  const doc = (id) => a.documents.find(d => d.id === id);
  return (<Card pad={false}><Table rows={rows} cols={[
    { h: "Required document", r: r => <span>{r.label}{!r.required && <span className="text-[11px] text-slate-400"> (optional)</span>}</span> },
    { h: "Status", r: r => <Chip value={r.status} /> },
    { h: "Matched upload", r: r => r.document_id ? <span className="text-[12px]">{doc(r.document_id) && doc(r.document_id).filename}<div className="text-[11px] text-slate-400">classifier {Math.round(((doc(r.document_id) || {}).classification || {}).confidence * 100)}%</div></span> : <span className="text-slate-300">-</span> },
    { h: "Validity", r: r => r.document_id && doc(r.document_id) ? <span><Chip value={doc(r.document_id).validity_status} /> <span className="text-[11px] text-slate-500">{((doc(r.document_id).fields || {}).valid_till || {}).value ? "till " + fmt.date(doc(r.document_id).fields.valid_till.value) : ""}</span></span> : "-" },
    { h: "Issuer verification", r: r => r.document_id && doc(r.document_id) ? <Chip value={doc(r.document_id).verification_status} label={RESULT_LABELS[doc(r.document_id).verification_status] || doc(r.document_id).verification_status} /> : "-" },
    { h: "", r: r => r.document_id ? <Btn small onClick={() => onEvidence({ document: doc(r.document_id), page: 1, title: r.label })}>View</Btn> : null }]} /></Card>);
}

function DocumentsTab({ a, isOfficer, onEvidence }) {
  return (<div className="space-y-3">{a.documents.map(d => { const m = d.metadata || {}; const fz = d.forensics || {}; return (
    <Card key={d.id} pad={false}><div className="flex gap-4 p-4">
      <img src={"/api/documents/" + d.id + "/page/1.png"} alt="" className="w-28 h-36 object-cover object-top rounded border border-slate-200 bg-white cursor-pointer shrink-0" onClick={() => onEvidence({ document: d, page: 1, title: d.filename })} />
      <div className="flex-1 min-w-0 text-[12px]">
        <div className="flex items-center gap-1.5 flex-wrap"><b className="text-[13px] text-slate-900">{d.filename}</b><Chip tone="navy" label={d.label} /><span className="text-slate-400">classifier {Math.round((d.classification || {}).confidence * 100)}% ({(d.classification || {}).method})</span>{d.doc_type_declared && d.doc_type_declared !== d.doc_type && <Chip tone="amber" label={"declared " + d.doc_type_declared} />}<Chip value={d.validity_status} /><Chip value={d.verification_status} label={"issuer: " + (RESULT_LABELS[d.verification_status] || d.verification_status)} /></div>
        <div className="text-slate-500 mt-1">{d.pages} page(s) · {(d.mime || "").split("/")[1]} · {Math.round((d.size || 0) / 1024)} KB · OCR {(d.ocr || {}).engines ? d.ocr.engines.join("+") : "-"} conf {(d.ocr || {}).confidence}{((d.ocr || {}).pages || []).some(p => p.deskew) ? " · deskewed " + d.ocr.pages.map(p => p.deskew).filter(Boolean).join("/") + "°" : ""} · SHA-256 <span className="font-mono text-[10px]">{(d.sha256 || "").slice(0, 16)}</span> · pHash <span className="font-mono text-[10px]">{(d.phash || "").slice(0, 16)}</span>{fz.anomaly_score !== undefined ? " · outlier score " + fz.anomaly_score : ""}</div>
        {isOfficer && <div className="text-slate-500 mt-0.5">Metadata: {m.producer || m.software || "-"}{m.creator ? " / " + m.creator : ""}{m.creation_date ? " · created " + fmt.dt(m.creation_date) : ""}{m.mod_date ? " · modified " + fmt.dt(m.mod_date) : ""}{m.incremental_updates ? " · " + m.incremental_updates + " incremental update(s)" : ""}{m.has_signature ? " · digital signature present" : ""}{fz.qr ? " · QR: " + fz.qr.payload : ""}</div>}
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-6">{Object.entries(d.fields || {}).filter(([k]) => k !== "issuer" && k !== "signature").map(([k, v]) => <div key={k} className="flex justify-between gap-2 border-b border-slate-100 py-0.5"><span className="text-slate-500">{fmt.title(k)}</span><span className="font-medium text-right truncate cursor-pointer hover:underline" title="show on page" onClick={() => onEvidence({ document: d, page: v.page || 1, bbox: v.bbox, title: fmt.title(k) + ": " + JSON.stringify(v.value), snippet: v.snippet })}>{typeof v.value === "object" ? v.value.value + " " + v.value.unit : String(v.value)} <span className="text-[10px] text-slate-400">p{v.page}</span></span></div>)}</div>
        {(fz.flags || []).length > 0 && isOfficer && <div className="mt-2 flex flex-wrap gap-1">{fz.flags.map((f, i) => <Chip key={i} tone="red" label={f.title} />)}</div>}
        <div className="mt-2 flex gap-3 text-[11px]"><a className="text-indigo-700 underline" href={"/api/documents/" + d.id + "/file"} target="_blank">Open original</a><button className="text-indigo-700 underline" onClick={() => onEvidence({ document: d, page: 1, title: d.filename, text: d.text_preview })}>View page & extracted text</button></div>
      </div></div></Card>); })}</div>);
}

function VerificationTab({ a, user, onChanged, toast }) {
  const doc = (id) => a.documents.find(d => d.id === id) || {};
  const canVerify = ["VERIFICATION_OFFICER", "SCRUTINY_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(user.role);
  const rv = async (id) => { try { await api.post("/documents/" + id + "/verify"); onChanged(); toast.show("Re-verification requested"); } catch (e) { toast.show(e.message, "err"); } };
  return (<Card pad={false}><Table rows={a.verifications} empty="No verification requests" cols={[
    { h: "Document", r: r => <span>{doc(r.document_id).filename}<div className="text-[11px] text-slate-400">{doc(r.document_id).label}</div></span> },
    { h: "Issuing authority / source", r: r => <span>{r.source}<div className="text-[11px] text-slate-400">{r.method}{r.response && r.response.endpoint ? " · " + r.response.endpoint : ""}</div></span> },
    { h: "Reference sent", r: r => <span className="font-mono text-[11px]">{(r.request || {}).reference || (r.request || {}).payload || "-"}</span> },
    { h: "Result", r: r => <Chip value={r.result} label={RESULT_LABELS[r.result] || r.result} /> },
    { h: "Detail", r: r => <span className="text-[12px]">{r.detail}{r.response && r.response.record && <div className="text-[10px] text-slate-400 font-mono mt-0.5">source record: {JSON.stringify(r.response.record)}</div>}</span> },
    { h: "When", r: r => fmt.dt(r.responded_at || r.requested_at) },
    { h: "", r: r => canVerify && <Btn small onClick={() => rv(r.document_id)}>Re-verify</Btn> }]} /></Card>);
}

function RecordsTab({ a }) {
  const s = a.summary || {};
  return (<div className="space-y-3">
    <Card title="Cross-check with institutional records in AICTE systems" pad={false}><Table dense rows={(s.records || []).map((r, i) => ({ id: i, ...r }))} empty="No record checks for this category" cols={[{ h: "Item", k: "item" }, { h: "On record", r: r => String(r.on_record ?? "-") }, { h: "Declared", r: r => String(r.declared ?? "-") }, { h: "Status", r: r => <Chip value={r.status} /> }, { h: "Note", r: r => r.note || "" }]} /></Card>
    <Card title="Infrastructure compliance assistance (configurable norms)" pad={false}><Table dense rows={(s.infrastructure || []).map((r, i) => ({ id: i, ...r }))} empty="No infrastructure norms evaluated" cols={[{ h: "Item", k: "item" }, { h: "Norm", k: "norm" }, { h: "Declared", r: r => String(r.declared ?? "-") }, { h: "Evidence (from documents)", r: r => String(r.evidence ?? "-") }, { h: "Source", k: "source" }, { h: "Status", r: r => <Chip value={r.status} /> }]} /></Card>
    <div className="text-[11px] text-slate-500">Norm values are illustrative placeholders; align with the applicable Approval Process Handbook in Admin &gt; Checklists. Shortfalls are flagged for additional evidence or physical inspection - never auto-rejected.</div></div>);
}

function DecisionPanel({ a, user, onChanged, toast }) {
  const [action, setAction] = useState("COMMUNICATE_DEFICIENCIES"); const [note, setNote] = useState("");
  const can = ["SCRUTINY_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(user.role);
  const openCrit = a.findings.filter(f => f.severity === "CRITICAL" && f.state === "OPEN").length;
  const send = async () => { try { await api.post("/applications/" + a.id + "/decision", { action, note }); onChanged(); toast.show("Decision recorded"); setNote(""); } catch (e) { toast.show(e.message, "err"); } };
  return (<Card title="Officer decision (human-in-the-loop)">
    {a.decision && <div className="mb-3 rounded-md bg-slate-50 border border-slate-200 px-3 py-2 text-[12px]"><Chip value={a.status} /><div className="mt-1 text-slate-700">{a.decision.note}</div><div className="text-[11px] text-slate-400">{a.decision.by} · {fmt.dt(a.decision.at)}</div></div>}
    {can ? <div>
      <Field label="Action"><Sel value={action} onChange={setAction} options={[["CLEAR", "Clear - no deficiencies"], ["COMMUNICATE_DEFICIENCIES", "Communicate deficiencies to institution"], ["ROUTE_INSPECTION", "Route for physical inspection"], ["HOLD", "Hold - under review"]]} /></Field>
      <Field label="Recorded note (mandatory)"><textarea rows="3" className={inputCls} value={note} onChange={e => setNote(e.target.value)} /></Field>
      {action === "CLEAR" && openCrit > 0 && <div className="text-[11px] text-red-700 mb-2">{openCrit} critical finding(s) still open - review them before clearing.</div>}
      <Btn tone="primary" disabled={note.trim().length < 10} onClick={send}>Record decision</Btn>
      <div className="text-[11px] text-slate-400 mt-2">The system flags; the officer decides. Every decision is hash-chained in the audit trail.</div></div>
      : <div className="text-[12px] text-slate-500">Decisions are recorded by Scrutiny / Bureau officers.</div>}</Card>);
}

function EvidenceViewer({ e, docs, onClose }) {
  const d = e.document;
  const [page, setPage] = useState(e.page || 1);
  const hl = e.bbox && page === (e.page || 1) ? "?highlight=" + e.bbox.map(v => Math.round(v)).join(",") : "";
  return (<Modal wide title={"Evidence - " + d.filename + (e.title ? " · " + e.title : "")} onClose={onClose}>
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="md:col-span-2"><div className="rounded-lg border border-slate-200 bg-slate-100 overflow-auto scroll-thin" style={{ maxHeight: "70vh" }}><img src={"/api/documents/" + d.id + "/page/" + page + ".png" + hl} alt="page" className="w-full" /></div>
        {d.pages > 1 && <div className="flex gap-1 mt-2 items-center text-[12px]"><Btn small disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</Btn><span>page {page} / {d.pages}</span><Btn small disabled={page >= d.pages} onClick={() => setPage(p => p + 1)}>Next</Btn></div>}</div>
      <div className="text-[12px] space-y-2">
        <div><b>Document:</b> {d.label}<div className="text-slate-500">{d.filename} · {d.pages} page(s) · OCR {(d.ocr || {}).engines ? d.ocr.engines.join("+") : "-"} (conf {(d.ocr || {}).confidence})</div></div>
        {e.bbox && <div className="text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">Highlighted region = the text the finding was derived from (page {e.page}).</div>}
        {e.snippet && <div><b>Extracted text</b><div className="font-mono text-[11px] bg-slate-50 border border-slate-200 rounded p-2 mt-1">...{e.snippet}...</div></div>}
        {e.text && <div><b>Recognised text (preview)</b><pre className="text-[10px] bg-slate-50 border border-slate-200 rounded p-2 mt-1 whitespace-pre-wrap max-h-64 overflow-auto">{e.text}</pre></div>}
        <a className="text-indigo-700 underline" href={"/api/documents/" + d.id + "/file"} target="_blank">Open original file</a>
      </div></div></Modal>);
}
