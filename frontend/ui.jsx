/* Shared UI primitives, API client and hooks (React 18, Tailwind). */
const { useState, useEffect, useMemo, useRef, useCallback } = React;
// Demo/screenshot mode (?demo=<user>): skip entrance animations so headless captures are never mid-fade.
if (new URLSearchParams(window.location.search).get("demo")) { document.body.classList.add("no-anim"); }

// ------------------------------------------------------------------ API client
const api = {
  token() { return localStorage.getItem("pramaan_token"); },
  async req(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    const t = api.token();
    if (t) headers["Authorization"] = "Bearer " + t;
    const r = await fetch("/api" + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    if (r.status === 401) { localStorage.removeItem("pramaan_token"); localStorage.removeItem("pramaan_user"); window.dispatchEvent(new Event("pramaan-logout")); }
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!r.ok) { const err = new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : ("HTTP " + r.status)); err.status = r.status; throw err; }
    return data;
  },
  get(p) { return api.req("GET", p); },
  post(p, b) { return api.req("POST", p, b || {}); },
  put(p, b) { return api.req("PUT", p, b || {}); },
};

function useApi(path, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.get(path).then(d => { if (alive) { setData(d); setError(null); } }).catch(e => { if (alive) setError(e.message); }).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [path, tick].concat(deps || []));
  return { data, error, loading, reload: () => setTick(t => t + 1) };
}

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => { const f = () => setHash(window.location.hash || "#/"); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return { parts, go: (p) => { window.location.hash = "#/" + p; } };
}

// ------------------------------------------------------------------ formatting
const fmt = {
  date(iso) { if (!iso) return "-"; const d = new Date(iso); return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); },
  dt(iso) { if (!iso) return "-"; const d = new Date(iso); return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) + " " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }); },
  stage(s) { return (STAGE_LABELS[s] || (s || "").replace(/_/g, " ")); },
  title(s) { if (s === "EOA") return "EoA"; if (s === "SAC_SHC") return "SAC / SHC"; if (s === "EVC") return "EVC"; return (s || "").toLowerCase().replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()); },
  days(n) { if (n === null || n === undefined) return "-"; return n + " d"; },
};
const STAGE_LABELS = {};
const ROLE_LABELS = { INSTITUTION: "Institution", SCRUTINY_OFFICER: "Scrutiny Officer", VERIFICATION_OFFICER: "Verification Officer", BUREAU_OFFICER: "Bureau Officer", ADMIN: "Administrator" };
const CATEGORY_LABELS = { COMPLETENESS: "Completeness", EXPIRY: "Validity / expiry", CONSISTENCY: "Cross-document consistency", RECORD_MISMATCH: "Institutional record cross-check", FORGERY_INDICATOR: "Anomaly / forgery indicator", DUPLICATE: "Duplicate / reuse", VERIFICATION: "Issuer verification", INFRASTRUCTURE: "Infrastructure norms", QUALITY: "Upload quality" };
const RESULT_LABELS = { VERIFIED: "Verified", MISMATCH: "Mismatch", EXPIRED: "Expired", PENDING: "Pending", SOURCE_UNAVAILABLE: "Source unavailable", MANUAL_REVIEW: "Manual review", NOT_APPLICABLE: "n/a" };

