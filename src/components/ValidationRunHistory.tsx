export type ValidationEvidenceReference = {
  document_id: number;
  filename: string;
  field: string;
  verification_status: string;
  evidence_status: string;
  page?: number | string;
  excerpt?: string;
  processing_provenance?: {
    document_sha256?: string | null;
    document_type?: string;
    processing_status?: string;
    processed_at?: string | null;
    schema_version_id?: number | null;
    extraction_method?: string | null;
    field_extraction_version?: string | null;
    ocr?: Record<string, unknown> | null;
  };
};

type ValidationRunResult = {
  type: string;
  rule_id?: string;
  document_type?: string;
  status?: string;
  reason_code?: string;
  explanation?: string;
  candidate_requirement?: string | null;
  source_reference?: Record<string, string | number> | null;
  rule_reference?: {
    rule_id: string;
    definition_sha256: string | null;
    preview_status: string;
  };
  evidence_refs?: ValidationEvidenceReference[];
  source?: string;
  items?: {
    document_type: string;
    status: string;
    document_ids: number[];
    missing_fields: string[];
    explanation: string;
    evidence_refs: ValidationEvidenceReference[];
  }[];
  field?: string;
  category?: string;
  document_ids?: number[];
  values?: (string | null)[];
  human_review_recommended?: boolean;
  document_id?: number;
  filename?: string;
  file_hash_check?: {
    status: string;
    stored_sha256?: string | null;
    current_sha256?: string | null;
    explanation: string;
  };
  duplicate_file_check?: {
    status: string;
    explanation: string;
    matches: { document_id: number; original_filename: string }[];
  };
  pdf_structure_check?: { status: string; explanation: string };
  metadata_check?: { status: string; explanation: string };
  issuer_verification?: string;
  authenticity_status?: string;
  limitations?: string[];
  finding_id?: number;
  finding_type?: string;
  severity?: string;
  description?: string;
  finding_ids?: number[];
  processing_status?: string;
  schema_version_id?: number | null;
  schema_version?: string | null;
  registry_status?: string | null;
  reason?: string;
  fields?: {
    field_id: string;
    label: string;
    status: string;
    required: boolean;
    value?: unknown;
    normalized_value?: unknown;
    source?: {
      value?: string | null;
      page?: number | null;
      evidence?: string | null;
      status?: string;
    } | null;
  }[];
  human_review_required?: boolean;
  disclaimer?: string;
  unlisted_extracted_fields?: string[];
};

export type ValidationRunRecord = {
  id: number;
  application_id: number;
  user_id: number;
  started_at: string;
  completed_at: string | null;
  execution_status: string;
  outcome: string;
  stage_outcomes: {
    name: string;
    status: string;
    reason: string;
    result_count: number;
    documents?: {
      document_id: number;
      document_type: string;
      processing_status: string;
      status: string;
      reason: string;
      schema_validation_status?: string;
      schema_version_id?: number | null;
    }[];
  }[];
  results: ValidationRunResult[];
  error_summary: string | null;
  evaluated_rules_count: number;
  not_evaluated_rules_count: number;
  not_applicable_rules_count: number;
};

type ValidationRunHistoryProps = {
  runs: ValidationRunRecord[];
};

function EvidenceReferences({ references }: { references: ValidationEvidenceReference[] }) {
  if (!references.length) {
    return <p className="validation-meta">
      No uploaded-document evidence references were persisted; uploaded-document excerpts and page references are unavailable.
    </p>;
  }
  return <ul>
    {references.map((reference, index) => (
      <li key={`${reference.document_id}-${reference.field}-${index}`}>
        Document {reference.document_id} ({reference.filename}) · {reference.field}
        {reference.page !== undefined ? ` · Uploaded-document page ${reference.page}` : ' · Uploaded-document page reference unavailable'}
        {reference.excerpt ? ` · Uploaded-document excerpt: "${reference.excerpt}"` : ' · Uploaded-document excerpt unavailable'}
        {reference.evidence_status === 'unavailable' ? ' · Uploaded-document evidence unavailable' : ''}
        {' · Unverified extraction'}
        {reference.processing_provenance?.document_sha256
          ? ` · Source document SHA-256 ${reference.processing_provenance.document_sha256}`
          : ' · Source document hash unavailable'}
        {reference.processing_provenance?.schema_version_id
          ? ` · Schema version ${reference.processing_provenance.schema_version_id}`
          : ''}
        {reference.processing_provenance?.extraction_method
          ? ` · Extraction ${reference.processing_provenance.extraction_method}`
          : ''}
        {reference.processing_provenance?.field_extraction_version
          ? ` · Extractor ${reference.processing_provenance.field_extraction_version}`
          : ''}
        {reference.processing_provenance?.ocr?.engine
          ? ` · OCR ${String(reference.processing_provenance.ocr.engine)} ${String(reference.processing_provenance.ocr.engine_version ?? '')}`
          : ''}
      </li>
    ))}
  </ul>;
}

