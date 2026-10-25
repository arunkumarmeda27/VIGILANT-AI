import React, { createContext, useContext, useMemo, useRef, useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, ClipboardCheck, Database, Eye, EyeOff, FileCheck2, FileText, LayoutDashboard, ListChecks, Menu, Search, ShieldCheck, UserRound, XCircle, Lock, Mail, Loader2 } from 'lucide-react';
import './styles.css';
import './command.css';
import { AssessmentReviewForm, validateAssessmentReviewNote, type AssessmentReviewOutcome } from './components/AssessmentReviewForm';

// --- Types ---
type DS = 'Not Submitted' | 'Received' | 'Validation Pending' | 'Verified' | 'Mismatch Detected' | 'Source Unavailable' | 'Manual Review Required';
type RS = 'Open' | 'In Review' | 'Resolved' | 'Awaiting Evidence';
type AS = 'Awaiting Scrutiny' | 'Missing Documents' | 'Discrepancies' | 'Manual Review' | 'Ready for Further Scrutiny';
type Doc = { id: string; name: string; required: boolean; status: DS; date: string; fields: Record<string, string>; comment: string };
type Finding = { id: string; type: 'Cross-document discrepancy' | 'Potential anomaly' | 'Missing evidence'; title: string; priority: 'High' | 'Medium' | 'Low'; status: RS; documents: string[]; field?: string; first?: string; second?: string; explanation: string; action: string; assignee: string; comments: string[] };
type App = { id: string; institution: string; category: string; submitted: string; status: AS; reviewer: string; nextAction: string; documents: Doc[]; findings: Finding[] };
type Audit = { id: string; applicationId: string; time: string; actor: string; action: string };
type User = { id: number; full_name: string; email: string; role: string; is_active: boolean };
type UserPage = { items: User[]; total: number; limit: number; offset: number };
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
  assigned_reviewer_id: number | null;
  application_reference: string;
  entity_name: string;
  rule_code: string;
  rule_title: string;
  category: string;
  status: string;
  explanation: string;
  assessed_at: string;
  reviewer_name: string | null;
  reviews: AssessmentReview[];
};
type AssessmentReview = {
  id: number;
  assessment_id: number;
  reviewer_id: number;
  reviewer_name: string;
  outcome: 'evidence_accepted' | 'evidence_rejected' | 'information_requested' | 'further_investigation';
  note: string;
  created_at: string;
};
type ComplianceAssessmentDetail = ComplianceAssessment & {
  application_status: string;
  rule_description: string;
  assigned_reviewer_id: number | null;
  document_evidence: {
    document_id: number;
    filename: string;
    document_type: string;
    processing_status: string;
    extraction_method: string;
    fields: Record<string, ExtractedField>;
  }[];
  reviews: AssessmentReview[];
};
type AssessmentReviewer = { id: number; full_name: string; email: string };
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
  classification: {
    status: 'classified' | 'needs_review' | 'unavailable';
    candidate_document_type: string | null;
    match_strength: 'strong' | 'possible' | 'none';
    evidence: { page: number; signal: string; excerpt: string; document_type?: string | null }[];
    explanation: string;
  } | null;
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

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

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
const navGroups = [
  { label: 'WORKSPACE', items: [['/dashboard', LayoutDashboard, 'Overview'], ['/applications', FileText, 'Applications'], ['/review-queue', ListChecks, 'Review Queue']] },
  { label: 'EVIDENCE', items: [['/verification', FileCheck2, 'Document Verification'], ['/ai-evidence', Search, 'AI Evidence Search']] },
  { label: 'GOVERNANCE', items: [['/compliance', ClipboardCheck, 'Compliance Assessment'], ['/reports', FileText, 'Validation Reports'], ['/audit-trail', ShieldCheck, 'Audit History'], ['/administration', UserRound, 'Administration']] },
] as const;

