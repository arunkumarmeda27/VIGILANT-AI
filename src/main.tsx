import React, { createContext, useContext, useMemo, useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, ClipboardCheck, Eye, EyeOff, FileCheck2, FileText, LayoutDashboard, ListChecks, Menu, Search, ShieldCheck, UserRound, XCircle, Lock, Mail, Loader2 } from 'lucide-react';
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
type EvidenceCitation = { source_document: string; pdf_page: number | string; printed_handbook_page: number | string; chunk_id: string };
type AIEvidence = { text: string; source_text: string; evidence_type: string; retrieval_score: number | null; citation: EvidenceCitation };
type AIWarning = { code: string; message: string; citations: EvidenceCitation[] };
type AIAnswer = { question: string; status: 'source_evidence_found' | 'insufficient_evidence'; answer: string; evidence: AIEvidence[]; warnings: AIWarning[] };
type ValidationReview = { status: string; reviewer: string | null; reviewed_at: string | null; notes: string };
type ValidationField = { value: string | null; page: number | null; evidence: string | null; confidence: number | null; status: string; verification_status: 'unverified' };
type ValidationRuleSource = { handbook_version: string; source_path: string; section: string; printed_page: number; pdf_page: number };
type ValidationRuleCandidate = {
  rule_id: string;
  document_type: string;
  candidate_requirement: string;
  known_scope: string;
  source_mapping_review: ValidationReview;
  currentness_review: ValidationReview;
  applicability_review: ValidationReview;
  preview_approved: boolean;
  eligibility: 'unknown' | 'not_applicable' | 'eligible_for_preview';
  evidence: { rule_id: string; clause_text: string; source: ValidationRuleSource };
};
type ValidationCheck = { rule_id: string; status: 'unknown' | 'not_assessed'; reason: string };
type PersistedApplication = {
  id: number;
  reference: string;
  entity_name: string;
  app_type: string;
  status: string | null;
  created_at: string;
  updated_at: string;
};
type PersistedInstitution = { id: number; name: string; created_at: string; updated_at: string };
type AuditEventItem = {
  id: number;
  user_id: number | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  timestamp: string;
  metadata: Record<string, string | number | boolean | string[] | null>;
};
type AuditEventPage = { items: AuditEventItem[]; limit: number; offset: number; total: number };
type ComplianceAssessment = {
  id: number;
  application_id: number;
  application_reference: string;
  entity_name: string;
  rule_code: string;
  rule_title: string;
  category: string;
  status: string;
  explanation: string;
  assessed_at: string;
  reviewer_name: string | null;
};
type ComplianceAssessmentPage = { items: ComplianceAssessment[]; total: number };
type ConsistencyResultRecord = {
  id: number;
  run_id: number;
  application_id: number;
  field: string;
  category: 'MATCH' | 'CONFIRMED_MISMATCH' | 'POSSIBLE_MISMATCH' | 'INSUFFICIENT_EVIDENCE' | 'NOT_APPLICABLE' | string;
  val1: string | null;
  val2: string | null;
  explanation: string;
  human_review_recommended: boolean;
  doc1_id: number;
  doc1_filename: string;
  doc2_id: number;
  doc2_filename: string;
};
type ConsistencyRunRecord = {
  id: number;
  application_id: number;
  status: string;
  comparisons_count: number;
  created_at: string;
  results: ConsistencyResultRecord[];
};
type ConsistencyRunHistory = { items: ConsistencyRunRecord[] };
type PersistedFinding = {
  id: number;
  application_id: number;
  document_id: number | null;
  finding_type: string;
  severity: string;
  description: string;
  status: string;
  created_at: string;
  reviews: { id: number; finding_id: number; reviewer_id: number; reviewer_name: string; outcome: 'confirmed_issue' | 'false_positive' | 'needs_further_review'; note: string; created_at: string }[];
};
type ApplicationChecklist = {
  application_id: number;
  category: string;
  source: 'synthetic_demo';
  items: { document_type: string; status: string; document_ids: number[]; missing_fields: string[]; explanation: string }[];
};
type PersistedDocument = {
  id: number;
  application_id: number;
  doc_type: string;
  original_filename: string;
  processing_status: string;
  sha256: string | null;
  file_size: number | null;
  created_at: string;
};
type ExtractedField = {
  value: string | null;
  page: number | null;
  evidence: string | null;
  confidence: number | null;
  status: string;
};
type DocumentProcessingResult = {
  document_id: number;
  processing_status: string;
  extraction_method: string;
  pages_processed: number;
  fields: Record<string, ExtractedField>;
  warnings: string[];
  processed_at: string | null;
};
type DocumentIntegrityPreview = {
  application_id: number;
  document_id: number;
  sha256: string | null;
  duplicate_file_check: { status: string; explanation: string; matches: { document_id: number; original_filename: string }[] };
  pdf_structure_check: { status: string; explanation: string; matches: { document_id: number; original_filename: string }[] };
  metadata_check: { status: string; explanation: string; matches: { document_id: number; original_filename: string }[] };
  issuer_verification: 'not_performed';
  authenticity_status: 'not_assessed';
  limitations: string[];
};
type DocumentValidationPreview = {
  application_id: number;
  document_id: number;
  application_scope_status: 'unknown';
  overall_status: 'unknown' | 'not_assessed';
  document_evidence: {
    document_id: number;
    processing_status: string;
    extraction_method: string;
    processed_at: string | null;
    fields: Record<string, ValidationField>;
    warnings: string[];
  };
  candidate_rules: ValidationRuleCandidate[];
  checks: ValidationCheck[];
  limitations: string[];
  warnings: string[];
};