const TONE = {
  slate: "bg-slate-100 text-slate-700", blue: "bg-blue-100 text-blue-800", green: "bg-green-100 text-green-800", amber: "bg-amber-100 text-amber-800",
  red: "bg-red-100 text-red-800", purple: "bg-violet-100 text-violet-800", teal: "bg-teal-100 text-teal-800", navy: "bg-ink-800 text-white",
};
const toneFor = (v) => ({
  DRAFT: "slate", SUBMITTED: "blue", VALIDATED: "blue", UNDER_REVIEW: "amber", DEFICIENCIES_COMMUNICATED: "amber", CLEARED: "green", ROUTED_FOR_INSPECTION: "purple",
  LOW: "green", MEDIUM: "amber", HIGH: "red", MISMATCH: "red", SOURCE_UNAVAILABLE: "slate", MANUAL_REVIEW: "amber", NOT_APPLICABLE: "slate", UNKNOWN: "slate",
  ACCEPTED: "red", DISMISSED: "slate", RESOLVED: "green", PRESENT: "green", MISSING: "red", NOT_REQUIRED: "slate", OPTIONAL: "slate", TOO_OLD: "amber", VALIDITY_UNKNOWN: "amber",
  OK: "green", SHORTFALL: "red", NO_EVIDENCE: "amber", MATCH: "green", EXCEEDS: "red", DIFFERS: "amber", PROPOSED_INCREASE: "blue", UNSUPPORTED: "red", ATTENTION: "amber",
  COMPLETENESS: "amber", CONSISTENCY: "purple", RECORD_MISMATCH: "blue", FORGERY_INDICATOR: "red", DUPLICATE: "red", INFRASTRUCTURE: "teal", QUALITY: "slate",
  IN_PROGRESS: "blue", RETURNED: "amber", APPROVED: "green", REJECTED: "red", ON_TRACK: "green", DUE_SOON: "amber", OVERDUE: "red",
  GREEN_CHANNEL: "green", HIGH_RISK: "red", NORMAL: "slate", INFO: "blue", WARNING: "amber", CRITICAL: "red", OPEN: "red", ACKNOWLEDGED: "amber", CLOSED: "slate",
  VALID: "green", EXPIRING: "amber", EXPIRED: "red", RENEWAL_SUBMITTED: "blue", RENEWED: "green", SUPERSEDED: "slate", PENDING: "amber", SUBMITTED: "blue", VERIFIED: "green",
  GREEN: "green", AMBER: "amber", RED: "red", QUEUED: "purple", SCHEDULED: "blue", COMPLETED: "green", SCRUTINY: "blue", RE_SCRUTINY: "blue", EVC: "purple", SAC_SHC: "teal", APPROVAL: "navy",
}[v] || "slate");

