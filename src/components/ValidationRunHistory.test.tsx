import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ValidationRunHistory, type ValidationRunRecord } from './ValidationRunHistory';

afterEach(cleanup);

describe('ValidationRunHistory', () => {
  it('renders persisted inconclusive run stages, unapproved rule state, and evidence provenance', () => {
    const run: ValidationRunRecord = {
      id: 41,
      application_id: 7,
      user_id: 3,
      started_at: '2026-03-22T10:00:00Z',
      completed_at: '2026-03-22T10:00:01Z',
      execution_status: 'completed',
      outcome: 'inconclusive',
      stage_outcomes: [
        { name: 'regulatory_validation', status: 'completed', reason: 'Registry loaded.', result_count: 1 },
        { name: 'cross_document_consistency', status: 'skipped', reason: 'At least two processed documents are required.', result_count: 0 },
        {
          name: 'document_processing',
          status: 'partial',
          reason: 'One document is pending.',
          result_count: 1,
          documents: [{
            document_id: 9,
            document_type: 'fire_safety_certificate',
            processing_status: 'pending',
            status: 'pending',
            reason: 'Document processing has not completed.',
          }],
        },
      ],
      results: [{
        type: 'regulatory_rule',
        rule_id: 'DOCUMENT-0004',
        status: 'Not evaluated',
        explanation: 'Candidate rule is not approved.',
        candidate_requirement: 'Candidate text from registry.',
        source_reference: { section: '1.1(v)', printed_page: 77 },
        rule_reference: {
          rule_id: 'DOCUMENT-0004',
          definition_sha256: 'a'.repeat(64),
          preview_status: 'not_approved_for_preview',
        },
        evidence_refs: [{
          document_id: 9,
          filename: 'certificate.pdf',
          field: 'certificate_number',
          verification_status: 'unverified',
          evidence_status: 'available',
          page: 2,
          excerpt: 'Certificate No: C-12',
          processing_provenance: {
            document_sha256: 'b'.repeat(64),
            schema_version_id: 5,
            extraction_method: 'ocr',
            field_extraction_version: 'schema-extraction-v2',
            ocr: { engine: 'tesseract', engine_version: '5.4' },
          },
        }],
      }],
      error_summary: null,
      evaluated_rules_count: 0,
      not_evaluated_rules_count: 1,
      not_applicable_rules_count: 0,
    };

    render(<ValidationRunHistory runs={[run]} />);

    expect(screen.getByText('Validation run 41')).toBeTruthy();
    expect(screen.getByText('completed · inconclusive')).toBeTruthy();
    expect(screen.getByText(/cross document consistency · skipped/)).toBeTruthy();
    expect(screen.getByText('DOCUMENT-0004 · Not evaluated')).toBeTruthy();
    expect(screen.getByText(/Document 9 · fire safety certificate · pending · pending/)).toBeTruthy();
    expect(screen.getByText(/Registry printed page 77/)).toBeTruthy();
    expect(screen.getByText(/certificate\.pdf/)).toBeTruthy();
    expect(screen.getByText(/Uploaded-document page 2/)).toBeTruthy();
    expect(screen.getByText(/Uploaded-document excerpt: "Certificate No: C-12"/)).toBeTruthy();
    expect(screen.getByText(/Rule definition SHA-256: a{64} · not approved for preview/)).toBeTruthy();
    expect(screen.getByText(/Source document SHA-256 b{64} · Schema version 5 · Extraction ocr · Extractor schema-extraction-v2 · OCR tesseract 5\.4/)).toBeTruthy();
  });

  it('distinguishes registry page metadata from missing uploaded-document evidence', () => {
    const run: ValidationRunRecord = {
      id: 43,
      application_id: 7,
      user_id: 3,
      started_at: '2026-03-22T10:00:00Z',
      completed_at: '2026-03-22T10:00:01Z',
      execution_status: 'completed',
      outcome: 'inconclusive',
      stage_outcomes: [],
      results: [{
        type: 'regulatory_rule',
        rule_id: 'DOCUMENT-0004',
        status: 'Not evaluated',
        explanation: 'Candidate rule is not approved.',
        source_reference: { section: '1.1(v)', printed_page: 77, pdf_page: 93 },
        evidence_refs: [],
      }],
      error_summary: null,
      evaluated_rules_count: 0,
      not_evaluated_rules_count: 1,
      not_applicable_rules_count: 0,
    };

    const { container } = render(<ValidationRunHistory runs={[run]} />);

    expect(screen.getByText(/Registry section 1\.1\(v\)/)).toBeTruthy();
    expect(screen.getByText(/Registry printed page 77/)).toBeTruthy();
    expect(screen.getByText(/Registry PDF page 93/)).toBeTruthy();
    expect(screen.getByText(/No uploaded-document evidence references were persisted/)).toBeTruthy();
    expect(container.textContent).not.toContain('Uploaded-document page 77');
    expect(container.textContent).not.toContain('No source excerpt or page reference was persisted.');
  });

  it('reports registry metadata and uploaded-document evidence as unavailable when provenance is missing', () => {
    const run: ValidationRunRecord = {
      id: 44,
      application_id: 7,
      user_id: 3,
      started_at: '2026-03-22T10:00:00Z',
      completed_at: '2026-03-22T10:00:01Z',
      execution_status: 'completed',
      outcome: 'inconclusive',
      stage_outcomes: [],
      results: [{
        type: 'regulatory_rule',
        rule_id: 'DOCUMENT-0012',
        status: 'Not evaluated',
        explanation: 'Source information was not available.',
        source_reference: null,
        evidence_refs: [],
      }],
      error_summary: null,
      evaluated_rules_count: 0,
      not_evaluated_rules_count: 1,
      not_applicable_rules_count: 0,
    };

    render(<ValidationRunHistory runs={[run]} />);

    expect(screen.getByText('Regulatory registry source metadata unavailable.')).toBeTruthy();
    expect(screen.getByText(/No uploaded-document evidence references were persisted/)).toBeTruthy();
  });

  it('renders partial outcomes and explicit unavailable or failed stages', () => {
    const run: ValidationRunRecord = {
      id: 42,
      application_id: 7,
      user_id: 3,
      started_at: '2026-03-22T10:00:00Z',
      completed_at: null,
      execution_status: 'partial',
      outcome: 'partial',
      stage_outcomes: [
        { name: 'regulatory_validation', status: 'unavailable', reason: 'Registry is unavailable.', result_count: 0 },
        { name: 'application_checklist', status: 'failed', reason: 'Checklist execution failed.', result_count: 0 },
      ],
      results: [],
      error_summary: 'Registry unavailable; checklist failed.',
      evaluated_rules_count: 0,
      not_evaluated_rules_count: 0,
      not_applicable_rules_count: 0,
    };

    render(<ValidationRunHistory runs={[run]} />);

    expect(screen.getByText('partial · partial')).toBeTruthy();
    expect(screen.getByText('Registry unavailable; checklist failed.')).toBeTruthy();
    expect(screen.getByText(/regulatory validation · unavailable/)).toBeTruthy();
    expect(screen.getByText(/application checklist · failed/)).toBeTruthy();
    expect(screen.getByText('No results were produced.')).toBeTruthy();
  });

  it('qualifies legacy confirmed mismatch results as unverified extraction discrepancies', () => {
    const run: ValidationRunRecord = {
      id: 45,
      application_id: 7,
      user_id: 3,
      started_at: '2026-03-22T10:00:00Z',
      completed_at: '2026-03-22T10:00:01Z',
      execution_status: 'completed',
      outcome: 'inconclusive',
      stage_outcomes: [],
      results: [{
        type: 'consistency',
        field: 'institution_name',
        category: 'CONFIRMED_MISMATCH',
        document_ids: [12, 13],
        values: ['Institute A', 'Institute B'],
        explanation: 'Historical comparison used the confirmed mismatch category.',
        human_review_recommended: true,
      }, {
        type: 'document_integrity',
        document_id: 12,
        filename: 'certificate.pdf',
        duplicate_file_check: {
          status: 'duplicate',
          explanation: 'A matching SHA-256 hash was found.',
          matches: [{ document_id: 11, original_filename: 'original.pdf' }],
        },
        pdf_structure_check: { status: 'readable', explanation: 'Parser read one page.' },
        metadata_check: { status: 'not_available', explanation: 'No metadata detected.' },
        issuer_verification: 'not_performed',
        authenticity_status: 'not_assessed',
        limitations: ['A matching hash does not establish authenticity.'],
        finding_ids: [29],
      }, {
        type: 'finding',
        finding_id: 29,
        finding_type: 'Duplicate document',
        severity: 'Low',
        status: 'open',
        document_id: 12,
        description: 'Exact file-byte match detected; advisory only.',
        evidence_refs: [],
      }],
      error_summary: null,
      evaluated_rules_count: 0,
      not_evaluated_rules_count: 0,
      not_applicable_rules_count: 0,
    };

    render(<ValidationRunHistory runs={[run]} />);

    expect(screen.getByText(/POSSIBLE_MISMATCH \(legacy stored status: CONFIRMED_MISMATCH\)/)).toBeTruthy();
    expect(screen.getByText(/Extracted differences are indicators only/)).toBeTruthy();
    expect(screen.getByText(/Human review recommended\./)).toBeTruthy();
    expect(screen.getByText(/Document integrity indicators · certificate\.pdf · document 12/)).toBeTruthy();
    expect(screen.getByText(/Matching document 11 \(original\.pdf\)/)).toBeTruthy();
    expect(screen.getByText(/Issuer verification · not_performed · Authenticity · not_assessed/)).toBeTruthy();
    expect(screen.getByText(/Persisted finding 29 · Duplicate document · Low · open/)).toBeTruthy();
  });
});