function Shell({ title, children, liveData = false }: { title: string; children: React.ReactNode; liveData?: boolean }) {
  const [open, setOpen] = useState(false);
  const { user, logout } = useAuth();
  return (
    <div className="app-shell">
      {open && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <aside id="workspace-navigation" className={open ? 'open' : ''}>
        <div className="sidebar-brand-row"><Brand /><button className="sidebar-close" aria-label="Close navigation" onClick={() => setOpen(false)}><XCircle size={19} /></button></div>
        <div className="workspace-label"><span className="workspace-dot" /> REVIEW WORKSPACE <span className="role-tag">{user?.role || 'GUEST'}</span></div>
        <nav aria-label="Main navigation">
          {navGroups.map(group => <div className="nav-group" key={group.label}>
            <p className="nav-group-label">{group.label}</p>
            {group.items.filter(([to]) => to !== '/administration' || user?.role === 'ADMIN').map(([to, I, label]) => (
              <NavLink key={to} to={to} onClick={() => setOpen(false)}><I size={18} strokeWidth={1.8} /><span>{label}</span>{label === 'Review Queue' && <span className="nav-arrow" aria-hidden="true">›</span>}</NavLink>
            ))}
          </div>)}
        </nav>
        <div className="sidebar-user">
          <span className="avatar">{user?.full_name?.substring(0, 2).toUpperCase() || '??'}</span>
          <span className="sidebar-user-meta"><b>{user?.full_name || 'Unknown'}</b><small>{user?.role || 'Guest'}</small></span>
          <button className="logout-btn" onClick={logout} title="Sign out" aria-label="Sign out"><XCircle size={16} /></button>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <button className="menu" aria-label="Open navigation" aria-expanded={open} aria-controls="workspace-navigation" onClick={() => setOpen(!open)}><Menu /></button>
          <div className="topbar-title"><p className="crumb">VIGILANT AI <span>/</span> {title}</p><h1>{title}</h1></div>
          <div className="topbar-context">{liveData ? <Database size={15} aria-hidden="true" /> : <ShieldCheck size={15} aria-hidden="true" />}<span>{liveData ? 'Persisted data' : 'Interactive demo'}</span></div>
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
function readableAuditAction(action: string) {
  const labels: Record<string, string> = {
    'application.created': 'Application created',
    'application.updated': 'Application details changed',
    'application.validate_all': 'Regulatory validation run',
    'application.validate_consistency': 'Cross-document comparison run',
    'application.checklist_validated': 'Document checklist run',
    'document.uploaded': 'Document uploaded',
    'document.duplicate_detected': 'Possible identical file detected',
    'document.processed': 'Document processing completed',
    'document.processing_failed': 'Document processing failed',
    'document.integrity_checked': 'Document integrity checks run',
    'compliance_assessment.reviewer_assigned': 'Assessment reviewer assigned',
    'compliance_assessment.review_recorded': 'Human assessment decision recorded',
    'finding.review_recorded': 'Finding review recorded',
    'institution.created': 'Institution created',
  };
  return labels[action] || action.replaceAll('.', ' · ').replaceAll('_', ' ');
}
function AppTable({ rows }: { rows: App[] }) { return <div className="table-wrap"><table><thead><tr><th>Application</th><th>Institution</th><th>Category</th><th>Completeness</th><th>Unresolved</th><th>Reviewer</th><th>Next action</th><th>Status</th></tr></thead><tbody>{rows.map(a => { const missing = a.documents.filter(d => d.status === 'Not Submitted').length; return <tr key={a.id}><td><Link className="table-link" to={`/applications/${a.id}`}>{a.id}</Link></td><td>{a.institution}</td><td>{a.category}</td><td>{missing ? `${missing} missing` : 'Received'}</td><td>{a.findings.filter(f => f.status !== 'Resolved').length}</td><td>{a.reviewer}</td><td>{a.nextAction}</td><td><Tag>{a.status}</Tag></td></tr> })}</tbody></table></div> }

function Home() { return <><header className="public-header"><Brand /><div className="header-actions"><Link className="text-link" to="/login">Sign in</Link><Link className="button primary" to="/dashboard">Open dashboard <ArrowRight size={16} /></Link></div></header><main><section className="hero"><div><p className="eyebrow">SIH26261 · evidence-led review</p><h1>Application validation that keeps people in the decision loop.</h1><p className="lede">VIGILANT AI is a frontend prototype for reviewing institutional application evidence, comparing documents, and organising manual scrutiny.</p><Link className="button primary" to="/dashboard">Open verification workspace <ArrowRight size={16} /></Link></div><div className="hero-panel"><p className="eyebrow">Simulated finding</p><h3>Registration mismatch</h3><p>Source-linked comparison and a recommended human action, never an automatic decision.</p></div></section></main></> }

function Dashboard() {
  const { token, logout } = useAuth();
  const [applications, setApplications] = useState<PersistedApplication[]>([]);
  const [documents, setDocuments] = useState<PersistedDocument[]>([]);
  const [assessments, setAssessments] = useState<ComplianceAssessment[]>([]);
  const [assessmentTotal, setAssessmentTotal] = useState(0);
  const [openFindingCount, setOpenFindingCount] = useState(0);
  const [pendingReviewCount, setPendingReviewCount] = useState(0);
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [refreshCount, setRefreshCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPartialErrors([]);
    if (!token) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    requestApi<PersistedApplication[]>('/api/applications/', token)
      .then(async items => {
        const [assessmentResult, auditResult] = await Promise.allSettled([
          loadAllComplianceAssessments(token),
          requestApi<AuditEventPage>('/api/audit-events/?limit=6&offset=0', token),
        ]);
        const [documentResults, findingResults] = await Promise.all([
          Promise.allSettled(items.map(application =>
            requestApi<PersistedDocument[]>(`/api/applications/${application.id}/documents`, token),
          )),
          Promise.allSettled(items.map(application =>
            requestApi<PersistedFinding[]>(`/api/applications/${application.id}/findings`, token),
          )),
        ]);
        const failures = [assessmentResult, auditResult, ...documentResults, ...findingResults]
          .filter(result => result.status === 'rejected');
        if (failures.some(result => result.status === 'rejected' && result.reason instanceof ApiRequestError && result.reason.status === 401)) {
          throw new ApiRequestError(401, 'Your session has expired. Please sign in again.');
        }
        const warnings: string[] = [];
        if (assessmentResult.status === 'rejected') warnings.push('Assessment records could not be loaded.');
        if (auditResult.status === 'rejected') warnings.push('Recent audit activity could not be loaded.');
        const availableDocuments = documentResults.flatMap(result => result.status === 'fulfilled' ? result.value : []);
        const availableFindings = findingResults.flatMap(result => result.status === 'fulfilled' ? result.value : []);
        const unavailableDocumentLists = documentResults.filter(result => result.status === 'rejected').length;
        const unavailableFindingLists = findingResults.filter(result => result.status === 'rejected').length;
        if (unavailableDocumentLists) warnings.push(`Document counts are incomplete for ${unavailableDocumentLists} application(s).`);
        if (unavailableFindingLists) warnings.push(`Finding counts are incomplete for ${unavailableFindingLists} application(s).`);
        const assessmentItems = assessmentResult.status === 'fulfilled' ? assessmentResult.value : [];
        const auditItems = auditResult.status === 'fulfilled' ? auditResult.value.items : [];
        const openFindings = availableFindings.filter(finding => finding.status.toLowerCase() === 'open').length;
        const pendingReviews = assessmentItems.filter(item =>
          item.assigned_reviewer_id !== null
          && !item.reviews.some(review => review.reviewer_id === item.assigned_reviewer_id),
        ).length;
        if (!cancelled) {
          setApplications(items);
          setDocuments(availableDocuments);
          setAssessments(assessmentItems.slice(0, 8));
          setAssessmentTotal(assessmentItems.length);
          setOpenFindingCount(openFindings);
          setPendingReviewCount(pendingReviews);
          setAuditEvents(auditItems);
          setPartialErrors(warnings);
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
  }, [token, logout, refreshCount]);

  const metrics = [
    ['Accessible applications', applications.length, '/applications'],
    ['Submitted', applications.filter(item => item.status === 'submitted').length, '/applications?status=submitted'],
    ['Documents uploaded', documents.length, '/verification'],
    ['Documents processed', documents.filter(item => item.processing_status === 'completed').length, '/verification'],
    ['Assessment records', assessmentTotal, '/review-queue'],
    ['Pending human reviews', pendingReviewCount, '/review-queue'],
    ['Open findings', openFindingCount, '/applications'],
    ['Processing failures', documents.filter(item => item.processing_status === 'failed').length, '/verification'],
    ['Awaiting processing', documents.filter(item => item.processing_status === 'pending' || item.processing_status === 'processing').length, '/verification'],
    ['OCR unavailable', documents.filter(item => item.processing_status === 'ocr_unavailable').length, '/verification'],
  ];
  const recent = [...applications].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 8);

  return (
    <Shell title="Overview" liveData>
      <div className="live-page-actions"><button className="button secondary" type="button" onClick={() => setRefreshCount(count => count + 1)} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh dashboard'}</button></div>
      {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
      {partialErrors.length > 0 && !loading && <p className="validation-meta" role="status">Some dashboard data is incomplete: {partialErrors.join(' ')}</p>}
      {loading ? <section className="content-section" role="status">Loading accessible applications and document statuses…</section> : (
        <>
          {applications.length === 0 && <section className="content-section live-empty-state"><h2>No accessible applications</h2><p>The backend returned no applications for this account.</p><Link className="button primary" to="/applications">Open application register</Link></section>}
          <div className="metric-grid six">
            {metrics.map(([label, value, href]) => <Link className="metric metric-link" to={href as string} key={label as string}><span>{label}</span><strong>{value}</strong><small>Open related records</small></Link>)}
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
          <div className="overview-activity-grid">
            <section className="content-section">
              <Heading title="Recent assessments" text="Persisted records available to your account. Automated results remain separate from human decisions." />
              {assessments.length ? <div className="overview-record-list">{assessments.slice(0, 6).map(item => <article key={item.id}>
                <div><b>{item.rule_code} · {item.application_reference}</b><Tag>{item.status}</Tag></div>
                <p>{item.entity_name} · {item.rule_title}</p>
                <small>{new Date(item.assessed_at).toLocaleString()} · Reviewer: {item.reviewer_name || 'Unassigned'}</small>
                <Link className="table-link" to={`/compliance-assessments/${item.id}`}>Open assessment <ArrowRight size={13} aria-hidden="true" /></Link>
              </article>)}</div> : <p className="validation-meta">No persisted assessments are available to this account.</p>}
              <Link className="button secondary overview-link" to="/review-queue">Open review queue</Link>
            </section>
            <section className="content-section">
              <Heading title="Recent audit activity" text="Authorized events returned by the backend. Event visibility is scoped by your account." />
              {auditEvents.length ? <div className="overview-audit-list">{auditEvents.map(event => <article key={event.id}>
                <span className="audit-marker" aria-hidden="true" />
                <div><b>{readableAuditAction(event.action)}</b><p>{event.entity_type} {event.entity_id} · {event.actor_name || 'Actor unavailable'}</p><time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()}</time></div>
              </article>)}</div> : <p className="validation-meta">No audit activity is available to this account.</p>}
              <Link className="button secondary overview-link" to="/audit-trail">View audit history</Link>
            </section>
          </div>
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
  const examples = [
    'What fire safety evidence is described in the available source?',
    'Which page discusses the required supporting documents?',
    'What does the source say about institutional infrastructure evidence?',
  ];

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
          text="Search indexed handbook text using ranked term matching. Results show source passages and citations; no regulatory conclusion is generated."
        />
        <div className="ai-examples" aria-label="Example questions">
          <span>Try an example</span>
          {examples.map(example => <button className="ai-example" type="button" key={example} disabled={isLoading} onClick={() => { setQuestion(example); setAnswer(null); setError(null); }}>{example}</button>)}
        </div>
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
        {isLoading && <p className="ai-search-loading" role="status"><Loader2 size={17} className="spin" aria-hidden="true" /> Searching the available source…</p>}
        {!answer && !error && !isLoading && <p className="ai-search-empty">Choose an example or enter a question. Returned passages and citations will appear here.</p>}
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
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState(() => searchParams.get('status') || 'All');
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
              <select aria-label="Filter application status" value={statusFilter} onChange={event => {
                const nextStatus = event.target.value;
                setStatusFilter(nextStatus);
                setSearchParams(nextStatus === 'All' ? {} : { status: nextStatus });
              }}>
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
      requestApi<ComplianceAssessmentPage>(`/api/compliance-assessments/?application_id=${id}&limit=200`, token),
    ]).then(([app, docs, history, persistedFindings, assessmentPage]) => {
      if (cancelled) return;
      setApplication(app);
      setEntityName(app.entity_name);
      setAppType(app.app_type);
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
      const assessmentPage = await requestApi<ComplianceAssessmentPage>(`/api/compliance-assessments/?application_id=${application.id}&limit=200`, token);
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
            {documents.filter(document => document.processing_status === 'completed').length < 2 && <p className="validation-meta">Cross-document comparison requires at least two successfully processed documents. It compares extracted fields; it does not verify document authenticity.</p>}
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
          {canEditDetails && (
            <section className="content-section">
              <Heading title="Update application" text="The backend enforces which fields your role may change. Application status is read-only until a controlled status workflow is available." />
              <form className="application-form live-application-form" onSubmit={update}>
                <label>Institution or organization name<input value={entityName} onChange={event => setEntityName(event.target.value)} maxLength={255} required /></label>
                <label>Application type<input value={appType} onChange={event => setAppType(event.target.value)} maxLength={100} required /></label>
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

function Detail() {
  const { id = '' } = useParams();
  const { apps } = useStore();
  const app = apps.find(a => a.id === id);
  const [tab, setTab] = useState('Overview');
  if (!app) return <Navigate to="/applications" replace />;
  const tabs = ['Overview', 'Documents', 'Findings', 'Compliance', 'Verification', 'Audit History'];
  const panels: Record<string, React.ReactNode> = {
    Overview: <Overview app={app} />, Documents: <Documents app={app} />, Findings: <Findings app={app} />,
    Compliance: <Compliance app={app} />, Verification: <Verification app={app} />, 'Audit History': <Audit app={app} />,
  };
  const selectTab = (index: number) => setTab(tabs[(index + tabs.length) % tabs.length]);
  return <Shell title="Application details">
    <section className="detail-head"><div><p className="eyebrow">{app.category}</p><h2>{app.id}</h2><p>{app.institution} · Submitted {app.submitted}</p></div><Tag>{app.status}</Tag></section>
    <div className="tabs" role="tablist" aria-label="Application details">
      {tabs.map((t, index) => <button key={t} id={`application-tab-${index}`} type="button" role="tab" aria-selected={tab === t} aria-controls="application-tabpanel" tabIndex={tab === t ? 0 : -1} className={tab === t ? 'active' : ''} onClick={() => setTab(t)} onKeyDown={event => {
        if (event.key === 'ArrowRight') { event.preventDefault(); selectTab(index + 1); document.getElementById(`application-tab-${(index + 1) % tabs.length}`)?.focus(); }
        else if (event.key === 'ArrowLeft') { event.preventDefault(); selectTab(index - 1); document.getElementById(`application-tab-${(index + tabs.length - 1) % tabs.length}`)?.focus(); }
        else if (event.key === 'Home') { event.preventDefault(); selectTab(0); document.getElementById('application-tab-0')?.focus(); }
        else if (event.key === 'End') { event.preventDefault(); selectTab(tabs.length - 1); document.getElementById(`application-tab-${tabs.length - 1}`)?.focus(); }
      }}>{t}</button>)}
    </div>
    <div id="application-tabpanel" role="tabpanel" aria-labelledby={`application-tab-${tabs.indexOf(tab)}`} tabIndex={0}>{panels[tab]}</div>
  </Shell>;
}

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
  const [actionDraft, setActionDraft] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [entityTypeDraft, setEntityTypeDraft] = useState('');
  const [entityTypeFilter, setEntityTypeFilter] = useState('');
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
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
    if (actionFilter) params.set('action', actionFilter);
    if (entityTypeFilter) params.set('entity_type', entityTypeFilter);
    requestApi<AuditEventPage>(`/api/audit-events/?${params.toString()}`, token)
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
  }, [token, logout, offset, actionFilter, entityTypeFilter]);

  const applyFilters = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setOffset(0);
    setActionFilter(actionDraft.trim());
    setEntityTypeFilter(entityTypeDraft);
  };

  const clearFilters = () => {
    setOffset(0);
    setActionDraft('');
    setActionFilter('');
    setEntityTypeDraft('');
    setEntityTypeFilter('');
  };

  return (
    <Shell title="Audit History" liveData>
      <section className="content-section">
        <Heading title="Authorized audit events" text="Events are filtered by server-side role and application access. Sensitive values and document contents are not included." />
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        <form className="audit-filter-form" onSubmit={applyFilters}>
          <label>Action contains<input value={actionDraft} onChange={event => setActionDraft(event.target.value)} maxLength={120} placeholder="e.g. review_recorded" /></label>
          <label>Event type<select value={entityTypeDraft} onChange={event => setEntityTypeDraft(event.target.value)}>
            <option value="">All event types</option><option value="application">Application</option><option value="document">Document</option><option value="compliance_assessment">Compliance assessment</option><option value="finding">Finding</option><option value="institution">Institution</option><option value="user">User</option>
          </select></label>
          <button className="button secondary" type="submit" disabled={loading}>Apply filters</button>
          <button className="button secondary" type="button" onClick={clearFilters} disabled={loading || (!actionDraft && !entityTypeDraft && !actionFilter && !entityTypeFilter)}>Clear</button>
        </form>
        {loading ? <p role="status">Loading audit history…</p> : page?.items.length ? (
          <>
            <div className="audit-event-list">
              {page.items.map(event => (
                <article className="audit-event-card" key={event.id}>
                  <div><b>{readableAuditAction(event.action)}</b><Tag>{event.entity_type}</Tag></div>
                  <p>Entity ID {event.entity_id} · {event.actor_name || `User ${event.user_id ?? 'unavailable'}`}</p>
                  <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()}</time>
                  {Object.keys(event.metadata).length > 0 && <details className="audit-event-details">
                    <summary>Event metadata</summary>
                    <dl className="audit-event-metadata">
                      {Object.entries(event.metadata).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{Array.isArray(value) ? value.join(', ') : value === null ? '—' : String(value)}</dd></div>)}
                    </dl>
                  </details>}
                </article>
              ))}
            </div>
            <div className="live-page-actions audit-pagination" role="group" aria-label="Audit history pagination">
              <button className="button secondary" aria-label="Previous audit history page" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
              <span aria-live="polite">Showing {offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}</span>
              <button className="button secondary" aria-label="Next audit history page" disabled={loading || offset + pageSize >= page.total} onClick={() => setOffset(offset + pageSize)}>Next</button>
            </div>
          </>
        ) : <p className="validation-meta">{actionFilter || entityTypeFilter ? 'No audit events match these filters.' : 'No audit events are available to this account.'}</p>}
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
        <Heading title={title} text="Persisted assessment snapshots are shown newest first. Changed results remain as history; repeated identical validation results do not create duplicate snapshots. Candidate registry rules are not treated as assessments." />
        {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
        {loading ? <p role="status">Loading authorized assessments…</p> : page?.items.length ? (
          <>
            <div className="table-wrap" role="region" aria-label={`${title} table; scroll horizontally for more columns`} tabIndex={0}><table><thead><tr><th>Application</th><th>Institution</th><th>Rule</th><th>Category</th><th>Recorded status</th><th>Reviewer</th><th>Human decisions</th><th>Assessed</th><th>Explanation</th><th>Review</th></tr></thead>
              <tbody>{page.items.map(item => <tr key={item.id}>
                <td><Link className="table-link" to={`/applications/${item.application_id}`}>{item.application_reference}</Link></td>
                <td>{item.entity_name}</td><td>{item.rule_code} · {item.rule_title}</td><td>{item.category}</td><td><Tag>{item.status}</Tag></td><td>{item.reviewer_name || 'Unassigned'}</td>
                <td>{item.reviews.length ? `${item.reviews.length} decision(s) · latest: ${item.reviews[item.reviews.length - 1].outcome.replaceAll('_', ' ')}` : 'No decision recorded'}</td>
                <td>{new Date(item.assessed_at).toLocaleString()}</td><td>{item.explanation}</td>
                <td><Link className="button secondary" to={`/compliance-assessments/${item.id}`}>Open review</Link></td>
              </tr>)}</tbody>
            </table></div>
            <div className="live-page-actions audit-pagination" role="group" aria-label="Assessment queue pagination">
              <button className="button secondary" aria-label="Previous assessment page" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
              <span aria-live="polite">Showing {offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}</span>
              <button className="button secondary" aria-label="Next assessment page" disabled={loading || offset + pageSize >= page.total} onClick={() => setOffset(offset + pageSize)}>Next</button>
            </div>
          </>
        ) : <p className="validation-meta">No persisted assessments are available to this account. This is not a finding of compliance or non-compliance.</p>}
      </section>
    </Shell>
  );
}

function ReviewQueue() { return <AssessmentWorkspace title="Human review queue" /> }

function AssessmentReviewPage() {
  const { id = '' } = useParams();
  const { token, user, logout } = useAuth();
  const [assessment, setAssessment] = useState<ComplianceAssessmentDetail | null>(null);
  const [reviewers, setReviewers] = useState<AssessmentReviewer[]>([]);
  const [reviewerId, setReviewerId] = useState('');
  const [outcome, setOutcome] = useState<AssessmentReviewOutcome>('information_requested');
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = async () => {
    if (!token) return;
    const item = await requestApi<ComplianceAssessmentDetail>(`/api/compliance-assessments/${id}`, token);
    setAssessment(item);
    setReviewerId(item.assigned_reviewer_id ? String(item.assigned_reviewer_id) : '');
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (!token) { setLoading(false); return () => { cancelled = true; }; }
    Promise.all([
      requestApi<ComplianceAssessmentDetail>(`/api/compliance-assessments/${id}`, token),
      user?.role === 'ADMIN' ? requestApi<AssessmentReviewer[]>('/api/compliance-assessments/reviewers', token) : Promise.resolve([]),
    ]).then(([item, availableReviewers]) => {
      if (cancelled) return;
      setAssessment(item);
      setReviewerId(item.assigned_reviewer_id ? String(item.assigned_reviewer_id) : '');
      setReviewers(availableReviewers);
    }).catch(reason => {
      if (cancelled) return;
      if (reason instanceof ApiRequestError && reason.status === 401) {
        logout();
        setError('Your session has expired. Please sign in again.');
      } else {
        setError(reason instanceof ApiRequestError ? reason.message : 'Could not load this assessment review.');
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, token, user?.role, logout]);

  const saveReview = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || savingRef.current) return;
    const noteError = validateAssessmentReviewNote(note);
    if (noteError) { setError(noteError); return; }
    savingRef.current = true;
    setSaving(true); setError(null); setNotice(null);
    try {
      await requestApi(`/api/compliance-assessments/${id}/reviews`, token, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome, note: note.trim() }),
      });
      await reload();
      setNote('');
      setNotice('Your decision was saved. The automated assessment remains unchanged.');
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : 'Could not save the review decision.');
    } finally { savingRef.current = false; setSaving(false); }
  };

  const assignReviewer = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || !reviewerId || savingRef.current) return;
    savingRef.current = true;
    setSaving(true); setError(null); setNotice(null);
    try {
      await requestApi(`/api/compliance-assessments/${id}/assignment`, token, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: Number(reviewerId) }),
      });
      await reload();
      setNotice('Reviewer assignment was saved and added to audit history.');
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : 'Could not assign this reviewer.');
    } finally { savingRef.current = false; setSaving(false); }
  };

  if (loading) return <Shell title="Assessment review" liveData><p role="status">Loading persisted review details…</p></Shell>;
  return (
    <Shell title="Assessment review" liveData>
      <div className="live-page-actions no-print"><Link className="button secondary" to="/review-queue">Back to review queue</Link></div>
      {error && <div className="validation-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}</div>}
      {notice && <p className="validation-meta" role="status">{notice}</p>}
      {assessment && <>
        <section className="content-section">
          <Heading title={`${assessment.rule_code} · ${assessment.rule_title}`} text="Recorded automated assessment and its source evidence. Human decisions are appended separately and do not change application approval status." />
          <dl className="validation-rule-meta">
            <div><dt>Application</dt><dd>{assessment.application_reference} · database ID {assessment.application_id}</dd></div>
            <div><dt>Institution</dt><dd>{assessment.entity_name}</dd></div>
            <div><dt>Category</dt><dd>{assessment.category}</dd></div>
            <div><dt>Application status</dt><dd>{assessment.application_status}</dd></div>
            <div><dt>Automated assessment</dt><dd>{assessment.status} · {new Date(assessment.assessed_at).toLocaleString()}</dd></div>
            <div><dt>Assigned reviewer</dt><dd>{assessment.reviewer_name || 'Unassigned'}</dd></div>
          </dl>
          <h3>Recorded explanation</h3><p>{assessment.explanation}</p>
          <h3>Stored rule description</h3><p>{assessment.rule_description || 'No rule description is stored.'}</p>
          <p className="validation-disclaimer">Rule provenance and official applicability are not included in this assessment record. Treat synthetic or unverified rules as advisory.</p>
        </section>
        {user?.role === 'ADMIN' && <section className="content-section">
          <Heading title="Assign reviewer" text="Only active backend reviewer accounts can be assigned. The server enforces this permission." />
          {reviewers.length ? <form className="assessment-assignment-form" onSubmit={assignReviewer}>
            <label>Reviewer<select required value={reviewerId} onChange={event => setReviewerId(event.target.value)}><option value="">Choose a reviewer</option>{reviewers.map(reviewer => <option key={reviewer.id} value={reviewer.id}>{reviewer.full_name} · {reviewer.email}</option>)}</select></label>
            <button className="button primary" disabled={saving || !reviewerId}>{saving ? 'Saving…' : 'Save assignment'}</button>
          </form> : <div className="reviewer-empty-state"><p>No active reviewer accounts are available to assign. An administrator can create a separate reviewer account or activate an existing one in <Link to="/administration">Administration → User management</Link>.</p><p>Administrator accounts are not treated as reviewers. Account creation or activation requires a deliberate administrator action.</p></div>}
        </section>}
        {user?.role === 'REVIEWER' && assessment.assigned_reviewer_id === user.id && <section className="content-section assessment-decision-section">
          <Heading title="Record human decision" text="This decision is stored as an append-only reviewer record. It does not change the automated assessment or application status." />
          <AssessmentReviewForm outcome={outcome} note={note} saving={saving} onOutcomeChange={setOutcome} onNoteChange={setNote} onSubmit={saveReview} />
        </section>}
        {user?.role === 'REVIEWER' && assessment.assigned_reviewer_id !== user.id && <section className="content-section"><Heading title="Human decision" text="Decisions can be recorded only by the reviewer assigned to this assessment." /><p>This assessment is not assigned to your reviewer account. Ask an administrator to assign it before recording a decision.</p></section>}
        <section className="content-section">
          <Heading title="Linked document evidence" text="Extracted values remain unverified and are shown with source excerpts and page references when recorded." />
          {assessment.document_evidence.length ? assessment.document_evidence.map(document => (
            <article className="validation-check" key={document.document_id}>
              <strong>Document {document.document_id} · {document.filename} · {document.document_type}</strong>
              <p>Processing: {document.processing_status} · Extraction: {document.extraction_method}</p>
              {Object.entries(document.fields).map(([name, field]) => <p key={name}><b>{name.replaceAll('_', ' ')}:</b> {field.value ?? 'Not extracted'} · Unverified{field.evidence ? ` · Source: ${field.evidence}` : ''}{field.page ? ` · Page ${field.page}` : ''}</p>)}
            </article>
          )) : <p>No documents are linked to this application's current record.</p>}
        </section>
        <section className="content-section">
          <Heading title="Human review history" text="Decisions are append-only, attributed to the authenticated reviewer, and recorded in audit history." />
          {assessment.reviews.length ? assessment.reviews.map(review => <article className="validation-check" key={review.id}>
            <strong>{review.outcome.replaceAll('_', ' ')} · {review.reviewer_name}</strong><p>{review.note || 'No note added.'}</p><time dateTime={review.created_at}>{new Date(review.created_at).toLocaleString()}</time>
          </article>) : <p>No human decisions have been recorded for this assessment.</p>}
        </section>
      </>}
    </Shell>
  );
}

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

async function loadAllComplianceAssessments(token: string, applicationId?: number): Promise<ComplianceAssessment[]> {
  const results: ComplianceAssessment[] = [];
  const limit = 200;
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;
  while (offset < total) {
    const filter = applicationId === undefined ? '' : `&application_id=${applicationId}`;
    const page = await requestApi<ComplianceAssessmentPage>(
      `/api/compliance-assessments/?limit=${limit}&offset=${offset}${filter}`,
      token,
    );
    results.push(...page.items);
    total = page.total;
    if (!page.items.length) break;
    offset += page.items.length;
  }
  return results;
}

async function loadAllAuditEvents(token: string, applicationId: number): Promise<AuditEventItem[]> {
  const results: AuditEventItem[] = [];
  const limit = 200;
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;
  while (offset < total) {
    const page = await requestApi<AuditEventPage>(
      `/api/audit-events/?application_id=${applicationId}&limit=${limit}&offset=${offset}`,
      token,
    );
    results.push(...page.items);
    total = page.total;
    if (!page.items.length) break;
    offset += page.items.length;
  }
  return results;
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
    setProcessingResults({});
    setValidation(null);
    setError(null);
    if (!token || !selectedApplicationId) {
      setDocumentsLoading(false);
      return () => { cancelled = true; };
    }
    setDocumentsLoading(true);
    requestApi<PersistedDocument[]>(`/api/applications/${selectedApplicationId}/documents`, token)
      .then(async items => {
        const persistedResults = await Promise.all(items
          .filter(item => ['completed', 'ocr_unavailable', 'failed'].includes(item.processing_status))
          .map(async item => {
            try {
              const result = await requestApi<DocumentProcessingResult>(
                `/api/applications/${selectedApplicationId}/documents/${item.id}/processing-result`, token,
              );
              return [item.id, result] as const;
            } catch (reason) {
              if (reason instanceof ApiRequestError && reason.status === 404) return null;
              throw reason;
            }
          }));
        if (cancelled) return;
        setDocuments(items);
        setProcessingResults(Object.fromEntries(persistedResults.filter((entry): entry is readonly [number, DocumentProcessingResult] => entry !== null)));
      })
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
                        <p>Issuer verification not connected — manual verification required. The API status is {integrityResults[document.id].issuer_verification}; no genuineness or fraud determination is made.</p>
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
                        {processingResults[document.id].classification && (
                          <section className="validation-subsection">
                            <h5>Content-based type suggestion · {processingResults[document.id].classification?.status.replaceAll('_', ' ')}</h5>
                            <p>{processingResults[document.id].classification?.explanation}</p>
                            <p><b>Suggested type:</b> {processingResults[document.id].classification?.candidate_document_type ?? 'Unclassified; assign manually'}</p>
                            {processingResults[document.id].classification?.evidence.map((evidence, index) => (
                              <p key={`${evidence.page}-${evidence.signal}-${index}`}>
                                {evidence.document_type ? `${evidence.document_type} · ` : ''}Page {evidence.page} · matched “{evidence.signal}” · {evidence.excerpt}
                              </p>
                            ))}
                            <small>Classification is a configurable text-match suggestion. It does not verify document authenticity or change the submitted document type.</small>
                          </section>
                        )}
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
    requestApi<PersistedApplication[]>('/api/applications/', token)
      .then(async apps => {
      const [docs, assessmentLists] = await Promise.all([
        Promise.all(apps.map(app => requestApi<PersistedDocument[]>(`/api/applications/${app.id}/documents`, token))),
        Promise.all(apps.map(app => loadAllComplianceAssessments(token, app.id))),
      ]);
      if (cancelled) return;
      setApplications(apps);
      setDocumentCounts(Object.fromEntries(apps.map((app, index) => [app.id, docs[index].length])));
      setAssessmentCounts(Object.fromEntries(apps.map((app, index) => [app.id, assessmentLists[index].length])));
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
                <p>Persisted documents: {documentCounts[application.id] ?? 0} · Assessment records: {assessmentCounts[application.id] ?? 0}</p>
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
  const [runs, setRuns] = useState<ConsistencyRunRecord[]>([]);
  const [findings, setFindings] = useState<PersistedFinding[]>([]);
  const [checklist, setChecklist] = useState<ApplicationChecklist | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [processingResults, setProcessingResults] = useState<Record<number, DocumentProcessingResult>>({});
  const [generatedAt, setGeneratedAt] = useState('');
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
      loadAllComplianceAssessments(token, Number(id)),
      requestApi<ConsistencyRunHistory>(`/api/applications/${id}/consistency-runs`, token),
      requestApi<PersistedFinding[]>(`/api/applications/${id}/findings`, token),
      loadAllAuditEvents(token, Number(id)),
      requestApi<ApplicationChecklist>(`/api/applications/${id}/checklist`, token)
        .catch(reason => {
          if (reason instanceof ApiRequestError && reason.status === 422) return null;
          throw reason;
        }),
    ]).then(async ([app, docs, assessmentItems, history, persistedFindings, events, checklistResult]) => {
      const extracted = await Promise.all(docs
        .filter(document => ['completed', 'ocr_unavailable', 'failed'].includes(document.processing_status))
        .map(async document => {
          try {
            const result = await requestApi<DocumentProcessingResult>(
              `/api/applications/${id}/documents/${document.id}/processing-result`, token,
            );
            return [document.id, result] as const;
          } catch (reason) {
            if (reason instanceof ApiRequestError && reason.status === 404) return null;
            throw reason;
          }
        }));
      if (cancelled) return;
      setApplication(app);
      setDocuments(docs);
      setAssessments(assessmentItems);
      setRuns(history.items);
      setFindings(persistedFindings);
      setChecklist(checklistResult);
      setAuditEvents(events);
      setProcessingResults(Object.fromEntries(extracted.filter((item): item is readonly [number, DocumentProcessingResult] => item !== null)));
      setGeneratedAt(new Date().toLocaleString());
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
          <header className="report-header"><p className="eyebrow">VIGILANT AI · reviewer record summary</p><small>Generated {generatedAt}</small></header>
          <h2>{application.entity_name}</h2>
          <p>{application.reference} · Database ID {application.id} · {application.app_type} · Application status: {application.status || 'Unknown'}</p>
          <p>Created {new Date(application.created_at).toLocaleString()} · Updated {new Date(application.updated_at).toLocaleString()}</p>
          <h3>Persisted document records</h3>
          {documents.length ? documents.map(document => <section className="report-evidence" key={document.id}>
            <p><b>Document {document.id} · {document.original_filename}</b> · {document.doc_type} · Processing: {document.processing_status}</p>
            {processingResults[document.id] ? <>
              <small>Extraction: {processingResults[document.id].extraction_method} · {processingResults[document.id].pages_processed} page(s) · extracted values are unverified</small>
              {Object.entries(processingResults[document.id].fields).map(([fieldName, field]) => <p key={fieldName}><b>{fieldName.replaceAll('_', ' ')}:</b> {field.value ?? 'Not extracted'} · Unverified{field.evidence ? ` · ${field.evidence}` : ''}{field.page ? ` · Page ${field.page}` : ''}</p>)}
            </> : <small>No persisted extraction result is available for this document.</small>}
          </section>) : <p>No documents are currently attached.</p>}
          <h3>Current synthetic checklist preview</h3>
          {checklist ? <>
            <p>Category: {checklist.category} · Source: synthetic demonstration configuration. This is not an official regulatory checklist.</p>
            {checklist.items.map(item => <section className="report-evidence" key={item.document_type}>
              <p><b>{item.document_type.replaceAll('_', ' ')} · {item.status.replaceAll('_', ' ')}</b></p>
              <p>{item.explanation}</p>
              <small>Linked documents: {item.document_ids.length ? item.document_ids.join(', ') : 'None'}{item.missing_fields.length ? ` · Fields not extracted: ${item.missing_fields.join(', ')}` : ''}</small>
            </section>)}
          </> : <p>No synthetic checklist is configured for this application category; no checklist conclusion is included.</p>}
          <h3>Persisted automated assessments</h3>
          {assessments.length ? <div className="report-assessment-list">{assessments.map(item => <section className="report-assessment" key={item.id}>
            <div><b>{item.rule_code} · {item.rule_title}</b><Tag>{item.status}</Tag></div>
            <p>{item.explanation}</p>
            <small>Assessment record {item.id} · Snapshot recorded {new Date(item.assessed_at).toLocaleString()} · Reviewer: {item.reviewer_name || 'Unassigned'}</small>
          </section>)}</div> : <p>No persisted assessments are available for this application.</p>}
          <h3>Human assessment review history</h3>
          {assessments.some(item => item.reviews.length) ? assessments.flatMap(item => item.reviews.map(review => ({ assessment: item, review })))
            .sort((left, right) => Date.parse(left.review.created_at) - Date.parse(right.review.created_at) || left.review.id - right.review.id)
            .map(({ assessment, review }) => <section className="report-evidence" key={`assessment-review-${review.id}`}>
              <p><b>Assessment {assessment.id} · {assessment.rule_code} · {review.outcome.replaceAll('_', ' ')}</b></p>
              <p>{review.note || 'No note added.'}</p>
              <small>{review.reviewer_name} · {new Date(review.created_at).toLocaleString()}</small>
            </section>) : <p>No human assessment decisions are stored for this application. This does not change its automated results or application status.</p>}
          <h3>Cross-document validation history</h3>
          {runs.length ? runs.map(run => <section className="report-evidence" key={run.id}><p><b>Run {run.id}</b> · {run.status} · {run.comparisons_count} comparison(s) · {new Date(run.created_at).toLocaleString()}</p>
            {run.results.length ? run.results.map(result => <p key={result.id}><b>{result.category} · {result.field}:</b> {result.doc1_filename}: {result.val1 ?? 'No value'} ↔ {result.doc2_filename}: {result.val2 ?? 'No value'}. {result.explanation}</p>) : <small>No comparable fields were recorded.</small>}
          </section>) : <p>No consistency runs are stored for this application.</p>}
          <h3>Persisted findings and reviewer decisions</h3>
          {findings.length ? findings.map(finding => <section className="report-evidence" key={finding.id}><p><b>Finding {finding.id} · {finding.finding_type} · {finding.severity} · {finding.status}</b> · {finding.description}</p>
            {finding.reviews.map(review => <p key={review.id}>Human review: {review.outcome.replaceAll('_', ' ')} · {review.reviewer_name} · {new Date(review.created_at).toLocaleString()}{review.note ? ` · ${review.note}` : ''}</p>)}
          </section>) : <p>No findings are stored. Their absence does not imply compliance.</p>}
          <h3>Authorized audit event references</h3>
          {auditEvents.length ? <div className="report-audit-list">{auditEvents.map(event => <section className="report-audit-event" key={event.id}>
            <b>{readableAuditAction(event.action)}</b><span>{event.entity_type} {event.entity_id}</span>
            <small>Event {event.id} · {event.actor_name || 'Actor unavailable'} · {new Date(event.timestamp).toLocaleString()}</small>
          </section>)}</div> : <p>No authorized audit events are available for this application.</p>}
          <p className="validation-disclaimer">Automated assessments are not human decisions. This report does not establish document authenticity, application completeness, fraud, or institutional compliance. Synthetic and unapproved rules remain advisory; final decisions belong to authorized human reviewers.</p>
          <footer className="report-footer"><span>VIGILANT AI · SIH26261 prototype</span><span>Generated {generatedAt} · Application {application.reference}</span></footer>
          <button className="button primary no-print" onClick={() => window.print()}>Print record summary</button>
        </article>
      )}
    </Shell>
  );
}

