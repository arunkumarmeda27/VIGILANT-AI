/**
 * A deterministic, provider-neutral validation core. It deliberately models
 * unavailable external services as non-successful outcomes: callers must not
 * infer authenticity or compliance from a missing integration.
 */
export type StageStatus = 'SUCCEEDED' | 'PARTIAL' | 'FAILED' | 'UNSUPPORTED' | 'INCONCLUSIVE' | 'SKIPPED';
export type VerificationStatus = 'VERIFIED' | 'FAILED' | 'INCONCLUSIVE' | 'UNAVAILABLE' | 'NOT_APPLICABLE' | 'PENDING_REVIEW';
export type Severity = 'HIGH' | 'MEDIUM' | 'LOW';

export type SchemaField = { key: string; required: boolean; kind: 'string' | 'date' | 'number'; normalize?: 'trim' | 'upper' };
export type DocumentSchema = {
  id: string;
  version: string;
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
  acceptedMimeTypes: readonly string[];
  fields: readonly SchemaField[];
};
export type Evidence = { id: string; source: string; documentId?: string; page?: number; value?: string };
export type Finding = { id: string; type: 'MISSING_FIELD' | 'CONFLICT' | 'ANOMALY' | 'RULE'; severity: Severity; message: string; evidence: Evidence[]; requiresReview: boolean };
export type ValidationDocument = { id: string; schemaId?: string; mimeType: string; values: Record<string, string | undefined>; checksum?: string };
export type ValidationRun = { id: string; applicationId: string; startedAt: string; stages: Array<{ name: string; status: StageStatus; detail: string }>; findings: Finding[]; verification: VerificationStatus; outcome: 'READY_FOR_REVIEW' | 'INCONCLUSIVE' | 'FAILED' };

const schemas: DocumentSchema[] = [
  { id: 'application-form', version: '1.0.0', status: 'ACTIVE', acceptedMimeTypes: ['application/pdf', 'image/png', 'image/jpeg'], fields: [
    { key: 'institutionName', required: true, kind: 'string', normalize: 'trim' },
    { key: 'registrationNumber', required: true, kind: 'string', normalize: 'upper' },
  ] },
  { id: 'governance-certificate', version: '1.0.0', status: 'ACTIVE', acceptedMimeTypes: ['application/pdf', 'image/png', 'image/jpeg'], fields: [
    { key: 'institutionName', required: true, kind: 'string', normalize: 'trim' },
    { key: 'registrationNumber', required: true, kind: 'string', normalize: 'upper' },
    { key: 'issueDate', required: false, kind: 'date' },
  ] },
];

export function getActiveSchema(schemaId: string): DocumentSchema | undefined {
  return schemas.find((schema) => schema.id === schemaId && schema.status === 'ACTIVE');
}

export function normalize(schema: DocumentSchema, values: ValidationDocument['values']): ValidationDocument['values'] {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => {
    const field = schema.fields.find((item) => item.key === key);
    if (!value || !field?.normalize) return [key, value];
    return [key, field.normalize === 'upper' ? value.trim().toUpperCase() : value.trim()];
  }));
}

function id(prefix: string, ordinal: number) { return `${prefix}-${ordinal.toString().padStart(3, '0')}`; }

/** Runs only local, deterministic checks. OCR, cryptographic checks and issuer APIs
 * are explicitly unavailable until an authorized adapter is configured. */
export function validateApplication(applicationId: string, documents: ValidationDocument[], now = new Date().toISOString()): ValidationRun {
  const findings: Finding[] = [];
  const stages: ValidationRun['stages'] = [];
  const indexed = new Map<string, string[]>();
  let ordinal = 1;

  for (const document of documents) {
    const schema = document.schemaId ? getActiveSchema(document.schemaId) : undefined;
    if (!schema) {
      stages.push({ name: `schema:${document.id}`, status: 'UNSUPPORTED', detail: 'No active schema is registered for this document.' });
      continue;
    }
    if (!schema.acceptedMimeTypes.includes(document.mimeType)) {
      stages.push({ name: `schema:${document.id}`, status: 'UNSUPPORTED', detail: `Unsupported media type: ${document.mimeType}.` });
      continue;
    }
    const values = normalize(schema, document.values);
    for (const field of schema.fields.filter((item) => item.required && !values[item.key])) {
      findings.push({ id: id('F', ordinal++), type: 'MISSING_FIELD', severity: 'HIGH', message: `${field.key} is required by ${schema.id} ${schema.version}.`, evidence: [{ id: id('E', ordinal), source: 'schema', documentId: document.id }], requiresReview: true });
    }
    const registration = values.registrationNumber;
    if (registration) indexed.set('registrationNumber', [...(indexed.get('registrationNumber') ?? []), `${document.id}:${registration}`]);
    stages.push({ name: `schema:${document.id}`, status: findings.some((finding) => finding.evidence.some((evidence) => evidence.documentId === document.id)) ? 'PARTIAL' : 'SUCCEEDED', detail: `Schema ${schema.id}@${schema.version} evaluated.` });
  }

  for (const [field, entries] of indexed) {
    const distinct = new Set(entries.map((entry) => entry.slice(entry.indexOf(':') + 1)));
    if (distinct.size > 1) findings.push({ id: id('F', ordinal++), type: 'CONFLICT', severity: 'HIGH', message: `${field} conflicts across submitted documents.`, evidence: entries.map((entry, index) => ({ id: id('E', ordinal + index), source: 'cross-document comparison', documentId: entry.slice(0, entry.indexOf(':')), value: entry.slice(entry.indexOf(':') + 1) })), requiresReview: true });
  }

  const duplicates = documents.filter((document, index) => document.checksum && documents.slice(0, index).some((previous) => previous.checksum === document.checksum));
  for (const duplicate of duplicates) findings.push({ id: id('F', ordinal++), type: 'ANOMALY', severity: 'MEDIUM', message: 'Duplicate content indicator detected; this is not proof of tampering.', evidence: [{ id: id('E', ordinal), source: 'checksum', documentId: duplicate.id }], requiresReview: true });

  stages.push({ name: 'issuer-verification', status: 'INCONCLUSIVE', detail: 'No authorized issuer-verification provider is configured.' });
  stages.push({ name: 'regulatory-evaluation', status: 'SKIPPED', detail: 'No versioned regulatory rule set is configured.' });
  const outcome: ValidationRun['outcome'] = findings.length ? 'READY_FOR_REVIEW' : 'INCONCLUSIVE';
  return { id: `RUN-${applicationId}-${now}`, applicationId, startedAt: now, stages, findings, verification: 'UNAVAILABLE', outcome };
}

export function canAccessApplication(actor: { institutionId: string; roles: string[] }, applicationInstitutionId: string): boolean {
  return actor.roles.includes('ADMIN') || actor.institutionId === applicationInstitutionId;
}
