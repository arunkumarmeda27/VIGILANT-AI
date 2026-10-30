import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DocumentTypeCorrection } from './DocumentTypeCorrection';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('DocumentTypeCorrection', () => {
  it('records a reasoned correction and reloads append-only history', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({
        id: 21,
        previous_document_type: 'legacy_type',
        corrected_document_type: 'approved_type',
        original_prediction: 'legacy_type',
        reason: 'Reviewed source document.',
        created_at: '2026-03-22T10:00:00Z',
      }))
      .mockResolvedValueOnce(jsonResponse([{
        id: 21,
        previous_document_type: 'legacy_type',
        corrected_document_type: 'approved_type',
        original_prediction: 'legacy_type',
        reason: 'Reviewed source document.',
        created_at: '2026-03-22T10:00:00Z',
      }]));
    vi.stubGlobal('fetch', fetchMock);
    const onCorrected = vi.fn();
    const user = userEvent.setup();

    render(
      <DocumentTypeCorrection
        applicationId={7}
        documentId={9}
        currentType="legacy_type"
        predictedType="legacy_type"
        types={[
          { id: 'legacy_type', display_name: 'Legacy type', status: 'active' },
          { id: 'approved_type', display_name: 'Approved type', status: 'active' },
        ]}
        token="reviewer-token"
        onCorrected={onCorrected}
      />,
    );

    await screen.findByText('No type corrections recorded.');
    await user.selectOptions(screen.getByLabelText('Corrected type'), 'approved_type');
    await user.type(screen.getByLabelText('Reviewer reason'), 'Reviewed source document.');
    await user.click(screen.getByRole('button', { name: 'Record type correction' }));

    expect(await screen.findByText(/legacy_type → approved_type/)).toBeTruthy();
    expect(onCorrected).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[1][0]).toContain('/type-corrections');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({
      document_type_id: 'approved_type',
      reason: 'Reviewed source document.',
    });
  });
});
