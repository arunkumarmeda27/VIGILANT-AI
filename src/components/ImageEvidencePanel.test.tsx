import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImageEvidencePanel } from './ImageEvidencePanel';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const persistedImage = {
  id: 12,
  application_id: 7,
  validation_run_id: null,
  original_filename: 'site.jpg',
  content_type: 'image/jpeg',
  sha256: 'abc123',
  file_size: 128,
  processing_status: 'quality_limited',
  analysis_result: {
    task: 'image_quality_assessment',
    analysis_version: 'deterministic-image-quality-v1',
    dimensions: { width: 20, height: 10 },
    metrics: { mean_grayscale_brightness_0_255: 12 },
    warnings: ['image_is_very_dark'],
    method: 'Deterministic quality flags only.',
    model: null,
    human_review_required: true,
  },
  created_at: '2026-03-22T10:00:00Z',
};

describe('ImageEvidencePanel', () => {
  it('uploads evidence, reloads persisted results, and downloads the authorized source', async () => {
    let saved = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/image-evidence') && init?.method === 'POST') {
        saved = true;
        return Response.json(persistedImage, { status: 201 });
      }
      if (url.endsWith('/image-evidence')) {
        return Response.json(saved ? [persistedImage] : []);
      }
      if (url.endsWith('/image-evidence/12/file')) {
        return new Response(new Blob(['image bytes']), { status: 200 });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:test-image'),
      revokeObjectURL: vi.fn(),
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    render(<ImageEvidencePanel applicationId={7} token="test-token" />);
    expect(await screen.findByText('No image evidence is stored for this application.')).toBeTruthy();

    const image = new File(['image bytes'], 'site.jpg', { type: 'image/jpeg' });
    fireEvent.change(screen.getByLabelText('Infrastructure image (PNG or JPEG)'), {
      target: { files: [image] },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Upload and assess image quality' }).closest('form')!);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/applications/7/image-evidence'),
      expect.objectContaining({ method: 'POST', body: expect.any(FormData) }),
    ));
    expect(await screen.findByText(/Image evidence saved with status quality_limited/)).toBeTruthy();
    expect(await screen.findByText('site.jpg · quality_limited')).toBeTruthy();
    expect(screen.getByText('Quality warning: image_is_very_dark')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Download source image' }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/applications/7/image-evidence/12/file'),
      { headers: { Authorization: 'Bearer test-token' } },
    );
    expect(screen.getByText(/does not detect infrastructure objects/)).toBeTruthy();
  });

  it('shows backend errors instead of presenting a successful empty history', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(
      { detail: 'Application access denied' },
      { status: 403 },
    )));

    render(<ImageEvidencePanel applicationId={7} token="test-token" />);

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Application access denied');
    expect(screen.queryByText('No image evidence is stored for this application.')).toBeNull();
  });
});