// ------------------------------------------------------------------ primitives
function Chip({ value, label, tone }) {
  const t = TONE[tone || toneFor(value)] || TONE.slate;
  return <span className={"inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold " + t}>{label || fmt.title(value)}</span>;
}
function Card({ title, right, children, className, pad }) {
  return (<div className={"rounded-xl bg-white shadow-sm border border-slate-200 " + (className || "")}>
    {(title || right) && <div className="flex items-center justify-between px-4 pt-3 pb-2"><h2 className="text-[13px] font-semibold text-slate-800">{title}</h2><div>{right}</div></div>}
    <div className={pad === false ? "" : "px-4 pb-4"}>{children}</div></div>);
}
function KPI({ label, value, tone, sub, onClick }) {
  const border = { blue: "border-l-blue-600", red: "border-l-red-600", amber: "border-l-amber-500", green: "border-l-green-600", purple: "border-l-violet-600", slate: "border-l-slate-400" }[tone || "blue"];
  return (<button onClick={onClick} className={"text-left rounded-xl bg-white border border-slate-200 border-l-[5px] shadow-sm px-4 py-3 hover:shadow transition " + border}>
    <div className="text-2xl font-bold text-slate-900 leading-tight">{value === null || value === undefined ? "-" : value}</div>
    <div className="text-[12px] text-slate-600 mt-0.5">{label}</div>{sub && <div className="text-[11px] text-slate-400">{sub}</div>}</button>);
}
function Btn({ children, onClick, tone, small, disabled, type, title }) {
  const t = { primary: "bg-ink-700 text-white hover:bg-ink-800", danger: "bg-red-600 text-white hover:bg-red-700", ok: "bg-green-600 text-white hover:bg-green-700", ghost: "bg-white border border-slate-300 text-slate-700 hover:bg-slate-50", amber: "bg-amber-500 text-white hover:bg-amber-600" }[tone || "ghost"];
  return <button type={type || "button"} title={title} disabled={disabled} onClick={onClick} className={"rounded-md font-medium transition disabled:opacity-40 disabled:cursor-not-allowed " + t + (small ? " px-2.5 py-1 text-[12px]" : " px-3.5 py-1.5 text-[13px]")}>{children}</button>;
}
function Field({ label, children, hint }) {
  return <label className="block text-[12px] text-slate-600 mb-3"><span className="font-medium text-slate-700">{label}</span><div className="mt-1">{children}</div>{hint && <div className="text-[11px] text-slate-400 mt-1">{hint}</div>}</label>;
}
const inputCls = "w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px] text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-200";
function Modal({ title, onClose, children, wide }) {
  return (<div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 p-4 overflow-y-auto" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className={"fade mt-6 w-full rounded-xl bg-white shadow-xl " + (wide ? "max-w-5xl" : "max-w-xl")}>
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3"><h3 className="text-[14px] font-semibold text-slate-800">{title}</h3><button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-lg leading-none">&times;</button></div>
      <div className="px-5 py-4">{children}</div></div></div>);
}
function Table({ cols, rows, onRow, empty, dense }) {
  if (!rows) return <Spinner />;
  if (!rows.length) return <Empty text={empty || "Nothing to show"} />;
  return (<div className="overflow-x-auto scroll-thin"><table className={"tbl w-full " + (dense ? "text-[12px]" : "")}><thead><tr>{cols.map((c, i) => <th key={i} style={c.w ? { width: c.w } : null}>{c.h}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={r.id || i} onClick={onRow ? () => onRow(r) : undefined} className={onRow ? "cursor-pointer" : ""}>{cols.map((c, j) => <td key={j}>{c.r ? c.r(r) : r[c.k]}</td>)}</tr>)}</tbody></table></div>);
}
function Spinner() { return <div className="py-8 text-center text-[13px] text-slate-400">Loading...</div>; }
function Empty({ text }) { return <div className="py-8 text-center text-[13px] text-slate-400">{text}</div>; }
function ErrorBox({ error }) { return error ? <div className="rounded-md bg-red-50 border border-red-200 text-red-700 text-[12px] px-3 py-2 mb-3">{error}</div> : null; }
function Bars({ items, color }) {
  const max = Math.max(1, ...items.map(i => i.count));
  return <div className="space-y-2">{items.map((i, k) => <div key={k} className="text-[12px]"><div className="flex justify-between"><span className="text-slate-700">{i.label}</span><b>{i.count}</b></div>
    <div className="h-2 rounded bg-slate-100 overflow-hidden mt-1"><div className="h-full rounded" style={{ width: (100 * i.count / max) + "%", background: i.color || color || "#2563EB" }}></div></div></div>)}</div>;
}
function Stepper({ stages, current, status }) {
  const idx = stages.findIndex(s => s.key === current);
  return (<ol className="flex items-center w-full">{stages.map((s, i) => {
    const done = status === "APPROVED" || i < idx; const cur = i === idx && status !== "APPROVED";
    return (<li key={s.key} className="flex-1 flex items-center">
      <div className="flex flex-col items-center min-w-[70px]">
        <div className={"h-7 w-7 rounded-full flex items-center justify-center text-[11px] font-bold border-2 " + (done ? "bg-green-600 border-green-600 text-white" : cur ? "bg-white border-blue-600 text-blue-700" : "bg-white border-slate-300 text-slate-400")}>{done ? "\u2713" : i + 1}</div>
        <div className={"mt-1 text-[11px] text-center " + (cur ? "font-semibold text-blue-800" : "text-slate-500")}>{s.label}<div className="text-[10px] text-slate-400">SLA {s.sla_days} d</div></div>
      </div>{i < stages.length - 1 && <div className={"h-0.5 flex-1 mx-1 mb-6 " + (done ? "bg-green-500" : "bg-slate-200")}></div>}</li>);
  })}</ol>);
}
function useToast() {
  const [msg, setMsg] = useState(null);
  const show = useCallback((m, tone) => { setMsg({ m, tone: tone || "ok" }); setTimeout(() => setMsg(null), 3500); }, []);
  const el = msg ? <div className={"fixed bottom-5 right-5 z-[60] fade rounded-lg px-4 py-2.5 text-[13px] text-white shadow-lg " + (msg.tone === "err" ? "bg-red-600" : "bg-slate-900")}>{msg.m}</div> : null;
  return { show, el };
}
function ChartBox({ type, labels, data, colors, height }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !window.Chart) return;
    const ch = new Chart(ref.current, { type: type || "bar", data: { labels, datasets: [{ data, backgroundColor: colors || "#2563EB", borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === "doughnut" } }, scales: type === "doughnut" ? {} : { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
    return () => ch.destroy();
  }, [JSON.stringify(labels), JSON.stringify(data)]);
  return <div style={{ height: height || 200 }}><canvas ref={ref}></canvas></div>;
}
function Section({ title, children, right }) { return <div className="mb-5"><div className="flex items-center justify-between mb-2"><h1 className="text-[17px] font-semibold text-slate-900">{title}</h1>{right}</div>{children}</div>; }
function Sel({ value, onChange, options, all }) {
  return <select value={value} onChange={e => onChange(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-[12px] text-slate-700">{all && <option value="">{all}</option>}{options.map(o => <option key={o[0]} value={o[0]}>{o[1]}</option>)}</select>;
}