async function responseError(response: Response, fallback: string): Promise<string> {
  try {
    const payload: { detail?: unknown } = await response.json();
    return typeof payload.detail === 'string' ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

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
const nav = [['/dashboard', LayoutDashboard, 'Overview'], ['/applications', FileText, 'Applications'], ['/review-queue', ListChecks, 'Review Queue'], ['/verification', FileCheck2, 'Document Verification'], ['/ai-evidence', Search, 'AI Evidence Search'], ['/compliance', ClipboardCheck, 'Compliance Assessment'], ['/reports', FileText, 'Validation Reports'], ['/audit-trail', ShieldCheck, 'Audit History'], ['/administration', UserRound, 'Administration']] as const;

function Shell({ title, children, liveData = false }: { title: string; children: React.ReactNode; liveData?: boolean }) {
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
          <Tag>{liveData ? 'Backend data' : 'Demo data'}</Tag>
        </header>
        <main className="app-content">
          {!liveData && <p className="demo-notice">Frontend demonstration · All extraction, verification, anomaly and compliance outcomes are deterministic simulated data. Human review is required.</p>}
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

function Dashboard() {
  const { token, logout } = useAuth();
  const [applications, setApplications] = useState<PersistedApplication[]>([]);
  const [documents, setDocuments] = useState<PersistedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    requestApi<PersistedApplication[]>('/api/applications/', token)
      .then(async items => {
        const lists = await Promise.all(items.map(application =>
          requestApi<PersistedDocument[]>(`/api/applications/${application.id}/documents`, token),
        ));
        if (!cancelled) {
          setApplications(items);
          setDocuments(lists.flat());
        }
      })
      .catch(reason => {
        if (cancelled) return;
        if (reason instanceof ApiRequestError && reason.status === 401) {
          logout();
          setError('Your session has expired. Please sign in again.');
        } else {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend. Check your connection and retry.');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, logout]);

  const metrics = [
    ['Accessible applications', applications.length],
    ['Submitted', applications.filter(item => item.status === 'submitted').length],
    ['Documents uploaded', documents.length],
    ['Processing failures', documents.filter(item => item.processing_status === 'failed').length],
    ['Processing pending', documents.filter(item => item.processing_status === 'pending' || item.processing_status === 'processing').length],
    ['Needs human review', documents.filter(item => item.processing_status === 'ocr_unavailable').length],
  ];
  const recent = [...applications].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 8);

  return (
    <Shell title="Overview" liveData>
      {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
      {loading ? <section className="content-section" role="status">Loading accessible applications and document statuses…</section> : (
        <>
          {applications.length === 0 && <section className="content-section live-empty-state"><h2>No accessible applications</h2><p>The backend returned no applications for this account.</p><Link className="button primary" to="/applications">Open application register</Link></section>}
          <div className="metric-grid six">
            {metrics.map(([label, value]) => <Link className="metric metric-link" to="/applications" key={label as string}><span>{label}</span><strong>{value}</strong><small>Backend data</small></Link>)}
          </div>
          <section className="content-section">
            <Heading title="Recently updated applications" text="Ordered by the backend-provided updated timestamp. No simulated application records are included." />
            {recent.length ? (
              <div className="table-wrap"><table><thead><tr><th>ID</th><th>Reference</th><th>Institution / organization</th><th>Type</th><th>Status</th><th>Updated</th></tr></thead>
                <tbody>{recent.map(application => <tr key={application.id}><td>{application.id}</td><td><Link className="table-link" to={`/applications/${application.id}`}>{application.reference}</Link></td><td>{application.entity_name}</td><td>{application.app_type}</td><td><Tag>{application.status || 'Unknown'}</Tag></td><td>{new Date(application.updated_at).toLocaleString()}</td></tr>)}</tbody>
              </table></div>
            ) : <p className="validation-meta">No applications to display.</p>}
          </section>
          <section className="content-section">
            <Heading title="Document processing status" text="Processing state is server-reported; OCR-unavailable documents need manual review or a supported OCR setup." />
            {documents.length ? <div className="live-document-list">{documents.filter(item => item.processing_status !== 'completed').map(document => <article className="live-document-card" key={document.id}><b>{document.original_filename}</b><p>Application {document.application_id} · Document {document.id}</p><Tag>{document.processing_status}</Tag></article>)}</div> : <p className="validation-meta">No uploaded documents are available.</p>}
          </section>
        </>
      )}
    </Shell>
  );
}

function AIEvidenceSearch() {
  const { token, logout } = useAuth();
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AIAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setError('Enter a question to search the regulatory evidence.');
      setAnswer(null);
      return;
    }
    if (!token) {
      setError('Your session has expired. Please sign in again.');
      logout();
      return;
    }

    setIsLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const response = await fetch(`${API_URL}/api/ai/ask`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question: trimmedQuestion }),
      });

      if (response.status === 401) {
        logout();
        return;
      }
      if (!response.ok) {
        let detail = response.status === 503
          ? 'The evidence service is temporarily unavailable. Please try again later.'
          : 'The evidence search could not be completed.';
        try {
          const payload: { detail?: unknown } = await response.json();
          if (typeof payload.detail === 'string') detail = payload.detail;
        } catch {
          // Keep the generic status-specific message when the response is not JSON.
        }
        setError(detail);
        return;
      }

      setAnswer(await response.json() as AIAnswer);
    } catch {
      setError('Could not reach the evidence service. Check your connection and try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Shell title="AI Evidence Search">
      <section className="content-section ai-search-panel">
        <Heading
          title="Search regulatory source evidence"
          text="Ask a question to retrieve passages from the available AICTE handbook source."
        />
        <form className="ai-search-form" onSubmit={handleSubmit}>
          <label htmlFor="ai-evidence-question">Question</label>
          <textarea
            id="ai-evidence-question"
            value={question}
            onChange={event => setQuestion(event.target.value)}
            placeholder="For example: What fire safety certificate is required?"
            maxLength={1000}
            rows={4}
            required
            aria-describedby="ai-question-help"
          />
          <div className="ai-search-form-footer">
            <small id="ai-question-help">{question.length}/1000 characters. Retrieved evidence is not a compliance determination.</small>
            <button className="button primary" type="submit" disabled={isLoading}>
              {isLoading ? <Loader2 size={17} className="spin" aria-hidden="true" /> : <Search size={17} aria-hidden="true" />}
              {isLoading ? 'Searching…' : 'Search evidence'}
            </button>
          </div>
        </form>
        {error && <div className="ai-search-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
      </section>

      {answer && (
        <section className={`content-section ai-answer ${answer.status === 'insufficient_evidence' ? 'ai-answer-insufficient' : ''}`} aria-live="polite">
          <div className="ai-answer-heading">
            <div>
              <p className="eyebrow">Evidence response</p>
              <h2>{answer.status === 'insufficient_evidence' ? 'Insufficient evidence' : 'Source evidence found'}</h2>
            </div>
            <span className={`ai-status ${answer.status}`}>{answer.status === 'insufficient_evidence' ? 'Insufficient evidence' : 'Retrieved evidence'}</span>
          </div>
          <p className="ai-answer-question"><strong>Question:</strong> {answer.question}</p>
          <p className="ai-answer-text">{answer.answer}</p>

          {answer.warnings.length > 0 && (
            <section className="ai-warnings" aria-label="Evidence warnings">
              <h3><AlertTriangle size={18} aria-hidden="true" />Warnings requiring review</h3>
              {answer.warnings.map((warning, index) => (
                <article className="ai-warning" key={`${warning.code}-${index}`}>
                  <strong>{warning.code}</strong>
                  <p>{warning.message}</p>
                  {warning.citations.length > 0 && (
                    <div className="ai-warning-citations">
                      {warning.citations.map((citation, citationIndex) => (
                        <Citation key={`${citation.chunk_id}-${citationIndex}`} citation={citation} />
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </section>
          )}

          {answer.evidence.length > 0 ? (
            <div className="ai-evidence-list">
              <h3>Retrieved passages</h3>
              {answer.evidence.map((item, index) => (
                <article className="ai-evidence-card" key={`${item.citation.chunk_id}-${index}`}>
                  <p className="ai-evidence-type">{item.evidence_type.replaceAll('_', ' ')}</p>
                  <blockquote>{item.text}</blockquote>
                  <Citation citation={item.citation} />
                </article>
              ))}
            </div>
          ) : answer.status === 'insufficient_evidence' ? (
            <p className="ai-no-evidence">No supporting passages were returned for this question.</p>
          ) : null}
          <p className="ai-disclaimer">Retrieved text and citations are provided for review. This response does not establish regulatory applicability or compliance.</p>
        </section>
      )}
    </Shell>
  );
}

function Citation({ citation }: { citation: EvidenceCitation }) {
  return (
    <dl className="ai-citation">
      <div><dt>Source document</dt><dd>{citation.source_document}</dd></div>
      <div><dt>PDF page</dt><dd>{citation.pdf_page}</dd></div>
      <div><dt>Printed handbook page</dt><dd>{citation.printed_handbook_page}</dd></div>
      <div><dt>Chunk ID</dt><dd>{citation.chunk_id}</dd></div>
    </dl>
  );
}

function Applications() {
  const { token, user, logout } = useAuth();
  const [applications, setApplications] = useState<PersistedApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (!token) {
      setApplications([]);
      setLoading(false);
      return () => { cancelled = true; };
    }
    requestApi<PersistedApplication[]>('/api/applications/', token)
      .then(items => { if (!cancelled) setApplications(items); })
      .catch(reason => {
        if (cancelled) return;
        if (reason instanceof ApiRequestError && reason.status === 401) {
          logout();
          setError('Your session has expired. Please sign in again.');
        } else {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend. Check your connection and retry.');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, logout, refreshKey]);

  const allowedToCreate = user?.role === 'ADMIN' || user?.role === 'INSTITUTION_USER';
  const visibleApplications = applications.filter(application =>
    (statusFilter === 'All' || application.status === statusFilter)
    && `${application.id} ${application.reference} ${application.entity_name} ${application.app_type}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <Shell title="Applications" liveData>
      <section className="content-section">
        <div className="section-heading">
          <div>
            <h2>Application register</h2>
            <p>Records and timestamps are loaded from the authenticated backend.</p>
          </div>
          <div className="live-page-actions">
            <button className="button secondary" type="button" onClick={() => setRefreshKey(value => value + 1)} disabled={loading}>
              {loading ? <Loader2 size={16} className="spin" aria-hidden="true" /> : 'Refresh'}
            </button>
            {allowedToCreate && <Link className="button primary" to="/applications/new">Create application</Link>}
          </div>
        </div>
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        {loading ? <p role="status">Loading permitted applications…</p> : applications.length === 0 ? (
          <div className="live-empty-state">
            <h3>No applications are available</h3>
            <p>The backend returned no applications accessible to this account.</p>
            {allowedToCreate && <Link className="button primary" to="/applications/new">Create an application</Link>}
          </div>
        ) : (
          <>
            <div className="filters">
              <label className="search"><Search size={17} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search ID, reference, institution or type" /></label>
              <select aria-label="Filter application status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}>
                <option>All</option>
                {Array.from(new Set(applications.map(application => application.status || 'Unknown'))).map(item => <option key={item}>{item}</option>)}
              </select>
            </div>
            {visibleApplications.length ? (
              <div className="table-wrap"><table><thead><tr><th>Database ID</th><th>Reference</th><th>Institution / organization</th><th>Application type</th><th>Status</th><th>Created</th><th>Last updated</th></tr></thead>
                <tbody>{visibleApplications.map(application => <tr key={application.id}>
                  <td>{application.id}</td>
                  <td><Link className="table-link" to={`/applications/${application.id}`}>{application.reference}</Link></td>
                  <td>{application.entity_name}</td><td>{application.app_type}</td>
                  <td><Tag>{application.status || 'Unknown'}</Tag></td>
                  <td>{new Date(application.created_at).toLocaleString()}</td>
                  <td>{new Date(application.updated_at).toLocaleString()}</td>
                </tr>)}</tbody>
              </table></div>
            ) : <p className="validation-meta">No applications match this search and status filter.</p>}
          </>
        )}
      </section>
    </Shell>
  );
}

function CreateApplication() {
  const { token, user, logout } = useAuth();
  const navigate = useNavigate();
  const [reference, setReference] = useState('');
  const [entityName, setEntityName] = useState('');
  const [applicationType, setApplicationType] = useState('');
  const [institutions, setInstitutions] = useState<PersistedInstitution[]>([]);
  const [institutionId, setInstitutionId] = useState('');
  const [institutionName, setInstitutionName] = useState('');
  const [loadingInstitutions, setLoadingInstitutions] = useState(false);
  const [creatingInstitution, setCreatingInstitution] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [institutionNotice, setInstitutionNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!token || user?.role !== 'ADMIN') return () => { cancelled = true; };
    setLoadingInstitutions(true);
    requestApi<PersistedInstitution[]>('/api/institutions/', token)
      .then(items => {
        if (cancelled) return;
        setInstitutions(items);
        setInstitutionId(current => current || (items[0] ? String(items[0].id) : ''));
      })
      .catch(reason => {
        if (!cancelled) {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not load institutions. Check the backend connection.');
        }
      })
      .finally(() => { if (!cancelled) setLoadingInstitutions(false); });
    return () => { cancelled = true; };
  }, [token, user?.role]);

  const createInstitution = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || creatingInstitution || user?.role !== 'ADMIN') return;
    setCreatingInstitution(true);
    setError(null);
    setInstitutionNotice(null);
    try {
      const created = await requestApi<PersistedInstitution>('/api/institutions/', token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: institutionName.trim() }),
      });
      setInstitutions(items => [...items, created].sort((a, b) => a.name.localeCompare(b.name)));
      setInstitutionId(String(created.id));
      setInstitutionName('');
      setInstitutionNotice(`Institution "${created.name}" created and selected.`);
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend while creating institution.');
      }
    } finally {
      setCreatingInstitution(false);
    }
  };

  if (user?.role !== 'ADMIN' && user?.role !== 'INSTITUTION_USER') return <Navigate to="/applications" replace />;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await requestApi<PersistedApplication>('/api/applications/', token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reference: reference.trim(),
          entity_name: entityName.trim(),
          app_type: applicationType.trim(),
          ...(user.role === 'ADMIN' ? { institution_id: Number(institutionId) } : {}),
        }),
      });
      navigate(`/applications/${created.id}`);
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend. Check your connection and try again.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Shell title="Create application" liveData>
      <section className="content-section">
        <Heading title="New application" text="The server sets the initial status and validates institution ownership. Application references must be unique." />
        {user?.role === 'ADMIN' && (
          <div className="institution-picker">
            <label>Application institution
              <select aria-label="Application institution" value={institutionId} onChange={event => setInstitutionId(event.target.value)} required disabled={loadingInstitutions || institutions.length === 0}>
                {institutions.length === 0 && <option value="">No institutions available</option>}
                {institutions.map(institution => <option key={institution.id} value={institution.id}>{institution.name} · ID {institution.id}</option>)}
              </select>
            </label>
            {institutions.length === 0 && <p className="validation-meta">Create an institution below before creating an application.</p>}
            <form className="institution-create-form" onSubmit={createInstitution}>
              <label>New institution name<input value={institutionName} onChange={event => setInstitutionName(event.target.value)} maxLength={255} required /></label>
              <button className="button secondary" type="submit" disabled={creatingInstitution}>{creatingInstitution ? 'Creating institution…' : 'Create institution'}</button>
            </form>
            {institutionNotice && <p className="validation-meta" role="status">{institutionNotice}</p>}
          </div>
        )}
        <form className="application-form live-application-form" onSubmit={submit}>
          <label>Application reference<input value={reference} onChange={event => setReference(event.target.value)} maxLength={100} required /></label>
          <label>Institution or organization name<input value={entityName} onChange={event => setEntityName(event.target.value)} maxLength={255} required /></label>
          <label>Application type<input value={applicationType} onChange={event => setApplicationType(event.target.value)} maxLength={100} required /></label>
          <p className="validation-meta">Initial status: Submitted (set by the backend)</p>
          {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
          <div className="live-page-actions">
            <Link className="button secondary" to="/applications">Cancel</Link>
            <button className="button primary" type="submit" disabled={saving || loadingInstitutions || (user?.role === 'ADMIN' && (!institutionId || institutions.length === 0))}>
              {saving ? <Loader2 size={17} className="spin" aria-hidden="true" /> : null}{saving ? 'Creating…' : 'Create application'}
            </button>
          </div>
        </form>
      </section>
    </Shell>
  );
}

function PersistedApplicationDetail() {
  const { id = '' } = useParams();
  const { token, user, logout } = useAuth();
  const [application, setApplication] = useState<PersistedApplication | null>(null);
  const [documents, setDocuments] = useState<PersistedDocument[]>([]);
  const [consistencyRuns, setConsistencyRuns] = useState<ConsistencyRunRecord[]>([]);
  const [assessments, setAssessments] = useState<ComplianceAssessment[]>([]);
  const [findings, setFindings] = useState<PersistedFinding[]>([]);
  const [checklist, setChecklist] = useState<ApplicationChecklist | null>(null);
  const [reviewDrafts, setReviewDrafts] = useState<Record<number, { outcome: string; note: string }>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [validatingConsistency, setValidatingConsistency] = useState(false);
  const [validatingRules, setValidatingRules] = useState(false);
  const [validatingChecklist, setValidatingChecklist] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [workflowNotice, setWorkflowNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [entityName, setEntityName] = useState('');
  const [appType, setAppType] = useState('');
  const [status, setStatus] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    Promise.all([
      requestApi<PersistedApplication>(`/api/applications/${id}`, token),
      requestApi<PersistedDocument[]>(`/api/applications/${id}/documents`, token),
      requestApi<ConsistencyRunHistory>(`/api/applications/${id}/consistency-runs`, token),
      requestApi<PersistedFinding[]>(`/api/applications/${id}/findings`, token),
      requestApi<ComplianceAssessmentPage>('/api/compliance-assessments/?limit=200', token),
    ]).then(([app, docs, history, persistedFindings, assessmentPage]) => {
      if (cancelled) return;
      setApplication(app);
      setEntityName(app.entity_name);
      setAppType(app.app_type);
      setStatus(app.status || '');
      setDocuments(docs);
      setConsistencyRuns(history.items);
      setFindings(persistedFindings);
      setAssessments(assessmentPage.items.filter(item => item.application_id === app.id));
    }).catch(reason => {
      if (cancelled) return;
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend. Check your connection and try again.');
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, token, logout]);

  const runConsistencyValidation = async () => {
    if (!token || !application || validatingConsistency) return;
    setValidatingConsistency(true);
    setWorkflowError(null);
    setWorkflowNotice(null);
    try {
      await requestApi<{ run_id: number }>(`/api/applications/${application.id}/validate-consistency`, token, { method: 'POST' });
      const history = await requestApi<ConsistencyRunHistory>(`/api/applications/${application.id}/consistency-runs`, token);
      setConsistencyRuns(history.items);
      setWorkflowNotice('Validation run saved. Previous runs remain available below.');
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setWorkflowError('Your session has expired. Please sign in again.');
      } else {
        setWorkflowError(reason instanceof ApiRequestError ? reason.message : 'Could not save cross-document validation.');
      }
    } finally {
      setValidatingConsistency(false);
    }
  };

  const runRegulatoryValidation = async () => {
    if (!token || !application || validatingRules) return;
    setValidatingRules(true);
    setWorkflowError(null);
    setWorkflowNotice(null);
    try {
      await requestApi(`/api/applications/${application.id}/validate-all`, token, { method: 'POST' });
      const assessmentPage = await requestApi<ComplianceAssessmentPage>('/api/compliance-assessments/?limit=200', token);
      setAssessments(assessmentPage.items.filter(item => item.application_id === application.id));
      setFindings(await requestApi<PersistedFinding[]>(`/api/applications/${application.id}/findings`, token));
      setWorkflowNotice('Registry assessments saved and loaded from the backend. Review their source and scope status below.');
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setWorkflowError('Your session has expired. Please sign in again.');
      } else {
        setWorkflowError(reason instanceof ApiRequestError ? reason.message : 'Could not run regulatory validation.');
      }
    } finally {
      setValidatingRules(false);
    }
  };

  const runChecklistValidation = async () => {
    if (!token || !application || validatingChecklist) return;
    setValidatingChecklist(true); setWorkflowError(null); setWorkflowNotice(null);
    try {
      const result = await requestApi<ApplicationChecklist>(`/api/applications/${application.id}/validate-checklist`, token, { method: 'POST' });
      setChecklist(result);
      setFindings(await requestApi<PersistedFinding[]>(`/api/applications/${application.id}/findings`, token));
      setWorkflowNotice('Synthetic checklist results and advisory findings were saved.');
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) { logout(); setWorkflowError('Your session has expired. Please sign in again.'); }
      else setWorkflowError(reason instanceof ApiRequestError ? reason.message : 'Could not run the checklist.');
    } finally { setValidatingChecklist(false); }
  };

  const submitFindingReview = async (finding: PersistedFinding) => {
    if (!token || !application) return;
    const draft = reviewDrafts[finding.id] ?? { outcome: 'needs_further_review', note: '' };
    setWorkflowError(null);
    try {
      await requestApi(`/api/applications/${application.id}/findings/${finding.id}/reviews`, token, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draft),
      });
      setFindings(await requestApi<PersistedFinding[]>(`/api/applications/${application.id}/findings`, token));
      setWorkflowNotice('Reviewer decision recorded in the audit history.');
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) { logout(); setWorkflowError('Your session has expired. Please sign in again.'); }
      else setWorkflowError(reason instanceof ApiRequestError ? reason.message : 'Could not save reviewer decision.');
    }
  };

  const update = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || !application || saving) return;
    const payload: { entity_name?: string; app_type?: string; status?: string } = {};
    if (user?.role === 'ADMIN' || user?.role === 'INSTITUTION_USER') {
      payload.entity_name = entityName.trim();
      payload.app_type = appType.trim();
    }
    if (user?.role === 'ADMIN' || user?.role === 'REVIEWER') payload.status = status.trim();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await requestApi<PersistedApplication>(`/api/applications/${application.id}`, token, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setApplication(updated);
      setEntityName(updated.entity_name);
      setAppType(updated.app_type);
      setStatus(updated.status || '');
      setNotice('Application details updated.');
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend. Check your connection and try again.');
      }
    } finally {
      setSaving(false);
    }
  };

  const canEditDetails = user?.role === 'ADMIN' || user?.role === 'INSTITUTION_USER';
  const canEditStatus = user?.role === 'ADMIN' || user?.role === 'REVIEWER';
  if (loading) return <Shell title="Application details" liveData><p role="status">Loading application…</p></Shell>;
  if (!application && !error) return <Navigate to="/applications" replace />;
  return (
    <Shell title="Application details" liveData>
      {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
      {application && (
        <>
          <section className="content-section">
            <div className="detail-head">
              <div><p className="eyebrow">Persisted application · database ID {application.id}</p><h2>{application.reference}</h2><p>{application.entity_name}</p></div>
              <Tag>{application.status || 'Unknown'}</Tag>
            </div>
            <dl className="validation-rule-meta">
              <div><dt>Application type</dt><dd>{application.app_type}</dd></div>
              <div><dt>Created</dt><dd>{new Date(application.created_at).toLocaleString()}</dd></div>
              <div><dt>Last updated</dt><dd>{new Date(application.updated_at).toLocaleString()}</dd></div>
              <div><dt>Persisted documents</dt><dd>{documents.length}</dd></div>
            </dl>
            <div className="live-page-actions">
              <Link className="button primary" to={`/verification?application_id=${application.id}`}>Open document workspace</Link>
              <Link className="button secondary" to="/applications">Back to applications</Link>
            </div>
          </section>
          <section className="content-section">
            <Heading title="Validation workflow" text="Run backend validation against this application's persisted documents and review stored results." />
            {workflowError && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{workflowError}</div>}
            {workflowNotice && <p className="validation-meta" role="status">{workflowNotice}</p>}
            <div className="live-page-actions">
              <button className="button secondary" type="button" onClick={runRegulatoryValidation} disabled={validatingRules || !documents.some(document => document.processing_status === 'completed')}>
                {validatingRules ? <Loader2 size={17} className="spin" aria-hidden="true" /> : null}{validatingRules ? 'Validating…' : 'Run regulatory validation'}
              </button>
              <button className="button secondary" type="button" onClick={runChecklistValidation} disabled={validatingChecklist}>
                {validatingChecklist ? <Loader2 size={17} className="spin" aria-hidden="true" /> : null}{validatingChecklist ? 'Checking…' : 'Run document checklist'}
              </button>
              <button className="button primary" type="button" onClick={runConsistencyValidation} disabled={validatingConsistency || documents.filter(document => document.processing_status === 'completed').length < 2}>
                {validatingConsistency ? <Loader2 size={17} className="spin" aria-hidden="true" /> : null}{validatingConsistency ? 'Comparing documents…' : 'Run cross-document validation'}
              </button>
              <Link className="button secondary" to={`/verification?application_id=${application.id}`}>Manage and process documents</Link>
            </div>
            <p className="validation-disclaimer">Regulatory statuses reflect the configured registry and extracted evidence only. Candidate rules may be synthetic, unapproved, or not confirmed current; results are not official legal or compliance determinations.</p>
          </section>
          <section className="content-section">
            <Heading title="Application document checklist" text="Category-based synthetic demonstration requirements; this is not an official AICTE checklist." />
            {checklist ? <div className="validation-check-list">{checklist.items.map(item => <article className="validation-check" key={item.document_type}>
              <strong>{item.document_type.replaceAll('_', ' ')} · {item.status.replaceAll('_', ' ')}</strong>
              <p>{item.explanation}</p><small>Document IDs: {item.document_ids.length ? item.document_ids.join(', ') : 'None'}{item.missing_fields.length ? ` · Missing extracted fields: ${item.missing_fields.join(', ')}` : ''}</small>
            </article>)}</div> : <p className="validation-meta">Run the checklist to inspect configured document types, processing state, and extracted-field presence.</p>}
          </section>
          <section className="content-section">
            <Heading title="Persisted regulatory assessments" text="Assessment records returned by the authorized API for this application." />
            {assessments.length ? <div className="validation-check-list">{assessments.map(assessment => (
              <article className="validation-check" key={assessment.id}>
                <strong>{assessment.rule_code} · {assessment.category} · {assessment.status}</strong>
                <p>{assessment.explanation}</p>
                <small>Assessed {new Date(assessment.assessed_at).toLocaleString()} · Reviewer: {assessment.reviewer_name || 'Unassigned'}</small>
              </article>
            ))}</div> : <p className="validation-meta">No persisted assessments are available for this application.</p>}
          </section>
          <section className="content-section">
            <Heading title="Persisted findings" text="Findings created by the backend validation workflow, with linked document references where available." />
            {findings.length ? findings.map(finding => (
              <article className="validation-check" key={finding.id}>
                <strong>{finding.finding_type} · {finding.severity} · {finding.status}</strong>
                <p>{finding.description}</p>
                <small>Recorded {new Date(finding.created_at).toLocaleString()} · Document: {finding.document_id ?? 'Not linked'}</small>
                {finding.reviews.map(review => <p key={review.id}><b>{review.outcome.replaceAll('_', ' ')}</b> · {review.reviewer_name} · {new Date(review.created_at).toLocaleString()}{review.note ? ` · ${review.note}` : ''}</p>)}
                {user?.role === 'REVIEWER' && <div className="application-form live-application-form">
                  <label>Review outcome<select value={reviewDrafts[finding.id]?.outcome ?? 'needs_further_review'} onChange={event => setReviewDrafts(current => ({ ...current, [finding.id]: { outcome: event.target.value, note: current[finding.id]?.note ?? '' } }))}>
                    <option value="confirmed_issue">Confirmed issue</option><option value="false_positive">False positive</option><option value="needs_further_review">Needs further review</option>
                  </select></label>
                  <label>Reviewer note<textarea maxLength={2000} value={reviewDrafts[finding.id]?.note ?? ''} onChange={event => setReviewDrafts(current => ({ ...current, [finding.id]: { outcome: current[finding.id]?.outcome ?? 'needs_further_review', note: event.target.value } }))} /></label>
                  <button className="button secondary" type="button" onClick={() => submitFindingReview(finding)}>Record review</button>
                </div>}
              </article>
            )) : <p className="validation-meta">No persisted findings are recorded for this application.</p>}
            <Link className="button secondary" to="/audit-trail">Open authorized audit history</Link>
          </section>
          <section className="content-section">
            <Heading title="Cross-document validation history" text="Every run and comparison below is loaded from persisted backend records." />
            {consistencyRuns.length ? consistencyRuns.map(run => (
              <article className="validation-rule" key={run.id}>
                <div className="validation-rule-title"><h3>Run {run.id}</h3><span className="validation-status">{run.status} · {run.comparisons_count} comparisons</span></div>
                <p className="validation-meta">{new Date(run.created_at).toLocaleString()}</p>
                {run.results.length ? run.results.map(result => (
                  <div className="validation-check" key={result.id}>
                    <strong>{result.field.replaceAll('_', ' ')} · {result.category}</strong>
                    <p>{result.doc1_filename} (ID {result.doc1_id}): {result.val1 ?? 'No extracted value'}</p>
                    <p>{result.doc2_filename} (ID {result.doc2_id}): {result.val2 ?? 'No extracted value'}</p>
                    <p>{result.explanation}</p>
                    {result.human_review_recommended && <p><b>Human review recommended.</b></p>}
                  </div>
                )) : <p className="validation-meta">No comparable extracted fields were returned in this run.</p>}
              </article>
            )) : <p className="validation-meta">No cross-document validation runs have been recorded for this application.</p>}
          </section>
          {(canEditDetails || canEditStatus) && (
            <section className="content-section">
              <Heading title="Update application" text="The backend enforces which fields your role may change." />
              <form className="application-form live-application-form" onSubmit={update}>
                {canEditDetails && <>
                  <label>Institution or organization name<input value={entityName} onChange={event => setEntityName(event.target.value)} maxLength={255} required /></label>
                  <label>Application type<input value={appType} onChange={event => setAppType(event.target.value)} maxLength={100} required /></label>
                </>}
                {canEditStatus && <label>Application status<input value={status} onChange={event => setStatus(event.target.value)} maxLength={50} required /></label>}
                {error && <div className="validation-error" role="alert">{error}</div>}
                {notice && <p role="status" className="validation-meta">{notice}</p>}
                <button className="button primary" type="submit" disabled={saving}>
                  {saving ? <Loader2 size={17} className="spin" aria-hidden="true" /> : null}{saving ? 'Saving…' : 'Save changes'}
                </button>
              </form>
            </section>
          )}
        </>
      )}
    </Shell>
  );
}

function Detail() { const { id = '' } = useParams(); const { apps } = useStore(); const app = apps.find(a => a.id === id); const [tab, setTab] = useState('Overview'); if (!app) return <Navigate to="/applications" replace />; const tabs = ['Overview', 'Documents', 'Findings', 'Compliance', 'Verification', 'Audit History']; return <Shell title="Application details"><section className="detail-head"><div><p className="eyebrow">{app.category}</p><h2>{app.id}</h2><p>{app.institution} · Submitted {app.submitted}</p></div><Tag>{app.status}</Tag></section><div className="tabs" role="tablist">{tabs.map(t => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>{tab === 'Overview' && <Overview app={app} />} {tab === 'Documents' && <Documents app={app} />} {tab === 'Findings' && <Findings app={app} />} {tab === 'Compliance' && <Compliance app={app} />} {tab === 'Verification' && <Verification app={app} />} {tab === 'Audit History' && <Audit app={app} />}</Shell> }

function Overview({ app }: { app: App }) { return <div className="detail-grid"><section className="content-section"><Heading title="Scrutiny summary" text="No automatic approval or rejection is generated." /><dl><dt>Current reviewer</dt><dd>{app.reviewer}</dd><dt>Documents</dt><dd>{app.documents.length} configured checklist items</dd><dt>Next required action</dt><dd>{app.nextAction}</dd></dl></section><section className="finding-card"><Heading title="Current review signal" text={app.findings[0]?.title || 'No unresolved findings.'} /><p>{app.findings[0]?.explanation || 'Configured comparisons currently contain a matching-value example.'}</p></section></div> }

function Documents({ app }: { app: App }) { const nav = useNavigate(); return <section className="content-section"><Heading title="Category-based document checklist" text="Illustrative requirements for this demo category. Receipt and verification are shown separately." /><div className="doc-list">{app.documents.map(d => <div key={d.id}><FileText size={20} /><span><b>{d.name}{d.required ? '' : ' (optional)'}</b><small>{d.date} · {d.status === 'Verified' ? 'Successful simulated validation' : 'Submission / validation state'}</small></span><Tag>{d.status}</Tag><button className="icon-button" aria-label={`Inspect ${d.name}`} onClick={() => nav(`/applications/${app.id}/documents/${d.id}`)}><Eye size={17} /></button></div>)}</div></section> }

function DocumentView() {
  const { id, docId } = useParams();
  const { apps } = useStore();
  const app = apps.find(item => item.id === id);
  const doc = app?.documents.find(item => item.id === docId);
  if (!app || !doc) return <Navigate to="/applications" replace />;
  return (
    <Shell title="Document inspection">
      <section className="detail-head">
        <div>
          <p className="eyebrow">Representative sample · no actual file/OCR processing</p>
          <h2>{doc.name}</h2>
          <p>{app.id} · submitted {doc.date}</p>
        </div>
        <div className="document-validation-action">
          <Tag>{doc.status}</Tag>
          <Link className="button primary" to="/verification"><FileCheck2 size={17} aria-hidden="true" />Open live workspace</Link>
        </div>
      </section>
      <p className="validation-demo-note">
        This is an illustrative frontend record, not a persisted backend document. Its fields and IDs cannot be validated as real evidence.
      </p>
      <div className="detail-grid">
        <section className="content-section document-preview">
          <FileText size={42} />
          <h3>Document preview unavailable in demo</h3>
          <p>A secure file viewer will be supplied by future document storage integration.</p>
        </section>
        <section className="content-section">
          <Heading title="Simulated extracted fields" text={doc.comment} />
          <dl>{Object.entries(doc.fields).map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd>{value}</dd></React.Fragment>)}</dl>
        </section>
      </div>
    </Shell>
  );
}

function ApplicationRouteView() {
  const { id = '' } = useParams();
  return /^\d+$/.test(id) ? <PersistedApplicationDetail /> : <Detail />;
}

function DocumentValidationResult({ preview }: { preview: DocumentValidationPreview }) {
  return (
    <section className="content-section validation-preview" aria-live="polite">
      <div className="validation-heading">
        <div>
          <p className="eyebrow">Backend validation preview</p>
          <h2>Preview status: {preview.overall_status}</h2>
        </div>
        <span className="validation-status">{preview.overall_status}</span>
      </div>
      <p className="validation-disclaimer">
        Extracted values, including OCR output, are unverified evidence. This preview does not establish document authenticity, fraud, or institutional compliance.
      </p>

      <section className="validation-subsection">
        <h3>Document evidence · document {preview.document_evidence.document_id}</h3>
        <p className="validation-meta">
          Processing: {preview.document_evidence.processing_status} · Extraction: {preview.document_evidence.extraction_method} · Application scope: {preview.application_scope_status}
        </p>
        {Object.entries(preview.document_evidence.fields).length ? (
          <div className="validation-fields">
            {Object.entries(preview.document_evidence.fields).map(([name, field]) => (
              <article className="validation-field" key={name}>
                <h4>{name.replaceAll('_', ' ')}</h4>
                <dl>
                  <div><dt>Extracted value</dt><dd>{field.value ?? 'Not extracted'}</dd></div>
                  <div><dt>Extraction status</dt><dd>{field.status} · {field.verification_status}</dd></div>
                  {field.evidence && <div className="validation-field-evidence"><dt>Evidence excerpt</dt><dd>{field.evidence}</dd></div>}
                  {field.page !== null && <div><dt>Document page</dt><dd>{field.page}</dd></div>}
                  {field.confidence !== null && <div><dt>Extraction confidence</dt><dd>{field.confidence}</dd></div>}
                </dl>
              </article>
            ))}
          </div>
        ) : <p className="validation-meta">No extracted fields were returned.</p>}
      </section>

      <section className="validation-subsection">
        <h3>Regulatory rule evidence and reviews</h3>
        <div className="validation-rule-list">
          {preview.candidate_rules.map(rule => (
            <article className="validation-rule" key={rule.rule_id}>
              <div className="validation-rule-title">
                <h4>{rule.rule_id}</h4>
                <span className="validation-status">{rule.eligibility}</span>
              </div>
              <p className="validation-clause">{rule.evidence.clause_text}</p>
              <dl className="validation-rule-meta">
                <div><dt>Handbook version</dt><dd>{rule.evidence.source.handbook_version}</dd></div>
                <div><dt>Section</dt><dd>{rule.evidence.source.section}</dd></div>
                <div><dt>Printed handbook page</dt><dd>{rule.evidence.source.printed_page}</dd></div>
                <div><dt>PDF page</dt><dd>{rule.evidence.source.pdf_page}</dd></div>
                <div><dt>Source mapping</dt><dd>{rule.source_mapping_review.status}</dd></div>
                <div><dt>Currentness</dt><dd>{rule.currentness_review.status}</dd></div>
                <div><dt>Applicability</dt><dd>{rule.applicability_review.status}</dd></div>
                <div><dt>Preview approval</dt><dd>{rule.preview_approved ? 'Approved' : 'Not approved'}</dd></div>
              </dl>
              <p className="validation-meta">Known scope: {rule.known_scope}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="validation-subsection">
        <h3>Checks</h3>
        {preview.checks.map(check => (
          <article className="validation-check" key={check.rule_id}>
            <strong>{check.rule_id}: {check.status}</strong>
            <p>{check.reason}</p>
          </article>
        ))}
      </section>

      {(preview.warnings.length > 0 || preview.limitations.length > 0) && (
        <section className="validation-cautions">
          <h3><AlertTriangle size={18} aria-hidden="true" />Limitations and warnings</h3>
          {preview.warnings.map((warning, index) => <p key={`warning-${index}`}>{warning}</p>)}
          {preview.limitations.map((limitation, index) => <p key={`limitation-${index}`}>{limitation}</p>)}
        </section>
      )}
    </section>
  );
}

function Findings({ app }: { app: App }) { return <section className="content-section"><Heading title="Cross-document comparisons and anomaly signals" text="A warning is not a confirmed fraud or regulatory violation." /><>{app.findings.length ? app.findings.map(f => <FindingCard key={f.id} app={app} f={f} />) : <Empty text="Matching simulated document values; no finding requires action." />}</></section> }

function FindingCard({ app, f }: { app: App; f: Finding }) { const { update } = useStore(); const [c, setC] = useState(''); return <article className="finding-card"><div className="finding-title"><AlertTriangle /><div><p className="eyebrow">{f.type} · simulated</p><h2>{f.title}</h2></div><Tag>{f.priority}</Tag></div>{f.field && <div className="comparison"><b>{f.field}</b><span>{f.documents[0]}: <mark>{f.first}</mark></span><span>{f.documents[1]}: <mark>{f.second}</mark></span></div>}<p>{f.explanation}</p><dl><dt>Related evidence</dt><dd>{f.documents.join(' · ')}</dd><dt>Suggested next action</dt><dd>{f.action}</dd></dl><div className="review-controls"><label>Reviewer<select value={f.assignee} onChange={e => update(app.id, f.id, { assignee: e.target.value })}>{reviewers.map(x => <option key={x}>{x}</option>)}</select></label><label>Status<select value={f.status} onChange={e => update(app.id, f.id, { status: e.target.value as RS })}>{(['Open', 'In Review', 'Awaiting Evidence', 'Resolved'] as RS[]).map(x => <option key={x}>{x}</option>)}</select></label></div><div className="comment-row"><input aria-label="Add review comment" value={c} onChange={e => setC(e.target.value)} placeholder="Add a demo reviewer comment" /><button className="button secondary" disabled={!c.trim()} onClick={() => { update(app.id, f.id, { comments: [...f.comments, c] }); setC('') }}>Add comment</button></div>{f.comments.map((x, i) => <small className="comment" key={i}>Reviewer note: {x}</small>)}</article> }

function Verification({ app }: { app: App }) { return <section className="content-section"><Heading title="Authorized-source verification" text="No network request is made; source outcomes are structured for future authorized integration." /><>{app.documents.map(d => <div key={d.id}><FileCheck2 size={22} /><div><b>{d.name}</b><p>Intended source: issuing authority · Method: future reference-ID lookup · Reference: {d.id.toUpperCase()}</p></div><Tag>{d.status === 'Source Unavailable' ? 'Source Unavailable' : d.status === 'Mismatch Detected' ? 'Mismatch' : d.status === 'Verified' ? 'Verified' : 'Pending'}</Tag></div>)}</></section> }

function Compliance({ app }: { app: App }) { const rules = [['DEMO-DOC-01', 'Illustrative required evidence is present', app.documents.some(d => d.status === 'Not Submitted') ? 'Insufficient Evidence' : 'Partially Verified'], ['DEMO-CON-02', 'Illustrative registration fields are consistent', app.findings.some(f => f.field === 'Registration number') ? 'Pending Manual Review' : 'Compliant'], ['DEMO-INF-01', 'Illustrative infrastructure evidence review', app.documents.some(d => d.name.includes('Land') || d.name.includes('Ownership')) ? 'Partially Verified' : 'Insufficient Evidence']]; return <section className="content-section"><Heading title="Requirement-by-requirement assessment" text="These are illustrative demo rules, not verified AICTE regulations." /><div className="rule-list">{rules.map(([id, desc, result]) => <div key={id}><b>{id}</b><span>{desc}<small>Supporting evidence: configured application documents</small></span><Tag>{result}</Tag><em>Human evidence review required</em></div>)}</div></section> }

function Audit({ app }: { app: App }) { const { audits } = useStore(); return <section className="content-section"><Heading title="Demonstration audit history" text="Frontend state only; this is not a secure or immutable production audit log." /><>{audits.filter(a => a.applicationId === app.id).map(x => <div className="audit-row" key={x.id}><b>{x.action}</b><small>{x.applicationId} · {x.actor} · {x.time}</small></div>)}</></section> }

function GlobalAudit() {
  const { token, logout } = useAuth();
  const [page, setPage] = useState<AuditEventPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 50;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    requestApi<AuditEventPage>(`/api/audit-events/?limit=${pageSize}&offset=${offset}`, token)
      .then(result => { if (!cancelled) setPage(result); })
      .catch(reason => {
        if (cancelled) return;
        if (reason instanceof ApiRequestError && reason.status === 401) {
          logout();
          setError('Your session has expired. Please sign in again.');
        } else {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend audit history.');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, logout, offset]);

  return (
    <Shell title="Audit History" liveData>
      <section className="content-section">
        <Heading title="Authorized audit events" text="Events are filtered by server-side role and application access. Sensitive values and document contents are not included." />
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        {loading ? <p role="status">Loading audit history…</p> : page?.items.length ? (
          <>
            <div className="audit-event-list">
              {page.items.map(event => (
                <article className="audit-event-card" key={event.id}>
                  <div><b>{event.action}</b><Tag>{event.entity_type}</Tag></div>
                  <p>Entity ID {event.entity_id} · {event.actor_name || `User ${event.user_id ?? 'unavailable'}`}</p>
                  <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()}</time>
                  {Object.keys(event.metadata).length > 0 && (
                    <dl className="audit-event-metadata">
                      {Object.entries(event.metadata).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{Array.isArray(value) ? value.join(', ') : value === null ? '—' : String(value)}</dd></div>)}
                    </dl>
                  )}
                </article>
              ))}
            </div>
            <div className="live-page-actions audit-pagination">
              <button className="button secondary" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
              <span>Showing {offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}</span>
              <button className="button secondary" disabled={loading || offset + pageSize >= page.total} onClick={() => setOffset(offset + pageSize)}>Next</button>
            </div>
          </>
        ) : <p className="validation-meta">No audit events are available to this account.</p>}
      </section>
    </Shell>
  );
}

function AssessmentWorkspace({ title }: { title: string }) {
  const { token, logout } = useAuth();
  const [page, setPage] = useState<ComplianceAssessmentPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 50;
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    requestApi<ComplianceAssessmentPage>(`/api/compliance-assessments/?limit=${pageSize}&offset=${offset}`, token)
      .then(result => { if (!cancelled) setPage(result); })
      .catch(reason => {
        if (cancelled) return;
        if (reason instanceof ApiRequestError && reason.status === 401) {
          logout();
          setError('Your session has expired. Please sign in again.');
        } else {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not load persisted compliance assessments.');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, logout, offset]);
  return (
    <Shell title={title} liveData>
      <section className="content-section">
        <Heading title={title} text="Only persisted reviewer assessments returned by the authorized backend are displayed. Candidate registry rules are not treated as assessments." />
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        {loading ? <p role="status">Loading authorized assessments…</p> : page?.items.length ? (
          <>
            <div className="table-wrap"><table><thead><tr><th>Application</th><th>Institution</th><th>Rule</th><th>Category</th><th>Recorded status</th><th>Reviewer</th><th>Assessed</th><th>Explanation</th></tr></thead>
              <tbody>{page.items.map(item => <tr key={item.id}>
                <td><Link className="table-link" to={`/applications/${item.application_id}`}>{item.application_reference}</Link></td>
                <td>{item.entity_name}</td><td>{item.rule_code} · {item.rule_title}</td><td>{item.category}</td><td><Tag>{item.status}</Tag></td><td>{item.reviewer_name || 'Unassigned'}</td><td>{new Date(item.assessed_at).toLocaleString()}</td><td>{item.explanation}</td>
              </tr>)}</tbody>
            </table></div>
            <div className="live-page-actions audit-pagination">
              <button className="button secondary" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
              <span>Showing {offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}</span>
              <button className="button secondary" disabled={loading || offset + pageSize >= page.total} onClick={() => setOffset(offset + pageSize)}>Next</button>
            </div>
          </>
        ) : <p className="validation-meta">No persisted assessments are available to this account. This is not a finding of compliance or non-compliance.</p>}
      </section>
    </Shell>
  );
}

function ReviewQueue() { return <AssessmentWorkspace title="Human review queue" /> }

class ApiRequestError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function requestApi<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new ApiRequestError(response.status, await responseError(response, `Request failed (${response.status}).`));
  }
  return await response.json() as T;
}

function GlobalVerification() {
  const { token, user, logout } = useAuth();
  const [applications, setApplications] = useState<PersistedApplication[]>([]);
  const [selectedApplicationId, setSelectedApplicationId] = useState(() => new URLSearchParams(window.location.search).get('application_id') || '');
  const [documents, setDocuments] = useState<PersistedDocument[]>([]);
  const [applicationLoading, setApplicationLoading] = useState(true);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [processingId, setProcessingId] = useState<number | null>(null);
  const [validatingId, setValidatingId] = useState<number | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadResetKey, setUploadResetKey] = useState(0);
  const [documentType, setDocumentType] = useState('fire_safety_certificate');
  const [processingResults, setProcessingResults] = useState<Record<number, DocumentProcessingResult>>({});
  const [integrityResults, setIntegrityResults] = useState<Record<number, DocumentIntegrityPreview>>({});
  const [integrityLoadingId, setIntegrityLoadingId] = useState<number | null>(null);
  const [validation, setValidation] = useState<{ documentId: number; preview: DocumentValidationPreview } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setApplicationLoading(true);
    setError(null);
    if (!token) {
      setApplications([]);
      setSelectedApplicationId('');
      setApplicationLoading(false);
      return () => { cancelled = true; };
    }
    requestApi<PersistedApplication[]>('/api/applications/', token)
      .then(items => {
        if (cancelled) return;
        setApplications(items);
        const requestedId = new URLSearchParams(window.location.search).get('application_id');
        setSelectedApplicationId(current => {
          const preferred = current || requestedId || '';
          return items.some(item => String(item.id) === preferred) ? preferred : (items[0] ? String(items[0].id) : '');
        });
      })
      .catch(reason => {
        if (cancelled) return;
        if (reason instanceof ApiRequestError && reason.status === 401) {
          logout();
          setError('Your session has expired. Please sign in again.');
        } else {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend while loading applications. Check your connection and try again.');
        }
      })
      .finally(() => { if (!cancelled) setApplicationLoading(false); });
    return () => { cancelled = true; };
  }, [token, logout]);

  useEffect(() => {
    let cancelled = false;
    setDocuments([]);
    setValidation(null);
    setError(null);
    if (!token || !selectedApplicationId) {
      setDocumentsLoading(false);
      return () => { cancelled = true; };
    }
    setDocumentsLoading(true);
    requestApi<PersistedDocument[]>(`/api/applications/${selectedApplicationId}/documents`, token)
      .then(items => { if (!cancelled) setDocuments(items); })
      .catch(reason => {
        if (cancelled) return;
        if (reason instanceof ApiRequestError && reason.status === 401) {
          logout();
          setError('Your session has expired. Please sign in again.');
        } else {
          setError(reason instanceof ApiRequestError ? reason.message : 'Could not reach the backend while loading documents. Check your connection and try again.');
        }
      })
      .finally(() => { if (!cancelled) setDocumentsLoading(false); });
    return () => { cancelled = true; };
  }, [selectedApplicationId, token, logout]);

  const refreshDocuments = async (applicationId: number) => {
    if (!token) throw new Error('Your session has expired. Please sign in again.');
    const items = await requestApi<PersistedDocument[]>(`/api/applications/${applicationId}/documents`, token);
    setDocuments(items);
  };

  const handleRequestError = (reason: unknown, fallback: string) => {
    if (reason instanceof ApiRequestError && reason.status === 401) {
      logout();
      setError('Your session has expired. Please sign in again.');
    } else {
      setError(reason instanceof ApiRequestError ? reason.message : fallback);
    }
  };

  const handleUpload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || !selectedApplicationId || !selectedFile) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const form = new FormData();
      form.append('file', selectedFile);
      form.append('doc_type', documentType);
      await requestApi<PersistedDocument>(
        `/api/applications/${selectedApplicationId}/documents`,
        token,
        { method: 'POST', body: form },
      );
      await refreshDocuments(Number(selectedApplicationId));
      setSelectedFile(null);
      setUploadResetKey(current => current + 1);
      setNotice('PDF uploaded to the selected application. Process it to extract available text and fields.');
    } catch (reason) {
      handleRequestError(reason, 'Could not upload this PDF. Check the file and connection, then try again.');
    } finally {
      setUploading(false);
    }
  };

  const handleProcess = async (document: PersistedDocument) => {
    if (!token) return;
    setProcessingId(document.id);
    setError(null);
    setNotice(null);
    setValidation(null);
    try {
      const result = await requestApi<DocumentProcessingResult>(
        `/api/applications/${document.application_id}/documents/${document.id}/process`,
        token,
        { method: 'POST' },
      );
      setProcessingResults(current => ({ ...current, [document.id]: result }));
      await refreshDocuments(document.application_id);
      setNotice(`Processing finished with status "${result.processing_status}". Extracted values are unverified and may require human review.`);
    } catch (reason) {
      handleRequestError(reason, 'Document processing failed. The backend may have rejected the file or processing may be unavailable.');
      if (reason instanceof ApiRequestError && reason.status !== 401) {
        refreshDocuments(document.application_id).catch(refreshError => handleRequestError(refreshError, 'Could not refresh document status.'));
      }
    } finally {
      setProcessingId(null);
    }
  };

  const handleValidate = async (document: PersistedDocument) => {
    if (!token || document.processing_status !== 'completed') return;
    setValidatingId(document.id);
    setError(null);
    setNotice(null);
    setValidation(null);
    try {
      const preview = await requestApi<DocumentValidationPreview>(
        `/api/applications/${document.application_id}/documents/${document.id}/validate`,
        token,
        { method: 'POST' },
      );
      setValidation({ documentId: document.id, preview });
    } catch (reason) {
      handleRequestError(reason, 'Validation preview failed. Check the service and try again.');
    } finally {
      setValidatingId(null);
    }
  };

  const handleIntegrityPreview = async (document: PersistedDocument) => {
    if (!token) return;
    setIntegrityLoadingId(document.id);
    setError(null);
    try {
      const result = await requestApi<DocumentIntegrityPreview>(
        `/api/applications/${document.application_id}/documents/${document.id}/integrity-check`,
        token,
        { method: 'POST' },
      );
      setIntegrityResults(current => ({ ...current, [document.id]: result }));
    } catch (reason) {
      handleRequestError(reason, 'Could not inspect document integrity metadata.');
    } finally {
      setIntegrityLoadingId(null);
    }
  };

  const selectedApplication = applications.find(item => String(item.id) === selectedApplicationId);

  return (
    <Shell title="Document Verification" liveData>
      <section className="content-section">
        <Heading
          title="Live document workspace"
          text="Applications and documents below are loaded from the authenticated backend. Access remains subject to the server's role and ownership checks."
        />
        {applicationLoading ? <p role="status">Loading permitted applications…</p> : applications.length === 0 ? (
          <div className="live-empty-state">
            <p className="validation-meta">No applications are available to your account.</p>
            {(user?.role === 'ADMIN' || user?.role === 'INSTITUTION_USER') && <Link className="button primary" to="/applications/new">Create an application</Link>}
          </div>
        ) : (
          <label className="live-application-select">
            Select persisted application
            <select
              aria-label="Select persisted application"
              value={selectedApplicationId}
              onChange={event => { setSelectedApplicationId(event.target.value); setSelectedFile(null); setNotice(null); }}
            >
              {applications.map(application => (
                <option key={application.id} value={application.id}>
                  #{application.id} · {application.reference} · {application.entity_name}
                </option>
              ))}
            </select>
          </label>
        )}
        {selectedApplication && (
          <p className="validation-meta">
            Database application ID: {selectedApplication.id} · {selectedApplication.reference} · {selectedApplication.entity_name} · {selectedApplication.app_type} · {selectedApplication.status || 'Status unavailable'}
          </p>
        )}
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        {notice && <p className="validation-meta" role="status">{notice}</p>}
      </section>

      {selectedApplication && (
        <>
          <section className="content-section">
            <Heading title="Upload a PDF" text="The backend validates PDF content and associates each upload with the selected persisted application." />
            <form className="live-upload-form" onSubmit={handleUpload}>
              <label>
                Document type
                <select value={documentType} onChange={event => setDocumentType(event.target.value)}>
                  <option value="fire_safety_certificate">Fire safety certificate</option>
                  <option value="faculty_qualification_certificate">Faculty qualification certificate</option>
                  <option value="accreditation_certificate">Accreditation certificate</option>
                  <option value="supporting_document">Other supporting document</option>
                </select>
              </label>
              <label>
                PDF file
                <input key={uploadResetKey} type="file" accept="application/pdf,.pdf" required onChange={event => setSelectedFile(event.target.files?.[0] ?? null)} />
              </label>
              <button className="button primary" type="submit" disabled={uploading || !selectedFile}>
                {uploading ? <Loader2 size={17} className="spin" aria-hidden="true" /> : <FileText size={17} aria-hidden="true" />}
                {uploading ? 'Uploading…' : 'Upload PDF'}
              </button>
            </form>
          </section>

          <section className="content-section">
            <Heading title="Persisted documents" text="Document IDs and processing states are returned by the backend; processing and validation actions target these numeric IDs." />
            {documentsLoading ? <p role="status">Loading documents…</p> : documents.length === 0 ? (
              <p className="validation-meta">No persisted documents are attached to this application yet.</p>
            ) : (
              <div className="live-document-list">
                {documents.map(document => (
                  <article className="live-document-card" key={document.id}>
                    <div className="live-document-heading">
                      <div>
                        <h3>{document.original_filename}</h3>
                        <p>Document ID: {document.id} · Application ID: {document.application_id}</p>
                      </div>
                      <Tag>{document.processing_status}</Tag>
                    </div>
                    <dl className="validation-rule-meta">
                      <div><dt>Document type</dt><dd>{document.doc_type}</dd></div>
                      <div><dt>Uploaded</dt><dd>{new Date(document.created_at).toLocaleString()}</dd></div>
                      {document.file_size !== null && <div><dt>File size</dt><dd>{document.file_size.toLocaleString()} bytes</dd></div>}
                    </dl>
                    <div className="live-document-actions">
                      <button className="button secondary" type="button" disabled={integrityLoadingId !== null} onClick={() => handleIntegrityPreview(document)}>
                        {integrityLoadingId === document.id ? <Loader2 size={17} className="spin" aria-hidden="true" /> : <ShieldCheck size={17} aria-hidden="true" />}
                        {integrityLoadingId === document.id ? 'Inspecting…' : 'Integrity checks'}
                      </button>
                      {(document.processing_status === 'pending' || document.processing_status === 'failed') && (
                        <button className="button secondary" type="button" disabled={processingId !== null} onClick={() => handleProcess(document)}>
                          {processingId === document.id ? <Loader2 size={17} className="spin" aria-hidden="true" /> : <FileText size={17} aria-hidden="true" />}
                          {processingId === document.id ? 'Processing…' : 'Process document'}
                        </button>
                      )}
                      <button className="button primary" type="button" disabled={document.processing_status !== 'completed' || validatingId !== null} onClick={() => handleValidate(document)}>
                        {validatingId === document.id ? <Loader2 size={17} className="spin" aria-hidden="true" /> : <FileCheck2 size={17} aria-hidden="true" />}
                        {validatingId === document.id ? 'Loading preview…' : 'Validate document'}
                      </button>
                    </div>
                    {integrityResults[document.id] && (
                      <section className="integrity-preview">
                        <h4>Integrity assistance · authenticity not assessed</h4>
                        <p><b>Duplicate-file hash check ({integrityResults[document.id].duplicate_file_check.status}):</b> {integrityResults[document.id].duplicate_file_check.explanation}</p>
                        {integrityResults[document.id].duplicate_file_check.matches.map(match => <p key={match.document_id}>Matching document ID {match.document_id}: {match.original_filename}</p>)}
                        <p><b>PDF structure ({integrityResults[document.id].pdf_structure_check.status}):</b> {integrityResults[document.id].pdf_structure_check.explanation}</p>
                        <p><b>Metadata ({integrityResults[document.id].metadata_check.status}):</b> {integrityResults[document.id].metadata_check.explanation}</p>
                        <p>Issuer verification: {integrityResults[document.id].issuer_verification}. No genuineness or fraud determination is made.</p>
                        {integrityResults[document.id].limitations.map((limitation, index) => <p key={index} className="validation-meta">{limitation}</p>)}
                      </section>
                    )}
                    {document.processing_status === 'ocr_unavailable' && (
                      <p className="validation-meta">Processing did not complete successfully for validation; the preview requires completed extraction.</p>
                    )}
                    {processingResults[document.id] && (
                      <section className="validation-subsection">
                        <h4>Latest extraction response · {processingResults[document.id].extraction_method}</h4>
                        <p className="validation-meta">Extraction is unverified. Pages processed: {processingResults[document.id].pages_processed}.</p>
                        {Object.entries(processingResults[document.id].fields).map(([name, field]) => (
                          <p key={name}><b>{name.replaceAll('_', ' ')}:</b> {field.value ?? 'Not extracted'}{field.evidence ? ` · Evidence: ${field.evidence}` : ''}{field.page !== null ? ` · Page ${field.page}` : ''}</p>
                        ))}
                        {processingResults[document.id].warnings.map((warning, index) => <p key={index}>{warning}</p>)}
                      </section>
                    )}
                    {validation?.documentId === document.id && <DocumentValidationResult preview={validation.preview} />}
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
      <p className="validation-disclaimer">
        Extracted text and OCR-derived fields are unverified evidence. A validation preview does not establish authenticity, fraud, or institutional compliance. Unknown and not_assessed results are reported as returned by the backend.
      </p>
    </Shell>
  );
}

function GlobalCompliance() { return <AssessmentWorkspace title="Compliance Assessment" /> }

function Reports() {
  const { token, logout } = useAuth();
  const [applications, setApplications] = useState<PersistedApplication[]>([]);
  const [documentCounts, setDocumentCounts] = useState<Record<number, number>>({});
  const [assessmentCounts, setAssessmentCounts] = useState<Record<number, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    Promise.all([
      requestApi<PersistedApplication[]>('/api/applications/', token),
      requestApi<ComplianceAssessmentPage>('/api/compliance-assessments/', token),
    ]).then(async ([apps, assessmentPage]) => {
      const docs = await Promise.all(apps.map(app =>
        requestApi<PersistedDocument[]>(`/api/applications/${app.id}/documents`, token),
      ));
      if (cancelled) return;
      setApplications(apps);
      setDocumentCounts(Object.fromEntries(apps.map((app, index) => [app.id, docs[index].length])));
      setAssessmentCounts(assessmentPage.items.reduce<Record<number, number>>((counts, item) => {
        counts[item.application_id] = (counts[item.application_id] || 0) + 1;
        return counts;
      }, {}));
    }).catch(reason => {
      if (cancelled) return;
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not load report data from the backend.');
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, logout]);
  return (
    <Shell title="Validation Reports" liveData>
      <section className="content-section">
        <Heading title="Persisted application summaries" text="Counts come from authorized application, document, and reviewer-assessment endpoints. No simulated compliance conclusion is generated." />
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        {loading ? <p role="status">Loading report summaries…</p> : applications.length ? (
          <div className="report-grid">{applications.map(application => (
            <article className="report-card" key={application.id}>
              <div>
                <h3>{application.reference} · {application.entity_name}</h3>
                <p>Database ID {application.id} · {application.app_type} · Status: {application.status || 'Unknown'}</p>
                <p>Persisted documents: {documentCounts[application.id] ?? 0} · Assessments in first API page: {assessmentCounts[application.id] ?? 0}</p>
                <small>These are record counts only. They do not indicate authenticity, completeness, or regulatory compliance.</small>
              </div>
              <Link className="button secondary" to={`/reports/${application.id}`}>Open record summary</Link>
            </article>
          ))}</div>
        ) : <p className="validation-meta">No reportable applications are available to this account.</p>}
      </section>
    </Shell>
  );
}

function PersistedReport() {
  const { id = '' } = useParams();
  const { token, logout } = useAuth();
  const [application, setApplication] = useState<PersistedApplication | null>(null);
  const [documents, setDocuments] = useState<PersistedDocument[]>([]);
  const [assessments, setAssessments] = useState<ComplianceAssessment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    Promise.all([
      requestApi<PersistedApplication>(`/api/applications/${id}`, token),
      requestApi<PersistedDocument[]>(`/api/applications/${id}/documents`, token),
      requestApi<ComplianceAssessmentPage>('/api/compliance-assessments/', token),
    ]).then(([app, docs, assessmentPage]) => {
      if (cancelled) return;
      setApplication(app);
      setDocuments(docs);
      setAssessments(assessmentPage.items.filter(item => item.application_id === app.id));
    }).catch(reason => {
      if (cancelled) return;
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not load the persisted application summary.');
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, token, logout]);
  if (loading) return <Shell title="Application report" liveData><p role="status">Loading persisted application summary…</p></Shell>;
  if (!application && !error) return <Navigate to="/reports" replace />;
  return (
    <Shell title="Application report" liveData>
      {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
      {application && (
        <article className="print-report">
          <p className="eyebrow">Persisted application summary · ID {application.id}</p>
          <h2>{application.entity_name}</h2>
          <p>{application.reference} · {application.app_type} · Status: {application.status || 'Unknown'}</p>
          <p>Created {new Date(application.created_at).toLocaleString()} · Updated {new Date(application.updated_at).toLocaleString()}</p>
          <h3>Persisted document records</h3>
          {documents.length ? documents.map(document => <p key={document.id}>Document {document.id} · {document.original_filename} · {document.doc_type} · {document.processing_status}</p>) : <p>No documents are currently attached.</p>}
          <h3>Stored reviewer assessments in first API page</h3>
          {assessments.length ? assessments.map(item => <p key={item.id}><b>{item.rule_code} · {item.rule_title}</b> — {item.status}. {item.explanation} Reviewer: {item.reviewer_name || 'Unassigned'}.</p>) : <p>No persisted assessments are available for this application.</p>}
          <p className="validation-disclaimer">This record summary reports stored data only. It does not establish document authenticity, application completeness, or institutional compliance. Candidate regulatory rules that have not passed review remain unassessed.</p>
          <button className="button primary no-print" onClick={() => window.print()}>Print record summary</button>
        </article>
      )}
    </Shell>
  );
}

function Report() { const { id = '' } = useParams(); const { apps } = useStore(); const app = apps.find(a => a.id === id); if (!app) return <Navigate to="/reports" replace />; return <Shell title="Validation report"><article className="print-report"><p className="eyebrow">Frontend demonstration report · simulated outcomes</p><h2>{app.institution}</h2><p>{app.id} · {app.category} · Submitted {app.submitted}</p><h3>Document checklist summary</h3><p>{app.documents.map(d => `${d.name}: ${d.status}`).join(' · ')}</p><h3>Unresolved issues and comparisons</h3><p>{app.findings.length ? app.findings.map(f => <p key={f.id}><b>{f.title}</b> — {f.explanation} Next step: {f.action}</p>).join('') : 'Matching simulated document values; no finding requires action.'}</p><h3>Overall scrutiny status</h3><p>{app.status}. This report does not declare an approval or rejection.</p><button className="button primary no-print" onClick={() => window.print()}>Print report</button></article></Shell> }

function ReportRouteView() { const { id = '' } = useParams(); return /^\d+$/.test(id) ? <PersistedReport /> : <Report /> }

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
          <label className="auth-field" htmlFor="login-email">
            <span>Email address</span>
            <div className="auth-input-wrap">
              <Mail size={18} aria-hidden="true" />
              <input
                id="login-email"
                type="email"
                placeholder="Email address"
                autoComplete="email"
                aria-describedby={error ? 'login-error' : undefined}
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
              />
            </div>
          </label>
          <label className="auth-field" htmlFor="login-password">
            <span>Password</span>
            <div className="auth-input-wrap">
              <Lock size={18} aria-hidden="true" />
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Password"
                autoComplete="current-password"
                aria-describedby={error ? 'login-error' : undefined}
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
              </button>
            </div>
          </label>

          {error && <div className="auth-error" id="login-error" role="alert"><AlertTriangle size={16} aria-hidden="true" />{error}</div>}

          <button type="submit" className="button primary full" disabled={isLoading}>
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
      <Route path="/applications/new" element={user ? <CreateApplication /> : <Navigate to="/login" replace />} />
      <Route path="/applications/:id" element={user ? <ApplicationRouteView /> : <Navigate to="/login" replace />} />
      <Route path="/applications/:id/documents/:docId" element={user ? <DocumentView /> : <Navigate to="/login" replace />} />
      <Route path="/review-queue" element={user ? <ReviewQueue /> : <Navigate to="/login" replace />} />
      <Route path="/verification" element={user ? <GlobalVerification /> : <Navigate to="/login" replace />} />
      <Route path="/ai-evidence" element={user ? <AIEvidenceSearch /> : <Navigate to="/login" replace />} />
      <Route path="/compliance" element={user ? <GlobalCompliance /> : <Navigate to="/login" replace />} />
      <Route path="/reports" element={user ? <Reports /> : <Navigate to="/login" replace />} />
      <Route path="/reports/:id" element={user ? <ReportRouteView /> : <Navigate to="/login" replace />} />
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
