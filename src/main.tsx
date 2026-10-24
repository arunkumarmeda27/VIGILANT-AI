import React, { createContext, useContext, useMemo, useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, ClipboardCheck, Eye, FileCheck2, FileText, LayoutDashboard, ListChecks, Menu, Search, ShieldCheck, UserRound, XCircle, Lock, Mail, Loader2 } from 'lucide-react';
import './styles.css';

// --- Types ---
type DS = 'Not Submitted' | 'Received' | 'Validation Pending' | 'Verified' | 'Mismatch Detected' | 'Source Unavailable' | 'Manual Review Required';
type RS = 'Open' | 'In Review' | 'Resolved' | 'Awaiting Evidence';
type AS = 'Awaiting Scrutiny' | 'Missing Documents' | 'Discrepancies' | 'Manual Review' | 'Ready for Further Scrutiny';
type Doc = { id: string; name: string; required: boolean; status: DS; date: string; fields: Record<string, string>; comment: string };
type Finding = { id: string; type: 'Cross-document discrepancy' | 'Potential anomaly' | 'Missing evidence'; title: string; priority: 'High' | 'Medium' | 'Low'; status: RS; documents: string[]; field?: string; first?: string; second?: string; explanation: string; action: string; assignee: string; comments: string[] };
type App = { id: string; institution: string; category: string; submitted: string; status: AS; reviewer: string; nextAction: string; documents: Doc[]; findings: Finding[] };
type Audit = { id: string; applicationId: string; time: string; actor: string; action: string };
type User = { id: number; full_name: string; email: string; role: string; is_active: boolean };

