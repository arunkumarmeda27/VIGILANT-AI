import { describe, expect, it } from 'vitest';
import { canAccessApplication, getActiveSchema, validateApplication } from './validation';

describe('validation orchestration', () => {
  it('keeps unavailable issuer checks inconclusive and surfaces cross-document conflicts', () => {
    const run = validateApplication('APP-1', [
      { id: 'one', schemaId: 'application-form', mimeType: 'application/pdf', values: { institutionName: ' Institute ', registrationNumber: ' reg-1 ' } },
      { id: 'two', schemaId: 'governance-certificate', mimeType: 'application/pdf', values: { institutionName: 'Institute', registrationNumber: 'reg-2' } },
    ], '2026-10-29T00:00:00.000Z');
    expect(run.verification).toBe('UNAVAILABLE');
    expect(run.outcome).toBe('READY_FOR_REVIEW');
    expect(run.findings.some((finding) => finding.type === 'CONFLICT')).toBe(true);
    expect(run.stages.find((stage) => stage.name === 'issuer-verification')?.status).toBe('INCONCLUSIVE');
  });

  it('marks unknown schemas and invalid media as unsupported rather than successful', () => {
    const run = validateApplication('APP-2', [
      { id: 'unknown', schemaId: 'unknown', mimeType: 'application/pdf', values: {} },
      { id: 'wrong-type', schemaId: 'application-form', mimeType: 'text/plain', values: {} },
    ]);
    expect(run.stages.filter((stage) => stage.status === 'UNSUPPORTED')).toHaveLength(2);
  });

  it('enforces institution isolation except for administrators', () => {
    expect(canAccessApplication({ institutionId: 'a', roles: ['REVIEWER'] }, 'b')).toBe(false);
    expect(canAccessApplication({ institutionId: 'a', roles: ['ADMIN'] }, 'b')).toBe(true);
    expect(getActiveSchema('application-form')?.version).toBe('1.0.0');
  });
});
