/* App shell: login, role-based navigation, hash routing. */
const NAV = {
  officer: [["dashboard", "Dashboard"], ["queue", "Verification Queue"], ["upload", "Upload & Validate"], ["alerts", "Critical Alerts"], ["metrics", "Evaluation"], ["checklists", "Checklists & Norms"], ["audit", "Audit Trail"]],
  institution: [["dashboard", "My Dashboard"], ["queue", "My Applications"], ["upload", "Submit Application"]],
};

function Login({ onLogin }) {
  const { data } = useApi("/auth/demo-users");
  const [u, setU] = useState(""); const [p, setP] = useState("demo123"); const [err, setErr] = useState(null);
  const login = async (username, password) => { try { const r = await api.post("/auth/login", { username, password }); localStorage.setItem("pramaan_token", r.token); localStorage.setItem("pramaan_user", JSON.stringify(r.user)); onLogin(r.user); } catch (e) { setErr(e.message); } };
  const groups = data ? [["AICTE officials", data.filter(x => ["SCRUTINY_OFFICER", "VERIFICATION_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(x.role))], ["Institutions", data.filter(x => x.role === "INSTITUTION")]] : [];
  return (<div className="min-h-screen flex"><div className="hidden lg:flex w-[42%] bg-ink-800 text-white flex-col justify-between p-10">
    <div><div className="text-3xl font-extrabold tracking-[.15em]">PRAMAAN</div><div className="text-indigo-200 text-[13px] mt-1">AI-Powered Application Validation, Document Authentication & Compliance Verification</div>
      <ul className="mt-10 space-y-3 text-[13px] text-indigo-100">{["OCR for digital PDFs and skewed scans (RapidOCR / text layer, OpenCV deskew)", "Document-type classification and evidence-linked field extraction", "Checklist completeness, validity, cross-document and institutional-record consistency", "Forgery indicators: metadata, impossible dates, duplicates (SHA-256 / perceptual hash), ELA, outlier scoring", "Verification with issuing authorities: API, QR, digital signature - verified / mismatch / expired / unavailable / manual", "Risk-prioritised queue, explainable findings, officer decisions, hash-chained audit"].map((t, i) => <li key={i} className="flex gap-2"><span className="text-indigo-300">{"\u25B8"}</span>{t}</li>)}</ul></div>
    <div className="text-[11px] text-indigo-300">Smart India Hackathon 2026 · PS SIH26261 · prototype with synthetic documents. Outputs are decision support; forgery indicators are preliminary and human-verified; regulatory decisions remain with AICTE officers.</div></div>
    <div className="flex-1 flex items-center justify-center p-8"><div className="w-full max-w-lg">
      <h1 className="text-xl font-semibold text-slate-900">Sign in</h1><div className="text-[12px] text-slate-500 mb-4">Role-based access (JWT + RBAC). Pick a demo account or enter credentials.</div>
      <div className="flex gap-2 mb-2"><input className={inputCls} placeholder="username" value={u} onChange={e => setU(e.target.value)} /><input className={inputCls} type="password" value={p} onChange={e => setP(e.target.value)} /><Btn tone="primary" onClick={() => login(u, p)}>Login</Btn></div>
      <ErrorBox error={err} />
      {groups.map(([g, list]) => <div key={g} className="mt-4"><div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">{g}</div><div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">{list.map(x => <button key={x.username} onClick={() => login(x.username, x.password)} className="text-left rounded-lg border border-slate-200 bg-white px-3 py-2 hover:border-indigo-400 hover:bg-indigo-50 transition"><div className="text-[13px] font-medium text-slate-800">{x.name}</div><div className="text-[11px] text-slate-500">{x.designation}</div><div className="text-[10px] text-slate-400 font-mono">{x.username} / {x.password}</div></button>)}</div></div>)}
    </div></div></div>);
}

function App() {
  const [user, setUser] = useState(() => {
    if (new URLSearchParams(window.location.search).get("demo")) { localStorage.removeItem("pramaan_token"); localStorage.removeItem("pramaan_user"); return null; }
    try { return api.token() ? JSON.parse(localStorage.getItem("pramaan_user")) : null; } catch (e) { return null; }
  });
  const { parts, go } = useHash();
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => { const f = () => setUser(null); window.addEventListener("pramaan-logout", f); return () => window.removeEventListener("pramaan-logout", f); }, []);
  useEffect(() => {
    const demo = new URLSearchParams(window.location.search).get("demo");
    if (demo) { api.post("/auth/login", { username: demo, password: "demo123" }).then(r => { localStorage.setItem("pramaan_token", r.token); localStorage.setItem("pramaan_user", JSON.stringify(r.user)); setUser(r.user); }).catch(() => {}); }
  }, []);
  if (!user) return <Login onLogin={u => { setUser(u); go("dashboard"); }} />;
  const nav = NAV[user.role === "INSTITUTION" ? "institution" : "officer"];
  const page = parts[0] || "dashboard";
  const sub = parts[1];
  const logout = () => { localStorage.removeItem("pramaan_token"); localStorage.removeItem("pramaan_user"); setUser(null); go(""); };
  let body;
  switch (page) {
    case "dashboard": body = <Dashboard user={user} go={go} refreshKey={refreshKey} />; break;
    case "queue": body = <Queue user={user} go={go} risk={sub} refreshKey={refreshKey} />; break;
    case "report": body = <Report id={sub} user={user} go={go} refreshKey={refreshKey} initialTab={parts[2]} evidenceId={parts[3]} />; break;
    case "upload": body = <Upload user={user} go={go} />; break;
    case "alerts": body = <Alerts refreshKey={refreshKey} />; break;
    case "metrics": body = <Metrics />; break;
    case "checklists": body = <Checklists user={user} />; break;
    case "audit": body = <Audit refreshKey={refreshKey} />; break;
    default: body = <Empty text="Page not found" />;
  }
  return (<div className="min-h-screen flex">
    <aside className="w-[230px] shrink-0 bg-ink-800 text-white flex flex-col">
      <div className="px-5 pt-5 pb-4"><div className="text-[22px] font-extrabold tracking-[.12em]">PRAMAAN</div><div className="text-[10px] text-indigo-200 leading-tight">AI Document Validation &amp; Compliance Verification</div></div>
      <nav className="px-3 flex-1">{nav.map(([k, l]) => <a key={k} href={"#/" + k} className={"block rounded-md px-3 py-2 text-[13px] mb-0.5 " + (page === k || (page === "report" && k === "queue") ? "bg-ink-700 font-semibold" : "text-indigo-100 hover:bg-ink-900/60")}>{l}</a>)}</nav>
      <div className="px-5 py-4 text-[10px] text-indigo-200 border-t border-ink-700">SIH 2026 · PS 26261 · synthetic documents<br />Decision support only - officers decide.</div>
    </aside>
    <main className="flex-1 min-w-0">
      <header className="bg-white border-b border-slate-200 px-5 py-2.5 flex items-center justify-between gap-3 sticky top-0 z-40">
        <div className="text-[11px] text-slate-500">Every finding is evidence-linked (document · page · text) and reviewable. <button className="text-indigo-700 underline" onClick={() => setRefreshKey(k => k + 1)}>refresh</button></div>
        <div className="flex items-center gap-3 text-[12px] text-slate-600"><div className="text-right"><div className="font-semibold text-slate-800">{user.name}</div><div className="text-[11px]">{user.designation} · {ROLE_LABELS[user.role]}</div></div><Btn small onClick={logout}>Sign out</Btn></div>
      </header>
      <div className="p-5">{body}</div>
    </main></div>);
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