function RegistrySourceMetadata({ source }: { source?: Record<string, string | number> | null }) {
  if (!source || !Object.keys(source).length) {
    return <small>Regulatory registry source metadata unavailable.</small>;
  }
  const metadata = [
    source.handbook_version !== undefined ? `Handbook version ${source.handbook_version}` : null,
    source.section !== undefined ? `Registry section ${source.section}` : null,
    source.printed_page !== undefined ? `Registry printed page ${source.printed_page}` : null,
    source.pdf_page !== undefined ? `Registry PDF page ${source.pdf_page}` : null,
    source.source_path !== undefined ? `Registry source file ${source.source_path}` : null,
  ].filter(Boolean);
  return <small>
    Regulatory registry source metadata: {metadata.length ? metadata.join(' · ') : 'details unavailable'}
  </small>;
}

function ResultDetails({ result }: { result: ValidationRunResult }) {
  if (result.type === 'document_integrity') {
    return <article className="validation-check">
      <strong>Document integrity indicators · {result.filename} · document {result.document_id}</strong>
      <p>Stored-file hash integrity · {result.file_hash_check?.status}: {result.file_hash_check?.explanation}</p>
      <p>Duplicate check · {result.duplicate_file_check?.status}: {result.duplicate_file_check?.explanation}</p>
      {result.duplicate_file_check?.matches.map(match => (
        <p key={match.document_id}>Matching document {match.document_id} ({match.original_filename})</p>
      ))}
      <p>PDF structure · {result.pdf_structure_check?.status}: {result.pdf_structure_check?.explanation}</p>
      <p>PDF metadata · {result.metadata_check?.status}: {result.metadata_check?.explanation}</p>
      <p>Issuer verification · {result.issuer_verification} · Authenticity · {result.authenticity_status}</p>
      {(result.finding_ids ?? []).length > 0 && <p>Linked persisted finding IDs: {result.finding_ids?.join(', ')}</p>}
      {(result.limitations ?? []).map(limitation => <small key={limitation}>{limitation}<br /></small>)}
    </article>;
  }

  if (result.type === 'document_schema_validation') {
    return <article className="validation-check">
      <strong>Document schema validation · Document {result.document_id} · {result.status}</strong>
      <p>Selected document type: {result.document_type || 'Unavailable'} · Registry status: {result.registry_status || 'Unavailable'} · Schema version: {result.schema_version || 'Unavailable'} (ID {result.schema_version_id ?? 'Unavailable'})</p>
      <p>{result.reason || 'Schema evaluation details are unavailable.'}</p>
      {(result.fields ?? []).map(field => <p key={field.field_id}>
        <b>Schema field {field.label} · {field.status}:</b> {field.value === null || field.value === undefined ? 'Missing' : String(field.value)}
        {field.source?.page ? ` · Uploaded-document page ${field.source.page}` : ' · Uploaded-document page unavailable'}
        {field.source?.evidence ? ` · Uploaded-document evidence: ${field.source.evidence}` : ' · Uploaded-document evidence unavailable'}
      </p>)}
      {(result.unlisted_extracted_fields ?? []).length > 0 && <p>Extracted fields not listed in this schema: {result.unlisted_extracted_fields?.join(', ')}</p>}
      <small>{result.disclaimer || 'Schema validation does not establish authenticity or regulatory compliance.'} Human review required: {result.human_review_required ? 'yes' : 'no'}.</small>
    </article>;
  }

  if (result.type === 'finding') {
    return <article className="validation-check">
      <strong>Persisted finding {result.finding_id} · {result.finding_type} · {result.severity} · {result.status}</strong>
      <p>{result.description}</p>
      {result.document_id !== null && result.document_id !== undefined && <p>Document {result.document_id}</p>}
      <EvidenceReferences references={result.evidence_refs ?? []} />
    </article>;
  }

  if (result.type === 'regulatory_rule') {
    const source = result.source_reference;
    return <article className="validation-check">
      <strong>{result.rule_id} · {result.status}</strong>
      {result.candidate_requirement && <p>{result.candidate_requirement}</p>}
      <p>{result.explanation}</p>
      {result.rule_reference && <p className="validation-meta">
        Rule definition SHA-256: {result.rule_reference.definition_sha256 ?? 'unavailable'} ·
        {' '}{result.rule_reference.preview_status.replaceAll('_', ' ')}
      </p>}
      <RegistrySourceMetadata source={source} />
      <EvidenceReferences references={result.evidence_refs ?? []} />
    </article>;
  }

  if (result.type === 'application_checklist') {
    return <article className="validation-check">
      <strong>Synthetic application checklist</strong>
      {(result.items ?? []).map(item => <div key={item.document_type}>
        <p><b>{item.document_type.replaceAll('_', ' ')} · {item.status.replaceAll('_', ' ')}</b></p>
        <p>{item.explanation}</p>
        <small>Documents: {item.document_ids.length ? item.document_ids.join(', ') : 'None'}
          {item.missing_fields.length ? ` · Missing extracted fields: ${item.missing_fields.join(', ')}` : ''}
        </small>
        <EvidenceReferences references={item.evidence_refs} />
      </div>)}
      <small>This configured checklist is synthetic demo content, not official regulatory policy.</small>
    </article>;
  }

  if (result.type === 'consistency') {
    const category = result.category === 'CONFIRMED_MISMATCH'
      ? 'POSSIBLE_MISMATCH (legacy stored status: CONFIRMED_MISMATCH)'
      : result.category;
    return <article className="validation-check">
      <strong>{result.field?.replaceAll('_', ' ')} · {category}</strong>
      <p>Documents: {(result.document_ids ?? []).join(', ') || 'Not linked'}</p>
      <p>Extracted values: {(result.values ?? []).map(value => value ?? 'No extracted value').join(' / ')}</p>
      <p>{result.explanation}</p>
      <p>Extracted differences are indicators only; a human reviewer must verify the source documents. They do not establish which value is correct or whether either underlying fact is false.</p>
      {result.human_review_recommended && <p><b>Human review recommended.</b></p>}
      <EvidenceReferences references={result.evidence_refs ?? []} />
    </article>;
  }

  return <article className="validation-check"><strong>{result.type}</strong><p>{result.explanation}</p></article>;
}

