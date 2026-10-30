import { useCallback, useEffect, useState } from 'react';

type ImageEvidenceRecord = {
  id: number;
  application_id: number;
  validation_run_id: number | null;
  original_filename: string;
  content_type: string;
  sha256: string;
  file_size: number;
  processing_status: string;
  analysis_result: {
    task: string;
    analysis_version: string;
    dimensions: { width: number; height: number };
    metrics: Record<string, number>;
    warnings: string[];
    method: string;
    model: string | null;
    human_review_required: boolean;
  };
  created_at: string;
};

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

async function imageRequest<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: string };
      detail = body.detail || detail;
    } catch {
      // Retain the HTTP status when the server does not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function ImageEvidencePanel({
  applicationId,
  token,
}: {
  applicationId: number;
  token: string;
}) {
  const [records, setRecords] = useState<ImageEvidenceRecord[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadRecords = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRecords(await imageRequest<ImageEvidenceRecord[]>(
        `/api/applications/${applicationId}/image-evidence`,
        token,
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load image evidence.');
    } finally {
      setLoading(false);
    }
  }, [applicationId, token]);

  useEffect(() => { void loadRecords(); }, [loadRecords]);

  async function uploadImage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || saving) return;
    const form = event.currentTarget;
    setSaving(true);
    setError(null);
    setNotice(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const created = await imageRequest<ImageEvidenceRecord>(
        `/api/applications/${applicationId}/image-evidence`,
        token,
        { method: 'POST', body: formData },
      );
      setFile(null);
      form.reset();
      setNotice(`Image evidence saved with status ${created.processing_status}. Human review is required.`);
      await loadRecords();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not analyze image evidence.');
    } finally {
      setSaving(false);
    }
  }

  async function downloadSource(record: ImageEvidenceRecord) {
    setError(null);
    try {
      const response = await fetch(
        `${API_URL}/api/applications/${applicationId}/image-evidence/${record.id}/file`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!response.ok) throw new Error(`Image download failed (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = record.original_filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not retrieve the source image.');
    }
  }

  return (
    <section className="content-section" aria-labelledby="image-evidence-heading">
      <h2 id="image-evidence-heading">Infrastructure image evidence</h2>
      <p>
        Upload PNG or JPEG images for deterministic image-quality signals. This
        does not detect infrastructure objects or establish compliance or
        authenticity.
      </p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="validation-meta" role="status">{notice}</p>}
      <form className="live-upload-form" onSubmit={uploadImage}>
        <label>
          Infrastructure image (PNG or JPEG)
          <input
            type="file"
            accept="image/png,image/jpeg,.png,.jpg,.jpeg"
            required
            onChange={event => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button className="button primary" type="submit" disabled={!file || saving}>
          {saving ? 'Analyzing…' : 'Upload and assess image quality'}
        </button>
      </form>
      <h3>Persisted image analysis history</h3>
      {error ? null : loading ? <p role="status">Loading image evidence…</p> : records.length === 0 ? (
        <p>No image evidence is stored for this application.</p>
      ) : records.map(record => (
        <article className="live-document-card" key={record.id}>
          <h4>{record.original_filename} · {record.processing_status}</h4>
          <p>
            Image {record.id} · {record.analysis_result.dimensions.width} ×
            {' '}{record.analysis_result.dimensions.height} · {record.file_size.toLocaleString()} bytes
          </p>
          <p>SHA-256: <code>{record.sha256}</code></p>
          <dl className="validation-rule-meta">
            {Object.entries(record.analysis_result.metrics).map(([name, value]) => (
              <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>
            ))}
          </dl>
          {record.analysis_result.warnings.map(warning => (
            <p className="validation-meta" key={warning}>Quality warning: {warning}</p>
          ))}
          <p>{record.analysis_result.method}</p>
          <p>
            Analysis {record.analysis_result.analysis_version} · model:
            {' '}{record.analysis_result.model ?? 'not used'} · human review required.
            {record.validation_run_id !== null
              ? ` Included in validation run ${record.validation_run_id}.`
              : ' Not yet included in a validation run.'}
          </p>
          <button
            className="button secondary"
            type="button"
            onClick={() => void downloadSource(record)}
          >
            Download source image
          </button>
        </article>
      ))}
    </section>
  );
}