const initial: App[] = [
  { id: 'APP-2026-00418', institution: 'Saraswati Institute of Technology', category: 'Illustrative: New programme approval', submitted: '18 Oct 2026', status: 'Discrepancies', reviewer: 'Ananya Rao', nextAction: 'Review registration-number evidence', documents: [{ id: 'd1', name: 'Application Form.pdf', required: true, status: 'Verified', date: '18 Oct 2026', fields: { 'Institution name': 'Saraswati Institute of Technology', 'Registration number': 'GOV-19248', 'Address': 'Mysuru, Karnataka', 'Document identifier': 'APP-418' }, comment: 'Simulated extracted values.' }, { id: 'd2', name: 'Governance Certificate.pdf', required: true, status: 'Mismatch Detected', date: '17 Oct 2026', fields: { 'Institution name': 'Saraswati Institute of Technology', 'Registration number': 'GOV-19284', 'Issue date': '16 May 2020', 'Document identifier': 'GC-19284' }, comment: 'Simulated extraction. Identifier differs from application form.' }, { id: 'd3', name: 'Faculty Register.pdf', required: true, status: 'Validation Pending', date: '16 Oct 2026', fields: { 'Institution name': 'Saraswati Institute of Technology', 'Issue date': '01 Oct 2026' }, comment: 'Simulated extraction awaiting review.' }, { id: 'd4', name: 'Land Ownership Record.pdf', required: false, status: 'Received', date: '15 Oct 2026', fields: { 'Address': 'Mysuru, Karnataka', 'Document identifier': 'LAND-091' }, comment: 'Receipt confirmed; validation has not completed.' }], findings: [{ id: 'F-418-01', type: 'Cross-document discrepancy', title: 'Registration number differs across records', priority: 'High', status: 'Open', documents: ['Application Form.pdf', 'Governance Certificate.pdf'], field: 'Registration number', first: 'GOV-19248', second: 'GOV-19284', explanation: 'The simulated extracted registration number differs between the application form and certificate. This is a review signal, not a confirmed violation.', action: 'Request authoritative correction or supporting evidence.', assignee: 'Ananya Rao', comments: ['Initial deterministic comparison created.'] }, { id: 'F-418-02', type: 'Potential anomaly', title: 'Certificate issue date needs contextual review', priority: 'Medium', status: 'In Review', documents: ['Governance Certificate.pdf'], explanation: 'The issue date predates the application by more than six years. Validity cannot be inferred from this date alone.', action: 'Confirm the certificate remains applicable.', assignee: 'Unassigned', comments: [] }] },
  { id: 'APP-2026-00412', institution: 'National College of Engineering', category: 'Illustrative: Extension of approval', submitted: '15 Oct 2026', status: 'Ready for Further Scrutiny', reviewer: 'Rahul Mehta', nextAction: 'Continue human scrutiny', documents: [{ id: 'd5', name: 'Application Form.pdf', required: true, status: 'Verified', date: '15 Oct 2026', fields: { 'Institution name': 'National College of Engineering', 'Registration number': 'NCE-4421', 'Address': 'Pune, Maharashtra' }, comment: 'Simulated values match the application form.' }, { id: 'd6', name: 'Governance Certificate.pdf', required: true, status: 'Verified', date: '14 Oct 2026', fields: { 'Institution name': 'National College of Engineering', 'Registration number': 'NCE-4421', 'Document identifier': 'GC-4421' }, comment: 'Simulated values match the application form.' }], findings: [] },
  { id: 'APP-2026-00397', institution: 'Coastal Polytechnic', category: 'Illustrative: New programme approval', submitted: '11 Oct 2026', status: 'Missing Documents', reviewer: 'Unassigned', nextAction: 'Obtain faculty register', documents: [{ id: 'd7', name: 'Application Form.pdf', required: true, status: 'Verified', date: '11 Oct 2026', fields: { 'Institution name': 'Coastal Polytechnic', 'Registration number': 'CP-7812' }, comment: 'Simulated extracted values.' }, { id: 'd8', name: 'Faculty Register.pdf', required: true, status: 'Not Submitted', date: '—', fields: {}, comment: 'No file received.' }], findings: [{ id: 'F-397-01', type: 'Missing evidence', title: 'Required faculty register was not submitted', priority: 'High', status: 'Awaiting Evidence', documents: ['Faculty Register.pdf'], explanation: 'This illustrative checklist item is configured as required for the selected demo category.', action: 'Request the missing evidence before review continues.', assignee: 'Unassigned', comments: [] }] },
  { id: 'APP-2026-00381', institution: 'Aravalli Technical University', category: 'Illustrative: Extension of approval', submitted: '08 Oct 2026', status: 'Manual Review', reviewer: 'Priya Shah', nextAction: 'Complete source verification', documents: [{ id: 'd9', name: 'Application Form.pdf', required: true, status: 'Verified', date: '08 Oct 2026', fields: { 'Institution name': 'Aravalli Technical University', 'Registration number': 'ATU-3307' }, comment: 'Simulated extracted values.' }, { id: 'd10', name: 'Ownership Record.pdf', required: true, status: 'Source Unavailable', date: '07 Oct 2026', fields: { 'Document identifier': 'OR-3307' }, comment: 'The simulated source is unavailable.' }], findings: [{ id: 'F-381-01', type: 'Potential anomaly', title: 'Source verification is unavailable', priority: 'Medium', status: 'In Review', documents: ['Ownership Record.pdf'], explanation: 'No source response is available in this frontend demonstration.', action: 'Perform authorized manual verification.', assignee: 'Priya Shah', comments: [] }] }
];
const reviewers = ['Unassigned', 'Ananya Rao', 'Rahul Mehta', 'Priya Shah'];