function Report() { const { id = '' } = useParams(); const { apps } = useStore(); const app = apps.find(a => a.id === id); if (!app) return <Navigate to="/reports" replace />; return <Shell title="Validation report"><article className="print-report"><p className="eyebrow">Frontend demonstration report · simulated outcomes</p><h2>{app.institution}</h2><p>{app.id} · {app.category} · Submitted {app.submitted}</p><h3>Document checklist summary</h3><p>{app.documents.map(d => `${d.name}: ${d.status}`).join(' · ')}</p><h3>Unresolved issues and comparisons</h3><p>{app.findings.length ? app.findings.map(f => <p key={f.id}><b>{f.title}</b> — {f.explanation} Next step: {f.action}</p>).join('') : 'Matching simulated document values; no finding requires action.'}</p><h3>Overall scrutiny status</h3><p>{app.status}. This report does not declare an approval or rejection.</p><button className="button primary no-print" onClick={() => window.print()}>Print report</button></article></Shell> }

function ReportRouteView() { const { id = '' } = useParams(); return /^\d+$/.test(id) ? <PersistedReport /> : <Report /> }

function Admin() {
  const { token, user } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [totalUsers, setTotalUsers] = useState(0);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [activeFilter, setActiveFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [roleDrafts, setRoleDrafts] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newRole, setNewRole] = useState('REVIEWER');
  const pageSize = 50;

  useEffect(() => {
    if (!token) return;
    let current = true;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
    if (search.trim()) params.set('search', search.trim());
    if (roleFilter) params.set('role', roleFilter);
    if (activeFilter) params.set('is_active', activeFilter);
    void requestApi<UserPage>(`/api/auth/users?${params.toString()}`, token)
      .then(page => {
        if (!current) return;
        setUsers(page.items);
        setTotalUsers(page.total);
        setRoleDrafts(Object.fromEntries(page.items.map(item => [item.id, item.role])));
      })
      .catch(cause => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load users.');
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [token, search, roleFilter, activeFilter, offset, reloadKey]);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    if (!window.confirm(`Create ${newRole.replaceAll('_', ' ').toLowerCase()} account for ${email.trim()}?`)) return;
    setError(null);
    setNotice(null);
    setSavingId(-1);
    try {
      await requestApi<User>('/api/auth/users', token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_name: name.trim(), email: email.trim(), password, role: newRole }),
      });
      setName(''); setEmail(''); setPassword(''); setNewRole('REVIEWER'); setOffset(0);
      setNotice('Account created. The password is not shown again.');
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create this account.');
    } finally { setSavingId(null); }
  }

  async function updateUser(account: User, changes: Partial<Pick<User, 'role' | 'is_active'>>) {
    if (!token || savingId !== null) return;
    const action = changes.is_active === false ? 'deactivate' : changes.is_active === true ? 'activate' : 'change this account role';
    if (!window.confirm(`Are you sure you want to ${action} for ${account.full_name}?`)) return;
    setError(null); setNotice(null); setSavingId(account.id);
    try {
      await requestApi<User>(`/api/auth/users/${account.id}`, token, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      });
      setNotice(`Updated ${account.full_name}.`);
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not update ${account.full_name}.`);
    } finally { setSavingId(null); }
  }

  return <Shell title="Administration" liveData>
    <section className="content-section">
      <Heading title="Signed-in account" text="Access is enforced by the backend for each request. Role changes here never replace server-side permission checks." />
      <dl className="validation-rule-meta">
        <div><dt>Account</dt><dd>{user?.full_name} · {user?.email}</dd></div>
        <div><dt>Server role</dt><dd>{user?.role}</dd></div>
        <div><dt>Access scope</dt><dd>Platform-wide administrator</dd></div>
      </dl>
      <div className="live-page-actions">
        <Link className="button secondary" to="/review-queue">Open assessment review queue</Link>
        <Link className="button secondary" to="/audit-trail">Open authorized audit history</Link>
      </div>
    </section>

    <section className="content-section">
      <Heading title="User management" text="Create accounts and manage roles or active status. Account changes are recorded in the audit history." />
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="admin-success" role="status">{notice}</p>}
      <form className="admin-create-form" onSubmit={createUser}>
        <label>Full name<input required maxLength={255} value={name} onChange={event => setName(event.target.value)} autoComplete="name" /></label>
        <label>Email<input required type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" /></label>
        <label>Initial password<input required minLength={12} maxLength={1024} type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password" /><small>At least 12 non-whitespace characters.</small></label>
        <label>Role<select value={newRole} onChange={event => setNewRole(event.target.value)}><option value="REVIEWER">Reviewer</option><option value="INSTITUTION_USER">Institution user</option><option value="ADMIN">Administrator</option></select></label>
        <button className="button primary" type="submit" disabled={savingId !== null}>{savingId === -1 ? 'Creating…' : 'Create account'}</button>
      </form>
      <p className="admin-note">The password is sent once to the authenticated API and cleared after creation. This interface does not provide password reset or recovery.</p>

      <div className="admin-filters" aria-label="Filter users">
        <label>Search<input type="search" value={search} onChange={event => { setSearch(event.target.value); setOffset(0); }} placeholder="Name or email" /></label>
        <label>Role<select value={roleFilter} onChange={event => { setRoleFilter(event.target.value); setOffset(0); }}><option value="">All roles</option><option value="ADMIN">Administrator</option><option value="REVIEWER">Reviewer</option><option value="INSTITUTION_USER">Institution user</option></select></label>
        <label>Status<select value={activeFilter} onChange={event => { setActiveFilter(event.target.value); setOffset(0); }}><option value="">All statuses</option><option value="true">Active</option><option value="false">Inactive</option></select></label>
      </div>
      <p className="admin-result-count">{totalUsers} account{totalUsers === 1 ? '' : 's'}{search.trim() || roleFilter || activeFilter ? ' match these filters.' : ' in the directory.'}</p>
      {loading ? <p role="status">Loading accounts…</p> : users.length ? <div className="table-wrap">
        <table className="admin-user-table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>
          {users.map(account => <tr key={account.id}>
            <td>{account.full_name}{account.id === user?.id ? ' (you)' : ''}</td><td>{account.email}</td>
            <td><div className="admin-role-control"><select aria-label={`Role for ${account.full_name}`} disabled={account.id === user?.id} title={account.id === user?.id ? 'You cannot remove your own administrator role.' : undefined} value={roleDrafts[account.id] ?? account.role} onChange={event => setRoleDrafts(drafts => ({ ...drafts, [account.id]: event.target.value }))}><option value="ADMIN">Administrator</option><option value="REVIEWER">Reviewer</option><option value="INSTITUTION_USER">Institution user</option></select><button className="button secondary" type="button" disabled={savingId !== null || account.id === user?.id || (roleDrafts[account.id] ?? account.role) === account.role} onClick={() => void updateUser(account, { role: roleDrafts[account.id] })}>Save role</button></div></td>
            <td><span className={`admin-user-status ${account.is_active ? 'active' : 'inactive'}`}>{account.is_active ? 'Active' : 'Inactive'}</span></td>
            <td><button className="button secondary" type="button" disabled={savingId !== null || account.id === user?.id} title={account.id === user?.id ? 'You cannot deactivate your own account.' : undefined} onClick={() => void updateUser(account, { is_active: !account.is_active })}>{account.is_active ? 'Deactivate' : 'Activate'}</button></td>
          </tr>)}
        </tbody></table>
      </div> : <p className="admin-empty">{search.trim() || roleFilter || activeFilter ? 'No accounts match these filters.' : 'No accounts are available.'}</p>}
      <div className="admin-pagination"><button className="button secondary" type="button" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><span>Showing {totalUsers ? offset + 1 : 0}–{Math.min(offset + users.length, totalUsers)} of {totalUsers}</span><button className="button secondary" type="button" disabled={loading || offset + users.length >= totalUsers} onClick={() => setOffset(offset + pageSize)}>Next</button></div>
    </section>

    <section className="content-section">
      <Heading title="Reviewer access and system limits" text="Only active REVIEWER accounts can be assigned. Administrator access does not substitute for reviewer assignment." />
      <p>Create or activate a reviewer above, then assign them to a specific assessment from its review page. When no active reviewer exists, create a separate account with the Reviewer role; administrator accounts are never treated as reviewers.</p>
      <div className="live-page-actions"><Link className="button secondary" to="/review-queue">Manage assessment assignments</Link><Link className="button secondary" to="/audit-trail">Review audit history</Link></div>
      <p className="validation-disclaimer">The health endpoint reports API process availability only. Database readiness and registry currentness are not exposed here. This prototype has no rule-configuration interface or password-recovery workflow.</p>
    </section>
  </Shell>;
}

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
      <Route path="/compliance-assessments/:id" element={user ? <AssessmentReviewPage /> : <Navigate to="/login" replace />} />
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
