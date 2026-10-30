import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DocumentRegistryAdmin } from './DocumentRegistryAdmin';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const draftType = {
  id: 'legacy_certificate',
  display_name: 'Legacy certificate',
  category: 'legacy_preview',
  family: 'certificate',
  description: 'Synthetic preview only.',
  aliases: [],
  supported_file_formats: ['pdf'],
  supported_languages: ['en'],
  application_categories: [],
  regulatory_rule_references: [],
  issuing_authority: null,
  verification_config: { method: 'not_configured' },
  expiry_config: null,
  status: 'draft',
  schema_versions: [{
    id: 8,
    schema_version: '1.0.0',
    definition: { fields: [{ id: 'number', label: 'Number', data_type: 'string', required: false }] },
    status: 'draft',
  }],
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('DocumentRegistryAdmin', () => {
  it('shows draft status and activates only after the backend accepts the request', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([draftType]))
      .mockResolvedValueOnce(jsonResponse({ status: 'active' }))
      .mockResolvedValueOnce(jsonResponse([{ ...draftType, status: 'active', schema_versions: [{ ...draftType.schema_versions[0], status: 'active' }] }]));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(<DocumentRegistryAdmin token="session-token" />);

    expect(await screen.findByText('legacy_certificate')).toBeTruthy();
    expect(screen.getByText('draft')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Activate draft' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/Activated schema 1\.0\.0/);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toContain('/schema-versions/8/activate');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      headers: { Authorization: 'Bearer session-token' },
    });
  });

  it('surfaces registry read failures instead of showing an empty success state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      jsonResponse({ detail: 'Registry database unavailable' }, 503),
    ));

    render(<DocumentRegistryAdmin token="session-token" />);

    expect((await screen.findByRole('alert')).textContent).toContain('Registry database unavailable');
    expect(screen.queryByText('No document types are registered.')).toBeNull();
  });

  it('updates draft metadata through the registry API', async () => {
    const updatedType = { ...draftType, display_name: 'Updated legacy certificate' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([draftType]))
      .mockResolvedValueOnce(jsonResponse(updatedType))
      .mockResolvedValueOnce(jsonResponse([updatedType]));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(<DocumentRegistryAdmin token="session-token" />);
    await user.click(await screen.findByRole('button', { name: 'Edit draft metadata' }));
    const nameInputs = screen.getAllByRole('textbox', { name: 'Display name' });
    const nameInput = nameInputs[nameInputs.length - 1];
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated legacy certificate');
    await user.click(screen.getByRole('button', { name: 'Save draft metadata' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toContain('/api/document-types/legacy_certificate');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({
        display_name: 'Updated legacy certificate',
        category: 'legacy_preview',
        description: 'Synthetic preview only.',
      }),
    });
  });
});