export function ValidationRunHistory({ runs }: ValidationRunHistoryProps) {
  if (!runs.length) return <p className="validation-meta">No central validation runs have been recorded for this application.</p>;
  return <div className="validation-check-list">
    {runs.map(run => <article className="validation-rule" key={run.id}>
      <div className="validation-rule-title">
        <h3>Validation run {run.id}</h3>
        <span className="validation-status">{run.execution_status} · {run.outcome}</span>
      </div>
      <p className="validation-meta">
        Started {new Date(run.started_at).toLocaleString()}
        {run.completed_at ? ` · Completed ${new Date(run.completed_at).toLocaleString()}` : ' · Completion time unavailable'}
      </p>
      <p>Rules: {run.evaluated_rules_count} evaluated · {run.not_evaluated_rules_count} not evaluated · {run.not_applicable_rules_count} not applicable</p>
      {run.error_summary && <p className="validation-error" role="alert">{run.error_summary}</p>}
      <h4>Stages</h4>
      {run.stage_outcomes.map((stage, index) => <p key={`${stage.name}-${index}`}>
        <b>{stage.name.replaceAll('_', ' ')} · {stage.status}</b> - {stage.reason} ({stage.result_count} results)
        {stage.documents?.map(document => <span className="validation-meta" key={document.document_id}>
          <br />Document {document.document_id} · {document.document_type.replaceAll('_', ' ')} · {document.processing_status} · {document.status}: {document.reason}
          {document.schema_validation_status ? ` · Schema ${document.schema_validation_status} (version ID ${document.schema_version_id ?? 'unavailable'})` : ''}
        </span>)}
      </p>)}
      <h4>Persisted results</h4>
      {run.results.length ? run.results.map((result, index) => <ResultDetails key={`${result.type}-${result.rule_id ?? result.field ?? index}-${index}`} result={result} />)
        : <p className="validation-meta">No results were produced.</p>}
    </article>)}
  </div>;
}