// --- Auth Context ---
type AuthState = {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, pass: string) => Promise<void>;
  logout: () => void;
};
const AuthContext = createContext<AuthState | null>(null);
const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
};

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function syncUser() {
      if (!token) {
        setIsLoading(false);
        return;
      }
      try {
        const res = await fetch(`${API_URL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          setUser(await res.json());
        } else {
          logout();
        }
      } catch (e) {
        logout();
      } finally {
        setIsLoading(false);
      }
    }
    syncUser();
  }, [token]);

  const login = async (email: string, pass: string) => {
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: pass }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Login failed');
    }
    const data = await res.json();
    localStorage.setItem('token', data.access_token);
    setToken(data.access_token);
  };

  const logout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// --- App Store ---
type StoreState = { apps: App[]; audits: Audit[]; update: (a: string, f: string, c: Partial<Finding>) => void };
const Store = createContext<StoreState | null>(null);
const useStore = () => {
  const context = useContext(Store);
  if (!context) throw new Error('useStore must be used within StoreProvider');
  return context;
};

function StoreProvider({ children }: { children: React.ReactNode }) {
  const [apps, setApps] = useState(initial);
  const [audits, setAudits] = useState<Audit[]>([{ id: 'a1', applicationId: 'APP-2026-00418', time: '23 Oct 2026, 10:42', actor: 'System demo', action: 'Configured cross-document comparison completed.' }, { id: 'a2', applicationId: 'APP-2026-00418', time: '23 Oct 2026, 10:16', actor: 'Ananya Rao', action: 'Opened application for review.' }]);
  const update = (id: string, fid: string, c: Partial<Finding>) => {
    setApps(x => x.map(a => a.id !== id ? a : { ...a, findings: a.findings.map(f => f.id !== fid ? f : { ...f, ...c }) }));
    setAudits(x => [{ id: crypto.randomUUID(), applicationId: id, time: '24 Oct 2026, 09:30', actor: 'Verification Officer (demo)', action: `Updated finding ${fid}: ${c.status ? 'status ' + c.status : 'assignment or comment'}.` }, ...x]);
  };
  return <Store.Provider value={{ apps, audits, update }}>{children}</Store.Provider>
}

const slug = (s: string) => s.toLowerCase().replaceAll(' ', '-');
function Tag({ children }: { children: string }) { return <span className={`status ${slug(children)}`}>{children}</span> }
function Brand() { return <Link className="brand" to="/"><span className="mark"><ShieldCheck size={19} /></span><span>VIGILANT <b>AI</b></span></Link> }
const nav = [['/dashboard', LayoutDashboard, 'Overview'], ['/applications', FileText, 'Applications'], ['/review-queue', ListChecks, 'Review Queue'], ['/verification', FileCheck2, 'Document Verification'], ['/compliance', ClipboardCheck, 'Compliance Assessment'], ['/reports', FileText, 'Validation Reports'], ['/audit-trail', ShieldCheck, 'Audit History'], ['/administration', UserRound, 'Administration']] as const;

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const { user, logout } = useAuth();
  return (
    <div className="app-shell">
      <aside className={open ? 'open' : ''}>
        <Brand />
        <p className="workspace">REVIEW WORKSPACE <span className="role-tag">{user?.role || 'GUEST'}</span></p>
        <nav>
          {nav.map(([to, I, label]) => (
            <NavLink key={to} to={to} onClick={() => setOpen(false)}><I size={18} />{label}</NavLink>
          ))}
        </nav>
        <div className="sidebar-user">
          <span className="avatar">{user?.full_name?.substring(0, 2).toUpperCase() || '??'}</span>
          <span><b>{user?.full_name || 'Unknown'}</b><small>{user?.role || 'Guest'}</small></span>
          <button className="logout-btn" onClick={logout} title="Sign out"><XCircle size={14} /></button>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <button className="menu" aria-label="Open navigation" onClick={() => setOpen(!open)}><Menu /></button>
          <div><p className="crumb">Workspace / {title}</p><h1>{title}</h1></div>
          <Tag>Demo data</Tag>
        </header>
        <main className="app-content">
          <p className="demo-notice">Frontend demonstration · All extraction, verification, anomaly and compliance outcomes are deterministic simulated data. Human review is required.</p>
          {children}
        </main>
      </div>
    </div>
  );
}

function Heading({ title, text }: { title: string; text: string }) { return <div className="section-heading"><div><h2>{title}</h2><p>{text}</p></div></div> }
function Empty({ text }: { text: string }) { return <div className="empty"><XCircle size={28} /><h3>Nothing to show</h3><p>{text}</p></div> }
function AppTable({ rows }: { rows: App[] }) { return <div className="table-wrap"><table><thead><tr><th>Application</th><th>Institution</th><th>Category</th><th>Completeness</th><th>Unresolved</th><th>Reviewer</th><th>Next action</th><th>Status</th></tr></thead><tbody>{rows.map(a => { const missing = a.documents.filter(d => d.status === 'Not Submitted').length; return <tr key={a.id}><td><Link className="table-link" to={`/applications/${a.id}`}>{a.id}</Link></td><td>{a.institution}</td><td>{a.category}</td><td>{missing ? `${missing} missing` : 'Received'}</td><td>{a.findings.filter(f => f.status !== 'Resolved').length}</td><td>{a.reviewer}</td><td>{a.nextAction}</td><td><Tag>{a.status}</Tag></td></tr> })}</tbody></table></div> }

function Home() { return <><header className="public-header"><Brand /><div className="header-actions"><Link className="text-link" to="/login">Sign in</Link><Link className="button primary" to="/dashboard">Open dashboard <ArrowRight size={16} /></Link></div></header><main><section className="hero"><div><p className="eyebrow">SIH26261 · evidence-led review</p><h1>Application validation that keeps people in the decision loop.</h1><p className="lede">VIGILANT AI is a frontend prototype for reviewing institutional application evidence, comparing documents, and organising manual scrutiny.</p><Link className="button primary" to="/dashboard">Open verification workspace <ArrowRight size={16} /></Link></div><div className="hero-panel"><p className="eyebrow">Simulated finding</p><h3>Registration mismatch</h3><p>Source-linked comparison and a recommended human action, never an automatic decision.</p></div></section></main></> }

function Dashboard() { const { apps, audits } = useStore(); const m = [['Total applications', apps.length, '/applications'], ['Awaiting scrutiny', apps.filter(a => a.status === 'Awaiting Scrutiny').length, '/applications'], ['Missing documents', apps.filter(a => a.status === 'Missing Documents').length, '/applications?status=Missing'], ['Cross-document discrepancies', apps.filter(a => a.status === 'Discrepancies').length, '/applications?status=Discrepancies'], ['Manual review', apps.filter(a => a.status === 'Manual Review').length, '/review-queue'], ['Ready for further scrutiny', apps.filter(a => a.status === 'Ready for Further Scrutiny').length, '/applications']]; return <Shell title="Overview"><div className="metric-grid six">{m.map(([l, v, to]) => <Link className="metric metric-link" to={to as string} key={l as string}><span>{l}</span><strong>{v}</strong><small>Open filtered view</small></Link>)}</div><section className="content-section"><Heading title="Priority review items" text="Applications with unresolved evidence or simulated validation signals." /><AppTable rows={apps.filter(a => a.findings.some(f => f.status !== 'Resolved'))} /></section><section className="content-section activity"><Heading title="Recent application activity" text="Frontend demonstration history." />{audits.slice(0, 4).map(x => <div className="audit-row" key={x.id}><b>{x.action}</b><small>{x.applicationId} · {x.actor} · {x.time}</small></div>)}</section></Shell> }

function Applications() { const { apps } = useStore(); const [q, setQ] = useState(''); const [status, setStatus] = useState('All'); const [sort, setSort] = useState('Newest'); const list = useMemo(() => apps.filter(a => (status === 'All' || a.status === status) && (a.id + a.institution + a.category).toLowerCase().includes(q.toLowerCase())).sort((a, b) => sort === 'Institution' ? a.institution.localeCompare(b.institution) : b.id.localeCompare(a.id)), [apps, q, status, sort]); return <Shell title="Applications"><section className="content-section"><Heading title="Application register" text="Illustrative categories and configurable document requirements; not official AICTE regulations." /><div className="filters"><label className="search"><Search size={17} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Search ID, institution or category" /></label><select aria-label="Filter application status" value={status} onChange={e => setStatus(e.target.value)}><option>All</option>{Array.from(new Set(apps.map(a => a.status))).map(s => <option key={s}>{s}</option>)}</select><select aria-label="Sort applications" value={sort} onChange={e => setSort(e.target.value)}><option>Newest</option><option>Institution</option></select></div>{list.length ? <AppTable rows={list} /> : <Empty text="No application matches these filters." />}</section></Shell> }

function Detail() { const { id = '' } = useParams(); const { apps } = useStore(); const app = apps.find(a => a.id === id); const [tab, setTab] = useState('Overview'); if (!app) return <Navigate to="/applications" replace />; const tabs = ['Overview', 'Documents', 'Findings', 'Compliance', 'Verification', 'Audit History']; return <Shell title="Application details"><section className="detail-head"><div><p className="eyebrow">{app.category}</p><h2>{app.id}</h2><p>{app.institution} · Submitted {app.submitted}</p></div><Tag>{app.status}</Tag></section><div className="tabs" role="tablist">{tabs.map(t => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>{tab === 'Overview' && <Overview app={app} />} {tab === 'Documents' && <Documents app={app} />} {tab === 'Findings' && <Findings app={app} />} {tab === 'Compliance' && <Compliance app={app} />} {tab === 'Verification' && <Verification app={app} />} {tab === 'Audit History' && <Audit app={app} />}</Shell> }

function Overview({ app }: { app: App }) { return <div className="detail-grid"><section className="content-section"><Heading title="Scrutiny summary" text="No automatic approval or rejection is generated." /><dl><dt>Current reviewer</dt><dd>{app.reviewer}</dd><dt>Documents</dt><dd>{app.documents.length} configured checklist items</dd><dt>Next required action</dt><dd>{app.nextAction}</dd></dl></section><section className="finding-card"><Heading title="Current review signal" text={app.findings[0]?.title || 'No unresolved findings.'} /><p>{app.findings[0]?.explanation || 'Configured comparisons currently contain a matching-value example.'}</p></section></div> }

function Documents({ app }: { app: App }) { const nav = useNavigate(); return <section className="content-section"><Heading title="Category-based document checklist" text="Illustrative requirements for this demo category. Receipt and verification are shown separately." /><div className="doc-list">{app.documents.map(d => <div key={d.id}><FileText size={20} /><span><b>{d.name}{d.required ? '' : ' (optional)'}</b><small>{d.date} · {d.status === 'Verified' ? 'Successful simulated validation' : 'Submission / validation state'}</small></span><Tag>{d.status}</Tag><button className="icon-button" aria-label={`Inspect ${d.name}`} onClick={() => nav(`/applications/${app.id}/documents/${d.id}`)}><Eye size={17} /></button></div>)}</div></section> }

function DocumentView() { const { id, docId } = useParams(); const { apps } = useStore(); const app = apps.find(a => a.id === id); const doc = app?.documents.find(d => d.id === docId); if (!app || !doc) return <Navigate to="/applications" replace />; return <Shell title="Document inspection"><section className="detail-head"><div><p className="eyebrow">Representative sample · no actual file/OCR processing</p><h2>{doc.name}</h2><p>{app.id} · submitted {doc.date}</p></div><Tag>{doc.status}</Tag></section><div className, "detail-grid"><section className="content-section document-preview"><FileText size={42} /><h3>Document preview unavailable in demo</h3><p>A secure file viewer will be supplied by future document storage integration.</p></section><section className="content-section"><Heading title="Simulated extracted fields" text={doc.comment} /><dl>{Object.entries(doc.fields).map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>)}</dl></section></div></Shell> }

function Findings({ app }: { app: App }) { return <section className="content-section"><Heading title="Cross-document comparisons and anomaly signals" text="A warning is not a confirmed fraud or regulatory violation." /><>{app.findings.length ? app.findings.map(f => <FindingCard key={f.id} app={app} f={f} />) : <Empty text="Matching simulated document values; no finding requires action." />}</section> }

function FindingCard({ app, f }: { app: App; f: Finding }) { const { update } = useStore(); const [c, setC] = useState(''); return <article className="finding-card"><div className="finding-title"><AlertTriangle /><div><p className="eyebrow">{f.type} · simulated</p><h2>{f.title}</h2></div><Tag>{f.priority}</Tag></div>{f.field && <div className="comparison"><b>{f.field}</b><span>{f.documents[0]}: <mark>{f.first}</mark></span><span>{f.documents[1]}: <mark>{f.second}</mark></span></div>}<p>{f.explanation}</p><dl><dt>Related evidence</dt><dd>{f.documents.join(' · ')}</dd><dt>Suggested next action</dt><dd>{f.action}</dd></dl><div className="review-controls"><label>Reviewer<select value={f.assignee} onChange={e => update(app.id, f.id, { assignee: e.target.value })}>{reviewers.map(x => <option key={x}>{x}</option>)}</select></label><label>Status<select value={f.status} onChange={e => update(app.id, f.id, { status: e.target.value as RS })}>{(['Open', 'In Review', 'Awaiting Evidence', 'Resolved'] as RS[]).map(x => <option key={x}>{x}</option>)}</select></label></div><div className="comment-row"><input aria-label="Add review comment" value={c} onChange={e => setC(e.target.value)} placeholder="Add a demo reviewer comment" /><button className="button secondary" disabled={!c.trim()} onClick={() => { update(app.id, f.id, { comments: [...f.comments, c] }); setC('') }}>Add comment</button></div>{f.comments.map((x, i) => <small className="comment" key={i}>Reviewer note: {x}</small>)}</article> }

function Verification({ app }: { app: App }) { return <section className="content-section"><Heading title="Authorized-source verification" text="No network request is made; source outcomes are structured for future authorized integration." /><>{app.documents.map(d => <div key={d.id}><FileCheck2 size={22} /><div><b>{d.name}</b><p>Intended source: issuing authority · Method: future reference-ID lookup · Reference: {d.id.toUpperCase()}</p></div><Tag>{d.status === 'Source Unavailable' ? 'Source Unavailable' : d.status === 'Mismatch Detected' ? 'Mismatch' : d.status === 'Verified' ? 'Verified' : 'Pending'}</Tag></div>)}</section></Shell> }

function Compliance({ app }: { app: App }) { const rules = [['DEMO-DOC-01', 'Illustrative required evidence is present', app.documents.some(d => d.status === 'Not Submitted') ? 'Insufficient Evidence' : 'Partially Verified'], ['DEMO-CON-02', 'Illustrative registration fields are consistent', app.findings.some(f => f.field === 'Registration number') ? 'Pending Manual Review' : 'Compliant'], ['DEMO-INF-01', 'Illustrative infrastructure evidence review', app.documents.some(d => d.name.includes('Land') || d.name.includes('Ownership')) ? 'Partially Verified' : 'Insufficient Evidence']]; return <section className="content-section"><Heading title="Requirement-by-requirement assessment" text="These are illustrative demo rules, not verified AICTE regulations." /><div className="rule-list">{rules.map(([id, desc, result]) => <div key={id}><b>{id}</b><span>{desc}<small>Supporting evidence: configured application documents</small></span><Tag>{result}</Tag><em>Human evidence review required</em></div>)}</div></section></Shell> }

function Audit({ app }: { app: App }) { const { audits } = useStore(); return <section className="content-section"><Heading title="Demonstration audit history" text="Frontend state only; this is not a secure or immutable production audit log." /><>{audits.filter(a => a.applicationId === app.id).map(x => <div className="audit-row" key={x.id}><b>{x.action}</b><small>{x.applicationId} · {x.actor} · {x.time}</small></div>)}</section></Shell> }

function ReviewQueue() { const { apps } = useStore(); const [p, setP] = useState('All'); const data = apps.flatMap(a => a.findings.map(f => ({ a, f }))).filter(x => p === 'All' || x.f.priority === p); return <Shell title="Human review queue"><section className="content-section"><Heading title="Consolidated attention queue" text="Assignments and statuses update the shared in-memory demo state." /><select aria-label="Filter priority" value={p} onChange={e => setP(e.target.value)}><option>All</option><option>High</option><option>Medium</option><option>Low</option></select><div className="table-wrap"><table><thead><tr><th>Application</th><th>Institution</th><th>Issue</th><th>Priority</th><th>Reviewer</th><th>Status</th><th>Action</th></tr></thead><tbody>{data.map(({ a, f }) => <tr key={f.id}><td><Link className="table-link" to={`/applications/${a.id}`}>{a.id}</Link></td><td>{a.institution}</td><td>{f.title}</td><td><Tag>{f.priority}</Tag></td><td>{f.assignee}</td><td>{f.status}</td><td><Link className="table-link" to={`/applications/${a.id}`}>Review</Link></td></tr>)}</tbody></table></div></section></Shell> }

function GlobalVerification() { const { apps } = useStore(); return <Shell title="Document Verification"><section className="content-section"><Heading title="Simulated verification workspace" text="Future integrations should call authorized services from a backend, never this browser-only demo." /><>{apps.flatMap(a => a.documents.map(d => <Link className="verification-card" to={`/applications/${a.id}/documents/${d.id}`} key={d.id}><FileCheck2 size={22} /><div><b>{d.name}</b><p>{a.id} · {a.institution} · simulated extraction and source-verification record</p></div><Tag>{d.status === 'Source Unavailable' ? 'Source Unavailable' : d.status === 'Mismatch Detected' ? 'Mismatch' : d.status === 'Verified' ? 'Verified' : 'Pending'}</Tag></Link>))}</section></Shell> }

function GlobalCompliance() { const { apps } = useStore(); return <Shell title="Compliance Assessment"><section className="content-section"><Heading title="Requirement-by-requirement assessment" text="Open an application to inspect contextual illustrative rules and evidence." /><AppTable rows={apps} /></section></Shell> }

function Reports() { const { apps } = useStore(); return <section className="content-section"><Heading title="Validation Reports" text="Reports describe scrutiny status and recommended steps; they never approve or reject applications automatically." /><div className="report-grid">{apps.map(a => <article className="report-card" key={a.id}><div><h3>{a.id} · {a.institution}</h3><p>Checklist: {a.documents.filter(d => d.status === 'Not Submitted').length ? 'missing evidence present' : 'configured items received'} · Findings: {a.findings.length} · Overall status: {a.status}</p><small>Simulated comparisons, verification results, and review history are available in the application report.</small></div><Link className="button secondary" to={`/reports/${a.id}`}>Preview report</Link></article>)}</div></section></Shell> }

function Report() { const { id = '' } = useParams(); const { apps } = useStore(); const app = apps.find(a => a.id === id); if (!app) return <Navigate to="/reports" replace />; return <Shell title="Validation report"><article className="print-report"><p className="eyebrow">Frontend demonstration report · simulated outcomes</p><h2>{app.institution}</h2><p>{app.id} · {app.category} · Submitted {app.submitted}</p><h3>Document checklist summary</h3><p>{app.documents.map(d => `${d.name}: ${d.status}`).join(' · ')}</p><h3>Unresolved issues and comparisons</h3><p>{app.findings.length ? app.findings.map(f => <p key={f.id}><b>{f.title}</b> — {f.explanation} Next step: {f.action}</p>).join('') : 'Matching simulated document values; no finding requires action.'}</p><h3>Overall scrutiny status</h3><p>{app.status}. This report does not declare an approval or rejection.</p><button className="button primary no-print" onClick={() => window.print()}>Print report</button></article></Shell> }

function Admin() { const [r, setR] = useState('Reviewer'); return <Shell title="Administration"><section className="content-section"><Heading title="Demo roles and permissions" text="This visible role switch is not authentication or real authorization; enforcement belongs in a future backend." /><label className="role-switch">Demo role<select value={r} onChange={e => setR(e.target.value)}><option>Administrator</option><option>Reviewer</option><option>Read-only observer</option></select></label><div className="rule-list"><div><b>{r}</b><span>{r === 'Administrator' ? 'Can configure future rules and reviewers.' : r === 'Reviewer' ? 'Can review findings and add comments.' : 'Can inspect records and reports only.'}</span><Tag>Frontend demo</Tag></div></div></section></Shell> }

function Login() {
  const nav = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await login(email, password);
      nav('/dashboard');
    } catch (e: any) {
      setError(e.message || 'An unexpected error occurred. Please check your credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth">
      <Brand />
      <section className="auth-card">
        <p className="eyebrow">Secure Access</p>
        <h1>Sign in to VIGILANT AI</h1>
        <p>Enter your institutional credentials to access the verification workspace.</p>

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="input-group">
            <Mail size={18} />
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="input-group">
            <Lock size={18} />
            <input
              type={showPassword ? 'text' : 'password'}
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
            <button
              type="button"
              className="password-toggle"
              onClick={() => setShowPassword(!showPassword)}
              title={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <Eye size={16} /> : <Eye size={16} style={{ opacity: 0.5 }} />}
            </button>
          </div>

          {error && <div className="auth-error"><AlertTriangle size={16} />{error}</div>}

          <button className="button primary full" disabled={isLoading}>
            {isLoading ? <Loader2 size={18} className="spin" /> : 'Sign in'}
            {!isLoading && <ArrowRight size={16} />}
          </button>
        </form>
      </section>
    </div>
  );
}

function Root() {
  const { user, isLoading } = useAuth();
  if (isLoading) return <div className="auth-loading"><Loader2 size={48} className="spin" /></div>;

  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={!user ? <Login /> : <Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={user ? <Dashboard /> : <Navigate to="/login" replace />} />
      <Route path="/applications" element={user ? <Applications /> : <Navigate to="/login" replace />} />
      <Route path="/applications/:id" element={user ? <Detail /> : <Navigate to="/login" replace />} />
      <Route path="/applications/:id/documents/:docId" element={user ? <DocumentView /> : <Navigate to="/login" replace />} />
      <Route path="/review-queue" element={user ? <ReviewQueue /> : <Navigate to="/login" replace />} />
      <Route path="/verification" element={user ? <GlobalVerification /> : <Navigate to="/login" replace />} />
      <Route path="/compliance" element={user ? <GlobalCompliance /> : <Navigate to="/login" replace />} />
      <Route path="/reports" element={user ? <Reports /> : <Navigate to="/login" replace />} />
      <Route path="/reports/:id" element={user ? <Report /> : <Navigate to="/login" replace />} />
      <Route path="/audit-trail" element={user ? <GlobalAudit /> : <Navigate to="/login" replace />} />
      <Route path="/administration" element={user?.role === 'ADMIN' ? <Admin /> : <Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <StoreProvider>
          <Root />
        </StoreProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
